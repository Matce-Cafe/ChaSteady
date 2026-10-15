import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from cha_stabilizer.errors import NeedsReviewError
from cha_stabilizer.core.media import check_cfr, verify_output


class MediaEvidenceTests(unittest.TestCase):
    def capture_pts(self, points):
        return subprocess.CompletedProcess([], 0, json.dumps({"frames": [
            {"best_effort_timestamp_time": str(t)} for t in points]}).encode(), b"")

    def test_probe_reads_past_boundary_but_counts_only_selected_frames(self):
        values = [1. + i / 50 for i in range(55)]
        with patch("cha_stabilizer.core.media.capture", return_value=self.capture_pts(values)) as capture:
            result = check_cfr(Path("input"), Path("probe"), 1., 2., 50.)
            self.assertEqual(result["sampled_frames"], 50)
            self.assertEqual(result["last_timestamp"], 1.98)
            command = capture.call_args[0][0]
            interval = command[command.index("-read_intervals") + 1]
            self.assertGreater(float(interval.split("%")[1]), 2.)

    def test_missing_last_frame_is_not_accepted(self):
        values = [1. + i / 50 for i in range(49)]
        with patch("cha_stabilizer.core.media.capture", return_value=self.capture_pts(values)):
            with self.assertRaises(NeedsReviewError):
                check_cfr(Path("input"), Path("probe"), 1., 2., 50.)

    def test_late_first_frame_is_not_accepted(self):
        values = [1. + i / 50 for i in range(1, 50)]
        with patch("cha_stabilizer.core.media.capture", return_value=self.capture_pts(values)):
            with self.assertRaises(NeedsReviewError):
                check_cfr(Path("input"), Path("probe"), 1., 2., 50.)

    def test_internal_pts_gap_rejected(self):
        values = [1. + i / 50 for i in range(50) if i != 25]
        with patch("cha_stabilizer.core.media.capture", return_value=self.capture_pts(values)):
            with self.assertRaises(NeedsReviewError):
                check_cfr(Path("input"), Path("probe"), 1., 2., 50.)

    def metadata(self, audio_duration="16.0"):
        return {"frames": 800, "fps": 50., "duration": 16., "audio_codec": "aac",
                "raw_streams": [{"codec_type": "audio", "duration": audio_duration, "start_time": "0"}]}

    def test_audio_tail_truncation_rejected(self):
        with patch("cha_stabilizer.core.media.probe", return_value=self.metadata("15.80")):
            with self.assertRaises(NeedsReviewError):
                verify_output(Path("output"), Path("ffmpeg"), Path("ffprobe"), 800, 50., 16., True)

    def test_verified_media_does_not_claim_fov_or_perceptual_win(self):
        with patch("cha_stabilizer.core.media.probe", return_value=self.metadata()), \
                patch("cha_stabilizer.core.media.check_cfr", return_value={"sampled_frames": 800}), \
                patch("cha_stabilizer.core.media.capture", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as capture:
            result = verify_output(Path("output"), Path("ffmpeg"), Path("ffprobe"), 800, 50., 16., True)
            self.assertEqual(result["status"], "verified_media")
            self.assertTrue(result["frame_count_verified"])
            self.assertTrue(result["full_decode_passed"])
            self.assertFalse(result["original_fov_verified"])
            self.assertFalse(result["perceptual_winner_claimed"])
            self.assertTrue(result["frame_timestamp_spacing_verified"])
            self.assertIn("0:V", capture.call_args[0][0])
            self.assertIn("0:a?", capture.call_args[0][0])

    def test_expected_average_rate_does_not_hide_variable_frame_spacing(self):
        values = [i / 50 for i in range(800)]
        values[400] += .001
        with patch("cha_stabilizer.core.media.probe", return_value=self.metadata()), \
                patch("cha_stabilizer.core.media.capture", return_value=self.capture_pts(values)):
            with self.assertRaises(NeedsReviewError):
                verify_output(Path("output"), Path("ffmpeg"), Path("ffprobe"), 800, 50., 16., True)

    def test_known_gamma22_not_retagged_as_bt709(self):
        from cha_stabilizer.core.pipeline import check_input
        meta = {"cfr_status": "metadata_consistent", "fps": 50., "start_time": 0., "duration": 1.,
                "color_transfer": "gamma22", "color_primaries": "bt709", "raw_streams": []}
        with self.assertRaises(NeedsReviewError):
            check_input(meta, 0., 1., 50.)

    def test_motion_probe_skips_cover_art(self):
        from cha_stabilizer.core.media import probe
        payload = {"streams": [
            {"codec_type": "video", "codec_name": "mjpeg", "width": 200, "height": 200,
             "disposition": {"attached_pic": 1}},
            {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720,
             "avg_frame_rate": "50/1", "r_frame_rate": "50/1", "duration": "16", "nb_frames": "800"}], "format": {}}
        result = subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b"")
        with patch("cha_stabilizer.core.media.local_file", side_effect=lambda value, *args: Path(value)), \
                patch("cha_stabilizer.core.media.capture", return_value=result):
            metadata = probe(Path("source"), Path("ffprobe"))
        self.assertEqual(metadata["video_codec"], "h264")
        self.assertEqual(metadata["frames"], 800)


if __name__ == "__main__":
    unittest.main()
