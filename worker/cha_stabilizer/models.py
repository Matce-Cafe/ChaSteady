"""Request models and strict validation for the local ChaSteady API.

The public API deliberately accepts paths and typed options, never commands,
output destinations, or per-job executable overrides.
"""
import math
from typing import Any, Dict, List, Mapping, Optional


JOB_KINDS = frozenset(("fusion", "preview", "gyroflow_export", "catalyst_assisted", "validate"))
JOB_STATES = frozenset(("queued", "running", "needs_manual", "needs_review", "failed", "cancelled", "verified_media"))
TERMINAL_STATES = frozenset(("needs_manual", "needs_review", "failed", "cancelled", "verified_media"))
THEME_MODES = frozenset(("system", "light", "dark"))
LANGUAGE_MODES = frozenset(("system", "zh", "en"))


class RequestValidationError(ValueError):
    """An invalid or unsafe API payload, suitable for an HTTP 422 response."""


def _object(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise RequestValidationError("{} must be an object".format(name))
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set, name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RequestValidationError("{} contains unsupported fields".format(name))


def _path_text(value: Any, name: str, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise RequestValidationError("{} must be a non-empty path string".format(name))
    if "\x00" in value:
        raise RequestValidationError("{} contains an invalid path".format(name))
    # Lexical path rejection occurs before any filesystem check. Import lazily to
    # avoid making path helpers depend on model validation.
    from .paths import validate_local_path_syntax
    try:
        validate_local_path_syntax(value, name)
    except ValueError as exc:
        raise RequestValidationError(str(exc)) from exc
    return value


def _finite_number(value: Any, name: str, optional: bool = False) -> Optional[float]:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestValidationError("{} must be a number".format(name))
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise RequestValidationError("{} must be finite".format(name)) from exc
    if not math.isfinite(result):
        raise RequestValidationError("{} must be finite".format(name))
    return result


def _time_range(value: Mapping[str, Any], *, require_start: bool = True) -> Dict[str, Optional[float]]:
    start = _finite_number(value.get("start"), "start", optional=not require_start)
    end = _finite_number(value.get("end"), "end", optional=True)
    if start is not None and start < 0:
        raise RequestValidationError("start must be non-negative")
    if end is not None and end < 0:
        raise RequestValidationError("end must be non-negative")
    if start is not None and end is not None and end <= start:
        raise RequestValidationError("end must be greater than start")
    return {"start": start, "end": end}


def validate_job_request(payload: Any) -> Dict[str, Any]:
    """Return a normalized request for one documented job kind."""
    raw = _object(payload, "job")
    _reject_unknown(raw, {"kind", "request"}, "job")
    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in JOB_KINDS:
        raise RequestValidationError("kind must be one of the supported job kinds")
    request = _object(raw.get("request", {}), "request")

    if kind == "fusion":
        allowed = {
            "original", "ctb", "reference", "start", "end", "ctb_origin",
            "reference_origin", "reference_intervals", "reference_fov", "quiet_sigma_seconds",
            "mode", "legacy_quiet_cache", "legacy_reference_cache",
        }
        _reject_unknown(request, allowed, "fusion request")
        result: Dict[str, Any] = {
            "original": _path_text(request.get("original"), "original"),
            "ctb": _path_text(request.get("ctb"), "ctb"),
            "reference": _path_text(request.get("reference"), "reference"),
        }
        fusion_range = _time_range(request)
        if fusion_range["end"] is None:
            raise RequestValidationError("fusion end is required")
        result.update(fusion_range)
        for key in ("ctb_origin", "reference_origin"):
            result[key] = _finite_number(request.get(key, 0), key)
        reference_fov = _finite_number(request.get("reference_fov", 1.0), "reference_fov")
        if reference_fov < 1.0 or reference_fov > 4.0:
            raise RequestValidationError("reference_fov must be between 1 and 4")
        result["reference_fov"] = reference_fov
        intervals = request.get("reference_intervals", [])
        if not isinstance(intervals, list):
            raise RequestValidationError("reference_intervals must be an array")
        result_intervals: List[Dict[str, float]] = []
        for index, interval in enumerate(intervals):
            interval_obj = _object(interval, "reference_intervals[{}]".format(index))
            _reject_unknown(interval_obj, {"start", "end"}, "reference interval")
            bounds = _time_range(interval_obj)
            if bounds["end"] is None:
                raise RequestValidationError("reference interval end is required")
            result_intervals.append({"start": bounds["start"], "end": bounds["end"]})
        result["reference_intervals"] = result_intervals
        quiet_sigma = _finite_number(request.get("quiet_sigma_seconds", 1.3), "quiet_sigma_seconds")
        if quiet_sigma <= 0 or quiet_sigma > 10.0:
            raise RequestValidationError("quiet_sigma_seconds must be greater than 0 and at most 10")
        result["quiet_sigma_seconds"] = quiet_sigma
        mode = request.get("mode", "fresh")
        if mode not in ("fresh", "cached_v9"):
            raise RequestValidationError("mode must be fresh or cached_v9")
        result["mode"] = mode
        quiet_cache = _path_text(request.get("legacy_quiet_cache"), "legacy_quiet_cache", optional=True)
        reference_cache = _path_text(request.get("legacy_reference_cache"), "legacy_reference_cache", optional=True)
        if mode == "cached_v9" and (quiet_cache is None or reference_cache is None):
            raise RequestValidationError("cached_v9 requires both explicit legacy cache paths")
        if mode == "fresh" and (quiet_cache is not None or reference_cache is not None):
            raise RequestValidationError("legacy cache paths are only accepted for cached_v9")
        result["legacy_quiet_cache"] = quiet_cache
        result["legacy_reference_cache"] = reference_cache
        return {"kind": kind, "request": result}

    if kind == "preview":
        allowed = {"source", "start", "end"}
        _reject_unknown(request, allowed, "preview request")
        result = {"source": _path_text(request.get("source"), "source")}
        preview_range = dict(request)
        preview_range.setdefault("start", 0)
        result.update(_time_range(preview_range))
        if result["start"] is None or result["start"] != 0:
            raise RequestValidationError("preview start must be 0")
        return {"kind": kind, "request": result}

    if kind == "validate":
        allowed = {"source", "expected_frames", "expected_fps"}
        _reject_unknown(request, allowed, "validation request")
        result = {"source": _path_text(request.get("source"), "source")}
        frames = request.get("expected_frames")
        if frames is not None:
            if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
                raise RequestValidationError("expected_frames must be a positive integer")
        result["expected_frames"] = frames
        fps = _finite_number(request.get("expected_fps"), "expected_fps", optional=True)
        if fps is not None and fps <= 0:
            raise RequestValidationError("expected_fps must be positive")
        result["expected_fps"] = fps
        return {"kind": kind, "request": result}

    if kind == "gyroflow_export":
        allowed = {"original", "project_template", "start", "end", "full_source", "output_preset"}
        _reject_unknown(request, allowed, "gyroflow_export request")
        result = {
            "original": _path_text(request.get("original"), "original"),
            "project_template": _path_text(request.get("project_template"), "project_template", optional=True),
        }
        bounds = _time_range(request, require_start=False)
        full_source = request.get("full_source", False)
        if not isinstance(full_source, bool):
            raise RequestValidationError("full_source must be a boolean")
        if full_source and ("start" in request or "end" in request):
            raise RequestValidationError("full_source cannot be combined with start or end")
        if not full_source:
            if bounds["start"] is None or bounds["end"] is None:
                raise RequestValidationError("start and end are required unless full_source is explicitly true")
            result.update(bounds)
        # For full_source, omit trim keys entirely. Their absence is meaningful
        # and adapter-side validation must accept the normalized request again.
        result["full_source"] = full_source
        output_preset = request.get("output_preset", "reference_1080p")
        if not isinstance(output_preset, str) or output_preset not in ("reference_1080p", "reference_720p"):
            raise RequestValidationError("output_preset must be reference_1080p or reference_720p")
        result["output_preset"] = output_preset
        return {"kind": kind, "request": result}

    # Catalyst is explicitly assisted, not an arbitrary UI automation payload.
    allowed = {"original", "start", "end"}
    _reject_unknown(request, allowed, "catalyst_assisted request")
    result = {"original": _path_text(request.get("original"), "original")}
    bounds = _time_range(request, require_start=False)
    if (bounds["start"] is None) != (bounds["end"] is None):
        raise RequestValidationError("start and end must both be provided when trimming Catalyst assistance")
    result.update(bounds)
    return {"kind": kind, "request": result}


def validate_media_inspect(payload: Any) -> str:
    raw = _object(payload, "media inspect")
    _reject_unknown(raw, {"path"}, "media inspect")
    return _path_text(raw.get("path"), "path") or ""


def validate_media_pick(payload: Any) -> str:
    raw = _object(payload, "media pick")
    _reject_unknown(raw, {"kind"}, "media pick")
    kind = raw.get("kind")
    if kind not in ("video", "project", "folder"):
        raise RequestValidationError("kind must be video, project, or folder")
    return kind


def validate_preferences_update(payload: Any) -> Dict[str, Any]:
    raw = _object(payload, "preferences")
    _reject_unknown(raw, {"theme_mode", "seed_color", "tool_paths", "language_mode"}, "preferences")
    result: Dict[str, Any] = {}
    if "language_mode" in raw:
        mode = raw["language_mode"]
        if not isinstance(mode, str) or mode not in LANGUAGE_MODES:
            raise RequestValidationError("language_mode must be system, zh, or en")
        result["language_mode"] = mode
    if "theme_mode" in raw:
        mode = raw["theme_mode"]
        if not isinstance(mode, str) or mode not in THEME_MODES:
            raise RequestValidationError("theme_mode must be system, light, or dark")
        result["theme_mode"] = mode
    if "seed_color" in raw:
        seed = raw["seed_color"]
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 or seed > 0xFFFFFFFF:
            raise RequestValidationError("seed_color must be an unsigned 32-bit ARGB integer")
        result["seed_color"] = seed
    if "tool_paths" in raw:
        paths = _object(raw["tool_paths"], "tool_paths")
        _reject_unknown(paths, {"ffmpeg", "ffprobe", "gyroflow", "catalyst"}, "tool_paths")
        from .paths import validate_local_path_syntax
        normalized: Dict[str, Optional[str]] = {}
        for name, value in paths.items():
            if value is None:
                normalized[name] = None
            else:
                if not isinstance(value, str) or not value or value != value.strip():
                    raise RequestValidationError("tool_paths.{} must be an absolute path or null".format(name))
                try:
                    validate_local_path_syntax(value, "tool_paths.{}".format(name))
                except ValueError as exc:
                    raise RequestValidationError(str(exc)) from exc
                normalized[name] = value
        result["tool_paths"] = normalized
    if not result:
        raise RequestValidationError("preferences update must change at least one supported setting")
    return result


def validate_preset_discovery(payload: Any) -> str:
    raw = _object(payload, "preset discovery")
    _reject_unknown(raw, {"experiment_root"}, "preset discovery")
    return _path_text(raw.get("experiment_root"), "experiment_root") or ""
