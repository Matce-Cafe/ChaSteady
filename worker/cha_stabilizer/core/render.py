"""Render CTB pixels with unit rigid matrices on one constant black canvas."""
import subprocess
import threading
from pathlib import Path
from typing import Callable, Dict, Tuple

import cv2
import numpy as np

from ..errors import AppError, CancelledError, NeedsReviewError
from .. import owned_processes as owners
from .geometry import expanded_canvas, check_unit
from .media import ownership, probe, verify_output, local_file
from .streams import FrameDecoder


def render_preview(ctb: Path, original: Path, output: Path, workdir: Path,
                   matrices: np.ndarray, start: float, end: float, ctb_origin: float,
                   fps: float, tools: Dict, cancel: threading.Event, on_event: Callable,
                   size: Tuple[int, int] = (1280, 720)) -> Dict:
    check_unit(matrices)
    if output.exists():
        raise FileExistsError(str(output))
    if start < ctb_origin or end <= start or abs((end - start) * fps - len(matrices)) > 1e-6:
        raise NeedsReviewError("渲染轨迹不覆盖所选源帧范围")
    ffmpeg, ffprobe = local_file(tools["ffmpeg"]), local_file(tools["ffprobe"])
    original_meta = probe(original, ffprobe, cancel=cancel)
    canvas = expanded_canvas(matrices, size)
    encoder_log = workdir / "encoder.log"
    if encoder_log.exists():
        raise FileExistsError(str(encoder_log))
    command = [str(ffmpeg), "-nostdin", "-hide_banner", "-v", "error", "-n", "-protocol_whitelist", "file,pipe",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "{}x{}".format(canvas.width, canvas.height),
               "-r", "{:.9f}".format(fps), "-i", "pipe:0", "-ss", "{:.9f}".format(start),
               "-protocol_whitelist", "file,pipe", "-i", str(original), "-map", "0:v:0", "-map", "1:a:0?",
               "-t", "{:.9f}".format(end - start), "-vf", "scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p",
               "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "18", "-b:v", "0",
               "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
               "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(output)]
    encoder = None
    with ownership(cancel) as registry, encoder_log.open("xb") as log:
        try:
            encoder = owners.spawn_owned_process(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                                   stderr=log, cwd=str(workdir))
            with FrameDecoder(ffmpeg, ctb, start - ctb_origin, end - start, len(matrices), size, workdir, cancel) as decoder:
                for i, matrix in enumerate(matrices):
                    if cancel.is_set():
                        raise CancelledError("已取消增稳渲染")
                    rgb = decoder.frame(i)
                    positioned = matrix.copy()
                    # The source-origin affine already rotates about source center.
                    # Add only the expanded-canvas offset; never rotate center twice.
                    positioned[:, 2] += canvas.offset
                    image = cv2.warpAffine(rgb, positioned, (canvas.width, canvas.height), flags=cv2.INTER_CUBIC,
                                            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
                    encoder.stdin.write(image.tobytes())
                    if (i + 1) % 25 == 0 or i + 1 == len(matrices):
                        on_event("render", (i + 1) / len(matrices), "渲染 {}/{} 帧".format(i + 1, len(matrices)))
            encoder.stdin.close()
            code = encoder.wait(timeout=120.0)
            if code:
                raise AppError("视频编码失败", {"return_code": code, "encoder_log": str(encoder_log)})
        finally:
            if encoder is not None:
                if encoder.poll() is None:
                    encoder.terminate()
                    try:
                        encoder.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        encoder.kill()
                        encoder.wait()
                registry.discard(encoder)
    on_event("verify", None, "完整解码并验证视频与原片对应音轨")
    validation = verify_output(output, ffmpeg, ffprobe, len(matrices), fps, end - start,
                               original_meta["audio_codec"] is not None, cancel)
    validation.update(scope="media_and_current_ctb_input_corners", all_input_corners_contained=True,
                      canvas=[canvas.width, canvas.height], minimum_corner_margin=canvas.minimum_margin,
                      rendered_pixel_source="ctb_only", estimated_similarity_scale_applied=False,
                      original_audio_source=str(original), audio_reencoded="aac48k_stereo_if_audio_present",
                      output_is_8bit_viewing_preview=True)
    return validation
