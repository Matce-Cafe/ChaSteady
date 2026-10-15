"""Local-only media inspection and owned subprocess I/O."""
import contextlib
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Optional

from ..errors import AppError, CancelledError, NeedsReviewError
from .. import owned_processes as owners


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".mkv", ".m4v", ".avi", ".webm"}


def local_file(value: Any, extensions=None) -> Path:
    text = str(value)
    if not text or "\x00" in text or text.startswith(("\\\\", "//")):
        raise NeedsReviewError("只接受明确的本机文件路径，不接受网络或设备路径")
    if os.name == "nt":
        if not re.match(r"^[A-Za-z]:[\\/]", text):
            raise NeedsReviewError("请选择本机盘符开头的绝对路径")
    elif not text.startswith("/"):
        raise NeedsReviewError("只接受本机绝对路径")
    from ..paths import resolve_local_input
    try:
        path = resolve_local_input(text, "media input")
    except (ValueError, OSError) as exc:
        raise NeedsReviewError("输入必须是本机普通文件，不接受symlink或junction") from exc
    if extensions is not None and path.suffix.lower() not in extensions:
        raise NeedsReviewError("输入文件类型不在当前支持范围", {"extension": path.suffix})
    return path


@contextlib.contextmanager
def ownership(cancel: Optional[threading.Event] = None):
    registry = owners.get_active_registry()
    if registry is not None:
        yield registry
        return
    registry = owners.OwnedProcessRegistry(cancel)
    with owners.registry_scope(registry):
        try:
            yield registry
        finally:
            if registry.snapshot():
                registry.terminate_all()


def capture(command, cancel: Optional[threading.Event] = None, timeout: float = 1800.0,
            cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    with ownership(cancel) as registry:
        process = owners.spawn_owned_process(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             cwd=str(cwd) if cwd else None)
        started = time.monotonic()
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    registry.terminate_all()
                    raise CancelledError("已取消本任务")
                if time.monotonic() - started > timeout:
                    registry.terminate_all()
                    raise NeedsReviewError("外部工具超时，保留任务诊断，不标为完成")
                try:
                    out, err = process.communicate(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise AppError("外部媒体工具返回错误", {"return_code": process.returncode,
                               "stderr": err.decode("utf-8", errors="replace")[-5000:]})
            return subprocess.CompletedProcess(command, process.returncode, out, err)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            registry.discard(process)


def _rate(value: Optional[str]) -> float:
    try:
        return float(Fraction(value or "0/1"))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _integer(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _depth(stream: Dict[str, Any]) -> int:
    bits = _integer(stream.get("bits_per_raw_sample"))
    if bits and bits > 0:
        return bits
    fmt = stream.get("pix_fmt", "")
    match = re.search(r"(?:p|p0)(9|10|12|14|16)(?:le|be)?$", fmt)
    if match:
        return int(match.group(1))
    if fmt in ("rgb48le", "rgb48be", "rgba64le", "rgba64be"):
        return 16
    return 8


def probe(path: Path, ffprobe: Path, count: bool = False,
          cancel: Optional[threading.Event] = None) -> Dict[str, Any]:
    path = local_file(path, VIDEO_EXTENSIONS)
    tool = local_file(ffprobe)
    command = [str(tool), "-v", "error", "-protocol_whitelist", "file,pipe"]
    if count:
        command.append("-count_frames")
    command += ["-show_streams", "-show_format", "-of", "json", str(path)]
    raw = json.loads(capture(command, cancel).stdout)
    stream = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"
                   and not s.get("disposition", {}).get("attached_pic")), None)
    if stream is None:
        raise NeedsReviewError("文件中未发现可处理的视频流")
    audio = next((s for s in raw["streams"] if s.get("codec_type") == "audio"), None)
    fps = _rate(stream.get("avg_frame_rate"))
    nominal = _rate(stream.get("r_frame_rate"))
    duration = stream.get("duration") or raw.get("format", {}).get("duration")
    try:
        duration = float(duration)
    except (ValueError, TypeError):
        duration = None
    frames = _integer(stream.get("nb_read_frames")) if count else _integer(stream.get("nb_frames"))
    return {"path": str(path), "name": path.name, "width": int(stream["width"]), "height": int(stream["height"]),
            "fps": fps, "frames": frames, "duration": duration, "video_codec": stream.get("codec_name"),
            "pixel_format": stream.get("pix_fmt"), "audio_codec": audio.get("codec_name") if audio else None,
            "bit_depth": _depth(stream), "start_time": float(stream.get("start_time", "0") or "0"),
            "time_base": stream.get("time_base"), "color_transfer": stream.get("color_transfer"),
            "color_primaries": stream.get("color_primaries"), "color_space": stream.get("color_space"),
            "cfr_status": "metadata_consistent" if fps > 0 and abs(fps - nominal) < 1e-5 else "unverified",
            "raw_streams": raw["streams"], "format": raw.get("format", {}), "original_fov_verified": False}


def check_cfr(path: Path, ffprobe: Path, start: float, end: float, fps: float,
              cancel: Optional[threading.Event] = None) -> Dict[str, Any]:
    if end <= start or fps <= 0:
        raise NeedsReviewError("无效时间范围或帧率")
    command = [str(ffprobe), "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "V:0",
               "-read_intervals", "{:.6f}%{:.6f}".format(start, end + max(.5, 5. / fps)), "-show_frames",
               "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)]
    data = json.loads(capture(command, cancel).stdout)
    times = [float(f["best_effort_timestamp_time"]) for f in data.get("frames", [])
             if "best_effort_timestamp_time" in f]
    selected = [t for t in times if start - 1e-6 <= t < end - 1e-6]
    if len(selected) < min(3, round((end - start) * fps)):
        raise NeedsReviewError("未能验证所选时间范围的帧时间戳")
    step = 1.0 / fps
    errors = [abs(b - a - step) for a, b in zip(selected[:-1], selected[1:])]
    maximum = max(errors, default=0.0)
    if maximum > max(1e-4, step * 0.01):
        raise NeedsReviewError("所选时间范围不是已验证的固定帧率，不静默插帧或重采样",
                               {"maximum_timestamp_step_error": maximum})
    expected = round((end - start) * fps)
    if (len(selected) != expected or abs(selected[0] - start) > 1e-4 or
            abs(selected[-1] - (end - step)) > 1e-4):
        raise NeedsReviewError("所选源帧时间戳未完整覆盖范围，不猜测起点或缺帧",
                               {"expected_frames": expected, "actual_frames": len(selected)})
    return {"sampled_frames": len(selected), "maximum_step_error": maximum,
            "first_timestamp": selected[0], "last_timestamp": selected[-1],
            "scope": "all_selected_interval_frame_timestamps"}


def fingerprint(path: Path) -> Dict[str, Any]:
    path = local_file(path)
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        digest.update(stream.read(1024 ** 2))
        if stat.st_size > 1024 ** 2:
            stream.seek(max(0, stat.st_size - 1024 ** 2))
            digest.update(stream.read(1024 ** 2))
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sampled_sha256": digest.hexdigest(), "hash_scope": "first_and_last_1MiB_not_full_file"}


def verify_output(path: Path, ffmpeg: Path, ffprobe: Path, expected_frames: Optional[int] = None,
                  expected_fps: Optional[float] = None, duration: Optional[float] = None,
                  expect_audio: Optional[bool] = None, cancel: Optional[threading.Event] = None) -> Dict[str, Any]:
    metadata = probe(path, ffprobe, count=True, cancel=cancel)
    if expected_frames is not None and metadata["frames"] != expected_frames:
        raise NeedsReviewError("实际视频帧数与所选源时间线不一致", {"expected": expected_frames, "actual": metadata["frames"]})
    if expected_fps is not None and abs(metadata["fps"] - expected_fps) > 1e-5:
        raise NeedsReviewError("导出帧率不匹配")
    if duration is not None and (metadata["duration"] is None or abs(metadata["duration"] - duration) > 0.06):
        raise NeedsReviewError("导出时长不匹配", {"expected": duration, "actual": metadata["duration"]})
    if expect_audio is True and metadata["audio_codec"] is None:
        raise NeedsReviewError("原片有音轨，但导出音轨缺失")
    audio = next((s for s in metadata["raw_streams"] if s.get("codec_type") == "audio"), None)
    if expect_audio is True and duration is not None and audio is not None:
        try:
            audio_start = float(audio.get("start_time", "0"))
            audio_duration = float(audio["duration"])
        except (KeyError, ValueError, TypeError):
            raise NeedsReviewError("音轨起点或尾段时长无法核实")
        if abs(audio_start) > .06 or abs(audio_duration - duration) > .08:
            raise NeedsReviewError("音轨起点或尾段与所选范围不一致，不忽略截断")
    timing = None
    if expected_fps is not None:
        if metadata["frames"] is None or metadata["frames"] <= 0:
            raise NeedsReviewError("无法核查完整导出帧时间戳")
        origin = metadata.get("start_time", 0.)
        timing = check_cfr(path, ffprobe, origin, origin + metadata["frames"] / expected_fps, expected_fps, cancel)
    capture([str(ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-threads", "3",
             "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:V", "-map", "0:a?", "-f", "null", "-"], cancel)
    return {"status": "verified_media", "scope": "media_only", "metadata": metadata,
            "frame_count_verified": expected_frames is not None, "full_decode_passed": True,
            "decode_scope": "all_non_attached_video_and_all_audio_streams",
            "frame_timestamp_spacing_verified": timing is not None, "frame_timestamps": timing,
            "original_fov_verified": False, "perceptual_winner_claimed": False}
