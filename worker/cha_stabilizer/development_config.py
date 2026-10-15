"""Optional, repository-private defaults for the unfrozen development CLI."""
import json
import stat
from pathlib import Path
from typing import Any, Dict, Optional

from .paths import UnsafePathError, _assert_no_reparse_components, validate_local_path_syntax


_CONFIG_NAME = "dev_worker_config.json"
_MAX_CONFIG_BYTES = 128 * 1024
_TOOL_KEYS = frozenset(("ffmpeg", "ffprobe", "gyroflow", "catalyst"))
_IDENTITY_KEYS = frozenset(("msix_executable", "nightly_executable", "default_template"))
_EMPTY_CONFIG = {
    "tool_paths": {key: None for key in _TOOL_KEYS},
    "gyroflow_identity": {key: None for key in _IDENTITY_KEYS},
    "c7037_data_root": None,
}


def load_development_config(app_root: Path, *, enabled: bool) -> Dict[str, Any]:
    """Load a strict private config only when an unfrozen development caller opts in."""
    if not enabled:
        return _empty_config()
    path = Path(app_root) / "private" / _CONFIG_NAME
    try:
        _assert_no_reparse_components(path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_nlink", 1) != 1 or info.st_size > _MAX_CONFIG_BYTES:
            return _empty_config()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"schema_version", "tool_paths", "gyroflow_identity", "c7037_data_root"}:
            return _empty_config()
        version = data.get("schema_version")
        if isinstance(version, bool) or version != 1:
            return _empty_config()
        tool_paths = data.get("tool_paths")
        identity = data.get("gyroflow_identity")
        if not isinstance(tool_paths, dict) or set(tool_paths) - _TOOL_KEYS:
            return _empty_config()
        if not isinstance(identity, dict) or set(identity) - _IDENTITY_KEYS:
            return _empty_config()
        result = _empty_config()
        result["c7037_data_root"] = _safe_local_path(data.get("c7037_data_root"), "development c7037_data_root")
        for key, value in tool_paths.items():
            result["tool_paths"][key] = _safe_local_path(value, "development tool_paths.{}".format(key))
        for key, value in identity.items():
            result["gyroflow_identity"][key] = _safe_local_path(value, "development gyroflow_identity.{}".format(key))
        return result
    except (OSError, ValueError, TypeError, json.JSONDecodeError, UnsafePathError):
        return _empty_config()


def _safe_local_path(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("{} must be a local absolute path or null".format(name))
    validate_local_path_syntax(value, name)
    return value


def _empty_config() -> Dict[str, Any]:
    return {
        "tool_paths": dict(_EMPTY_CONFIG["tool_paths"]),
        "gyroflow_identity": dict(_EMPTY_CONFIG["gyroflow_identity"]),
        "c7037_data_root": _EMPTY_CONFIG["c7037_data_root"],
    }
