"""Experimental strict CTB quiet-trajectory estimation: failures remain missing."""
import math

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d

from ..errors import NeedsReviewError
from .geometry import translation_matrices
from .media import ownership
from .streams import FrameDecoder
from .registration import _coverage


def detect(gray):
    h, w = gray.shape
    mask = cv2.erode((gray > 8).astype(np.uint8) * 255, np.ones((5, 5), np.uint8))
    result = []
    for row in range(4):
        for col in range(6):
            x0, x1 = col * w // 6, (col + 1) * w // 6
            y0, y1 = row * h // 4, (row + 1) * h // 4
            points = cv2.goodFeaturesToTrack(gray[y0:y1, x0:x1], maxCorners=35, qualityLevel=.012,
                                            minDistance=7, mask=mask[y0:y1, x0:x1], blockSize=7)
            if points is not None:
                p = points.reshape(-1, 2)
                p[:, 0] += x0
                p[:, 1] += y0
                result.append(p)
    return np.concatenate(result).astype(np.float32).reshape(-1, 1, 2) if result else None


def quiet_trajectory(ctb, start, end, origin, fps, size, sigma_seconds, workdir, tools, cancel, on_event):
    if not np.isfinite(sigma_seconds) or not 0 < sigma_seconds <= 10.:
        raise NeedsReviewError("安静轨迹平滑范围必须在0到10秒之间，避免无限内存kernel")
    count = round((end - start) * fps)
    cumulative = np.eye(3)
    poses = np.zeros((count, 4), float)
    diagnostics = []
    previous = None
    center = np.asarray(size, float) / 2.
    with ownership(cancel), FrameDecoder(tools["ffmpeg"], ctb, start - origin, end - start, count, size,
                                        workdir, cancel) as decoder:
        for i in range(count):
            gray = cv2.cvtColor(decoder.frame(i), cv2.COLOR_RGB2GRAY)
            if previous is not None:
                p = detect(previous)
                if p is None or len(p) < 24:
                    raise NeedsReviewError("CTB静态纹理不足，未填入identity增量", {"frame": i})
                nxt, valid, _ = cv2.calcOpticalFlowPyrLK(previous, gray, p, None, winSize=(27, 27), maxLevel=4)
                if nxt is None or valid is None:
                    raise NeedsReviewError("CTB正向光流缺失", {"frame": i})
                back, reverse_valid, _ = cv2.calcOpticalFlowPyrLK(gray, previous, nxt, None, winSize=(27, 27), maxLevel=4)
                if back is None or reverse_valid is None:
                    raise NeedsReviewError("CTB反向光流缺失", {"frame": i})
                keep = valid.ravel().astype(bool) & reverse_valid.ravel().astype(bool)
                keep &= np.linalg.norm(back.reshape(-1, 2) - p.reshape(-1, 2), axis=1) < 1.5
                a, b = p.reshape(-1, 2)[keep], nxt.reshape(-1, 2)[keep]
                if len(a) < 18:
                    raise NeedsReviewError("CTB双向可信点不足", {"frame": i, "tracks": len(a)})
                cv2.setRNGSeed(21000 + i)
                model, mask = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=2.,
                                                         maxIters=3000, confidence=.999, refineIters=12)
                if model is None or mask is None:
                    raise NeedsReviewError("CTB相似运动拟合失败", {"frame": i})
                accepted = mask.ravel().astype(bool)
                inliers = int(accepted.sum())
                ratio = inliers / len(a)
                for points in (a[accepted], b[accepted]):
                    coverage = _coverage(points, size)
                    if (coverage["cells"] < 6 or coverage["hull"] < .035 or
                            coverage["bounds"][0] < .30 or coverage["bounds"][1] < .18):
                        raise NeedsReviewError("CTB可信点空间覆盖不足，拒绝把局部主体运动当相机运动",
                                               {"frame": i, "coverage": coverage})
                residual = np.linalg.norm(a @ model[:, :2].T + model[:, 2] - b, axis=1)[accepted]
                if not len(residual) or np.percentile(residual, 90) > 2.5:
                    raise NeedsReviewError("CTB轨迹重投影残差超限", {"frame": i})
                scale = float(math.hypot(model[0, 0], model[1, 0]))
                angle = math.degrees(math.atan2(model[1, 0], model[0, 0]))
                if inliers < 18 or ratio < .30 or not .92 < scale < 1.08 or abs(angle) > 4.:
                    raise NeedsReviewError("新CTB轨迹未通过可信闸门；请核查或使用明确的旧方案复现",
                                           {"frame": i, "inliers": inliers, "ratio": ratio, "scale": scale, "angle": angle})
                delta = np.eye(3)
                delta[:2, :2] = model[:, :2]
                delta[:2, 2] = model[:, :2] @ center + model[:, 2] - center
                cumulative = delta @ cumulative
                diagnostics.append({"frame": i, "inliers": inliers, "ratio": ratio, "measured": True})
            linear = cumulative[:2, :2]
            poses[i, :2] = -np.linalg.solve(linear, cumulative[:2, 2])
            poses[i, 2] = math.atan2(linear[1, 0], linear[0, 0])
            poses[i, 3] = math.log(math.hypot(linear[0, 0], linear[1, 0]))
            previous = gray
            if (i + 1) % 25 == 0 or i + 1 == count:
                on_event("quiet_tracking", (i + 1) / count, "可信CTB轨迹 {}/{}".format(i + 1, count))
    poses[:, 2] = np.unwrap(poses[:, 2])
    target = gaussian_filter1d(poses[:, :2], sigma_seconds * fps, axis=0, mode="reflect")
    difference = poses[:, :2] - target
    c, s, scale = np.cos(poses[:, 2]), np.sin(poses[:, 2]), np.exp(poses[:, 3])
    shifts = np.column_stack([scale * (c * difference[:, 0] - s * difference[:, 1]),
                             scale * (s * difference[:, 0] + c * difference[:, 1])])
    warnings = ["新轨迹实验使用窗口内reflect边界平滑；不是已认证的全长或实时运动估计。"]
    return translation_matrices(shifts), diagnostics, warnings
