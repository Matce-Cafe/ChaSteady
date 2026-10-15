"""Owned H.264/AAC playback proxies and media-only validation, without overwrites."""
from pathlib import Path

import numpy as np

from ..diagnostics import checkpoint
from ..errors import NeedsReviewError
from ..models import validate_job_request
from ..paths import validate_owned_file
from ..core.media import local_file, probe, check_cfr, capture, verify_output, fingerprint, VIDEO_EXTENSIONS
from ..core.pipeline import require_tools, safe_workdir, check_input, write_json


def run_preview(request, workdir, toolchain, cancel, on_event):
    checkpoint("preview.validate_request.begin")
    request = validate_job_request({"kind": "preview", "request": request})["request"]
    checkpoint("preview.validate_request.end")
    checkpoint("preview.local_file.begin")
    source = local_file(request["source"], VIDEO_EXTENSIONS)
    checkpoint("preview.local_file.end")
    checkpoint("preview.require_tools.begin")
    tools = require_tools(toolchain)
    checkpoint("preview.require_tools.end")
    checkpoint("preview.safe_workdir.begin")
    workdir = safe_workdir(workdir, [source])
    checkpoint("preview.safe_workdir.end")
    checkpoint("preview.inspect_callback.begin")
    on_event("inspect", None, "探测源媒体，准备本机浏览器观看预览")
    checkpoint("preview.inspect_callback.end")
    meta = probe(source, tools["ffprobe"], cancel=cancel)
    end = request["end"] if request["end"] is not None else meta["duration"]
    fps = meta["fps"]
    if end is None or not np.isfinite(fps) or not 1 <= fps <= 120 or abs(end * fps - round(end * fps)) > 1e-5:
        raise NeedsReviewError("预览范围和帧率必须落在明确的固定帧网格")
    check_input(meta, 0., end, fps)
    timing = check_cfr(source, tools["ffprobe"], 0., end, fps, cancel)
    before = fingerprint(source)
    output, manifest = workdir / "preview.mp4", workdir / "manifest.json"
    filters = "scale=w='max(2,trunc(min(1280,iw)/2)*2)':h=-2:flags=area,format=yuv420p"
    on_event("preview_encode", None, "编码H.264/AAC观看预览；编码器未提供已核实的数值进度")
    command = [str(tools["ffmpeg"]), "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-n", "-threads", "3",
               "-protocol_whitelist", "file,pipe", "-i", str(source), "-t", "{:.9f}".format(end),
               "-map", "0:V:0", "-map", "0:a:0?", "-sn", "-dn", "-vf", filters,
               "-vsync", "0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(output)]
    result = capture(command, cancel, timeout=7200., cwd=workdir)
    with (workdir / "encoder.log").open("xb") as log:
        log.write(result.stderr)
    on_event("verify", None, "完整AV解码与实际帧数校验")
    validation = verify_output(output, tools["ffmpeg"], tools["ffprobe"], round(end * fps), fps,
                               end, meta["audio_codec"] is not None, cancel)
    validation["scope"] = "preview_media_only"
    warnings = ["8-bit H.264/AAC观看预览；保留源文件，不等于恢复位深、裁切或原片全FOV。",
                "仅媒体可播放性和帧时间戳校验，不是增稳效果评定。"]
    if fingerprint(source) != before:
        raise NeedsReviewError("源输入指纹发生改变", {"outputs": [{"path": output, "kind": "diagnostic", "mime": "video/mp4"}]})
    write_json(manifest, {"kind": "preview", "source": before, "selected_interval_timestamps": timing,
                          "validation": validation, "warnings": warnings})
    for file in (manifest, output):
        validate_owned_file(file, workdir, [source])
    return {"outputs": [
        {"path": output, "label": "本机H.264/AAC观看预览", "kind": "preview", "mime": "video/mp4",
         "metadata": validation["metadata"], "validation_scope": validation["scope"], "warnings": warnings},
        {"path": manifest, "label": "预览验证记录", "kind": "manifest", "mime": "application/json"}],
        "manifest": manifest, "warnings": warnings, "validation": validation}


def run_validation(request, workdir, toolchain, cancel, on_event):
    request = validate_job_request({"kind": "validate", "request": request})["request"]
    source = local_file(request["source"], VIDEO_EXTENSIONS)
    tools = require_tools(toolchain)
    workdir = safe_workdir(workdir, [source])
    on_event("media_validation", None, "完整AV解码，检验实际帧数与指定帧率")
    before = fingerprint(source)
    validation = verify_output(source, tools["ffmpeg"], tools["ffprobe"], request["expected_frames"],
                               request["expected_fps"], cancel=cancel)
    if fingerprint(source) != before:
        raise NeedsReviewError("输入指纹在校验期间发生改变，未标记校验成功")
    warnings = ["仅媒体校验，不验证原片全FOV、时间同步或感知增稳效果。",
                "没有指定预期帧数时，实际帧数只是读取结果，不证明源时间线完整。"]
    manifest = workdir / "manifest.json"
    write_json(manifest, {"kind": "validate", "source": before, "validation": validation, "warnings": warnings})
    validate_owned_file(manifest, workdir, [source])
    return {"outputs": [{"path": manifest, "label": "媒体校验报告", "kind": "manifest", "mime": "application/json",
                          "validation_scope": validation["scope"]}],
            "manifest": manifest, "warnings": warnings, "validation": validation}
