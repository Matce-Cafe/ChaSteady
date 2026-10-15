from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from cha_stabilizer.core.pipeline import run_fusion


class StopAtBlend(Exception):
    pass


class PipelineBranchTests(unittest.TestCase):
    def test_nonoverlap_skips_reference_timing_and_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory)
            paths = {name: workdir / (name + ".mp4") for name in ("original", "ctb", "reference")}
            quiet = np.tile(np.asarray([[1., 0., 0.], [0., 1., 0.]]), (5, 1, 1))

            def metadata(path, *args, **kwargs):
                result = {"fps": 50., "cfr_status": "metadata_consistent", "duration": 1.,
                          "width": 1280, "height": 720, "start_time": 0., "color_transfer": "bt709",
                          "color_primaries": "bt709", "raw_streams": [{"codec_type": "video",
                          "sample_aspect_ratio": "1:1", "field_order": "progressive"}]}
                if Path(path) == paths["reference"]:
                    result.update(fps=0., cfr_status="unverified", duration=None, width=640, height=480)
                return result

            def stop(q, reference, gains, *args):
                np.testing.assert_array_equal(q, quiet)
                np.testing.assert_array_equal(reference, quiet)
                self.assertFalse(np.any(gains))
                raise StopAtBlend()

            request = {"original": str(paths["original"]), "ctb": str(paths["ctb"]),
                       "reference": str(paths["reference"]), "start": 0., "end": .1,
                       "ctb_origin": 0., "reference_origin": 0., "reference_intervals": [{"start": .2, "end": .3}],
                       "mode": "fresh", "quiet_sigma_seconds": 1.3}
            with patch("cha_stabilizer.core.pipeline.require_tools", return_value={"ffmpeg": Path("ffmpeg"), "ffprobe": Path("ffprobe")}), \
                    patch("cha_stabilizer.core.pipeline.local_file", side_effect=lambda value, *args: Path(value)), \
                    patch("cha_stabilizer.core.pipeline.safe_workdir", return_value=workdir), \
                    patch("cha_stabilizer.core.pipeline.ensure_not_alias"), \
                    patch("cha_stabilizer.core.pipeline.probe", side_effect=metadata), \
                    patch("cha_stabilizer.core.pipeline.fingerprint", side_effect=lambda path: {"path": str(path)}), \
                    patch("cha_stabilizer.core.pipeline.check_cfr", return_value={"scope": "mock"}) as timing, \
                    patch("cha_stabilizer.core.pipeline.quiet_trajectory", return_value=(quiet, [], [])), \
                    patch("cha_stabilizer.core.pipeline.write_json"), \
                    patch("cha_stabilizer.core.pipeline.register_videos") as registration, \
                    patch("cha_stabilizer.core.pipeline.anchored_blend", side_effect=stop):
                with self.assertRaises(StopAtBlend):
                    run_fusion(request, workdir, {}, threading.Event(), lambda *args: None)
            self.assertEqual([call.args[0] for call in timing.call_args_list], [paths["original"], paths["ctb"]])
            registration.assert_not_called()


if __name__ == "__main__":
    unittest.main()
