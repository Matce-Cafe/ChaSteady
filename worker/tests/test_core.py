import unittest
from unittest.mock import patch
from pathlib import Path

import cv2
import numpy as np

from cha_stabilizer.errors import NeedsReviewError
from cha_stabilizer.core.geometry import affine, recover, compose, check_unit, expanded_canvas, corners
from cha_stabilizer.core.fusion import anchored_blend, interval_gains
from cha_stabilizer.core.registration import fit_pair
from cha_stabilizer.core.cache import HASHES
from cha_stabilizer.core.tracking import quiet_trajectory


SIZE = (1280, 720)


class CoreTests(unittest.TestCase):
    def setUp(self):
        cv2.setNumThreads(4)

    def trajectories(self, n=500, fps=50.):
        times = np.arange(n) / fps
        quiet = np.asarray([affine([3 * np.sin(t), 10 * t], 0., SIZE) for t in times])
        reference = np.asarray([affine([15 + np.sin(t * 32), -8 + np.cos(t * 29)],
                                      .02 + .006 * np.sin(t * 24), SIZE) for t in times])
        return quiet, reference

    def test_affine_source_origin_and_recover(self):
        matrix = affine([3., -8.], .032, SIZE)
        np.testing.assert_allclose(matrix[:, :2] @ (np.asarray(SIZE) / 2) + matrix[:, 2], [643., 352.])
        q, a = recover(matrix[None], SIZE)
        np.testing.assert_allclose(q, [[3., -8.]])
        np.testing.assert_allclose(a, [.032])

    def test_rotation_reflection_and_small_scale_rejected(self):
        matrix = affine([0, 0], 0., SIZE)[None]
        for scale in (1.0000002, 1.01, -1.):
            changed = matrix.copy()
            changed[:, 0, 0] *= scale
            with self.assertRaises(NeedsReviewError):
                check_unit(changed)

    def test_nonfinite_or_empty_rejected(self):
        for value in (np.zeros((0, 2, 3)), np.full((3, 2, 3), np.nan)):
            with self.assertRaises(NeedsReviewError):
                check_unit(value)

    def test_canvas_all_frames_offset_once(self):
        matrices = np.asarray([affine([40., -20.], .05, SIZE), affine([-100., 35.], -.07, SIZE)])
        canvas = expanded_canvas(matrices, SIZE)
        self.assertEqual(canvas.width % 2, 0)
        self.assertEqual(canvas.height % 2, 0)
        for m in matrices:
            p = corners(SIZE) @ m[:, :2].T + m[:, 2] + canvas.offset
            self.assertTrue(np.all(p >= 4 - 1e-8))
            self.assertTrue(np.all(p <= np.asarray([canvas.width, canvas.height]) - 4 + 1e-8))
        self.assertGreaterEqual(canvas.minimum_margin, 4.)

    def test_oversize_canvas_rejected_not_cropped(self):
        with self.assertRaises(NeedsReviewError):
            expanded_canvas(np.asarray([affine([10000, 0], 0, SIZE)]), SIZE)

    def test_quiet_endpoint_exact(self):
        quiet, reference = self.trajectories()
        result = anchored_blend(quiet, reference, np.zeros(len(quiet)))
        self.assertTrue(np.array_equal(result.matrices, quiet))
        self.assertFalse(result.actual_gain.any())
        self.assertFalse(result.anchors[:, 0].any())

    def test_reference_frozen_equivalence(self):
        quiet, reference = self.trajectories()
        result = anchored_blend(quiet, reference, np.ones(len(quiet)))
        anchor = result.anchors[0, 1]
        h = affine(anchor[:2], anchor[2], SIZE)
        self.assertTrue(np.all(result.actual_gain == 1.))
        self.assertTrue(np.all(result.anchors[:, 1] == anchor))
        expected = np.asarray([compose(h, m) for m in reference])
        np.testing.assert_allclose(result.matrices, expected, atol=1e-10, rtol=0.)

    def test_return_frozen_no_forced_pan_and_budget(self):
        quiet, reference = self.trajectories()
        result = anchored_blend(quiet, reference, np.r_[np.zeros(100), np.ones(200), np.zeros(200)])
        settled = np.flatnonzero((np.arange(500) > 320) & (result.actual_gain == 0))
        self.assertGreaterEqual(len(settled), 120)
        first = settled[0]
        anchor = result.anchors[first, 0]
        self.assertTrue(np.all(result.anchors[first:, 0] == anchor))
        h = affine(anchor[:2], anchor[2], SIZE)
        np.testing.assert_allclose(result.matrices[first:], [compose(h, m) for m in quiet[first:]], atol=1e-10, rtol=0.)
        self.assertLessEqual(result.anchor_changes.max(), .1000001)
        self.assertLessEqual(result.weight_changes.max(), .2500001)
        self.assertLessEqual(result.controller_changes.max(), .3500001)

    def test_fps_budgets_are_rates(self):
        for fps in (25., 60.):
            quiet, reference = self.trajectories(500, fps)
            result = anchored_blend(quiet, reference, np.r_[np.zeros(100), np.ones(200), np.zeros(200)], fps=fps)
            self.assertLessEqual(result.controller_changes.max(), 17.5 / fps + 1e-7)

    def test_interval_end_exclusive(self):
        gain = interval_gains(153., 150, 50., [{"start": 154., "end": 155.}])
        self.assertEqual(int(gain.sum()), 50)
        self.assertEqual(gain[49], 0)
        self.assertEqual(gain[50], 1)
        self.assertEqual(gain[100], 0)

    def test_bad_driver_rejected(self):
        quiet, reference = self.trajectories(10)
        with self.assertRaises(NeedsReviewError):
            anchored_blend(quiet, reference, np.full(10, np.nan))

    def test_cache_digests_are_sha256(self):
        self.assertEqual(len(HASHES), 6)
        for digest in HASHES.values():
            self.assertEqual(len(digest), 64)
            int(digest, 16)

    def test_registration_global_transform_scale_not_applied(self):
        size = (640, 360)
        rng = np.random.default_rng(142)
        source = rng.integers(35, 230, (360, 640, 3), dtype=np.uint8)
        source = cv2.GaussianBlur(source, (3, 3), .5)
        rotation = cv2.getRotationMatrix2D((320, 180), 1.2, 1.03)
        rotation[:, 2] += [8., -4.]
        target = cv2.warpAffine(source, rotation, size)
        matrix, record = fit_pair(source, target, size=size)
        self.assertTrue(record["accepted"], record)
        check_unit(matrix[None])
        self.assertAlmostEqual(record["scale_estimated_not_applied"], 1.03, places=2)
        q, _ = recover(matrix[None], size)
        np.testing.assert_allclose(q[0], [8., -4.], atol=.25, rtol=0.)

    def test_blank_registration_fails_not_identity(self):
        image = np.zeros((360, 640, 3), dtype=np.uint8)
        matrix, record = fit_pair(image, image, size=(640, 360))
        self.assertIsNone(matrix)
        self.assertFalse(record["accepted"])

    def test_impractical_smoothing_rejected_before_decoder(self):
        with patch("cha_stabilizer.core.tracking.FrameDecoder") as decoder:
            with self.assertRaises(NeedsReviewError):
                quiet_trajectory(Path("unused"), 0., 1., 0., 50., (640, 360), 1e6,
                                 Path("unused"), {"ffmpeg": Path("unused")}, None, lambda *args: None)
            decoder.assert_not_called()

    def test_blank_tracker_fails_not_identity_fill(self):
        class Decoder:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def frame(self, i):
                return np.zeros((360, 640, 3), np.uint8)
        with patch("cha_stabilizer.core.tracking.FrameDecoder", Decoder), self.assertRaises(NeedsReviewError):
            quiet_trajectory(Path("unused"), 0., .1, 0., 50., (640, 360), 1.3,
                             Path("unused"), {"ffmpeg": Path("unused")}, None, lambda *args: None)


if __name__ == "__main__":
    unittest.main()
