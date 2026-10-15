"""Exercise bounded report replacement using app-owned fixtures, no build."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_worker

ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / "private/test-temp"
TEMP.mkdir(exist_ok=True)


def permission_error(code):
    error = PermissionError("simulated report sharing/permission failure")
    error.winerror = code
    return error


class FreezeReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="freeze-report-", dir=str(TEMP))
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "report.json"
        self.path.write_text('{"old": true}', encoding="utf-8")

    def test_transient_sharing_failure_retries_without_changing_permissions(self):
        replace = freeze_worker.os.replace
        calls = []
        def transient(source, target):
            calls.append((source, target))
            if len(calls) == 1:
                raise permission_error(32)
            return replace(source, target)
        with mock.patch.object(freeze_worker.os, "replace", side_effect=transient), mock.patch.object(freeze_worker.time, "sleep"):
            freeze_worker.write_report(self.path, {"new": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"new": True})

    def test_persistent_denial_is_bounded_and_retains_old_and_temporary_reports(self):
        before = self.path.read_bytes()
        with mock.patch.object(freeze_worker.os, "replace", side_effect=permission_error(5)) as replace, mock.patch.object(freeze_worker.time, "sleep") as sleep:
            with self.assertRaises(PermissionError):
                freeze_worker.write_report(self.path, {"new": True})
        self.assertEqual(replace.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(list(self.path.parent.glob("report.json.*.tmp"))), 1)

    def test_worker_test_report_separates_skips_from_executed_cases(self):
        root = self.path.parent
        stage = root / "stage"
        stage.mkdir()
        result = mock.Mock(returncode=0, stdout=b"", stderr=b"Ran 127 tests in 1.234s\n\nOK (skipped=1)\n")
        with mock.patch.object(freeze_worker.subprocess, "run", return_value=result):
            report = freeze_worker.run_worker_tests(root, root / "fixture-python.exe", stage, root, {})
        self.assertTrue(report["passed"])
        self.assertEqual(report["test_count"], 127)
        self.assertEqual(report["skipped_count"], 1)
        self.assertEqual(report["executed_test_count"], 126)

    def test_incomplete_worker_suite_still_blocks_freezing(self):
        root = self.path.parent
        stage = root / "stage"
        stage.mkdir()
        result = mock.Mock(returncode=0, stdout=b"", stderr=b"Ran 111 tests in 1.234s\n\nOK\n")
        with mock.patch.object(freeze_worker.subprocess, "run", return_value=result):
            report = freeze_worker.run_worker_tests(root, root / "fixture-python.exe", stage, root, {})
        self.assertFalse(report["passed"])
        self.assertEqual(report["skipped_count"], 0)
        self.assertEqual(report["executed_test_count"], 111)

    def test_other_permission_failures_are_not_retried(self):
        before = self.path.read_bytes()
        with mock.patch.object(freeze_worker.os, "replace", side_effect=permission_error(1314)) as replace, mock.patch.object(freeze_worker.time, "sleep") as sleep:
            with self.assertRaises(PermissionError):
                freeze_worker.write_report(self.path, {"new": True})
        self.assertEqual(replace.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
