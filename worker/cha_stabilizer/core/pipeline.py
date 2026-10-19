"""Local fusion pipeline with explicit provenance and bounded verification scope."""
import json
from pathlib import Path

import cv2
import numpy as np

from ..errors import NeedsReviewError
from ..models import validate_job_request
from ..paths import validate_owned_file, ensure_not_alias, _assert_no_reparse_components
from .cache import load_legacy
from .fusion import FusionSettings, anchored_blend, interval_gains
from .geometry import check_unit
from .media import local_file, probe, check_cfr, fingerprint, VIDEO_EXTENSIONS
from .registration import register_videos
from .render import render_preview
from .tracking import quiet_trajectory


def write_json(path, content):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(content, stream, ensure_ascii=False, indent=2, allow_nan=False)


def require_tools(tools):
    if not tools.get("ffmpeg") or not tools.get("ffprobe"):
        raise NeedsReviewError("请先配置本机FFmpeg和ffprobe，不下载或猜测可执行文件")
    return {"ffmpeg": local_file(tools["ffmpeg"]), "ffprobe": local_file(tools["ffprobe"])}


def safe_workdir(workdir, inputs):
    path = Path(workdir)
    _assert_no_reparse_components(path)
    if not path.is_dir():
        raise NeedsReviewError("处理目录必须已存在且由本工具拥有")
    for name in ("preview.mp4", "manifest.json", "trajectory.npz", "failure.json"):
        target = path / name
        if target.exists():
            raise FileExistsError(str(target))
        ensure_not_alias(target, inputs)
    return path


def check_input(meta, start, end, fps):
    if meta["cfr_status"] != "metadata_consistent" or abs(meta["fps"] - fps) > 1e-5:
        raise NeedsReviewError("输入帧率不一致或无法确认，不静默重采样")
    if abs(meta["start_time"]) > 1e-4:
        raise NeedsReviewError("输入视频存在非零首PTS，必须先核查时间映射")
    if meta["duration"] is None or start < 0 or end > meta["duration"] + 1e-4:
        raise NeedsReviewError("输入不覆盖选定时间范围")
    if meta["color_transfer"] in ("smpte2084", "arib-std-b67"):
        raise NeedsReviewError("当前预览管线未认证HDR色调映射，拒绝伪装成正确SDR输出")
    if meta.get("color_primaries") not in (None, "unknown", "unspecified", "bt709"):
        raise NeedsReviewError("当前预览未认证非BT.709原色色域转换，不仅修改颜色标签")
    if meta.get("color_transfer") not in (None, "unknown", "unspecified", "bt709"):
        raise NeedsReviewError("当前预览未认证非BT.709传递函数转换，不仅修改颜色标签")
    stream = next(s for s in meta["raw_streams"] if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic"))
    if stream.get("sample_aspect_ratio") not in (None, "N/A", "0:1", "1:1"):
        raise NeedsReviewError("当前管线不支持非方形像素")
    if stream.get("field_order") not in (None, "unknown", "progressive"):
        raise NeedsReviewError("当前管线不支持隔行视频")
    if any(abs(float(item.get("rotation", 0))) > 1e-6 for item in stream.get("side_data_list", [])):
        raise NeedsReviewError("旋转显示元数据需要专门映射，不在当前管线静默旋转")


def run_fusion(request, workdir, toolchain, cancel, on_event):
    request = validate_job_request({"kind": "fusion", "request": request})["request"]
    tools = require_tools(toolchain)
    paths = {key: local_file(request[key], VIDEO_EXTENSIONS) for key in ("original", "ctb", "reference")}
    inputs = list(paths.values())
    for i, first in enumerate(inputs):
        ensure_not_alias(first, inputs[i + 1:])
    workdir = safe_workdir(workdir, inputs)
    cv2.setNumThreads(4)
    start, end = request["start"], request["end"]
    on_event("inspect", None, "探测输入与所选源帧时间戳")
    metadata = {key: probe(path, tools["ffprobe"], cancel=cancel) for key, path in paths.items()}
    before = {key: fingerprint(path) for key, path in paths.items()}
    fps = metadata["original"]["fps"]
    if not np.isfinite(fps) or not 1 <= fps <= 120:
        raise NeedsReviewError("当前预览只支持已核实的1–120fps固定帧率")
    for value in (start, end, request["ctb_origin"], request["reference_origin"]):
        if value < 0 or abs(value * fps - round(value * fps)) > 1e-5:
            raise NeedsReviewError("时间范围及导出原点必须落在源帧网格上")
    count = round((end - start) * fps)
    if count < 3 or count > 30000:
        raise NeedsReviewError("本轮预览范围需要3到30000个源帧")
    requested = interval_gains(start, count, fps, request["reference_intervals"])
    reference_needed = request["mode"] == "cached_v9" or bool(np.any(requested))
    width, height = metadata["ctb"]["width"], metadata["ctb"]["height"]
    size = (1280, round((1280 * height / width) / 2) * 2)
    if size[1] < 128 or size[1] > 4096:
        raise NeedsReviewError("输入纵横比超出本轮安全预览范围")
    timing = {}
    for key, origin in (("original", 0.), ("ctb", request["ctb_origin"]), ("reference", request["reference_origin"])):
        local_start, local_end = start - origin, end - origin
        if key == "reference" and not reference_needed:
            timing[key] = {"scope": "not_required_no_reference_gain_on_selected_frames"}
            continue
        meta = metadata[key]
        if abs(meta["width"] / meta["height"] - width / height) > 1e-5:
            raise NeedsReviewError("三路输入纵横比不一致，不拉伸或裁切以强行匹配")
        check_input(meta, local_start, local_end, fps)
        timing[key] = check_cfr(paths[key], tools["ffprobe"], local_start, local_end, fps, cancel)
    warnings = [
        "只保留当前CTB输入矩形；不能恢复上游裁切或8-bit损失，原片全FOV尚未认证。",
        "输出是1280宽内容的8-bit H.264/AAC观看预览，不是4K/10-bit母版。",
        "区间是明确的人工策略，失败的RAW陀螺自动分类保持关闭。",
        "控制器角点速度只约束同一输入帧下的控制状态变化，不是画面稳定度保证。",
        "三路时间原点由用户/已知预设声明；验证PTS覆盖不等于独立证明内容同步。",
        "输入指纹是stat和首尾抽样摘要，不是全文件完整性证明。",
    ]
    output, manifest = workdir / "preview.mp4", workdir / "manifest.json"
    details = {"schema_version": 1, "kind": "fusion", "request": request, "inputs": before,
               "input_metadata": metadata, "selected_interval_timestamps": timing,
               "analysis_size": list(size), "source_frames": [round(start * fps), round(end * fps)],
               "automatic_motion_classifier_enabled": False,
               "reference_fov_analysis_only": request["reference_fov"], "warnings": warnings}
    try:
        if request["mode"] == "cached_v9":
            on_event("cached_trajectory", None, "读取已批准摘要的C7037历史轨迹；不是新测量")
            quiet, reference, provenance = load_legacy(
                request, size, fps, discovery_binding=toolchain.get("_cached_v9_discovery_binding")
            )
            warnings.append("明确的C7037旧V9复现；CTB安静目标含历史跟踪缺口，不声称重新测量为零。")
            details["trajectory_provenance"] = provenance
        else:
            quiet, quiet_diagnostics, new_warnings = quiet_trajectory(
                paths["ctb"], start, end, request["ctb_origin"], fps, size,
                request["quiet_sigma_seconds"], workdir, tools, cancel, on_event)
            warnings.extend(new_warnings)
            write_json(workdir / "quiet_tracking.json", quiet_diagnostics)
            if np.any(requested):
                reference, registration = register_videos(
                    paths["ctb"], paths["reference"], start, end, request["ctb_origin"],
                    request["reference_origin"], fps, size, workdir, tools, cancel, on_event,
                    reference_fov=request["reference_fov"])
                write_json(workdir / "registration.json", registration)
            else:
                # This is an inactive placeholder, not measured zero reference
                # motion: no GF command is enabled and only quiet is selected.
                reference = quiet.copy()
                details["reference_measurement"] = "not_required_no_reference_gain_on_selected_frames"
            details["trajectory_provenance"] = {"mode": "fresh", "missing_measurement_filler_used": False,
                                                 "coordinate_gauge_first_frame": "identity_not_motion_measurement"}
        on_event("fusion", None, "计算双锚点全局刚性轨迹，不混合GF像素")
        controller_keys = ("alignment_tau_seconds", "minimum_weight_transition_seconds", "weight_corner_speed", "anchor_corner_speed")
        if any(key in request for key in controller_keys):
            settings = FusionSettings(**{key: request[key] for key in controller_keys if key in request})
            result = anchored_blend(quiet, reference, requested, fps, size, settings)
            details["fusion_settings"] = {key: getattr(settings, key) for key in controller_keys}
        else:
            # 历史请求沿用原调用及默认数学语义；不改变旧 golden 的入口。
            result = anchored_blend(quiet, reference, requested, fps, size)
        check_unit(result.matrices)
        trajectory = workdir / "trajectory.npz"
        with trajectory.open("xb") as stream:
            np.savez_compressed(stream, render_source_origin_unit_affines=result.matrices,
                                actual_reference_gain=result.actual_gain, requested_reference_gain=requested,
                                anchors=result.anchors, source_frames=np.arange(round(start * fps), round(end * fps)),
                                controller_changes=result.controller_changes, fps=fps)
        details["controller"] = {"variant": "dual_anchor", "maximum_controller_change": float(result.controller_changes.max()),
                                  "maximum_anchor_change": float(result.anchor_changes.max()),
                                  "maximum_weight_change": float(result.weight_changes.max()),
                                  "scale_applied": False, "rgb_crossfade": False, "local_warp": False}
        validation = render_preview(paths["ctb"], paths["original"], output, workdir, result.matrices,
                                    start, end, request["ctb_origin"], fps, tools, cancel, on_event, size)
        after = {key: fingerprint(path) for key, path in paths.items()}
        if before != after:
            raise NeedsReviewError("输入文件指纹在运行期间改变，结果保留但不标为已校验")
        details["post_inputs"] = after
        details["validation"] = validation
        write_json(manifest, details)
        for path in (output, manifest, trajectory):
            validate_owned_file(path, workdir, inputs)
        return {"outputs": [
            {"path": output, "label": "V9分段融合 · 8-bit观看预览", "kind": "preview", "mime": "video/mp4",
             "metadata": validation["metadata"], "validation_scope": validation["scope"], "warnings": warnings},
            {"path": manifest, "label": "来源与验证记录", "kind": "manifest", "mime": "application/json"},
            {"path": trajectory, "label": "刚性轨迹与控制记录", "kind": "diagnostic", "mime": "application/octet-stream"}],
            "manifest": manifest, "warnings": warnings, "validation": validation}
    except NeedsReviewError as exc:
        details["failure"] = {"message": exc.message, "details": exc.details}
        write_json(workdir / "failure.json", details)
        retained = [{"path": workdir / "failure.json", "label": "未通过闸门的诊断", "kind": "diagnostic", "mime": "application/json"}]
        if output.is_file():
            retained.append({"path": output, "label": "未通过全部校验的输出", "kind": "diagnostic", "mime": "video/mp4",
                             "warnings": ["待核查，不能作为完成结果"]})
        raise NeedsReviewError(exc.message, {"outputs": retained, "reason": exc.details}) from exc
