"""Single-threaded background executor for API-owned jobs."""
import copy
import hashlib
import importlib
import math
import queue
import re
import stat
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import AppError, CancelledError, NeedsManualError, NeedsReviewError
from .diagnostics import checkpoint
from .job_store import JobStore, PreferenceStore
from .models import RequestValidationError, validate_job_request
from .owned_processes import OwnedProcessRegistry, get_active_registry, registry_scope
from .paths import UnsafePathError, ensure_not_alias, path_is_within, resolve_local_input, same_file_or_alias, validate_owned_file


class JobRunner:
    """Run at most one accepted job at a time on one owned worker thread."""

    def __init__(self, store: JobStore, preferences: PreferenceStore):
        self.store = store
        self.preferences = preferences
        self._queue = queue.Queue()
        self._events: Dict[str, threading.Event] = {}
        self._registries: Dict[str, OwnedProcessRegistry] = {}
        self._discovered_presets: List[Dict[str, Any]] = []
        self._discovery_generation = 0
        self._cache_bindings: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._stopping = False
        self._thread = threading.Thread(target=self._work, name="cha-stabilizer-job-worker", daemon=True)
        self._thread.start()

    def submit(self, payload: Any) -> Dict[str, Any]:
        normalized = validate_job_request(payload)
        kind, request = normalized["kind"], normalized["request"]
        resolved_request, input_paths = self._resolve_inputs(kind, request)
        with self._lock:
            if self._stopping:
                raise RuntimeError("local worker is shutting down")
            cache_binding = None
            if kind == "fusion" and resolved_request["mode"] == "cached_v9":
                cache_binding = self._validate_cached_v9(resolved_request)
            job = self.store.create(kind, resolved_request)
            job_id = job["id"]
            if cache_binding is not None:
                self._cache_bindings[job_id] = cache_binding
            self._events[job_id] = threading.Event()
            self._queue.put((job_id, input_paths))
            return job

    def _resolve_inputs(self, kind: str, request: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Path]]:
        resolved = dict(request)
        path_fields: List[str]
        if kind == "fusion":
            path_fields = ["original", "ctb", "reference", "legacy_quiet_cache", "legacy_reference_cache"]
        elif kind in ("gyroflow_export", "catalyst_assisted"):
            path_fields = ["original", "project_template"] if kind == "gyroflow_export" else ["original"]
        else:
            path_fields = ["source"]
        inputs: List[Path] = []
        for field in path_fields:
            raw = resolved.get(field)
            if raw is None:
                continue
            try:
                path = resolve_local_input(raw, field)
            except UnsafePathError as exc:
                raise RequestValidationError(str(exc)) from exc
            resolved[field] = str(path)
            inputs.append(path)
        # Distinct roles must not silently refer to one aliased file.
        for index, first in enumerate(inputs):
            for second in inputs[index + 1:]:
                try:
                    ensure_not_alias(first, [second])
                except UnsafePathError as exc:
                    raise RequestValidationError("job inputs must not alias one another") from exc
        return resolved, inputs

    def register_discovered_presets(self, presets: Any) -> None:
        """Replace the in-memory cache allowlist with one explicit user discovery."""
        validated = []
        if isinstance(presets, list):
            for item in presets[:3]:
                if not isinstance(item, dict) or not isinstance(item.get("request"), dict):
                    continue
                try:
                    request = validate_job_request({"kind": "fusion", "request": item["request"]})["request"]
                except (RequestValidationError, TypeError, ValueError):
                    continue
                if (
                    request.get("mode") != "cached_v9"
                    or not isinstance(item.get("source_binding"), str)
                    or not isinstance(item.get("cache_hashes"), dict)
                ):
                    continue
                validated.append({
                    "id": str(item.get("id", "")),
                    "request": request,
                    "source_binding": item["source_binding"],
                    "cache_hashes": dict(item["cache_hashes"]),
                })
        with self._lock:
            self._discovered_presets = validated
            self._discovery_generation += 1

    def _validate_cached_v9(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Accept only a preset discovered in this worker session, rechecking pins."""
        with self._lock:
            candidates = copy.deepcopy(self._discovered_presets)
            generation = self._discovery_generation
        for candidate in candidates:
            allowed_request = candidate["request"]
            if not _same_cached_request(request, allowed_request):
                continue
            try:
                validate_cached_v9_discovery(request, candidate)
            except (OSError, ValueError, UnsafePathError) as exc:
                raise RequestValidationError("discovered C7037 source or cache binding changed; rediscover the selected folder") from exc
            with self._lock:
                if generation != self._discovery_generation:
                    raise RequestValidationError("C7037 discovery changed while the cached preset was being submitted")
            return candidate
        raise RequestValidationError("cached_v9 requires a matching preset discovered from a user-selected local folder in this session")

    def cancel(self, job_id: str) -> Dict[str, Any]:
        registry = None
        with self._lock:
            job = self.store.get(job_id)
            if job["state"] == "queued":
                event = self._events.get(job_id)
                if event is not None:
                    event.set()
                return self.store.cancel_queued(job_id)
            if job["state"] != "running":
                raise ValueError("job is already in a terminal state")
            event = self._events.get(job_id)
            if event is None:
                raise ValueError("job cancellation is unavailable")
            event.set()
            registry = self._registries.get(job_id)
            self.store.update_progress(job_id, "cancellation_requested", None, "Cancellation requested; stopping only this job's owned child processes.")
        if registry is not None:
            registry.terminate_all()
        return self.store.get(job_id)

    def shutdown(self, wait: Optional[float] = 3.0) -> None:
        with self._lock:
            if not self._stopping:
                self._stopping = True
                for job_id, event in list(self._events.items()):
                    try:
                        job = self.store.get(job_id)
                    except KeyError:
                        continue
                    if job["state"] == "queued":
                        event.set()
                        try:
                            self.store.cancel_queued(job_id)
                        except ValueError:
                            pass
                    elif job["state"] == "running":
                        event.set()
                        registry = self._registries.get(job_id)
                        if registry is not None:
                            registry.terminate_all()
                self._queue.put(None)
        if self._thread is not threading.current_thread() and self._thread.is_alive():
            self._thread.join(None if wait is None else max(0.0, wait))

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            job_id, input_paths = item
            with self._lock:
                try:
                    job = self.store.get(job_id)
                except KeyError:
                    self._cache_bindings.pop(job_id, None)
                    continue
                if job["state"] != "queued":
                    self._cache_bindings.pop(job_id, None)
                    continue
                event = self._events[job_id]
                if event.is_set():
                    try:
                        self.store.cancel_queued(job_id)
                    except ValueError:
                        pass
                    self._cache_bindings.pop(job_id, None)
                    continue
                try:
                    self.store.set_state(job_id, "running", stage="starting", progress=None, message="Starting the local worker.")
                except ValueError:
                    continue
                checkpoint("job.running_state_written")
                registry = OwnedProcessRegistry(event)
                checkpoint("job.registry_constructed")
                self._registries[job_id] = registry
            try:
                with registry_scope(registry):
                    checkpoint("job.registry_scope_entered")
                    self._execute(job_id, input_paths, event)
            finally:
                if registry.snapshot():
                    registry.terminate_all()
                with self._lock:
                    self._registries.pop(job_id, None)
                    self._cache_bindings.pop(job_id, None)

    def _execute(self, job_id: str, input_paths: List[Path], cancel_event: threading.Event) -> None:
        try:
            checkpoint("job.get_kind.begin")
            kind = self.store.get(job_id)["kind"]
            checkpoint("job.get_kind.end")
            checkpoint("job.get_request.begin")
            request = self.store.get_request(job_id)
            checkpoint("job.get_request.end")
            checkpoint("job.get_run_dir.begin")
            workdir = self.store.get_run_dir(job_id)
            checkpoint("job.get_run_dir.end")
            checkpoint("job.toolchain.begin")
            toolchain = self._toolchain()
            checkpoint("job.toolchain.end")
            if kind == "fusion" and request.get("mode") == "cached_v9":
                with self._lock:
                    cache_binding = self._cache_bindings.get(job_id)
                if cache_binding is None:
                    raise NeedsReviewError("This cached V9 job has no active user-discovery binding; rediscover the selected folder.")
                toolchain["_cached_v9_discovery_binding"] = copy.deepcopy(cache_binding)
            callback = lambda stage, progress, message: self._on_event(job_id, cancel_event, stage, progress, message)
            if kind in ("fusion", "preview", "validate", "gyroflow_export") and (
                toolchain.get("ffmpeg") is None or toolchain.get("ffprobe") is None
            ):
                message = "Both configured ffmpeg and ffprobe are required for media processing and validation."
                self._safe_set_state(
                    job_id, "failed", stage="missing_capability", message=message,
                    error={"code": "missing_capability", "message": message},
                    result={"capability": "ffmpeg_and_ffprobe"},
                )
                return
            if cancel_event.is_set():
                raise CancelledError("Job was cancelled before processing began.")
            if kind == "fusion":
                checkpoint("job.adapter_import.fusion.begin")
                module = importlib.import_module(".core.pipeline", package="cha_stabilizer")
                checkpoint("job.adapter_import.fusion.end")
                action = getattr(module, "run_fusion")
            elif kind == "preview":
                checkpoint("job.adapter_import.preview.begin")
                module = importlib.import_module(".adapters.ffmpeg", package="cha_stabilizer")
                checkpoint("job.adapter_import.preview.end")
                action = getattr(module, "run_preview")
            elif kind == "validate":
                checkpoint("job.adapter_import.validate.begin")
                module = importlib.import_module(".adapters.ffmpeg", package="cha_stabilizer")
                checkpoint("job.adapter_import.validate.end")
                action = getattr(module, "run_validation")
            elif kind == "gyroflow_export":
                checkpoint("job.adapter_import.gyroflow_export.begin")
                module = importlib.import_module(".adapters.gyroflow", package="cha_stabilizer")
                checkpoint("job.adapter_import.gyroflow_export.end")
                action = getattr(module, "run_export")
            else:
                self._execute_catalyst(job_id, request, workdir, toolchain, cancel_event, callback)
                return
            if not callable(action):
                raise ImportError("required worker entry point is unavailable")
            checkpoint("job.action_call.begin")
            result = action(request, workdir, toolchain, cancel_event, callback)
            checkpoint("job.action_call.end")
            registry = get_active_registry()
            if registry is not None:
                children = registry.snapshot()
                active_children = [process for process in children if process.poll() is None]
                for process in children:
                    if process.poll() is not None:
                        registry.discard(process)
                if active_children:
                    registry.terminate_all()
                    raise AppError("Worker returned before its owned subprocesses exited.")
            if cancel_event.is_set():
                raise CancelledError("Cancellation requested; owned work was stopped.")
            self._finish_result(job_id, result, input_paths, cancel_event)
        except CancelledError as exc:
            self._safe_set_state(job_id, "cancelled", stage="cancelled", message=exc.message)
        except NeedsManualError as exc:
            if cancel_event.is_set():
                self._safe_set_state(job_id, "cancelled", stage="cancelled", message="Cancellation requested; owned work was stopped.")
                return
            details = _public_error_details(getattr(exc, "details", {}) or {})
            message = _public_text(exc.message or "Manual action is required before this job can proceed.")
            self._safe_set_state(job_id, "needs_manual", stage="needs_manual", message=message,
                                 error={"code": exc.code, "message": message}, result={"next_steps": details})
        except NeedsReviewError as exc:
            if cancel_event.is_set():
                self._safe_set_state(job_id, "cancelled", stage="cancelled", message="Cancellation requested; owned work was stopped.")
                return
            message = _public_text(exc.message or "The result needs review and was not marked complete.")
            details = getattr(exc, "details", {}) or {}
            retained = self._retain_review_outputs(job_id, details, input_paths)
            public_details = _public_error_details(details)
            self._safe_set_state(job_id, "needs_review", stage="needs_review", message=message,
                                 error={"code": exc.code, "message": message},
                                 result={"details": public_details, "retained_artifact_ids": retained})
        except AppError as exc:
            if cancel_event.is_set():
                self._safe_set_state(job_id, "cancelled", stage="cancelled", message="Cancellation requested; owned work was stopped.")
                return
            message = _public_text(exc.message or "The local worker could not complete this job.")
            failure_stage = "missing_capability" if exc.code == "missing_capability" else "failed"
            details = _public_error_details(getattr(exc, "details", {}) or {})
            self._safe_set_state(job_id, "failed", stage=failure_stage, message=message,
                                 error={"code": exc.code, "message": message}, result={"details": details})
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            if cancel_event.is_set():
                self._safe_set_state(job_id, "cancelled", stage="cancelled", message="Cancellation requested; owned work was stopped.")
                return
            if self.store.get(job_id)["kind"] == "catalyst_assisted":
                message = "Catalyst automation is not enabled; perform the operation manually in Catalyst Browse."
                self._safe_set_state(job_id, "needs_manual", stage="needs_manual", message=message,
                                     error={"code": "needs_manual", "message": message},
                                     result={"next_steps": ["Open Catalyst Browse manually.", "Inspect or export the selected media there.", "Return to ChaSteady and validate the resulting media."]})
            else:
                message = "This processing capability is not available in the current worker build."
                self._safe_set_state(job_id, "failed", stage="missing_capability", message=message,
                                     error={"code": "missing_capability", "message": message},
                                     result={"capability": self.store.get(job_id)["kind"]})
        except Exception:
            if cancel_event.is_set():
                self._safe_set_state(job_id, "cancelled", stage="cancelled", message="Cancellation requested; owned work was stopped.")
                return
            # Do not serialize tracebacks, source paths, environment values, or
            # command lines into the public job record.
            message = "The local worker failed unexpectedly. Check the selected files and configured tools."
            self._safe_set_state(job_id, "failed", stage="failed", message=message,
                                 error={"code": "processing_failed", "message": message})

    def _execute_catalyst(self, job_id, request, workdir, toolchain, cancel_event, callback) -> None:
        # This MVP has no verified owned-window/UIA probe. Never launch Catalyst
        # or trust installed-version/root-window checks as automation authority.
        raise NeedsManualError(
            "Catalyst assistance is not enabled; no Catalyst process or UI action was started.",
            {"steps": [
                "Open Catalyst Browse manually.",
                "Inspect or export the selected media using its normal UI.",
                "Return to ChaSteady and run media validation on the resulting owned file.",
            ]},
        )

    def _retain_review_outputs(self, job_id: str, details: Any, input_paths: List[Path]) -> List[str]:
        """Expose only explicitly described retained files that pass ownership checks."""
        if not isinstance(details, dict):
            return []
        outputs = details.get("outputs", [])
        if not isinstance(outputs, list):
            return []
        workdir = self.store.get_run_dir(job_id)
        retained: List[str] = []
        for output in outputs:
            if not isinstance(output, dict) or not output.get("path"):
                continue
            path = Path(output["path"])
            if not path.is_absolute():
                path = workdir / path
            warnings = output.get("warnings", [])
            if not isinstance(warnings, list):
                warnings = []
            metadata = output.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            try:
                artifact = self.store.add_artifact(
                    job_id,
                    path=path,
                    label=_public_text(str(output.get("label", "Retained diagnostic")), 200),
                    kind=_public_text(str(output.get("kind", "diagnostic")), 80),
                    mime=output.get("mime", "application/octet-stream"),
                    metadata=_public_error_details(metadata),
                    validation_scope=_public_text(output["validation_scope"], 500) if isinstance(output.get("validation_scope"), str) else None,
                    warnings=[_public_text(str(warning)) for warning in warnings],
                    inputs=input_paths,
                )
                retained.append(artifact["id"])
            except (OSError, TypeError, ValueError):
                # Unsafe, outside-run or malformed diagnostics remain private and
                # are never turned into a downloadable artifact.
                continue
        return retained

    def _finish_result(
        self,
        job_id: str,
        result: Any,
        input_paths: List[Path],
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        if not isinstance(result, dict):
            raise AppError("Worker returned an invalid result; it was not marked complete.")
        outputs = result.get("outputs")
        if not isinstance(outputs, list):
            raise AppError("Worker did not return a verifiable output list.")
        warnings = result.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        for warning in warnings:
            self.store.add_warning(job_id, _public_text(str(warning)))
        kind = self.store.get(job_id)["kind"]
        if kind == "fusion":
            self.store.add_warning(job_id, "Source FOV is unverified; output dimensions do not certify full-input coverage.")
            self.store.add_warning(job_id, "CTB correspondence applies to the CTB input rectangle only.")
            self.store.add_warning(job_id, "Reference FOV is an analysis-only scale adjustment; it does not zoom the render or certify original FOV.")
            request = self.store.get_request(job_id)
            if request.get("mode") == "cached_v9":
                self.store.add_warning(job_id, "Cached v9 is an explicit C7037 legacy reproduction with known cache gaps, not a fresh measurement.")
        workdir = self.store.get_run_dir(job_id)
        manifest = result.get("manifest")
        if not manifest:
            raise AppError("Worker did not return its required job manifest.")
        manifest_path = Path(manifest)
        if not manifest_path.is_absolute():
            manifest_path = workdir / manifest_path
        try:
            validate_owned_file(manifest_path, workdir, input_paths)
        except (OSError, ValueError) as exc:
            raise AppError("Worker manifest was not an owned regular file.") from exc
        for output in outputs:
            if not isinstance(output, dict) or "path" not in output:
                raise AppError("Worker returned an output without an owned file path.")
            output_path = Path(output["path"])
            if not output_path.is_absolute():
                output_path = workdir / output_path
            output_warnings = output.get("warnings", [])
            if not isinstance(output_warnings, list):
                output_warnings = []
            output_metadata = output.get("metadata") if isinstance(output.get("metadata"), dict) else {}
            output_metadata = _public_error_details(output_metadata)
            self.store.add_artifact(
                job_id,
                path=output_path,
                label=_public_text(str(output.get("label", "Output")), 200),
                kind=_public_text(str(output.get("kind", "media")), 80),
                mime=output.get("mime", "application/octet-stream"),
                metadata=output_metadata,
                validation_scope=_public_text(output["validation_scope"], 500) if isinstance(output.get("validation_scope"), str) else None,
                warnings=[_public_text(str(warning)) for warning in output_warnings],
                inputs=input_paths,
            )
        if not outputs:
            raise NeedsReviewError("Worker produced no owned artifact; result requires review.")
        validation = result.get("validation")
        if not isinstance(validation, dict):
            validation = {}
        validation = _public_error_details(validation)
        if not isinstance(validation, dict):
            validation = {}
        validation_state = validation.get("status")
        scope = validation.get("scope")
        explicitly_verified = (
            validation.get("verified_media") is True
            or validation_state == "verified_media"
        )
        if explicitly_verified and isinstance(scope, str) and scope.strip():
            state = "verified_media"
            message = "Media evidence verified within the reported scope; this is not a perceptual winner or original-FOV certificate."
            error = None
        else:
            state = "needs_review"
            message = "Outputs were produced, but the worker did not provide scoped media-verification evidence."
            error = {"code": "needs_review", "message": message}
        public_result = {
            "validation": validation,
            "manifest_available": bool(result.get("manifest")),
        }
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("Cancellation requested; owned work was stopped.")
        self._safe_set_state(job_id, state, stage=state, progress=1.0 if state == "verified_media" else None,
                             message=message, error=error, result=public_result)

    def _on_event(self, job_id: str, cancel_event: threading.Event, stage: Any, progress: Any, message: Any) -> None:
        if cancel_event.is_set():
            raise CancelledError("Cancellation requested; stopping this job's owned work.")
        if isinstance(progress, bool) or not isinstance(progress, (float, int)) or not math.isfinite(float(progress)):
            progress = None
        safe_stage = _public_text(str(stage or "processing"), 120)
        safe_message = _public_text(str(message or "Processing."))
        self.store.update_progress(job_id, safe_stage, progress, safe_message)

    def _safe_set_state(self, job_id: str, state: str, **kwargs: Any) -> None:
        try:
            current = self.store.get(job_id)["state"]
            if current == "running":
                self.store.set_state(job_id, state, **kwargs)
            elif current == "queued" and state in ("cancelled", "failed"):
                self.store.set_state(job_id, state, **kwargs)
        except (KeyError, ValueError):
            pass

    def _toolchain(self) -> Dict[str, Any]:
        checkpoint("toolchain.preferences_get.begin")
        preference_value = self.preferences.get()
        checkpoint("toolchain.preferences_get.end")
        paths = preference_value["tool_paths"]
        result: Dict[str, Any] = {}
        for name in ("ffmpeg", "ffprobe", "gyroflow", "catalyst"):
            checkpoint("toolchain.path.{}.begin".format(name))
            configured = paths.get(name)
            if not configured:
                result[name] = None
                checkpoint("toolchain.path.{}.end".format(name))
                continue
            try:
                result[name] = resolve_local_input(configured, "configured {} executable".format(name))
            except (OSError, ValueError):
                result[name] = None
            checkpoint("toolchain.path.{}.end".format(name))
        result["development_identity"] = (
            self.preferences.development_config["gyroflow_identity"]
            if not self.preferences.desktop else {}
        )
        return result


_PRIVATE_DETAIL_KEYS = frozenset({
    "path", "paths", "source_path", "output_path", "manifest", "outputs", "artifacts",
    "project_template", "executable", "command", "args", "argv", "stderr", "stdout",
    "encoder_log", "cwd", "workdir", "run_dir", "root", "token", "nonce", "authorization",
})
_ABSOLUTE_PATH_TEXT = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\|(?:^|\s)/(?:users|home|tmp|private|var|mnt)/)")


def _public_text(value: str, limit: int = 1000) -> str:
    text = str(value)
    if _ABSOLUTE_PATH_TEXT.search(text):
        return "[redacted path-related detail]"
    return text[:limit]


def _public_error_details(value: Any, key: str = "", depth: int = 0) -> Any:
    key_name = str(key).casefold()
    if key_name in _PRIVATE_DETAIL_KEYS or "token" in key_name or "nonce" in key_name or "path" in key_name or key_name.endswith("_source"):
        return None
    if isinstance(value, Path):
        return None
    if depth > 8:
        return None
    if isinstance(value, dict):
        clean = {}
        for item_key, item_value in list(value.items())[:100]:
            safe_key = _public_text(str(item_key), 80)
            item = _public_error_details(item_value, str(item_key), depth + 1)
            if item is not None:
                clean[safe_key] = item
        return clean
    if isinstance(value, (list, tuple)):
        return [item for item in (_public_error_details(entry, depth=depth + 1) for entry in list(value)[:100]) if item is not None]
    if isinstance(value, str):
        return _public_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return _public_text(str(value))


def _fold_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return str(Path(value)).replace("\\", "/").rstrip("/").casefold()


C7037_EXPERIMENT_DIR = "Frontier_Stabilization_20261012_150110"
_C7037_EXPERIMENT_DIR = C7037_EXPERIMENT_DIR
_C7037_PATH_FIELDS = frozenset(("original", "ctb", "reference", "legacy_quiet_cache", "legacy_reference_cache"))
_C7037_PRESET_SPECS = (
    {
        "label": "C7037 Zoom In 140–156",
        "quiet": Path("Gyroflow_ZoomFix_20261012_141809/previews/CTB_TRANSLATION_ZOOM_IN_140-156_SIGMA_0.90.npz"),
        "reference": Path("Frontier_Stabilization_20261012_150110/analysis/ctb_rigid_gf_reference_full_v7_20261013_zoomin-140-156.npz"),
        "start": 140.0, "end": 156.0, "sigma": 0.90,
        "intervals": [{"start": 153.0, "end": 156.0}],
        "warning": "Known legacy cache gap around frames 153–156; cached trajectory is not a fresh measurement.",
    },
    {
        "label": "C7037 Fixed 212–228",
        "quiet": Path("Gyroflow_ZoomFix_20261012_141809/previews/CTB_TRANSLATION_FIXED400_212-228_SIGMA_1.30.npz"),
        "reference": Path("Frontier_Stabilization_20261012_150110/analysis/ctb_rigid_gf_reference_full_v7_20261013_fixed400-212-228.npz"),
        "start": 212.0, "end": 228.0, "sigma": 1.30,
        "intervals": [],
        "warning": "Fixed-strengthened CTB interval 212–228; no quiet reference interval is enabled.",
    },
    {
        "label": "C7037 Zoom Out 230–246",
        "quiet": Path("Frontier_Stabilization_20261012_150110/previews/CTB_RAFT_GLOBAL_TRANSLATION_ZOOM_OUT_230-246.npz"),
        "reference": Path("Frontier_Stabilization_20261012_150110/analysis/ctb_rigid_gf_reference_full_v7_20261013_zoomout-230-246.npz"),
        "start": 230.0, "end": 246.0, "sigma": 1.30,
        "intervals": [{"start": 231.8, "end": 235.5}],
        "warning": "Known legacy cache gap around frames 231.8–235.5; cached trajectory is not a fresh measurement.",
    },
)


def _preset_id(label: str) -> str:
    return label.lower().replace(" ", "-").replace("–", "-")


def _preset_warnings(warning: str) -> List[str]:
    return [
        "Explicit C7037 cached-v9 reproduction only; never use as a fresh measurement.",
        warning,
        "Source/cache binding is recorded at selection time; this preset does not certify original FOV or recover source crop/bit-depth loss.",
    ]


def _known_c7037_presets(data_root: Path) -> List[Dict[str, Any]]:
    """Build the fixed six-cache allowlist relative to an explicitly selected data root."""
    root = Path(data_root)
    original = root / "C7037.MP4"
    ctb = root / "Catalyst Browse" / "C7037-Catalyst-Browse.mp4"
    reference = root / "Gyroflow" / "C7037_Gyroflow.mp4"
    result = []
    for spec in _C7037_PRESET_SPECS:
        result.append(_preset(
            spec["label"], original, ctb, reference, root / spec["quiet"], root / spec["reference"],
            spec["start"], spec["end"], spec["sigma"], copy.deepcopy(spec["intervals"]), spec["warning"],
        ))
    return result


def c7037_preset_catalog() -> List[Dict[str, Any]]:
    """Metadata-only catalog; file paths are disclosed only after user discovery."""
    return [
        {
            "id": _preset_id(spec["label"]),
            "label": spec["label"],
            "kind": "fusion",
            "mode": "cached_v9",
            "discovery_required": True,
            "warnings": _preset_warnings(spec["warning"]),
        }
        for spec in _C7037_PRESET_SPECS
    ]


def _preset(label, original, ctb, reference, quiet, legacy_reference, start, end, sigma, intervals, warning):
    return {
        "id": _preset_id(label),
        "label": label,
        "kind": "fusion",
        "mode": "cached_v9",
        "request": {
            "original": str(original), "ctb": str(ctb), "reference": str(reference),
            "start": start, "end": end, "ctb_origin": 0, "reference_origin": 0,
            "reference_intervals": intervals, "reference_fov": 1.0, "quiet_sigma_seconds": sigma,
            "mode": "cached_v9", "legacy_quiet_cache": str(quiet),
            "legacy_reference_cache": str(legacy_reference),
        },
        "warnings": _preset_warnings(warning),
    }


def _cached_source_binding(paths: List[Path]) -> str:
    binding = []
    for path in paths[:3]:
        info = path.stat()
        binding.append({"name": path.name, "size": info.st_size, "mtime_ns": getattr(info, "st_mtime_ns", 0)})
    return hashlib.sha256(repr(binding).encode("utf-8")).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_cached_request(request: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    if set(request) != set(expected):
        return False
    return all(
        _fold_path(request[key]) == _fold_path(expected[key])
        if key in _C7037_PATH_FIELDS else request[key] == expected[key]
        for key in expected
    )


def validate_cached_v9_discovery(request: Dict[str, Any], binding: Dict[str, Any]) -> None:
    """Recheck session discovery provenance, fixed relative layout and six cache SHA pins."""
    if not isinstance(binding, dict) or not isinstance(binding.get("request"), dict):
        raise ValueError("missing user-discovery provenance")
    if not _same_cached_request(request, binding["request"]):
        raise ValueError("cached request differs from its discovered preset")
    original = Path(request["original"]).resolve(strict=True)
    data_root = original.parent
    from .paths import _assert_no_reparse_components, validate_local_path_syntax
    _assert_no_reparse_components(data_root)
    experiment_root = data_root / _C7037_EXPERIMENT_DIR
    expected_candidates = _known_c7037_presets(data_root)
    allowed = next((candidate for candidate in expected_candidates if _same_cached_request(request, candidate["request"])), None)
    if (
        allowed is None
        or binding.get("id") != allowed["id"]
        or not experiment_root.is_dir()
    ):
        raise ValueError("cached request is outside the explicit C7037 layout")
    validate_local_path_syntax(str(experiment_root), "experiment_root")
    _assert_no_reparse_components(experiment_root)
    inputs = [resolve_local_input(request[key], "discovered C7037 input") for key in (
        "original", "ctb", "reference", "legacy_quiet_cache", "legacy_reference_cache"
    )]
    if any(not path_is_within(path, data_root) for path in inputs):
        raise ValueError("discovered C7037 input escaped the selected root")
    if any(same_file_or_alias(first, [second]) for index, first in enumerate(inputs[:3])
           for second in inputs[index + 1:3]):
        raise ValueError("source inputs alias one another")
    if _cached_source_binding(inputs) != binding.get("source_binding"):
        raise ValueError("source identity changed after discovery")
    from .core.cache import HASHES
    cache_hashes = binding.get("cache_hashes")
    if not isinstance(cache_hashes, dict) or set(cache_hashes) != {inputs[3].name, inputs[4].name}:
        raise ValueError("discovery does not contain the exact cache hash pair")
    for path in inputs[3:]:
        if path.stat().st_size > 16 * 1024 ** 2:
            raise ValueError("discovered cache exceeds the approved size limit")
        digest = _sha256_path(path)
        if digest != HASHES.get(path.name) or digest != cache_hashes.get(path.name):
            raise ValueError("cache SHA no longer matches the discovery allowlist")


def discover_c7037_presets(experiment_root: str) -> List[Dict[str, Any]]:
    """Offer fixed C7037 cache pairs below a user-selected local experiment root."""
    from .paths import _assert_no_reparse_components, validate_local_path_syntax
    validate_local_path_syntax(experiment_root, "experiment_root")
    selected = Path(experiment_root)
    _assert_no_reparse_components(selected)
    info = selected.lstat()
    if not stat.S_ISDIR(info.st_mode) or selected.name != _C7037_EXPERIMENT_DIR:
        raise RequestValidationError("Select the local C7037 experiment folder for preset discovery.")
    resolved_experiment = selected.resolve(strict=True)
    data_root = resolved_experiment.parent
    _assert_no_reparse_components(data_root)
    if not data_root.is_dir() or not path_is_within(resolved_experiment, data_root):
        raise RequestValidationError("The selected experiment root is not an approved local folder.")

    from .core.cache import HASHES
    result: List[Dict[str, Any]] = []
    for preset in _known_c7037_presets(data_root):
        request = dict(preset["request"])
        try:
            inputs = [resolve_local_input(request[key], "discovered C7037 input") for key in (
                "original", "ctb", "reference", "legacy_quiet_cache", "legacy_reference_cache"
            )]
            if any(not path_is_within(path, data_root) for path in inputs):
                continue
            if any(same_file_or_alias(first, [second]) for index, first in enumerate(inputs[:3])
                   for second in inputs[index + 1:3]):
                continue
            cache_hashes = {}
            valid_caches = True
            for path in inputs[3:]:
                if path.stat().st_size > 16 * 1024 ** 2 or path.name not in HASHES:
                    valid_caches = False
                    break
                digest = _sha256_path(path)
                if digest != HASHES[path.name]:
                    valid_caches = False
                    break
                cache_hashes[path.name] = digest
            if not valid_caches:
                continue
        except (OSError, ValueError, UnsafePathError):
            continue
        for key, path in zip(("original", "ctb", "reference", "legacy_quiet_cache", "legacy_reference_cache"), inputs):
            request[key] = str(path)
        preset_id = preset["id"]
        result.append({
            "id": preset_id,
            "label": preset["label"],
            "kind": preset["kind"],
            "mode": preset["mode"],
            "request": request,
            "warnings": list(preset["warnings"]),
            "source_binding": _cached_source_binding(inputs),
            "cache_hashes": cache_hashes,
        })
    return result
