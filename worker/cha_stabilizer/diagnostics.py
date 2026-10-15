"""Opt-in, value-free checkpoints for owned desktop-worker diagnostics."""
import os
import sys
import threading
import time


_CHECKPOINT_NAMES = frozenset({
    "job.running_state_written",
    "job.registry_constructed",
    "job.registry_scope_entered",
    "job.get_kind.begin",
    "job.get_kind.end",
    "job.get_request.begin",
    "job.get_request.end",
    "job.get_run_dir.begin",
    "job.get_run_dir.end",
    "job.toolchain.begin",
    "job.toolchain.end",
    "job.adapter_import.fusion.begin",
    "job.adapter_import.fusion.end",
    "job.adapter_import.preview.begin",
    "job.adapter_import.preview.end",
    "job.adapter_import.validate.begin",
    "job.adapter_import.validate.end",
    "job.adapter_import.gyroflow_export.begin",
    "job.adapter_import.gyroflow_export.end",
    "job.action_call.begin",
    "job.action_call.end",
    "toolchain.preferences_get.begin",
    "toolchain.preferences_get.end",
    "toolchain.path.ffmpeg.begin",
    "toolchain.path.ffmpeg.end",
    "toolchain.path.ffprobe.begin",
    "toolchain.path.ffprobe.end",
    "toolchain.path.gyroflow.begin",
    "toolchain.path.gyroflow.end",
    "toolchain.path.catalyst.begin",
    "toolchain.path.catalyst.end",
    "preview.validate_request.begin",
    "preview.validate_request.end",
    "preview.local_file.begin",
    "preview.local_file.end",
    "preview.require_tools.begin",
    "preview.require_tools.end",
    "preview.safe_workdir.begin",
    "preview.safe_workdir.end",
    "preview.inspect_callback.begin",
    "preview.inspect_callback.end",
    "job_store.progress_lock.wait",
    "job_store.progress_lock.acquired",
    "job_store.progress_lock.exit",
    "job_store.write_record.begin",
    "job_store.write_record.end",
    "http.health.handler_enter",
    "http.job_status.handler_enter",
    "http.json_response.write.begin",
    "http.json_response.write.end",
})


def checkpoint(name: str) -> None:
    """Write only a fixed label, monotonic timestamp, and current thread ID."""
    if os.environ.get("CHASTEADY_TEST_CHECKPOINTS") != "1":
        return
    if not isinstance(name, str) or name not in _CHECKPOINT_NAMES:
        return
    stream = getattr(sys, "stderr", None)
    if stream is None:
        return
    line = "CHASTEADY_TEST_CHECKPOINT name={} monotonic_ns={} thread_id={}\n".format(
        name, time.monotonic_ns(), threading.get_native_id(),
    )
    try:
        stream.write(line)
        stream.flush()
    except (OSError, ValueError):
        # Diagnostic output must not change processing or shutdown behavior.
        return
