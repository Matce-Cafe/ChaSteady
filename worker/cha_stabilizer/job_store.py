"""Private JSON-backed preferences and job/artifact state."""
import copy
import datetime
import json
import os
import re
import stat
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import JOB_STATES, TERMINAL_STATES, validate_preferences_update
from .diagnostics import checkpoint
from .errors import is_known_message_key, typed_error_message, typed_progress_message
from .development_config import load_development_config
from .paths import (
    UnsafePathError,
    _assert_no_reparse_components,
    _create_windows_private_file,
    _copy_windows_dacl,
    create_run_directory,
    ensure_private_layout,
    same_file_or_alias,
    validate_owned_file,
    validate_run_directory,
)


_ARTIFACT_MIME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$")
_JOB_FILENAME = "job.json"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        return value
    return str(value)


_PRIVATE_PUBLIC_KEYS = frozenset({
    "path", "paths", "source_path", "output_path", "manifest", "outputs", "artifacts_path",
    "project_template", "executable", "command", "args", "argv", "stderr", "stdout",
    "encoder_log", "cwd", "workdir", "run_dir", "root", "token", "nonce", "authorization",
})
_PRIVATE_TEXT_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\|(?:^|\s)/(?:users|home|tmp|private|var|mnt)/)")


def _public_message_args(message_key: Any, value: Any) -> Optional[Dict[str, Any]]:
    if not is_known_message_key(message_key) or not isinstance(value, dict):
        return None
    if not value:
        return {}
    if message_key not in (
        "job.progress.render", "job.progress.registration", "job.progress.quietTracking"
    ) or set(value) != {"current", "total"}:
        return None
    current, total = value.get("current"), value.get("total")
    if (
        isinstance(current, bool) or not isinstance(current, int) or current < 0 or current > 1_000_000_000
        or isinstance(total, bool) or not isinstance(total, int) or total < 0 or total > 1_000_000_000
    ):
        return None
    return {"current": current, "total": total}


def _public_job_value(value: Any, key: str = "", depth: int = 0) -> Any:
    key_name = str(key).casefold()
    if key_name in _PRIVATE_PUBLIC_KEYS or "token" in key_name or "nonce" in key_name or "path" in key_name or key_name.endswith("_source"):
        return None
    if isinstance(value, Path) or depth > 8:
        return None
    if isinstance(value, dict):
        result = {}
        for item_key, item_value in list(value.items())[:100]:
            safe_key = str(item_key)[:80]
            safe_name = safe_key.casefold()
            if (safe_name in _PRIVATE_PUBLIC_KEYS or "token" in safe_name or "nonce" in safe_name
                    or "path" in safe_name or safe_name.endswith("_source")):
                if safe_name == "args" and "message_key" in value:
                    typed_args = _public_message_args(value.get("message_key"), item_value)
                    if typed_args is not None:
                        result[safe_key] = typed_args
                continue
            if item_value is None:
                result[safe_key] = None
                continue
            clean = _public_job_value(item_value, safe_key, depth + 1)
            if clean is not None:
                result[safe_key] = clean
        return result
    if isinstance(value, (list, tuple)):
        return [None if item is None else _public_job_value(item, depth=depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        if _PRIVATE_TEXT_PATH.search(value):
            return "[redacted path-related detail]"
        return value[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        return value
    return str(value)[:1000]


def _public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    value = _public_job_value(job)
    return value if isinstance(value, dict) else {}


def _read_json_regular(path: Path, max_bytes: int = 2 * 1024 * 1024) -> Any:
    _assert_no_reparse_components(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags)
    try:
        opened = os.fstat(fd)
        _assert_no_reparse_components(path)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or opened.st_size > max_bytes
            or getattr(opened, "st_nlink", 1) != 1
            or (getattr(opened, "st_dev", None), getattr(opened, "st_ino", None))
            != (getattr(current, "st_dev", None), getattr(current, "st_ino", None))
        ):
            raise ValueError("stored JSON file is not a bounded, single-link regular file")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _atomic_json_write(path: Path, value: Any, *, protect_windows_acl: bool = False) -> None:
    parent = path.parent
    _assert_no_reparse_components(parent)
    destination_exists = path.exists() or path.is_symlink()
    if destination_exists:
        _assert_no_reparse_components(path)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise UnsafePathError("stored JSON destination is not a regular file")
    temporary = parent / (".{}.{}.tmp".format(path.name, uuid.uuid4().hex))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if protect_windows_acl and os.name == "nt":
        fd = _create_windows_private_file(temporary)
    else:
        fd = os.open(str(temporary), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if protect_windows_acl and destination_exists and os.name == "nt":
            _copy_windows_dacl(path, temporary)
        os.replace(str(temporary), str(path))
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


class PreferenceStore:
    """Persist only app-owned UI settings and known executable paths."""

    DEFAULTS = {
        "theme_mode": "system",
        "seed_color": 4283215696,
        "tool_paths": {"ffmpeg": None, "ffprobe": None, "gyroflow": None, "catalyst": None},
        "language_mode": "system",
    }
    DESKTOP_DEFAULTS = DEFAULTS

    def __init__(self, app_root: Path, *, desktop: bool = False):
        self.app_root = Path(app_root).resolve(strict=True)
        self.private_dir, self.runs_root = ensure_private_layout(self.app_root)
        self.path = self.private_dir / "preferences.json"
        self.desktop = bool(desktop or getattr(sys, "frozen", False))
        self.development_config = load_development_config(
            self.app_root, enabled=not self.desktop,
        )
        self.defaults = copy.deepcopy(self.DEFAULTS)
        if not self.desktop:
            self.defaults["tool_paths"].update(self.development_config["tool_paths"])
        self._lock = threading.RLock()
        self._value = copy.deepcopy(self.defaults)
        if self.path.exists():
            try:
                data = _read_json_regular(self.path)
                self._value = self._validate_full(data)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                # Keep the corrupt file intact for user recovery. Do not silently
                # replace persisted preferences with defaults.
                self._value = copy.deepcopy(self.defaults)
            else:
                if "language_mode" not in data:
                    # Migrate only a valid legacy document. Invalid settings remain
                    # byte-for-byte intact for user recovery.
                    try:
                        _atomic_json_write(self.path, self._value, protect_windows_acl=True)
                    except (OSError, ValueError, UnsafePathError):
                        pass

    def _validate_full(self, data: Any) -> Dict[str, Any]:
        legacy_fields = {"theme_mode", "seed_color", "tool_paths"}
        current_fields = legacy_fields | {"language_mode"}
        if not isinstance(data, dict) or set(data) not in (legacy_fields, current_fields):
            raise ValueError("invalid preference schema")
        update = validate_preferences_update(data)
        if set(update) not in (legacy_fields, current_fields):
            raise ValueError("incomplete preference schema")
        merged = copy.deepcopy(self.defaults)
        merged.update(update)
        merged["tool_paths"] = dict(self.defaults["tool_paths"], **update["tool_paths"])
        return merged

    def get(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._value)

    def update(self, payload: Any) -> Dict[str, Any]:
        update = validate_preferences_update(payload)
        with self._lock:
            candidate = copy.deepcopy(self._value)
            for key, value in update.items():
                if key == "tool_paths":
                    candidate[key].update(value)
                else:
                    candidate[key] = value
            _atomic_json_write(self.path, candidate, protect_windows_acl=True)
            self._value = candidate
            return copy.deepcopy(candidate)


class JobStore:
    """Thread-safe, restart-aware JSON job store below private/runs."""

    def __init__(self, app_root: Path):
        self.app_root = Path(app_root).resolve(strict=True)
        self.private_dir, self.runs_root = ensure_private_layout(self.app_root)
        self._lock = threading.RLock()
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        # Only inspect immediate canonical UUID children; no recursive disk scan.
        for directory in self.runs_root.iterdir():
            try:
                _assert_no_reparse_components(directory)
                if not directory.is_dir():
                    continue
            except (OSError, ValueError, UnsafePathError):
                continue
            try:
                parsed = uuid.UUID(directory.name)
                if str(parsed) != directory.name:
                    continue
                safe_run_dir = validate_run_directory(directory, self.runs_root, directory.name)
                data = _read_json_regular(safe_run_dir / _JOB_FILENAME)
                record = data.get("record") if isinstance(data, dict) else None
                if not isinstance(record, dict):
                    continue
                job = record.get("job")
                if not isinstance(job, dict) or job.get("id") != directory.name:
                    continue
                if job.get("state") not in JOB_STATES:
                    continue
                record["run_dir"] = str(safe_run_dir)
                if not isinstance(record.get("artifact_paths"), dict):
                    record["artifact_paths"] = {}
                if not isinstance(record.get("request"), dict):
                    record["request"] = {}
                if job["state"] in ("queued", "running"):
                    job["state"] = "failed"
                    job["stage"] = "interrupted"
                    job["progress"] = None
                    job["message"] = "The application stopped before this job completed. Its source files were not changed."
                    job["error"] = {
                        "code": "worker_interrupted",
                        "message": job["message"],
                        "message_key": "job.error.workerInterrupted",
                        "args": {},
                    }
                    job["message_key"] = "job.progress.failed"
                    job["args"] = {}
                    job["updated_at"] = utc_now()
                    self._write_record(record)
                # Discard artifact references that no longer validate as owned.
                cleaned: Dict[str, Dict[str, Any]] = {}
                for artifact_id, details in record["artifact_paths"].items():
                    if not isinstance(details, dict):
                        continue
                    try:
                        artifact_path = validate_owned_file(
                            Path(details["path"]), Path(record["run_dir"]),
                            [Path(p) for p in details.get("inputs", [])],
                        )
                        if details.get("run_dir") != record["run_dir"]:
                            continue
                        cleaned[artifact_id] = dict(details, path=str(artifact_path))
                    except (KeyError, OSError, ValueError, UnsafePathError):
                        continue
                record["artifact_paths"] = cleaned
                prior_artifacts = job.get("artifacts", [])
                if not isinstance(prior_artifacts, list):
                    prior_artifacts = []
                job["artifacts"] = [
                    artifact for artifact in prior_artifacts
                    if isinstance(artifact, dict) and artifact.get("id") in cleaned
                ]
                if len(job["artifacts"]) != len(prior_artifacts):
                    self._write_record(record)
                self._records[directory.name] = record
            except (OSError, ValueError, TypeError, json.JSONDecodeError, UnsafePathError):
                continue

    def _write_record(self, record: Dict[str, Any]) -> None:
        checkpoint("job_store.write_record.begin")
        try:
            job_id = record["job"]["id"]
            run_dir = validate_run_directory(Path(record["run_dir"]), self.runs_root, job_id)
            record["run_dir"] = str(run_dir)
            _atomic_json_write(run_dir / _JOB_FILENAME, {"record": record})
        finally:
            checkpoint("job_store.write_record.end")

    def create(self, kind: str, request: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        run_dir = create_run_directory(self.runs_root, job_id)
        now = utc_now()
        job = {
            "id": job_id,
            "kind": kind,
            "state": "queued",
            "stage": "queued",
            "progress": 0.0,
            "message": "Waiting for the local worker.",
            "message_key": "job.progress.queued",
            "args": {},
            "created_at": now,
            "updated_at": now,
            "artifacts": [],
            "warnings": [],
            "error": None,
            "result": None,
        }
        record = {
            "job": job,
            "request": copy.deepcopy(request),
            "run_dir": str(run_dir.resolve(strict=True)),
            "artifact_paths": {},
        }
        with self._lock:
            self._records[job_id] = record
            self._write_record(record)
        return _public_job(job)

    def _record(self, job_id: str) -> Dict[str, Any]:
        try:
            return self._records[job_id]
        except KeyError as exc:
            raise KeyError("unknown job") from exc

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            return _public_job(self._record(job_id)["job"])

    def get_request(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._record(job_id)["request"])

    def get_run_dir(self, job_id: str) -> Path:
        with self._lock:
            record = self._record(job_id)
            return validate_run_directory(Path(record["run_dir"]), self.runs_root, job_id)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = [record["job"] for record in self._records.values()]
            jobs.sort(key=lambda job: job.get("created_at", ""), reverse=True)
            return [_public_job(job) for job in jobs]

    def update_progress(
        self,
        job_id: str,
        stage: str,
        progress: Optional[float],
        message: str,
        *,
        message_key: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        checkpoint("job_store.progress_lock.wait")
        with self._lock:
            checkpoint("job_store.progress_lock.acquired")
            try:
                record = self._record(job_id)
                job = record["job"]
                if job["state"] != "running":
                    return _public_job(job)
                if not isinstance(stage, str) or not stage:
                    stage = "processing"
                if progress is not None:
                    if isinstance(progress, bool) or not isinstance(progress, (int, float)):
                        progress = None
                    else:
                        progress = float(progress)
                        if not (0.0 <= progress <= 1.0):
                            progress = None
                safe_message = str(message or "Processing.")[:1000]
                job.update({
                    "stage": stage[:120],
                    "progress": progress,
                    "message": safe_message,
                    "updated_at": utc_now(),
                })
                typed = typed_progress_message(stage, safe_message)
                if message_key is not None:
                    typed = (message_key, dict(args or {}))
                if typed is not None:
                    job["message_key"], job["args"] = typed[0], dict(typed[1])
                else:
                    job.pop("message_key", None)
                    job.pop("args", None)
                self._write_record(record)
                return _public_job(job)
            finally:
                checkpoint("job_store.progress_lock.exit")

    def set_state(
        self,
        job_id: str,
        state: str,
        *,
        stage: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        error: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if state not in JOB_STATES:
            raise ValueError("unsupported job state")
        with self._lock:
            record = self._record(job_id)
            job = record["job"]
            current = job["state"]
            if current in TERMINAL_STATES and current != state:
                raise ValueError("terminal job state cannot change")
            allowed = {
                "queued": {"running", "cancelled", "failed"},
                "running": {"needs_manual", "needs_review", "failed", "cancelled", "verified_media"},
            }
            if state != current and state not in allowed.get(current, set()):
                raise ValueError("invalid job state transition")
            if progress is not None:
                if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not 0.0 <= float(progress) <= 1.0:
                    progress = None
                else:
                    progress = float(progress)
            job["state"] = state
            job["stage"] = str(stage or state)[:120]
            job["progress"] = progress
            if message is not None:
                job["message"] = str(message)[:1000]
            typed_progress = typed_progress_message(job["stage"], job.get("message"))
            if typed_progress is not None:
                job["message_key"], job["args"] = typed_progress[0], dict(typed_progress[1])
            else:
                job.pop("message_key", None)
                job.pop("args", None)
            if state in ("failed", "needs_review", "needs_manual") and error is not None:
                error_code = str(error.get("code", "processing_failed"))[:100]
                error_message = str(error.get("message", "Job did not complete."))[:1000]
                typed_error = typed_error_message(error_code, error_message)
                error_value = {"code": error_code, "message": error_message}
                if typed_error is not None:
                    error_value["message_key"], error_value["args"] = typed_error[0], dict(typed_error[1])
                job["error"] = error_value
            elif state == "cancelled":
                job["error"] = None
            elif state == "verified_media":
                job["error"] = None
            if result is not None:
                job["result"] = _json_safe(result)
            job["updated_at"] = utc_now()
            self._write_record(record)
            return _public_job(job)

    def add_warning(self, job_id: str, warning: str) -> None:
        if not warning:
            return
        with self._lock:
            record = self._record(job_id)
            warnings = record["job"]["warnings"]
            if warning not in warnings:
                warnings.append(str(warning)[:1000])
                self._write_record(record)

    def add_artifact(
        self,
        job_id: str,
        *,
        path: Path,
        label: str,
        kind: str,
        mime: str,
        metadata: Optional[Dict[str, Any]] = None,
        validation_scope: Optional[str] = None,
        warnings: Optional[Iterable[str]] = None,
        inputs: Iterable[Path] = (),
    ) -> Dict[str, Any]:
        if not isinstance(mime, str) or not _ARTIFACT_MIME.match(mime):
            raise ValueError("worker returned an invalid artifact MIME type")
        input_paths = [Path(item).resolve(strict=True) for item in inputs]
        with self._lock:
            record = self._record(job_id)
            run_dir = validate_run_directory(Path(record["run_dir"]), self.runs_root, job_id)
            resolved = validate_owned_file(Path(path), run_dir, input_paths)
            if resolved.stat().st_size <= 0:
                raise ValueError("worker artifact must not be empty")
            for existing in record["artifact_paths"].values():
                if same_file_or_alias(resolved, Path(existing["path"])):
                    raise UnsafePathError("worker outputs must not alias one another")
            artifact_id = str(uuid.uuid4())
            artifact = {
                "id": artifact_id,
                "label": str(label or "Output")[:200],
                "kind": str(kind or "media")[:80],
                "url": "/api/artifacts/{}/content".format(artifact_id),
                "mime": mime,
                "media_metadata": _json_safe(metadata or {}),
                "validation_scope": str(validation_scope)[:500] if validation_scope else None,
                "warnings": [str(item)[:1000] for item in (warnings or []) if item],
            }
            record["job"]["artifacts"].append(artifact)
            record["artifact_paths"][artifact_id] = {
                "path": str(resolved),
                "run_dir": str(run_dir),
                "inputs": [str(item) for item in input_paths],
            }
            record["job"]["updated_at"] = utc_now()
            self._write_record(record)
            return _public_job(artifact)

    def get_artifact(
        self, artifact_id: str, *, verified_preview: bool = False
    ) -> Tuple[Dict[str, Any], Path, Path, List[Path]]:
        with self._lock:
            for record in self._records.values():
                details = record["artifact_paths"].get(artifact_id)
                if details is None:
                    continue
                public = next((item for item in record["job"]["artifacts"] if item["id"] == artifact_id), None)
                if public is None:
                    break
                if verified_preview and not (
                    record["job"].get("kind") == "preview"
                    and record["job"].get("state") == "verified_media"
                    and public.get("kind") == "preview"
                    and public.get("mime") == "video/mp4"
                    and public.get("validation_scope") == "preview_media_only"
                ):
                    raise KeyError("artifact is not a verified preview")
                run_dir = validate_run_directory(Path(record["run_dir"]), self.runs_root, record["job"]["id"])
                if str(run_dir) != details.get("run_dir"):
                    raise UnsafePathError("artifact workspace does not match its job")
                inputs = [Path(item) for item in details.get("inputs", [])]
                path = validate_owned_file(Path(details["path"]), run_dir, inputs)
                return _public_job(public), path, run_dir, inputs
        raise KeyError("unknown artifact")

    def cancel_queued(self, job_id: str) -> Dict[str, Any]:
        return self.set_state(job_id, "cancelled", stage="cancelled", message="Cancelled before processing started.")
