"""Strict same-frame global CTB-to-reference registration; no local warp transfer."""
import math
from typing import Tuple

import cv2
import numpy as np

from ..errors import NeedsReviewError
from .geometry import affine
from .media import ownership
from .streams import FrameDecoder

COLS, ROWS = 6, 4


def _cell(point, size):
    w, h = size
    return min(ROWS - 1, max(0, int(point[1] * ROWS / h))) * COLS + min(COLS - 1, max(0, int(point[0] * COLS / w)))


def _features(gray, detector, size):
    w, h = size
    mask = cv2.erode((gray > 8).astype(np.uint8) * 255, np.ones((7, 7), np.uint8))
    mx, my = max(2, int(w * .012)), max(2, int(h * .012))
    mask[:my], mask[-my:], mask[:, :mx], mask[:, -mx:] = 0, 0, 0, 0
    points, descriptions = [], []
    for row in range(ROWS):
        for col in range(COLS):
            x0, x1 = col * w // COLS, (col + 1) * w // COLS
            y0, y1 = row * h // ROWS, (row + 1) * h // ROWS
            keypoints, desc = detector.detectAndCompute(gray[y0:y1, x0:x1], mask[y0:y1, x0:x1])
            if desc is None:
                continue
            if len(keypoints) > 120:
                keep = np.argsort([k.response for k in keypoints])[-120:]
                keypoints, desc = [keypoints[int(i)] for i in keep], desc[keep]
            points.extend((k.pt[0] + x0, k.pt[1] + y0) for k in keypoints)
            descriptions.append(desc)
    return np.asarray(points, dtype=np.float32).reshape(-1, 2), np.concatenate(descriptions) if descriptions else None


def _matches(pa, da, pb, db, size):
    if da is None or db is None or min(len(da), len(db)) < 2:
        return []
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    fwd = {p[0].queryIdx: p[0] for p in matcher.knnMatch(da, db, k=2) if len(p) == 2 and p[0].distance < .8 * p[1].distance}
    rev = {p[0].queryIdx: p[0].trainIdx for p in matcher.knnMatch(db, da, k=2) if len(p) == 2 and p[0].distance < .8 * p[1].distance}
    candidates = [m for i, m in fwd.items() if rev.get(m.trainIdx) == i]
    candidates.sort(key=lambda m: m.distance)
    a_count, b_count = np.zeros(24, int), np.zeros(24, int)
    selected = []
    for m in candidates:
        a, b = _cell(pa[m.queryIdx], size), _cell(pb[m.trainIdx], size)
        if a_count[a] >= 8 or b_count[b] >= 8:
            continue
        a_count[a] += 1
        b_count[b] += 1
        selected.append(m)
    return selected


def _coverage(points, size):
    if len(points) < 3:
        return {"cells": 0, "hull": 0., "bounds": [0., 0.]}
    w, h = size
    hull = float(cv2.contourArea(cv2.convexHull(np.asarray(points, dtype=np.float32))) / (w * h))
    bounds = np.ptp(points, axis=0) / np.asarray([w, h])
    return {"cells": len({_cell(p, size) for p in points}), "hull": hull, "bounds": bounds.tolist()}


def fit_pair(source_rgb, reference_rgb, index: int = 0, size: Tuple[int, int] = (1280, 720)):
    detector = cv2.SIFT_create(nfeatures=120, contrastThreshold=.022, edgeThreshold=12, sigma=1.6)
    pa, da = _features(cv2.cvtColor(source_rgb, cv2.COLOR_RGB2GRAY), detector, size)
    pb, db = _features(cv2.cvtColor(reference_rgb, cv2.COLOR_RGB2GRAY), detector, size)
    matches = _matches(pa, da, pb, db, size)
    record = {"frame": index, "accepted": False, "balanced_matches": len(matches), "inliers": 0,
              "inlier_ratio": 0., "failures": [], "scale_estimated_not_applied": None}
    if len(matches) < 3:
        record["failures"] = ["insufficient_mutual_matches"]
        return None, record
    a = np.asarray([pa[m.queryIdx] for m in matches], np.float32)
    b = np.asarray([pb[m.trainIdx] for m in matches], np.float32)
    cv2.setRNGSeed(1771 + index)
    model, mask = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=3.,
                                            maxIters=5000, confidence=.999, refineIters=15)
    if model is None or mask is None:
        record["failures"] = ["no_similarity_model"]
        return None, record
    keep = mask.ravel().astype(bool)
    count, ratio = int(keep.sum()), float(keep.mean())
    residual = np.linalg.norm(a @ model[:, :2].T + model[:, 2] - b, axis=1)[keep]
    scale = float(math.hypot(model[0, 0], model[1, 0]))
    angle = float(math.atan2(model[1, 0], model[0, 0]))
    source_cov, reference_cov = _coverage(a[keep], size), _coverage(b[keep], size)
    failures = []
    if count < 18:
        failures.append("inliers_below_18")
    if ratio < .22:
        failures.append("ratio_below_0p22")
    for label, cov in (("source", source_cov), ("reference", reference_cov)):
        if cov["cells"] < 6 or cov["hull"] < .035 or cov["bounds"][0] < .30 or cov["bounds"][1] < .18:
            failures.append(label + "_coverage_failed")
    median = float(np.median(residual)) if count else None
    p90 = float(np.percentile(residual, 90)) if count else None
    if median is None or median > 2.5 or p90 > 5.5:
        failures.append("reprojection_residual_failed")
    if not .65 <= scale <= 1.45 or abs(math.degrees(angle)) > 7.:
        failures.append("scale_or_angle_failed")
    record.update(inliers=count, inlier_ratio=ratio, scale_estimated_not_applied=scale,
                  median_residual=median, p90_residual=p90, source_coverage=source_cov,
                  reference_coverage=reference_cov, failures=failures, accepted=not failures)
    if failures:
        return None, record
    center = np.asarray(size, float) / 2.
    center_shift = model[:, :2] @ center + model[:, 2] - center
    return affine(center_shift, angle, size), record


def register_videos(ctb, reference, start, end, ctb_origin, reference_origin, fps, size, workdir, tools,
                    cancel, on_event, reference_fov=1.0):
    count = round((end - start) * fps)
    matrices, diagnostics = [], []
    with ownership(cancel), FrameDecoder(tools["ffmpeg"], ctb, start - ctb_origin, end - start, count,
                                        size, workdir, cancel) as source, FrameDecoder(
            tools["ffmpeg"], reference, start - reference_origin, end - start, count, size, workdir,
            cancel, analysis_fov=reference_fov) as target:
        for i in range(count):
            matrix, record = fit_pair(source.frame(i), target.frame(i), i, size)
            diagnostics.append(record)
            if matrix is None:
                raise NeedsReviewError("同帧整体配准未通过闸门，未使用邻帧复制或零运动替代",
                                       {"source_frame": round(start * fps) + i, "registration": record})
            matrices.append(matrix)
            if (i + 1) % 10 == 0 or i + 1 == count:
                on_event("registration", (i + 1) / count, "同帧配准 {}/{}".format(i + 1, count))
    return np.asarray(matrices), diagnostics
