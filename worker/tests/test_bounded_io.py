"""有界 PTS 台账与自有假子进程测试，不启动真实媒体引擎。"""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cha_stabilizer.adapters import gyroflow
from cha_stabilizer.core.bounded_io import consume_lines, capture_small
from cha_stabilizer.errors import CancelledError, NeedsReviewError
from cha_stabilizer.owned_processes import OwnedProcessRegistry, registry_scope


class BoundedChildIOTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()
        self.registry = OwnedProcessRegistry(self.cancel)

    def run_code(self, code, callback=lambda line: None, **kwargs):
        with registry_scope(self.registry):
            return consume_lines([sys.executable, "-I", "-c", code], callback, self.cancel, **kwargs)

    def test_stdout_stderr_are_drained_with_bounded_line_consumer(self):
        lines = []
        result = self.run_code("import sys; print('first'); sys.stderr.write('diagnostic'); print('last')", lines.append)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(lines, [b"first", b"last"])
        self.assertEqual(result["stderr"], b"diagnostic")
        self.assertEqual(self.registry.snapshot(), [])

    def test_oversized_line_is_rejected_without_buffering_entire_output(self):
        with self.assertRaises(NeedsReviewError):
            self.run_code("import sys; sys.stdout.write('x'*100000); sys.stdout.flush()", max_line_bytes=1024)
        self.assertEqual(self.registry.snapshot(), [])

    def test_stdout_and_stderr_byte_budgets_are_enforced(self):
        for code, limits in (("print('x\\n'*10000)", {"max_stdout_bytes": 1024}),
                             ("import sys; sys.stderr.write('x'*100000)", {"max_stderr_bytes": 1024})):
            self.registry = OwnedProcessRegistry(self.cancel)
            with self.subTest(limits=limits), self.assertRaises(NeedsReviewError):
                self.run_code(code, **limits)
            self.assertEqual(self.registry.snapshot(), [])

    def test_deadline_terminates_only_owned_process(self):
        started = time.monotonic()
        with self.assertRaises(NeedsReviewError):
            self.run_code("import time; time.sleep(30)", timeout=0.2)
        self.assertLess(time.monotonic() - started, 8.0)
        self.assertEqual(self.registry.snapshot(), [])

    def test_cancellation_is_observed_during_blocked_pipe_read(self):
        timer = threading.Timer(0.2, self.cancel.set)
        timer.start()
        try:
            with self.assertRaises(CancelledError):
                self.run_code("import time; time.sleep(30)", timeout=20.0)
        finally:
            timer.cancel()
        self.assertEqual(self.registry.snapshot(), [])

    def test_small_metadata_capture_has_independent_byte_limit(self):
        with self.assertRaises(NeedsReviewError):
            capture_small([sys.executable, "-I", "-c", "print('x'*2000)"], max_bytes=1024)


class StreamingPTSLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.code = self.root / "code"
        self.data = self.root / "data"
        self.ledgers = self.root / "ledgers"
        for directory in (self.code, self.data, self.ledgers):
            directory.mkdir()
        self.fake = self.code / "fake_ffprobe.py"
        self.fake.write_text(
            "import json,sys\n"
            "from pathlib import Path\n"
            "args=sys.argv[1:]\n"
            "if '-show_frames' in args:\n"
            "    count=99 if Path(args[-1]).stem=='short' else 100\n"
            "    for index in range(count): print('best_effort_timestamp='+str(index*20))\n"
            "else:\n"
            "    print(json.dumps({'streams':[{'codec_type':'video','time_base':'1/1000','avg_frame_rate':'50/1','duration':'2.0','width':1280,'height':720}], 'format':{'duration':'2.0'}}))\n",
            encoding="utf-8")
        self.source = self.data / "source.mp4"
        self.source.write_bytes(b"fake source, never decoded by a real media engine")
        self.cancel = threading.Event()

    def tearDown(self):
        self.temp.cleanup()

    def probe(self, source):
        def small(command, cancel):
            return capture_small([sys.executable, "-I", str(self.fake)] + command[1:], cancel)

        def lines(command, callback, cancel, **kwargs):
            return consume_lines([sys.executable, "-I", str(self.fake)] + command[1:], callback, cancel, **kwargs)

        with patch.object(gyroflow, "capture_small", side_effect=small), \
                patch.object(gyroflow, "consume_lines", side_effect=lines):
            return gyroflow._probe_media(source, Path(sys.executable), self.cancel, ledger_dir=self.ledgers)

    def test_actual_fakeexec_uses_streaming_ledger_not_full_frame_json(self):
        probe = self.probe(self.source)
        self.assertNotIn("pts", probe)
        self.assertNotIn("frames", probe)
        self.assertEqual(probe["ledger_frames"], 100)
        self.assertTrue(probe["ledger_complete"])
        self.assertEqual(hashlib.sha256(probe["ledger_path"].read_bytes()).hexdigest(), probe["ledger_sha256"])
        result = gyroflow._mapping_evidence(probe, probe, None, None, True)
        self.assertTrue(result["trim_mapping_verified"])
        self.assertFalse(result["content_correspondence_verified"])
        self.assertEqual(result["expected_frames"], 100)

    def test_missing_frame_is_not_filled_or_trimmed_to_force_match(self):
        source = self.probe(self.source)
        short = self.data / "short.mp4"
        short.write_bytes(b"fake short output")
        output = self.probe(short)
        result = gyroflow._mapping_evidence(source, output, None, None, True)
        self.assertFalse(result["trim_mapping_verified"])
        self.assertEqual(result["actual_frames"], 99)
        self.assertEqual(result["expected_frames"], 100)

    def test_tampered_or_partial_ledger_is_not_mapping_evidence(self):
        probe = self.probe(self.source)
        probe["ledger_path"].write_bytes(b"0\n20\n")
        with self.assertRaises(NeedsReviewError):
            gyroflow._mapping_evidence(probe, probe, None, None, True)
        probe["ledger_complete"] = False
        with self.assertRaises(NeedsReviewError):
            list(gyroflow._iter_probe_pts(probe))

    def test_mapping_consumes_iterators_without_materializing_all_pts(self):
        count = 10000
        source = {"stream": {"time_base": "1/50000"}, "pts": (Fraction(index, 50) for index in range(count))}
        output = {"stream": {"time_base": "1/1000"}, "pts": (Fraction(index, 50) for index in range(count))}
        result = gyroflow._mapping_evidence(source, output, None, None, True)
        self.assertTrue(result["trim_mapping_verified"])
        self.assertEqual(result["actual_frames"], count)
        self.assertFalse(result["content_correspondence_verified"])

    def test_pts_comparison_observes_cancellation_without_content_claim(self):
        source = {"stream": {"time_base": "1/1000"}, "pts": [Fraction(0), Fraction(1, 50)]}
        output = {"stream": {"time_base": "1/1000"}, "pts": [Fraction(0), Fraction(1, 50)]}
        self.cancel.set()
        with self.assertRaises(CancelledError):
            gyroflow._mapping_evidence(source, output, None, None, True, cancel=self.cancel)

    def test_full_decode_maps_all_non_attached_video_and_all_audio(self):
        seen = {}

        def consume(command, callback, cancel, **kwargs):
            seen.update(command=command, budget=kwargs)
            return {"returncode": 0, "stderr": b""}

        with patch.object(gyroflow, "consume_lines", side_effect=consume):
            result = gyroflow._decode_output(self.source, Path(sys.executable), self.cancel, 351.84)
        self.assertTrue(result["passed"])
        self.assertIn("0:V", seen["command"])
        self.assertIn("0:a?", seen["command"])
        self.assertIn("-xerror", seen["command"])
        self.assertGreater(seen["budget"]["timeout"], 300)
        self.assertEqual(result["scope"], "all_non_attached_video_and_all_audio_streams")


if __name__ == "__main__":
    unittest.main()
