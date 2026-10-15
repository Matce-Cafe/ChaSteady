"""Source-origin unit-scale rigid geometry and complete input containment."""
from dataclasses import dataclass
from typing import Tuple

import numpy as np

from ..errors import NeedsReviewError


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    offset: np.ndarray
    minimum_margin: float


def rotation(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.asarray([[c, -s], [s, c]], dtype=np.float64)


def check_unit(matrices: np.ndarray) -> None:
    m = np.asarray(matrices)
    if m.ndim != 3 or m.shape[1:] != (2, 3) or not np.isfinite(m).all() or not len(m):
        raise NeedsReviewError("刚性轨迹缺失或含非有限数值")
    r = m[:, :, :2]
    if (not np.allclose(r.transpose(0, 2, 1) @ r, np.eye(2), atol=1e-8, rtol=0.0) or
            not np.allclose(np.linalg.det(r), 1.0, atol=1e-8, rtol=0.0)):
        raise NeedsReviewError("轨迹包含缩放、剪切或非正常旋转，拒绝渲染")


def recover(matrices: np.ndarray, size: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    check_unit(matrices)
    center = np.asarray(size, dtype=np.float64) / 2.0
    r = matrices[:, :, :2]
    q = matrices[:, :, 2] - center + np.einsum("nij,j->ni", r, center)
    angles = np.unwrap(np.arctan2(r[:, 1, 0], r[:, 0, 0]))
    return q, angles


def affine(shift: np.ndarray, angle: float, size: Tuple[int, int]) -> np.ndarray:
    center = np.asarray(size, dtype=np.float64) / 2.0
    r = rotation(angle)
    return np.column_stack([r, center + np.asarray(shift) - r @ center])


def compose(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return np.column_stack([first[:, :2] @ second[:, :2], first[:, :2] @ second[:, 2] + first[:, 2]])


def corners(size: Tuple[int, int]) -> np.ndarray:
    w, h = size
    return np.asarray([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]], dtype=np.float64)


def corner_distance(first: np.ndarray, second: np.ndarray, size: Tuple[int, int]) -> float:
    points = corners(size)
    a = points @ first[:, :2].T + first[:, 2]
    b = points @ second[:, :2].T + second[:, 2]
    return float(np.max(np.linalg.norm(a - b, axis=1)))


def expanded_canvas(matrices: np.ndarray, size: Tuple[int, int], guard: float = 4.0,
                    max_dimension: int = 8192) -> Canvas:
    check_unit(matrices)
    center = np.asarray(size, dtype=np.float64) / 2.0
    points = np.einsum("nkj,pj->npk", matrices[:, :, :2], corners(size)) + matrices[:, None, :, 2]
    half = np.maximum(np.max(np.abs(points - center), axis=(0, 1)) + guard, center + guard)
    w, h = (np.ceil(half).astype(int) * 2).tolist()
    if max(w, h) > max_dimension:
        raise NeedsReviewError("无裁切画布超过当前编码器安全尺寸，不以缩放或裁切掩盖问题",
                               {"required_canvas": [w, h], "limit": max_dimension})
    offset = np.asarray([w / 2.0, h / 2.0]) - center
    positioned = points + offset
    margins = np.stack([positioned[:, :, 0], w - positioned[:, :, 0],
                        positioned[:, :, 1], h - positioned[:, :, 1]])
    minimum = float(np.min(margins))
    if minimum < -1e-8:
        raise NeedsReviewError("至少一帧CTB输入角点超出恒定黑画布")
    return Canvas(w, h, offset, minimum)


def translation_matrices(shifts: np.ndarray) -> np.ndarray:
    shifts = np.asarray(shifts, dtype=np.float64)
    if shifts.ndim != 2 or shifts.shape[1] != 2 or not np.isfinite(shifts).all():
        raise NeedsReviewError("平移轨迹无效")
    result = np.zeros((len(shifts), 2, 3), dtype=np.float64)
    result[:, 0, 0] = 1.0
    result[:, 1, 1] = 1.0
    result[:, :, 2] = shifts
    return result
