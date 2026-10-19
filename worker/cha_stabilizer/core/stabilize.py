"""单原片顺序编排；能力或对应证据不足时保留真实终态，不制造下游进度。"""
import hashlib
import json
import math
import os
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .. import __version__
from ..errors import CancelledError, CtbExecutorUnavailableError, ContentCorrespondenceUnverifiedError, NeedsManualError, NeedsReviewError
from ..models import STABILIZE_PROFILE, STABILIZE_PARAMETERS, STABILIZE_PARAMETER_BOUNDS
from ..paths import resolve_local_input, validate_owned_file
from ..runtime_context import RunnerContext
from .bounded_io import capture_small
from .media import VIDEO_EXTENSIONS, local_file, probe, verify_output
from .pipeline import check_input, write_json


def full_file_identity(path, cancel=None, *, timeout=1800.0, max_bytes=None):
    path = resolve_local_input(str(path), "identity input")
    digest = hashlib.sha256()
    started = time.monotonic()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        total = 0
        if max_bytes is not None and before.st_size > max_bytes:
            raise NeedsReviewError("File identity exceeds its declared byte budget.")
        while True:
            if cancel is not None and cancel.is_set():
                raise CancelledError("Source identity validation was cancelled.")
            if time.monotonic() - started > timeout:
                raise NeedsReviewError("Full file identity exceeded its bounded time budget.")
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise NeedsReviewError("File identity grew beyond its declared byte budget.")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    current = resolve_local_input(str(path), "identity input").stat()
    # Windows 3.15 的路径 stat 与句柄 fstat 对 ctime 可能分别返回创建/更改时间。
    # 两次句柄 ctime 仍须精确相同；路径身份用 size/mtime/device/file-id 精确交叉核对。
    fields = ("st_size", "st_mtime_ns", "st_dev", "st_ino")
    if before.st_ctime_ns != after.st_ctime_ns or any(
        getattr(before, key) != getattr(value, key) for value in (after, current) for key in fields
    ):
        raise NeedsReviewError("Source identity changed while the full hash was being read.")
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": before.st_size,
            "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns,
            "device": before.st_dev, "file_id": before.st_ino, "hash_scope": "full_file"}


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _algorithm_identity(cancel):
    if getattr(sys, "frozen", False):
        return {"worker_version": __version__, "frozen_worker": full_file_identity(Path(sys.executable), cancel)}
    root = Path(__file__).resolve().parents[1]
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(root.rglob("*.py"))}
    return {"worker_version": __version__, "source_sha256": _canonical_hash(hashes), "source_files": hashes}


def _template(toolchain):
    context = toolchain.get("_runner_context")
    if isinstance(context, RunnerContext) and context.production:
        # 生产尚无已审、源与镜头绑定的推荐模板；不能偷用私有开发配置。
        return None
    raw = (toolchain.get("development_identity") or {}).get("default_template")
    if raw:
        try:
            return resolve_local_input(str(raw), "development template")
        except (OSError, ValueError):
            pass
    return None


def capability(toolchain):
    from ..adapters import gyroflow
    blockers = ["ctb_executor_unavailable"]
    if not toolchain.get("ffmpeg") or not toolchain.get("ffprobe"):
        blockers.append("ffmpeg_and_ffprobe_unavailable")
    executable = toolchain.get("gyroflow")
    identity = None
    if executable:
        try:
            identity = gyroflow._identity_for_toolchain(Path(executable), gyroflow._sha256_file(Path(executable)), toolchain)
        except (OSError, ValueError):
            pass
    if not identity or not identity.get("direct_cli_launch_supported"):
        blockers.append("gyroflow_identity_unverified_or_cli_blocked")
    if _template(toolchain) is None:
        blockers.append("gyroflow_template_unavailable")
    return {"workflow_version": 1, "available": False, "automatic_ctb_exports": 0,
            "ctb_automatic": False, "continuation_supported": True, "blocking_codes": blockers,
            "content_correspondence_verified": False,
            "profiles": [{"id": STABILIZE_PROFILE, "parameters": dict(STABILIZE_PARAMETERS),
                          "parameter_bounds": {key: dict(value) for key, value in STABILIZE_PARAMETER_BOUNDS.items()}}]}


def _tool_identity(name, path, cancel):
    identity = full_file_identity(path, cancel)
    if name in ("ffmpeg", "ffprobe"):
        version = capture_small([str(path), "-version"], cancel, timeout=30.0, max_bytes=65536)
        lines = version.decode("utf-8", errors="replace").splitlines()
        if not lines:
            raise NeedsReviewError("The configured media tool returned no actual version identity.")
        identity["actual_version"] = lines[0][:500]
    elif name == "gyroflow":
        from ..adapters.gyroflow import _pe_version
        identity["actual_file_version"] = _pe_version(Path(path))
    return identity


def _copy_manual(source, destination, cancel, *, max_bytes=None):
    before = full_file_identity(source, cancel, max_bytes=max_bytes)
    started = time.monotonic()
    total = 0
    with Path(source).open("rb") as original, Path(destination).open("xb") as output:
        while True:
            if time.monotonic() - started > 1800.0:
                raise NeedsReviewError("Manual CTB import exceeded its bounded time budget.")
            if cancel.is_set():
                raise CancelledError("Manual CTB import was cancelled.")
            chunk = original.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise NeedsReviewError("Owned input snapshot exceeded its declared byte budget.")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    after = full_file_identity(source, cancel, max_bytes=max_bytes)
    copied = full_file_identity(destination, cancel, max_bytes=max_bytes)
    if before != after or before["sha256"] != copied["sha256"] or before["bytes"] != copied["bytes"]:
        raise NeedsReviewError("The manual CTB source changed during its owned import.")
    return before, copied


def _validation_summary(validation):
    # job.json 只保留门禁必需的有界摘要，不持久化任意 format/tags/raw_streams。
    def scalar(value):
        if isinstance(value, str):
            return value[:160]
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        return None

    def select(value, keys):
        if not isinstance(value, dict):
            return {}
        return {key: scalar(value[key]) for key in keys if key in value}

    summary = select(validation, ("status", "scope", "verified_media", "frame_count_verified", "full_decode_passed",
                                  "decode_scope", "frame_timestamp_spacing_verified", "original_fov_verified", "perceptual_winner_claimed"))
    summary["metadata"] = select(validation.get("metadata", {}), (
        "width", "height", "fps", "frames", "duration", "video_codec", "pixel_format", "audio_codec", "bit_depth",
        "start_time", "time_base", "color_transfer", "color_primaries", "color_space", "cfr_status"))
    summary["frame_timestamps"] = select(validation.get("frame_timestamps", {}), (
        "sampled_frames", "maximum_step_error", "first_timestamp", "last_timestamp", "scope"))
    summary["metadata_scope"] = "bounded_required_media_fields_only_no_format_tags_or_raw_streams"
    return summary


def _source_timeline(metadata):
    fps, duration = metadata.get("fps"), metadata.get("duration")
    frames = metadata.get("frames")
    if (not isinstance(fps, (float, int)) or isinstance(fps, bool) or not math.isfinite(fps) or not 1 <= fps <= 120
            or not isinstance(duration, (float, int)) or isinstance(duration, bool) or not math.isfinite(duration) or duration <= 0):
        raise NeedsReviewError("The original source has no supported bounded CFR metadata timeline.")
    if isinstance(frames, bool) or not isinstance(frames, int) or not 3 <= frames <= 30000:
        raise NeedsReviewError("A bounded container frame count is required before full-source processing; no frame count was guessed.")
    stream = next((item for item in metadata.get("raw_streams", []) if item.get("codec_type") == "video"
                   and not item.get("disposition", {}).get("attached_pic")), {})
    text = str(stream.get("duration") or duration)
    try:
        if len(text) > 80:
            raise InvalidOperation
        decimal = Decimal(text)
        if not decimal.is_finite():
            raise InvalidOperation
        # 仅补偿最多一微秒小数单位的量化，不改实际 PTS/CFR/帧数验证阈值。
        quantum = min(Decimal(1).scaleb(decimal.as_tuple().exponent), Decimal("0.000001"))
        tolerance = float(quantum / 2) + 1e-12
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise NeedsReviewError("The container duration has no bounded decimal precision.") from exc
    end = frames / fps
    if abs(duration - end) > tolerance:
        raise NeedsReviewError("Container frame count and rounded duration disagree; no resampling or estimated count was accepted.")
    return {"start": 0.0, "end": end, "fps": fps, "frames": frames, "full_source": True,
            "container_duration_seconds": duration, "metadata_duration_rounding_tolerance_seconds": tolerance,
            "frame_count_basis": "container_nb_frames_metadata_not_decoded_count", "frame_count_verified": False}


def _accept_manual(manual, original, workdir, metadata, toolchain, cancel, store, job_id):
    imported = workdir / ("manual-ctb" + Path(manual["source"]).suffix.lower())
    local_file(manual["source"], VIDEO_EXTENSIONS)
    source_ctb, copied_ctb = _copy_manual(manual["source"], imported, cancel)
    validate_owned_file(imported, workdir, [original, Path(manual["source"])])
    declaration = {"origin": "manual_import", "source": source_ctb, "owned": copied_ctb, "declaration": manual}
    store.bind_workflow_identity(job_id, "manual_ctb", declaration)
    artifact = store.add_artifact(job_id, path=imported, label="Manual CTB import · not automatic", kind="intermediate",
                                 mime="video/mp4" if imported.suffix == ".mp4" else "application/octet-stream",
                                 metadata={"origin": "manual_import", "sha256": copied_ctb["sha256"]},
                                 validation_scope="manual_import_full_hash_only_no_content_correspondence",
                                 inputs=[original, Path(manual["source"])])
    if manual["origin_seconds"] != 0.0:
        raise NeedsReviewError("A full-source continuation requires the declared manual CTB origin to be zero.")
    validation = verify_output(imported, toolchain["ffmpeg"], toolchain["ffprobe"],
                               metadata["frames"], metadata["fps"],
                               metadata["duration"], cancel=cancel)
    store.bind_workflow_identity(job_id, "manual_ctb_validation", _validation_summary(validation))
    return imported, artifact


def fusion_request_for_profile(request, *, ctb, reference, duration):
    # 只由服务器构造 fresh 请求；不接受历史缓存，也不推广 C7037 人工参考窗口。
    return dict(request["parameters"], original=request["original"], ctb=str(ctb), reference=str(reference),
                start=0.0, end=duration, ctb_origin=0.0, reference_origin=0.0, reference_intervals=[], mode="fresh")


def run_stabilize(request, workdir, toolchain, cancel, on_event, *, store, job_id):
    context = toolchain.get("_runner_context")
    if not isinstance(context, RunnerContext):
        raise NeedsReviewError("Stabilization requires an immutable trusted runner context.")
    workdir = context.validate(Path(workdir))

    def start(stage, text):
        if cancel.is_set():
            raise CancelledError("Stabilization was cancelled before the next stage.")
        store.workflow_stage(job_id, stage, "running")
        on_event(stage, None, text)

    def passed(stage, evidence):
        store.workflow_stage(job_id, stage, "passed", evidence=evidence)

    start("source_acceptance", "Reading the original source and its full immutable identity.")
    original = local_file(request["original"], VIDEO_EXTENSIONS)
    original_identity = full_file_identity(original, cancel)
    parameters_identity = {"profile": request["profile"], "parameters": request["parameters"], "full_source": True}
    parent = request.get("_parent_identity")
    if parent and (parent.get("original") != original_identity or parent.get("parameters") != parameters_identity):
        raise NeedsReviewError("The parent source or frozen parameters changed; continuation was not accepted.")
    store.bind_workflow_identity(job_id, "original", original_identity)
    store.bind_workflow_identity(job_id, "parameters", parameters_identity)
    store.bind_workflow_identity(job_id, "algorithm", _algorithm_identity(cancel))
    metadata = None
    if not toolchain.get("ffprobe"):
        raise NeedsManualError("Source media acceptance requires a configured ffprobe; no engine export was started.",
                               {"blocking_codes": ["ffprobe_unavailable", "ctb_executor_unavailable"],
                                "automatic_ctb_exports": 0})
    if toolchain.get("ffprobe"):
        metadata = probe(original, toolchain["ffprobe"], cancel=cancel)
        timeline = _source_timeline(metadata)
        check_input(metadata, 0.0, metadata["duration"], metadata["fps"])
        store.bind_workflow_identity(job_id, "source_range", timeline)
        # 实际帧数与 PTS 尚待后续完整门禁；规范化边界只用于精确源帧网格。
        metadata = dict(metadata, duration=timeline["end"], frames=timeline["frames"])
    imported = ctb_artifact = None
    manual = request.get("manual_ctb")
    if manual and metadata is not None and toolchain.get("ffmpeg") and toolchain.get("ffprobe"):
        imported, ctb_artifact = _accept_manual(manual, original, workdir, metadata, toolchain, cancel, store, job_id)
    passed("source_acceptance", {"full_hash_recorded": True, "media_inspected": metadata is not None,
                                "manual_ctb_owned_artifact_id": ctb_artifact["id"] if ctb_artifact else None})

    start("capability_preflight", "Checking legal engine capability before any export process is started.")
    report = capability(toolchain)
    store.bind_workflow_identity(job_id, "capability_preflight", report)
    manual = request.get("manual_ctb")
    if not manual:
        raise CtbExecutorUnavailableError(
            "No verified legal automatic Catalyst executor is available; no CTB or GF export was started.",
            {"blocking_codes": report["blocking_codes"], "automatic_ctb_exports": 0,
             "continuation_kind": "stabilize_continue", "manual_ctb_is_automatic": False},
        )
    blockers = [code for code in report["blocking_codes"] if code != "ctb_executor_unavailable"]
    if blockers:
        raise NeedsManualError("Manual continuation still lacks a required verified processing capability.",
                               {"blocking_codes": blockers, "automatic_ctb_exports": 0})
    if metadata is None:
        raise NeedsReviewError("The original source has not passed media acceptance.")
    for name in ("ffmpeg", "ffprobe", "gyroflow"):
        store.bind_workflow_identity(job_id, name, _tool_identity(name, toolchain[name], cancel))
    template = _template(toolchain)
    if template.stat().st_size > 2 * 1024 ** 2:
        raise NeedsReviewError("The selected template exceeds its bounded snapshot budget.")
    template_snapshot = workdir / "gf-template-input.gyroflow"
    template_source_identity, template_snapshot_identity = _copy_manual(template, template_snapshot, cancel, max_bytes=2 * 1024 ** 2)
    store.bind_workflow_identity(job_id, "template", {"source": template_source_identity,
                                                    "owned_snapshot": template_snapshot_identity})
    passed("capability_preflight", {"manual_ctb_is_automatic": False, "automatic_ctb_exports": 0})

    start("ctb", "Using the revalidated owned manual CTB import; this is not automatic CTB.")
    if imported is None or ctb_artifact is None:
        raise NeedsReviewError("The manual CTB has not passed owned import and media acceptance.")
    passed("ctb", {"origin": "manual_import", "artifact_id": ctb_artifact["id"], "automatic_ctb_exports": 0})

    start("gf", "Exporting a fresh GF reference from the same original source, never from CTB or a pretrim.")
    from ..adapters.gyroflow import run_export
    gf = run_export({"original": str(original), "project_template": str(template_snapshot), "full_source": True,
                     "output_preset": "reference_1080p"}, workdir, dict(toolchain, _fresh_source_project=True), cancel, on_event)
    gf_outputs = []
    for output in gf["outputs"]:
        artifact = store.add_artifact(job_id, path=Path(output["path"]), label=output.get("label", "GF reference"),
                                      kind="intermediate", mime=output.get("mime", "application/octet-stream"),
                                      metadata=output.get("metadata", {}), validation_scope=output.get("validation_scope"),
                                      warnings=output.get("warnings", []), inputs=[original, template, template_snapshot, imported])
        gf_outputs.append({"artifact_id": artifact["id"], "identity": full_file_identity(output["path"], cancel)})
    try:
        template_source_unchanged = full_file_identity(template, cancel, max_bytes=2 * 1024 ** 2) == template_source_identity
        template_snapshot_unchanged = full_file_identity(template_snapshot, cancel, max_bytes=2 * 1024 ** 2) == template_snapshot_identity
    except (OSError, ValueError):
        template_source_unchanged = template_snapshot_unchanged = False
    store.bind_workflow_identity(job_id, "gf", {"source": original_identity, "outputs": gf_outputs,
                                              "template_sha256": template_snapshot_identity["sha256"],
                                              "template_source_unchanged": template_source_unchanged,
                                              "template_snapshot_unchanged": template_snapshot_unchanged,
                                              "project_input_sha256_before": gf["validation"].get("project_input_sha256_before"),
                                              "validation": gf["validation"]})
    if not template_source_unchanged or not template_snapshot_unchanged:
        raise NeedsReviewError("The template source or owned snapshot changed; GF provenance retains the actual pre-export template identity, not the replacement hash.")
    if full_file_identity(original, cancel) != original_identity:
        raise NeedsReviewError("The original source changed during the engine stages.")
    passed("gf", {"artifact_ids": [item["artifact_id"] for item in gf_outputs], "fresh_original_input": True})

    start("correspondence", "Checking the declared time/content correspondence gate independently of engine exit codes.")
    # 当前只有完整 PTS、帧数及 AV 解码；有限内容抽样也不能升级为全源逐帧对应。
    write_json(workdir / "correspondence.json", {"schema_version": 1, "status": "needs_review",
               "full_source_content_correspondence_verified": False, "gf_validation": gf["validation"],
               "manual_ctb_origin_seconds": manual["origin_seconds"], "parameters": parameters_identity,
               "fresh_measurement_started": False, "legacy_trajectory_reused": False})
    raise ContentCorrespondenceUnverifiedError("Full-source decoded content correspondence remains unverified; fresh measurement, fusion, render and preview were not started.",
                           {"blocking_codes": ["full_content_correspondence_unverified"],
                            "content_correspondence_verified": False, "automatic_ctb_exports": 0,
                            "outputs": [{"path": workdir / "correspondence.json", "label": "Correspondence gate evidence",
                                         "kind": "diagnostic", "mime": "application/json"}]})
