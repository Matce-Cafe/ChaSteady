import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cha_stabilizer import cli


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_same_process_duplicate_is_rejected_and_release_allows_reacquire(self):
        first = cli.LocalInstanceLock(self.root)
        second = cli.LocalInstanceLock(self.root)
        self.assertTrue(first.acquire())
        try:
            self.assertFalse(second.acquire())
        finally:
            first.release()
        third = cli.LocalInstanceLock(self.root)
        self.assertTrue(third.acquire())
        third.release()

    def test_second_process_is_rejected_and_lock_releases_after_first_exits(self):
        first = cli.LocalInstanceLock(self.root)
        self.assertTrue(first.acquire())
        worker_path = Path(cli.__file__).resolve().parents[1]
        code = (
            "import sys; from pathlib import Path; "
            "sys.path.insert(0, {!r}); "
            "from cha_stabilizer.cli import LocalInstanceLock; "
            "lock=LocalInstanceLock(Path(sys.argv[1])); "
            "acquired=lock.acquire(); print('ACQUIRED' if acquired else 'BUSY', flush=True); "
            "lock.release() if acquired else None"
        ).format(str(worker_path))
        try:
            child = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", code, str(self.root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "BUSY")
        finally:
            first.release()
        second = cli.LocalInstanceLock(self.root)
        self.assertTrue(second.acquire())
        second.release()

    def test_cli_duplicate_exits_before_server_or_job_store_creation(self):
        stderr = io.StringIO()
        with patch("cha_stabilizer.cli.LocalInstanceLock") as lock_class, \
                patch("cha_stabilizer.cli.create_server") as create_server, \
                contextlib.redirect_stderr(stderr):
            lock_class.return_value.acquire.return_value = False
            status = cli.main(["--no-browser"])
        self.assertEqual(status, 2)
        lock_class.assert_called_once()
        create_server.assert_not_called()
        self.assertIn("already running", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
