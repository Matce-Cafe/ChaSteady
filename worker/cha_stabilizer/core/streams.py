"""Bounded RGB frame decoding with persistent stderr and owned child lifetime."""
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from ..errors import CancelledError, NeedsReviewError
from .. import owned_processes as owners
from .media import local_file, VIDEO_EXTENSIONS


def exact(stream, size: int) -> bytes:
    parts = []
    while size:
        value = stream.read(size)
        if not value:
            break
        parts.append(value)
        size -= len(value)
    return b"".join(parts)


class FrameDecoder:
    def __init__(self, ffmpeg: Path, path: Path, start: float, duration: float, frames: int,
                 size: Tuple[int, int], workdir: Path, cancel: Optional[threading.Event] = None,
                 analysis_fov: float = 1.0):
        self.ffmpeg, self.path = local_file(ffmpeg), local_file(path, VIDEO_EXTENSIONS)
        self.start, self.duration, self.frames = start, duration, frames
        self.width, self.height = size
        self.workdir, self.cancel = workdir, cancel
        self.analysis_fov = float(analysis_fov)
        if not np.isfinite(self.analysis_fov) or not 1.0 <= self.analysis_fov <= 4.0:
            raise NeedsReviewError("参考分析FOV必须在1到4之间")
        self.process = None
        self.log = None
        self.log_path = workdir / ("decoder-" + uuid.uuid4().hex + ".log")
        if start < 0 or duration <= 0 or frames <= 0 or min(size) < 16 or max(size) > 8192:
            raise NeedsReviewError("视频解码范围或尺寸无效")

    def __enter__(self):
        self.log = self.log_path.open("xb")
        scaled_w = round(self.width * self.analysis_fov / 2) * 2
        scaled_h = round(self.height * self.analysis_fov / 2) * 2
        if max(scaled_w, scaled_h) > 8192:
            self.log.close()
            raise NeedsReviewError("参考分析尺寸超过当前安全上限")
        filters = "scale={}:{}:flags=area".format(scaled_w, scaled_h)
        if self.analysis_fov != 1.0:
            filters += ",crop={}:{}:(iw-{})/2:(ih-{})/2:exact=1".format(self.width, self.height, self.width, self.height)
        command = [str(self.ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-threads", "3",
                   "-xerror", "-ss", "{:.9f}".format(self.start), "-protocol_whitelist", "file,pipe", "-i", str(self.path),
                   "-t", "{:.9f}".format(self.duration), "-map", "0:V:0", "-an", "-sn", "-dn",
                   "-vf", filters, "-frames:v", str(self.frames),
                   "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
        try:
            self.process = owners.spawn_owned_process(command, stdout=subprocess.PIPE, stderr=self.log,
                                                       bufsize=self.width * self.height * 3, cwd=str(self.workdir))
        except Exception:
            self.log.close()
            raise
        return self

    def frame(self, index: int) -> np.ndarray:
        if self.cancel is not None and self.cancel.is_set():
            raise CancelledError("已取消视频解码")
        data = exact(self.process.stdout, self.width * self.height * 3)
        if len(data) != self.width * self.height * 3:
            if self.cancel is not None and self.cancel.is_set():
                raise CancelledError("已取消视频解码")
            raise NeedsReviewError("解码帧缺失或截断，未填充零运动或重复帧", {"missing_frame_index": index,
                                   "decoder_log": str(self.log_path)})
        return np.frombuffer(data, np.uint8).reshape(self.height, self.width, 3)

    def __exit__(self, exc_type, exc_value, traceback):
        process = self.process
        if process is not None:
            process.stdout.close()
            if exc_type is not None and process.poll() is None:
                process.terminate()
            try:
                code = process.wait(timeout=15.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                code = process.returncode
            registry = owners.get_active_registry()
            if registry is not None:
                registry.discard(process)
            self.log.close()
            if exc_type is None and code:
                raise NeedsReviewError("解码器返回错误，不采用部分帧结果", {"return_code": code, "decoder_log": str(self.log_path)})
        return False
