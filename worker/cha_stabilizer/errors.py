"""Actionable failures and typed message-key mappings for the local API."""
import re
from typing import Any, Dict, Optional, Tuple


_ERROR_MESSAGE_KEYS = {
    "needs_review": "job.error.needsReview",
    "needs_manual": "job.error.needsManual",
    "cancelled": "job.error.cancelled",
    "worker_interrupted": "job.error.workerInterrupted",
    "missing_capability": "job.error.missingCapability",
    "ctb_executor_unavailable": "job.error.ctbExecutorUnavailable",
    "full_content_correspondence_unverified": "job.error.fullContentCorrespondenceUnverified",
    "processing_failed": "job.error.processingFailed",
    "media_lease_unavailable": "nativeMedia.error.leaseUnavailable",
    "unsupported_action": "nativeProtocol.error.unsupportedAction",
    "unsupported_protocol": "nativeProtocol.error.unsupportedVersion",
    "native_protocol_error": "nativeProtocol.error.generic",
    "invalid_request": "api.error.invalidRequest",
    "bad_request": "api.error.badRequest",
    "unauthorized": "api.error.unauthorized",
    "media_session_required": "api.error.mediaSessionRequired",
    "invalid_host": "api.error.invalidHost",
    "invalid_origin": "api.error.invalidOrigin",
    "invalid_target": "api.error.invalidTarget",
    "invalid_path": "api.error.invalidPath",
    "not_found": "api.error.notFound",
    "artifact_unavailable": "api.error.artifactUnavailable",
    "range_not_satisfiable": "api.error.rangeNotSatisfiable",
    "unsafe_path": "api.error.unsafePath",
    "conflict": "api.error.conflict",
    "ui_not_built": "api.error.uiNotBuilt",
    "method_not_allowed": "api.error.methodNotAllowed",
    "internal_error": "api.error.internal",
}

_PROGRESS_MESSAGE_KEYS = {
    "queued": "job.progress.queued",
    "starting": "job.progress.starting",
    "inspect": "job.progress.inspect",
    "source_acceptance": "job.progress.sourceAcceptance",
    "capability_preflight": "job.progress.capabilityPreflight",
    "ctb": "job.progress.ctb",
    "gf": "job.progress.gf",
    "correspondence": "job.progress.correspondence",
    "fresh_measurement": "job.progress.freshMeasurement",
    "final_validation": "job.progress.finalValidation",
    "gyroflow_preflight": "job.progress.gyroflowPreflight",
    "gyroflow_export": "job.progress.gyroflowExport",
    "gyroflow_export_verified": "job.progress.gyroflowExportVerified",
    "cancellation_requested": "job.progress.cancellationRequested",
    "cached_trajectory": "job.progress.cachedTrajectory",
    "fusion": "job.progress.fusion",
    "render": "job.progress.render",
    "verify": "job.progress.verify",
    "registration": "job.progress.registration",
    "quiet_tracking": "job.progress.quietTracking",
    "preview_encode": "job.progress.previewEncode",
    "media_validation": "job.progress.mediaValidation",
    "catalyst_manual_handoff": "job.progress.catalystManualHandoff",
    "needs_manual": "job.progress.needsManual",
    "needs_review": "job.progress.needsReview",
    "failed": "job.progress.failed",
    "cancelled": "job.progress.cancelled",
    "verified_media": "job.progress.verifiedMedia",
}
_COUNTER = re.compile(r"(?<!\d)(\d{1,9})\s*/\s*(\d{1,9})(?!\d)")
_KNOWN_MESSAGE_KEYS = frozenset(_ERROR_MESSAGE_KEYS.values()) | frozenset(_PROGRESS_MESSAGE_KEYS.values())


def is_known_message_key(value: Any) -> bool:
    return isinstance(value, str) and value in _KNOWN_MESSAGE_KEYS


def typed_error_message(code: Any, message: Any = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Return a stable key plus safe typed args for errors recognized by the app."""
    if not isinstance(code, str):
        return None
    key = _ERROR_MESSAGE_KEYS.get(code)
    return (key, {}) if key else None


def typed_progress_message(stage: Any, message: Any = None) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Map known progress stages to keys without changing machine stage enums."""
    if not isinstance(stage, str):
        return None
    key = _PROGRESS_MESSAGE_KEYS.get(stage)
    if key is None:
        return None
    args: Dict[str, Any] = {}
    if stage in ("render", "registration", "quiet_tracking") and isinstance(message, str):
        match = _COUNTER.search(message)
        if match:
            args = {"current": int(match.group(1)), "total": int(match.group(2))}
    return key, args


class AppError(Exception):
    code = "processing_failed"

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        *,
        message_key: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        typed = typed_error_message(self.code, message)
        self.message_key = message_key or (typed[0] if typed else None)
        self.message_args = dict(args if args is not None else (typed[1] if typed else {}))


class NeedsReviewError(AppError):
    code = "needs_review"


class NeedsManualError(AppError):
    code = "needs_manual"


class CtbExecutorUnavailableError(NeedsManualError):
    code = "ctb_executor_unavailable"


class ContentCorrespondenceUnverifiedError(NeedsReviewError):
    code = "full_content_correspondence_unverified"


class CancelledError(AppError):
    code = "cancelled"
