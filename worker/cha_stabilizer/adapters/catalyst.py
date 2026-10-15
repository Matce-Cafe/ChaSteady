"""Safe capability discovery and manual handoff for Catalyst Browse.

Catalyst Browse is a GUI product on this host. This adapter never launches or
manipulates it; the current UI Automation evidence requires a manual handoff.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..errors import CancelledError, NeedsManualError, NeedsReviewError


_MANUAL_STEPS = [
    "Open Catalyst Browse and select the original clip in Browse mode.",
    "For stabilization, use Adjust Clip on one selected clip, set the requested mark-in/mark-out range, choose the permitted stabilization controls, and Analyze.",
    "Open Export, choose a new destination and format, enable Use mark in/out points when exporting a range, and start the export manually.",
    "Keep the source clip unchanged. Verify the new output with ffprobe and a complete audio/video decode; report exact duration/frame-count differences rather than assuming the requested frame count.",
]


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _probe_record() -> Dict[str, Any]:
    path = _root() / "docs" / "catalyst_automation_probe.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _configured_executable(config: Optional[Dict[str, Any]]) -> Optional[Path]:
    config = config if isinstance(config, dict) else {}
    toolchain = config.get("toolchain")
    value = config.get("catalyst")
    if not value and isinstance(toolchain, dict):
        value = toolchain.get("catalyst")
    if isinstance(value, dict):
        value = value.get("path")
    if isinstance(value, (str, Path)) and str(value).strip():
        return Path(value).expanduser()
    return None


def capabilities(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return installed-tool detection separately from proven UI automation."""
    executable = _configured_executable(config)
    detected = executable is not None and executable.is_file()
    record = _probe_record() if detected else {}
    probe = record.get("probe", {}) if isinstance(record.get("probe"), dict) else {}
    export = record.get("export", {}) if isinstance(record.get("export"), dict) else {}
    application = record.get("application", {}) if isinstance(record.get("application"), dict) else {}
    expected_path = str(application.get("executable", record.get("executable", ""))).casefold()
    same_executable = bool(expected_path) and str(executable.resolve()).casefold() == expected_path
    uia_verified = bool(
        detected
        and same_executable
        and probe.get("uia_verified") is True
        and export.get("media_export_verified") is True
        and export.get("validation_passed") is True
    )
    if not detected:
        status = "not_detected"
    elif uia_verified:
        status = "uia_export_verified"
    elif probe.get("status") == "uia_tree_captured_unverified":
        status = "installed_no_actionable_uia_controls"
    else:
        status = "installed_manual_handoff"

    version = record.get("application", {}).get("file_version") if isinstance(record.get("application"), dict) else None
    return {
        "detected": detected,
        "path": str(executable) if detected else None,
        "mode": "assisted",
        "uia_verified": uia_verified,
        "status": status,
        "version": version,
        "profile_safety_required": True,
        "license_state": "not_verified",
        "export_verified": uia_verified,
        "manual_steps": list(_MANUAL_STEPS),
        "limitations": [
            "No official Catalyst Browse command-line export interface was found in the installed package or reviewed Sony help.",
            "The owned-window probe exposed only the top-level window; no actionable semantic controls or export were verified.",
            "Do not infer Prepare entitlement or bypass license, activation, sign-in, or terms prompts.",
            "Current CTB-based output is limited by the input's existing crop and 8-bit H.264 encoding.",
        ],
        "probe_report": str(_root() / "docs" / "catalyst_automation_probe.json"),
    }


def _validate_request(request: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(request, dict):
        raise NeedsReviewError("Catalyst request must be an object.")
    original = request.get("original")
    if not isinstance(original, (str, Path)) or not str(original).strip():
        raise NeedsReviewError("Choose an original local media file for Catalyst Browse.")
    original_path = Path(original).expanduser()
    if not original_path.is_absolute() or not original_path.is_file():
        raise NeedsReviewError(
            "Catalyst Browse requires an existing absolute local source path.",
            {"original": str(original_path)},
        )
    start = request.get("start")
    end = request.get("end")
    if start is not None or end is not None:
        try:
            start_value = float(start) if start is not None else 0.0
            end_value = float(end) if end is not None else math.inf
        except (TypeError, ValueError):
            raise NeedsReviewError("Mark-in/mark-out values must be numeric seconds.")
        if not math.isfinite(start_value) or start_value < 0 or end_value <= start_value:
            raise NeedsReviewError("Mark-in/mark-out range is invalid.", {"start": start, "end": end})
    return {"original": str(original_path), "start": start, "end": end}


def run_assisted(
    request: Dict[str, Any],
    workdir: Path,
    toolchain: Dict[str, Any],
    cancel: Any,
    on_event: Optional[Callable[[str, Optional[float], str], None]],
) -> Dict[str, Any]:
    """Stop safely at a manual handoff until owned-window export is verified."""
    if cancel is not None and getattr(cancel, "is_set", lambda: False)():
        raise CancelledError("Catalyst handoff cancelled before starting.")
    validated = _validate_request(request)
    info = capabilities({"toolchain": toolchain or {}})
    if not info["detected"]:
        raise NeedsManualError(
            "Catalyst Browse is not installed at the configured path; no export was started.",
            {
                "status": "not_detected",
                "path": info["path"],
                "request": validated,
                "next_steps": list(_MANUAL_STEPS),
            },
        )
    if not info["uia_verified"]:
        reason = (
            "Catalyst Browse was detected, but a usable owned-window UI Automation export path "
            "has not been verified. No application was launched and no media was exported."
        )
        if callable(on_event):
            on_event("catalyst_manual_handoff", None, reason)
        raise NeedsManualError(
            reason,
            {
                "status": info["status"],
                "catalyst_path": info["path"],
                "version": info["version"],
                "license_state": info["license_state"],
                "request": validated,
                "workdir": str(Path(workdir).resolve()),
                "next_steps": list(_MANUAL_STEPS),
                "warnings": info["limitations"],
            },
        )
    # Do not silently auto-enable an experimental UIA path just because a
    # metadata file claims success. A separately reviewed implementation is
    # required before this branch can ever start Catalyst.
    raise NeedsManualError(
        "Catalyst UIA evidence exists, but this adapter has no reviewed export executor.",
        {
            "status": "executor_not_implemented",
            "request": validated,
            "next_steps": list(_MANUAL_STEPS),
        },
    )
