"""Dual-anchor fusion of quiet and reference target trajectories, not RGB images."""
from dataclasses import dataclass
from typing import Tuple

import numpy as np

from ..errors import NeedsReviewError
from .geometry import affine, check_unit, corner_distance, recover, rotation


@dataclass(frozen=True)
class FusionSettings:
    alignment_tau_seconds: float = 0.12
    minimum_weight_transition_seconds: float = 0.30
    weight_corner_speed: float = 12.5
    anchor_corner_speed: float = 5.0


@dataclass
class FusionResult:
    matrices: np.ndarray
    actual_gain: np.ndarray
    anchors: np.ndarray
    anchor_changes: np.ndarray
    weight_changes: np.ndarray
    controller_changes: np.ndarray


def _pose(q0, a0, q1, a1, anchors, weight, size):
    quiet_q = rotation(anchors[0, 2]) @ q0 + anchors[0, :2]
    ref_q = rotation(anchors[1, 2]) @ q1 + anchors[1, :2]
    quiet_a, ref_a = a0 + anchors[0, 2], a1 + anchors[1, 2]
    out = affine((1.0 - weight) * quiet_q + weight * ref_q,
                 (1.0 - weight) * quiet_a + weight * ref_a, size)
    return out, quiet_q, quiet_a, ref_q, ref_a


def anchored_blend(quiet: np.ndarray, reference: np.ndarray, requested: np.ndarray,
                   fps: float = 50.0, size: Tuple[int, int] = (1280, 720),
                   settings: FusionSettings = FusionSettings()) -> FusionResult:
    q0, a0 = recover(quiet, size)
    q1, a1 = recover(reference, size)
    gain = np.asarray(requested, dtype=np.float64)
    n = len(quiet)
    if (len(reference) != n or gain.shape != (n,) or not np.isfinite(gain).all() or
            np.min(gain) < 0.0 or np.max(gain) > 1.0 or not np.isfinite(fps) or fps <= 0.0):
        raise NeedsReviewError("目标轨迹、权重或帧率无效")
    if min(settings.alignment_tau_seconds, settings.minimum_weight_transition_seconds,
           settings.weight_corner_speed, settings.anchor_corner_speed) <= 0.0:
        raise NeedsReviewError("融合时间和角点速度参数必须为正值")
    dt = 1.0 / fps
    reference_width_factor = size[0] / 1280.0
    anchor_budget = settings.anchor_corner_speed * dt * reference_width_factor
    weight_budget = settings.weight_corner_speed * dt * reference_width_factor
    radius = float(np.linalg.norm(np.asarray(size, dtype=float) / 2.0))
    alpha_base = 1.0 - np.exp(-dt / settings.alignment_tau_seconds)
    max_step = dt / settings.minimum_weight_transition_seconds
    anchors = np.zeros((2, 3), dtype=np.float64)
    anchors[1, 2] = a0[0] - a1[0]
    anchors[1, :2] = q0[0] - rotation(anchors[1, 2]) @ q1[0]
    weight = float(gain[0])
    output = np.empty_like(reference, dtype=np.float64)
    weights = np.empty(n)
    history = np.empty((n, 2, 3))
    ac, wc, total = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(n):
        old_weight = weight
        previous, *_ = _pose(q0[i], a0[i], q1[i], a1[i], anchors, old_weight, size)
        remaining = anchor_budget
        for branch in (1, 0):
            alpha = alpha_base * ((1.0 - gain[i]) ** 4 if branch == 1 else gain[i] ** 4)
            if alpha == 0.0:
                continue
            before, quiet_q, quiet_a, ref_q, ref_a = _pose(q0[i], a0[i], q1[i], a1[i], anchors, old_weight, size)
            if branch == 1:
                source_q, source_a, target_q, target_a, contribution = q1[i], a1[i], quiet_q, quiet_a, old_weight
            else:
                source_q, source_a, target_q, target_a, contribution = q0[i], a0[i], ref_q, ref_a, 1.0 - old_weight
            old = anchors[branch].copy()
            old_q = rotation(old[2]) @ source_q + old[:2]
            goal_a = target_a - source_a
            goal_a = old[2] + np.arctan2(np.sin(goal_a - old[2]), np.cos(goal_a - old[2]))

            def proposal(fraction):
                angle = old[2] + fraction * (goal_a - old[2])
                goal_shift = target_q - rotation(angle) @ source_q
                shift = old[:2] + fraction * (goal_shift - old[:2])
                new_q = rotation(angle) @ source_q + shift
                bound = contribution * (np.linalg.norm(new_q - old_q) + radius * abs(angle - old[2]))
                return np.r_[shift, angle], float(bound)

            next_anchor, bound = proposal(alpha)
            if bound > remaining:
                lo, hi = 0.0, alpha
                for _ in range(24):
                    middle = (lo + hi) / 2.0
                    _, value = proposal(middle)
                    if value <= remaining:
                        lo = middle
                    else:
                        hi = middle
                next_anchor, _ = proposal(lo)
            anchors[branch] = next_anchor
            after, *_ = _pose(q0[i], a0[i], q1[i], a1[i], anchors, old_weight, size)
            actual = corner_distance(before, after, size)
            if actual > remaining + 1e-7:
                raise NeedsReviewError("活动锚点角点变化超过预算")
            remaining = max(0.0, remaining - actual)
        before_weight, quiet_q, quiet_a, ref_q, ref_a = _pose(q0[i], a0[i], q1[i], a1[i], anchors, old_weight, size)
        ac[i] = corner_distance(previous, before_weight, size)
        distance = np.linalg.norm(ref_q - quiet_q) + radius * abs(ref_a - quiet_a)
        limit = min(max_step, weight_budget / max(1e-12, distance))
        weight = float(old_weight + np.clip(gain[i] - old_weight, -limit, limit))
        if abs(weight - gain[i]) < 1e-12:
            weight = float(gain[i])
        out, *_ = _pose(q0[i], a0[i], q1[i], a1[i], anchors, weight, size)
        if weight == 0.0 and np.array_equal(anchors[0], np.zeros(3)):
            out = quiet[i].copy()
        output[i], weights[i], history[i] = out, weight, anchors
        wc[i] = corner_distance(before_weight, out, size)
        total[i] = corner_distance(previous, out, size)
        if ac[i] > anchor_budget + 1e-7 or wc[i] > weight_budget + 1e-7 or total[i] > anchor_budget + weight_budget + 1e-7:
            raise NeedsReviewError("控制器引入的角点位移超过预算")
    check_unit(output)
    return FusionResult(output, weights, history, ac, wc, total)


def interval_gains(start: float, frames: int, fps: float, intervals) -> np.ndarray:
    gain = np.zeros(frames, dtype=np.float64)
    times = start + np.arange(frames) / fps
    for item in intervals:
        a, b = float(item["start"]), float(item["end"])
        if not np.isfinite([a, b]).all() or b <= a:
            raise NeedsReviewError("参考时间区间无效")
        gain[(times >= a) & (times < b)] = 1.0
    return gain
