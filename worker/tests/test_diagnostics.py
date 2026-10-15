import io
import os
import re
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from cha_stabilizer.diagnostics import checkpoint


class DiagnosticCheckpointTests(unittest.TestCase):
    def test_default_is_silent(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stderr(output):
                checkpoint("job.running_state_written")
        self.assertEqual(output.getvalue(), "")

    def test_opt_in_emits_only_fixed_metadata(self):
        output = io.StringIO()
        sentinels = ("BEARER_SENTINEL", "C:\\private\\clip.mp4", "HANDLE_SENTINEL", "HEADER_SENTINEL")
        with patch.dict(os.environ, {"CHASTEADY_TEST_CHECKPOINTS": "1"}):
            with redirect_stderr(output):
                checkpoint("job.running_state_written")
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertRegex(
            lines[0],
            re.compile(r"^CHASTEADY_TEST_CHECKPOINT name=job\.running_state_written monotonic_ns=\d+ thread_id=\d+$"),
        )
        for sentinel in sentinels:
            self.assertNotIn(sentinel, output.getvalue())
        self.assertNotIn("path=", output.getvalue())
        self.assertNotIn("token=", output.getvalue())
        self.assertNotIn("handle=", output.getvalue())
        self.assertNotIn("headers=", output.getvalue())

    def test_unregistered_label_is_silent_even_when_enabled(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"CHASTEADY_TEST_CHECKPOINTS": "1"}):
            with redirect_stderr(output):
                checkpoint("source=C:\\private\\clip.mp4 token=secret")
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
