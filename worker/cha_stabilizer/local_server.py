"""Loopback-only local HTTP API and owned static UI server."""
import importlib
import json
import math
import mimetypes
import os
import re
import secrets
import threading
try:
    import tkinter
    from tkinter import filedialog
except ImportError:
    tkinter = None
    filedialog = None
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import __version__
from .errors import AppError, typed_error_message
from .diagnostics import checkpoint
from .job_runner import JobRunner, discover_c7037_presets
from .job_store import JobStore, PreferenceStore, _json_safe, _public_job_value
from .models import (
    RequestValidationError,
    validate_job_request,
    validate_media_inspect,
    validate_media_pick,
    validate_preset_discovery,
)
from .owned_processes import OwnedProcessRegistry, registry_scope
from .paths import (
    UnsafePathError,
    _assert_no_reparse_components,
    open_validated_owned_file,
    require_disjoint_roots,
    resolve_local_input,
    validate_local_path_syntax,
)


_MAX_JSON_BYTES = 1024 * 1024
_JOB_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_ARTIFACT_ID = _JOB_ID
_HTTP_METHOD_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,32}$")
_BYTE_RANGE = re.compile(r"^bytes=([0-9]*)-([0-9]*)$")


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BadRequest("JSON objects must not contain duplicate keys")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise BadRequest("JSON numbers must be finite")


def _probe_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, bool) or isinstance(value, int) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return None


def _select_static_root(resource_root: Path) -> Path:
    """Resolve the packaged app/web layout, retaining the checkout web-build fallback."""
    root = Path(resource_root)
    candidates = (root / "web", root / "ui" / "build" / "web")
    for candidate in candidates:
        try:
            _assert_no_reparse_components(candidate)
            if candidate.is_dir():
                return candidate
        except (OSError, UnsafePathError):
            continue
    return candidates[0]


class LocalApplication:
    def __init__(
        self,
        server: "ChaSteadyHTTPServer",
        app_root: Optional[Path] = None,
        *,
        resource_root: Optional[Path] = None,
        data_root: Optional[Path] = None,
        desktop: bool = False,
    ):
        self.server = server
        fallback_root = Path(app_root or Path(__file__).resolve().parents[2])
        self.resource_root = Path(resource_root or fallback_root).resolve(strict=True)
        self.data_root = Path(data_root or app_root or fallback_root).resolve(strict=True)
        if desktop:
            require_disjoint_roots(self.resource_root, self.data_root)
        # app_root remains a compatibility alias for existing backend callers.
        self.app_root = self.data_root
        self.desktop = bool(desktop)
        self.static_root = _select_static_root(self.resource_root)
        self.preferences = PreferenceStore(self.data_root, desktop=self.desktop)
        self.jobs = JobStore(self.data_root)
        self.runner = JobRunner(self.jobs, self.preferences)
        self.nonce = secrets.token_urlsafe(48)
        self.media_cookie = secrets.token_urlsafe(32)
        self._closed = False
        self._inspection_lock = threading.RLock()
        self._inspection_registries = set()
        self._inspection_threads = {}

    def close(self) -> None:
        with self._inspection_lock:
            if self._closed:
                return
            self._closed = True
            inspections = list(self._inspection_registries)
            inspection_threads = list(self._inspection_threads.values())
        # Mark submissions closed before doing any potentially slow cleanup.
        self.runner.shutdown(wait=0.0)
        for registry in inspections:
            registry.cancel_event.set()
            registry.terminate_all()
        self.runner.shutdown(wait=None)
        current = threading.current_thread()
        for thread in inspection_threads:
            if thread is not current and thread.is_alive():
                thread.join()

    def configured_tool(self, key: str) -> Tuple[Optional[Path], Optional[str]]:
        raw = self.preferences.get()["tool_paths"].get(key)
        if not raw:
            return None, raw
        try:
            path = resolve_local_input(raw, "configured {} executable".format(key))
            return path, str(path)
        except (OSError, ValueError, UnsafePathError):
            return None, raw

    def _gyroflow_capability(self, configured: Tuple[Optional[Path], Optional[str]]) -> Dict[str, Any]:
        executable, configured_text = configured
        report = self.resource_root / "docs" / "gyroflow_export_probe.json"
        result: Dict[str, Any] = {
            "detected": False,
            "path": str(executable) if executable is not None else configured_text,
            "mode": "cli",
            "version": None,
            "sha256": None,
            "prior_verified": False,
            "profile_safety_required": True,
            "export_verified": False,
            "trim_mapping_verified": False,
            "probe_report": str(report),
            "cli_status": "unverified",
            "validation_status": "unverified",
        }
        if executable is None:
            return result
        try:
            module = importlib.import_module(".adapters.gyroflow", package="cha_stabilizer")
            capability_fn = getattr(module, "capabilities")
            value = capability_fn({
                "executable": executable,
                "probe_report": report,
                "development_identity": self.preferences.development_config["gyroflow_identity"]
                if not self.desktop else {},
            })
        except Exception:
            # An absent or unreadable audit manifest must never inherit a prior
            # verification claim from another Gyroflow installation.
            return result
        if not isinstance(value, dict):
            return result
        result["detected"] = value.get("detected") is True
        result["mode"] = "cli"
        for key in ("version", "sha256", "probe_report", "cli_status", "validation_status"):
            field = value.get(key)
            if isinstance(field, (str, int, float, bool)) or field is None:
                result[key] = str(field) if key == "probe_report" and field is not None else field
        result["prior_verified"] = result["detected"] and value.get("prior_verified") is True
        result["export_verified"] = result["detected"] and value.get("export_verified") is True
        result["trim_mapping_verified"] = result["detected"] and value.get("trim_mapping_verified") is True
        # This is an enforced safety property, not a configurable status field.
        result["profile_safety_required"] = True
        result["path"] = str(executable)
        return result

    def capabilities(self) -> Dict[str, Any]:
        tools: Dict[str, Tuple[Optional[Path], Optional[str]]] = {
            key: self.configured_tool(key) for key in ("ffmpeg", "ffprobe", "gyroflow", "catalyst")
        }
        catalog = []
        for preset in discover_c7037_catalog():
            catalog.append(preset)
        gyroflow = self._gyroflow_capability(tools["gyroflow"])
        return {
            "ffmpeg": {
                "detected": tools["ffmpeg"][0] is not None and tools["ffprobe"][0] is not None,
                "path": tools["ffmpeg"][1],
            },
            "gyroflow": gyroflow,
            "catalyst": {
                "detected": tools["catalyst"][0] is not None,
                "path": tools["catalyst"][1],
                "mode": "assisted",
                "uia_verified": False,
            },
            "ffprobe": {"detected": tools["ffprobe"][0] is not None, "path": tools["ffprobe"][1]},
            "preset_catalog": catalog,
            "native_picker": _native_picker_available(),
        }

    def inspect_media(self, raw_path: str) -> Dict[str, Any]:
        try:
            path = resolve_local_input(raw_path, "path")
        except UnsafePathError as exc:
            raise RequestValidationError(str(exc)) from exc
        ffprobe, configured = self.configured_tool("ffprobe")
        if ffprobe is None:
            raise CapabilityUnavailable("ffprobe is not configured or is not an available regular executable file.")
        try:
            module = importlib.import_module(".core.media", package="cha_stabilizer")
            probe = getattr(module, "probe")
        except (ImportError, AttributeError) as exc:
            raise CapabilityUnavailable("The media-inspection capability is not available in this worker build.") from exc
        cancel_event = threading.Event()
        registry = OwnedProcessRegistry(cancel_event)
        with self._inspection_lock:
            if self._closed:
                raise CapabilityUnavailable("The local service is shutting down.")
            self._inspection_registries.add(registry)
            self._inspection_threads[registry] = threading.current_thread()
        timer = threading.Timer(300.0, _stop_owned_probe, args=(cancel_event, registry))
        timer.daemon = True
        timer.start()
        try:
            with registry_scope(registry):
                summary = probe(path, ffprobe, count=False, cancel=cancel_event)
            if cancel_event.is_set():
                raise CapabilityUnavailable("Media inspection was stopped with its owned ffprobe process.")
        except AppError:
            raise
        except Exception as exc:
            if cancel_event.is_set():
                raise CapabilityUnavailable("Media inspection exceeded its local time limit and was stopped safely.") from exc
            raise AppError("Media inspection failed. Confirm the selected file and configured ffprobe executable.") from exc
        finally:
            timer.cancel()
            if cancel_event.is_set():
                registry.terminate_all()
            with self._inspection_lock:
                self._inspection_registries.discard(registry)
                self._inspection_threads.pop(registry, None)
        if cancel_event.is_set():
            raise CapabilityUnavailable("Media inspection was stopped with its owned ffprobe process.")
        if not isinstance(summary, dict):
            raise AppError("The media inspector returned an invalid summary.")
        fields = (
            "width", "height", "fps", "frames", "duration", "video_codec",
            "pixel_format", "audio_codec", "bit_depth", "cfr_status", "start_time",
            "time_base", "color_transfer", "color_primaries", "color_space",
        )
        result: Dict[str, Any] = {"path": str(path), "name": path.name}
        for key in fields:
            value = summary.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                result[key] = _probe_scalar(value)
            else:
                result[key] = None
        # Expose bounded stream metadata for codec/HDR diagnosis, not arbitrary
        # format tags, source bytes, or unbounded nested ffprobe output.
        stream_fields = {
            "index", "codec_name", "codec_long_name", "profile", "codec_type",
            "width", "height", "coded_width", "coded_height", "pix_fmt",
            "bits_per_raw_sample", "bits_per_sample", "r_frame_rate", "avg_frame_rate",
            "time_base", "start_pts", "start_time", "duration_ts", "duration", "nb_frames",
            "color_range", "color_space", "color_transfer", "color_primaries", "field_order",
            "channels", "channel_layout", "sample_rate", "bit_rate",
        }
        streams = summary.get("raw_streams")
        if isinstance(streams, list):
            result["raw_streams"] = [
                {key: _probe_scalar(value)
                 for key, value in stream.items() if key in stream_fields
                 and (isinstance(value, (str, int, float, bool)) or value is None)}
                for stream in streams[:16] if isinstance(stream, dict)
            ]
        else:
            result["raw_streams"] = []
        # A ratio may be returned by the probe; expose only a stable scalar FPS.
        if result.get("fps") is not None:
            try:
                fps = float(result["fps"])
                if fps <= 0 or fps != fps or fps in (float("inf"), float("-inf")):
                    result["fps"] = None
            except (TypeError, ValueError):
                result["fps"] = None
        return result

    def pick_media(self, kind: str) -> Dict[str, Optional[str]]:
        if not _native_picker_available():
            raise CapabilityUnavailable("A native file picker is unavailable in this Python build.")
        tk = tkinter.Tk()
        tk.withdraw()
        try:
            if kind == "folder":
                selected = filedialog.askdirectory(parent=tk, mustexist=True)
            elif kind == "project":
                selected = filedialog.askopenfilename(
                    parent=tk,
                    filetypes=[("Gyroflow project", "*.gyroflow *.json"), ("All files", "*.*")],
                )
            else:
                selected = filedialog.askopenfilename(
                    parent=tk,
                    filetypes=[("Video media", "*.mp4 *.mov *.mkv *.avi *.mxf *.webm *.mts *.m2ts"), ("All files", "*.*")],
                )
        finally:
            tk.destroy()
        if not selected:
            return {"path": None}
        try:
            validate_local_path_syntax(selected, "selected path")
            selected_path = Path(selected)
            _assert_no_reparse_components(selected_path)
            if kind == "folder":
                if not selected_path.is_dir():
                    raise UnsafePathError("selected path is not a directory")
                resolved = selected_path.resolve(strict=True)
            else:
                resolved = resolve_local_input(selected, "selected path")
        except (OSError, ValueError) as exc:
            raise RequestValidationError("The selected path is not an approved local path.") from exc
        return {"path": str(resolved)}


class CapabilityUnavailable(RuntimeError):
    pass


def _stop_owned_probe(event: threading.Event, registry: OwnedProcessRegistry) -> None:
    event.set()
    registry.terminate_all()


def _native_picker_available() -> bool:
    return tkinter is not None and filedialog is not None


def discover_c7037_catalog() -> list:
    """Metadata-only preset catalog; paths are built only from user discovery."""
    from .job_runner import c7037_preset_catalog
    return c7037_preset_catalog()


def _make_handler():
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "ChaSteadyLocal"
        sys_version = ""

        @property
        def app(self) -> LocalApplication:
            return self.server.app

        def log_message(self, format_string: str, *args: Any) -> None:
            # Avoid logging Authorization, cookies, local source paths or request
            # bodies. The loopback UI has no telemetry or external log sink.
            return

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_OPTIONS(self):
            self._dispatch("OPTIONS")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_PATCH(self):
            self._dispatch("PATCH")

        def do_TRACE(self):
            self._dispatch("TRACE")

        def do_CONNECT(self):
            self._dispatch("CONNECT")

        def __getattr__(self, name):
            if name.startswith("do_"):
                method = name[3:]
                if _HTTP_METHOD_TOKEN.match(method):
                    return lambda: self._dispatch(method)
            raise AttributeError(name)

        def _dispatch(self, method: str) -> None:
            try:
                if not self._valid_host():
                    self._send_error(HTTPStatus.FORBIDDEN, "invalid_host", "This local service only accepts its loopback Host.")
                    return
                if method not in ("POST", "PUT"):
                    lengths = self.headers.get_all("Content-Length", [])
                    if self.headers.get("Transfer-Encoding") is not None or len(lengths) > 1:
                        raise BadRequest("Request bodies are not accepted for this method")
                    if lengths:
                        try:
                            length = int(lengths[0])
                        except ValueError as exc:
                            raise BadRequest("Invalid Content-Length") from exc
                        if length != 0:
                            raise BadRequest("Request bodies are not accepted for this method")
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.scheme or parsed.netloc:
                    self._send_error(HTTPStatus.BAD_REQUEST, "invalid_target", "Absolute-form request targets are not accepted.")
                    return
                route = parsed.path
                if not self._valid_origin_and_fetch():
                    self._send_error(HTTPStatus.FORBIDDEN, "invalid_origin", "Cross-origin requests are not allowed.")
                    return
                if route == "/api" or route.startswith("/api/"):
                    if route == "/api/artifacts/" or route.startswith("/api/artifacts/"):
                        self._dispatch_artifact(method, route)
                        return
                    if not self._authorized():
                        self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "A valid local session is required.")
                        return
                    if route == "/api/session" and method == "POST":
                        self._post_session()
                    elif route == "/api/health" and method in ("GET", "HEAD"):
                        checkpoint("http.health.handler_enter")
                        self._json_response(HTTPStatus.OK, {"version": __version__, "session_ready": True}, head=method == "HEAD")
                    elif route == "/api/capabilities" and method in ("GET", "HEAD"):
                        self._json_response(HTTPStatus.OK, self.app.capabilities(), head=method == "HEAD")
                    elif route == "/api/preferences" and method in ("GET", "HEAD"):
                        self._json_response(HTTPStatus.OK, self.app.preferences.get(), head=method == "HEAD")
                    elif route == "/api/preferences" and method == "PUT":
                        self._put_preferences()
                    elif route == "/api/media/inspect" and method == "POST":
                        self._post_inspect()
                    elif route == "/api/media/pick" and method == "POST":
                        self._post_pick()
                    elif route == "/api/jobs" and method in ("GET", "HEAD"):
                        self._json_response(HTTPStatus.OK, {"jobs": self.app.jobs.list()}, head=method == "HEAD")
                    elif route == "/api/jobs" and method == "POST":
                        self._post_job()
                    elif route.startswith("/api/jobs/"):
                        self._dispatch_job(method, route)
                    elif route == "/api/presets/discover" and method == "POST":
                        self._post_discover()
                    else:
                        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "API route not found.")
                    return
                if method in ("GET", "HEAD"):
                    self._serve_static(parsed.path, head=method == "HEAD")
                else:
                    self._send_error(HTTPStatus.METHOD_NOT_ALLOWED, "method_not_allowed", "This route does not accept that method.")
            except BadRequest as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, "bad_request", str(exc))
            except RequestValidationError as exc:
                self._send_error(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_request", str(exc))
            except CapabilityUnavailable as exc:
                self._send_error(HTTPStatus.CONFLICT, "missing_capability", str(exc))
            except ArtifactUnavailable as exc:
                self._send_error(HTTPStatus.NOT_FOUND, "artifact_unavailable", str(exc))
            except KeyError as exc:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", str(exc).strip("'"))
            except AppError as exc:
                self._send_error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, exc.message, exc.details)
            except (OSError, UnsafePathError) as exc:
                self._send_error(HTTPStatus.FORBIDDEN, "unsafe_path", str(exc) or "Path could not be accessed safely.")
            except ValueError as exc:
                self._send_error(HTTPStatus.CONFLICT, "conflict", str(exc))
            except Exception:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The local service could not complete the request.")

        def _valid_host(self) -> bool:
            values = self.headers.get_all("Host", [])
            raw = values[0] if len(values) == 1 else None
            if not raw or "@" in raw or "/" in raw or "\\" in raw:
                return False
            allowed = {
                "127.0.0.1:{}".format(self.server.server_port).lower(),
                "localhost:{}".format(self.server.server_port).lower(),
            }
            return raw.lower() in allowed

        def _valid_origin_and_fetch(self) -> bool:
            origins = self.headers.get_all("Origin", [])
            if len(origins) > 1:
                return False
            origin = origins[0] if origins else None
            if origin is not None:
                allowed = {
                    "http://127.0.0.1:{}".format(self.server.server_port),
                    "http://localhost:{}".format(self.server.server_port),
                }
                if origin not in allowed:
                    return False
            fetch_values = self.headers.get_all("Sec-Fetch-Site", [])
            if len(fetch_values) > 1:
                return False
            fetch_site = fetch_values[0] if fetch_values else None
            if fetch_site is not None and fetch_site.lower() not in ("same-origin", "same-site", "none"):
                return False
            return True

        def _authorized(self) -> bool:
            values = self.headers.get_all("Authorization", [])
            header = values[0] if len(values) == 1 else ""
            prefix = "Bearer "
            if not header.startswith(prefix):
                return False
            supplied = header[len(prefix):]
            return bool(supplied) and supplied.isascii() and secrets.compare_digest(supplied, self.app.nonce)

        def _read_json(self, allow_empty: bool = False) -> Any:
            if self.headers.get("Transfer-Encoding") is not None:
                raise BadRequest("Transfer-Encoding is not accepted")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) > 1:
                raise BadRequest("Only one Content-Length is accepted")
            raw_length = lengths[0] if lengths else None
            if raw_length is None:
                if allow_empty:
                    return {}
                raise BadRequest("Content-Length is required")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise BadRequest("Invalid Content-Length") from exc
            if length < 0 or length > _MAX_JSON_BYTES:
                raise BadRequest("JSON request body is too large")
            if length == 0 and allow_empty:
                return {}
            content_types = self.headers.get_all("Content-Type", [])
            if len(content_types) != 1:
                raise BadRequest("Exactly one JSON Content-Type is required")
            content_type = content_types[0].split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise BadRequest("Content-Type must be application/json")
            data = self.rfile.read(length)
            try:
                value = json.loads(
                    data.decode("utf-8"),
                    object_pairs_hook=_unique_json_object,
                    parse_constant=_reject_json_constant,
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BadRequest("Request body must be valid UTF-8 JSON") from exc
            return value

        def _post_session(self) -> None:
            payload = self._read_json(allow_empty=True)
            if payload != {}:
                raise RequestValidationError("session request body must be empty")
            cookie = "chasteady_media={}; HttpOnly; SameSite=Strict; Path=/api/artifacts/; Max-Age=86400".format(self.app.media_cookie)
            self._json_response(HTTPStatus.OK, {"session_ready": True}, extra_headers={"Set-Cookie": cookie, "Cache-Control": "no-store"})

        def _put_preferences(self) -> None:
            value = self._read_json()
            updated = self.app.preferences.update(value)
            self._json_response(HTTPStatus.OK, updated)

        def _post_inspect(self) -> None:
            payload = self._read_json()
            raw_path = validate_media_inspect(payload)
            result = self.app.inspect_media(raw_path)
            self._json_response(HTTPStatus.OK, result)

        def _post_pick(self) -> None:
            payload = self._read_json()
            kind = validate_media_pick(payload)
            result = self.app.pick_media(kind)
            self._json_response(HTTPStatus.OK, result)

        def _post_job(self) -> None:
            payload = self._read_json()
            # Validate shape before source filesystem access; JobRunner performs
            # the second normalized validation before it creates the workspace.
            validate_job_request(payload)
            job = self.app.runner.submit(payload)
            self._json_response(HTTPStatus.ACCEPTED, {"job": job})

        def _dispatch_job(self, method: str, route: str) -> None:
            parts = route.split("/")
            if len(parts) == 4 and parts[3] and _JOB_ID.match(parts[3]) and method in ("GET", "HEAD"):
                checkpoint("http.job_status.handler_enter")
                self._json_response(HTTPStatus.OK, self.app.jobs.get(parts[3]), head=method == "HEAD")
                return
            if len(parts) == 5 and parts[3] and _JOB_ID.match(parts[3]) and parts[4] == "cancel" and method == "POST":
                payload = self._read_json(allow_empty=True)
                if payload != {}:
                    raise RequestValidationError("cancel request body must be empty")
                job = self.app.runner.cancel(parts[3])
                self._json_response(HTTPStatus.OK, {"job": job})
                return
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Job route not found.")

        def _post_discover(self) -> None:
            payload = self._read_json()
            root = validate_preset_discovery(payload)
            presets = discover_c7037_presets(root)
            self.app.runner.register_discovered_presets(presets)
            self._json_response(HTTPStatus.OK, {"presets": presets})

        def _dispatch_artifact(self, method: str, route: str) -> None:
            parts = route.split("/")
            # /api/artifacts/<id>/content or /api/artifacts/<id>/open
            if len(parts) != 5 or not _ARTIFACT_ID.match(parts[3]):
                if not self._authorized():
                    self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "A valid local session is required.")
                else:
                    self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Artifact route not found.")
                return
            artifact_id, action = parts[3], parts[4]
            if action == "content" and method in ("GET", "HEAD"):
                if not self._valid_media_cookie():
                    self._send_error(HTTPStatus.UNAUTHORIZED, "media_session_required", "A local media-read session is required.")
                    return
                self._serve_artifact(artifact_id, head=method == "HEAD")
                return
            # Opening is a mutating API action and requires the bearer nonce,
            # not the media-only cookie.
            if not self._authorized():
                self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "A valid local session is required.")
                return
            if action == "open" and method == "POST":
                payload = self._read_json(allow_empty=True)
                if payload != {}:
                    raise RequestValidationError("artifact open request body must be empty")
                self._open_artifact(artifact_id)
                return
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Artifact route not found.")

        def _valid_media_cookie(self) -> bool:
            fetch_values = self.headers.get_all("Sec-Fetch-Site", [])
            if len(fetch_values) > 1:
                return False
            fetch_site = fetch_values[0] if fetch_values else None
            if fetch_site and fetch_site.lower() not in ("same-origin", "none"):
                return False
            cookie_values = self.headers.get_all("Cookie", [])
            if len(cookie_values) != 1:
                return False
            raw = cookie_values[0]
            supplied = []
            for pair in raw.split(";"):
                name, separator, value = pair.strip().partition("=")
                if separator and name == "chasteady_media":
                    supplied.append(value)
            return (
                len(supplied) == 1
                and supplied[0].isascii()
                and secrets.compare_digest(supplied[0], self.app.media_cookie)
            )

        def _artifact_file(self, artifact_id: str):
            try:
                return self.app.jobs.get_artifact(artifact_id)
            except KeyError:
                raise
            except (OSError, UnsafePathError, ValueError) as exc:
                raise ArtifactUnavailable("Artifact is no longer an owned regular file.") from exc

        def _serve_artifact(self, artifact_id: str, head: bool = False) -> None:
            artifact, path, run_dir, inputs = self._artifact_file(artifact_id)
            try:
                handle = open_validated_owned_file(path, run_dir, inputs)
            except (OSError, UnsafePathError) as exc:
                raise ArtifactUnavailable("Artifact is no longer an owned regular file.") from exc
            try:
                size = os.fstat(handle.fileno()).st_size
                start, end, status = 0, size - 1, HTTPStatus.OK
                range_values = self.headers.get_all("Range", [])
                range_header = range_values[0] if len(range_values) == 1 else None
                if len(range_values) > 1:
                    self._send_error(
                        HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                        "range_not_satisfiable",
                        "Only one artifact byte range is supported.",
                        extra_headers={"Content-Range": "bytes */{}".format(size)},
                    )
                    return
                if range_values and self.headers.get("If-Range") is None:
                    try:
                        start, end = _parse_range(range_header, size)
                    except RangeNotSatisfiable as exc:
                        self._send_error(
                            HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                            "range_not_satisfiable",
                            str(exc),
                            extra_headers={"Content-Range": "bytes */{}".format(size)},
                        )
                        return
                    status = HTTPStatus.PARTIAL_CONTENT
                length = max(0, end - start + 1)
                self.send_response(status)
                self._security_headers()
                self.send_header("Content-Type", artifact["mime"])
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "private, no-store")
                self.send_header("Content-Disposition", "inline; filename*=UTF-8''{}".format(urllib.parse.quote(artifact["label"], safe="")))
                if status == HTTPStatus.PARTIAL_CONTENT:
                    self.send_header("Content-Range", "bytes {}-{}/{}".format(start, end, size))
                self.end_headers()
                if not head and length:
                    handle.seek(start)
                    remaining = length
                    while remaining:
                        chunk = handle.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                handle.close()

        def _open_artifact(self, artifact_id: str) -> None:
            artifact, path, run_dir, inputs = self._artifact_file(artifact_id)
            mime = artifact.get("mime", "")
            if not (mime.startswith("video/") or mime.startswith("audio/") or mime.startswith("image/")):
                raise RequestValidationError("Only owned media artifacts can be opened externally.")
            # Re-check ownership immediately before handing the file to the OS.
            handle = open_validated_owned_file(path, run_dir, inputs)
            handle.close()
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                raise CapabilityUnavailable("Opening media with a local file association is unavailable on this platform.")
            startfile(str(path))
            self._json_response(HTTPStatus.ACCEPTED, {"opened": True})

        def _serve_static(self, request_path: str, head: bool = False) -> None:
            index_path = self.app.static_root / "index.html"
            if not self.app.static_root.is_dir() or not index_path.is_file():
                self._send_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "ui_not_built",
                    "The Flutter web UI has not been built into ui/build/web yet.",
                )
                return
            try:
                decoded = urllib.parse.unquote(request_path, errors="strict")
            except (UnicodeDecodeError, ValueError):
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_path", "Invalid static resource path.")
                return
            if "\x00" in decoded or "\\" in decoded or ":" in decoded:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_path", "Invalid static resource path.")
                return
            relative = decoded.lstrip("/") or "index.html"
            if Path(relative).is_absolute():
                self._send_error(HTTPStatus.FORBIDDEN, "invalid_path", "Absolute static paths are not allowed.")
                return
            parts = Path(relative).parts
            if any(part in (".", "..") for part in parts):
                self._send_error(HTTPStatus.FORBIDDEN, "invalid_path", "Static path traversal is not allowed.")
                return
            candidate = self.app.static_root.joinpath(*parts)
            try:
                if candidate.exists():
                    _assert_no_reparse_components(candidate)
                    resolved = candidate.resolve(strict=True)
                    if not _path_within(resolved, self.app.static_root.resolve(strict=True)) or not resolved.is_file():
                        raise UnsafePathError("static file escaped the UI directory")
                else:
                    # Flutter web routes are served from the one fixed index file.
                    candidate = self.app.static_root / "index.html"
                    if not candidate.is_file():
                        raise FileNotFoundError
                    _assert_no_reparse_components(candidate)
                    resolved = candidate.resolve(strict=True)
            except (OSError, UnsafePathError, RuntimeError):
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Static resource not found.")
                return
            info = resolved.stat()
            content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self._security_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(info.st_size))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not head:
                with resolved.open("rb") as handle:
                    while True:
                        chunk = handle.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")

        def _json_response(self, status: int, payload: Any, *, head: bool = False, extra_headers: Optional[Dict[str, str]] = None) -> None:
            body = json.dumps(_json_safe(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(status)
            self._security_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if not extra_headers or "Cache-Control" not in extra_headers:
                self.send_header("Cache-Control", "no-store")
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            if not head:
                checkpoint("http.json_response.write.begin")
                try:
                    self.wfile.write(body)
                finally:
                    checkpoint("http.json_response.write.end")

        def _send_error(
            self,
            status: int,
            code: str,
            message: str,
            details: Optional[Dict[str, Any]] = None,
            extra_headers: Optional[Dict[str, str]] = None,
        ) -> None:
            self.close_connection = True
            headers = dict(extra_headers or {})
            headers["Connection"] = "close"
            safe_message = _public_job_value(str(message))
            safe_details = _public_job_value(details or {})
            error_value = {"code": str(code), "message": safe_message, "details": safe_details}
            typed = typed_error_message(code, safe_message)
            if typed is not None:
                error_value["message_key"], error_value["args"] = typed[0], dict(typed[1])
            self._json_response(
                status,
                {"error": error_value},
                head=self.command == "HEAD",
                extra_headers=headers,
            )

    return Handler


class BadRequest(ValueError):
    pass


class ArtifactUnavailable(RuntimeError):
    pass


def _parse_range(header: str, size: int) -> Tuple[int, int]:
    if size <= 0 or not isinstance(header, str):
        raise RangeNotSatisfiable(size)
    match = _BYTE_RANGE.fullmatch(header)
    if match is None:
        raise RangeNotSatisfiable(size)
    first, last = match.groups()
    # At most 20 decimal digits are meaningful for local file sizes and this
    # cap avoids unbounded integer parsing from an oversized Range header.
    if (not first and not last) or len(first) > 20 or len(last) > 20:
        raise RangeNotSatisfiable(size)
    try:
        if not first:
            suffix = int(last)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(first)
            end = size - 1 if not last else int(last)
    except ValueError as exc:
        raise RangeNotSatisfiable(size) from exc
    if start >= size or end < start:
        raise RangeNotSatisfiable(size)
    return start, min(end, size - 1)


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return str(path).casefold().startswith(str(root).rstrip("/\\").casefold() + os.sep.casefold())


class RangeNotSatisfiable(ValueError):
    def __init__(self, size: int):
        super().__init__("requested byte range is not satisfiable")
        self.size = size


class ChaSteadyHTTPServer(ThreadingHTTPServer):
    """A local-only HTTP server with a per-process session nonce."""

    daemon_threads = True
    block_on_close = False
    request_queue_size = 16

    def __init__(
        self,
        app_root: Optional[Path] = None,
        port: int = 0,
        *,
        resource_root: Optional[Path] = None,
        data_root: Optional[Path] = None,
        desktop: bool = False,
    ):
        if not isinstance(port, int) or port < 0 or port > 65535:
            raise ValueError("port must be between 0 and 65535")
        fallback_root = Path(app_root or Path(__file__).resolve().parents[2])
        self.resource_root = Path(resource_root or fallback_root).resolve(strict=True)
        self.data_root = Path(data_root or app_root or fallback_root).resolve(strict=True)
        self.app_root = self.data_root
        super().__init__(("127.0.0.1", port), _make_handler())
        try:
            self.app = LocalApplication(
                self, app_root, resource_root=self.resource_root, data_root=self.data_root, desktop=desktop,
            )
        except Exception:
            ThreadingHTTPServer.server_close(self)
            raise
        self.timeout = 0.5

    @property
    def session_url(self) -> str:
        return "http://127.0.0.1:{}/#session={}".format(self.server_port, self.app.nonce)

    def server_close(self) -> None:
        try:
            self.app.close()
        finally:
            super().server_close()


def create_server(
    app_root: Optional[Path] = None,
    port: int = 0,
    *,
    resource_root: Optional[Path] = None,
    data_root: Optional[Path] = None,
    desktop: bool = False,
) -> ChaSteadyHTTPServer:
    return ChaSteadyHTTPServer(
        app_root=app_root, port=port, resource_root=resource_root, data_root=data_root, desktop=desktop,
    )
