import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cha_stabilizer.errors import AppError, NeedsReviewError
from cha_stabilizer.job_runner import JobRunner
from cha_stabilizer.job_store import JobStore, PreferenceStore
from cha_stabilizer.models import RequestValidationError
from cha_stabilizer.owned_processes import OwnedProcessRegistry, registry_scope, spawn_owned_process


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"read-only-original")
        self.store = JobStore(self.root)
        self.preferences = PreferenceStore(self.root)
        self.preferences.update({"tool_paths": {"ffmpeg": sys.executable, "ffprobe": sys.executable}})
        self.runner = JobRunner(self.store, self.preferences)

    def tearDown(self):
        self.runner.shutdown()
        self.temp.cleanup()

    def test_fusion_input_roles_reject_hardlink_aliases(self):
        ctb_alias = self.root / "ctb-hardlink.mp4"
        reference = self.root / "reference.mp4"
        reference.write_bytes(b"separate-reference")
        try:
            os.link(str(self.source), str(ctb_alias))
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable in this test environment")
        with self.assertRaises(RequestValidationError):
            self.runner._resolve_inputs("fusion", {
                "original": str(self.source),
                "ctb": str(ctb_alias),
                "reference": str(reference),
            })

    def test_adapter_cannot_mark_verified_while_owned_child_is_running(self):
        job = self.store.create("validate", {"source": str(self.source)})
        self.store.set_state(job["id"], "running", stage="decoding", progress=None, message="Started")
        run_dir = self.store.get_run_dir(job["id"])
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "output.mp4").write_bytes(b"output")
        child = {}

        def run_validation(request, workdir, toolchain, cancel, on_event):
            child["process"] = spawn_owned_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return {
                "outputs": [{"path": run_dir / "output.mp4", "label": "Output", "kind": "video", "mime": "video/mp4"}],
                "manifest": run_dir / "manifest.json",
                "validation": {"status": "verified_media", "scope": "media_only"},
            }

        module = SimpleNamespace(run_validation=run_validation)
        registry = OwnedProcessRegistry(threading.Event())
        with registry_scope(registry), patch("cha_stabilizer.job_runner.importlib.import_module", return_value=module):
            self.runner._execute(job["id"], [self.source.resolve()], registry.cancel_event)
        self.assertEqual(self.store.get(job["id"])["state"], "failed")
        self.assertIsNotNone(child["process"].poll())
        self.assertEqual(self.store.get(job["id"])["artifacts"], [])

    def test_media_job_fails_missing_capability_without_ffprobe(self):
        self.preferences.update({"tool_paths": {"ffprobe": None}})
        job = self.store.create("validate", {"source": str(self.source)})
        self.store.set_state(job["id"], "running", stage="starting", progress=None, message="Started")
        with patch("cha_stabilizer.job_runner.importlib.import_module", side_effect=AssertionError("adapter must not run")):
            self.runner._execute(job["id"], [self.source.resolve()], threading.Event())
        failed = self.store.get(job["id"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["stage"], "missing_capability")
        self.assertEqual(failed["error"]["code"], "missing_capability")

    def test_worker_error_details_never_expose_paths_or_process_output(self):
        job = self.store.create("validate", {"source": str(self.source)})
        self.store.set_state(job["id"], "running", stage="starting", progress=None, message="Started")
        workdir = self.store.get_run_dir(job["id"])
        error_details = {
            "expected_frames": 150,
            "private_path": str(workdir / "secret.json"),
            "stderr": "could not open D:/private/runs/secret/input.mp4",
            "token": "not-for-client",
        }

        def run_validation(request, workdir, toolchain, cancel, on_event):
            raise AppError("failed while reading D:/private/runs/secret/input.mp4", error_details)

        module = SimpleNamespace(run_validation=run_validation)
        with patch("cha_stabilizer.job_runner.importlib.import_module", return_value=module):
            self.runner._execute(job["id"], [self.source.resolve()], threading.Event())

        saved = self.store.get(job["id"])
        self.assertEqual(saved["state"], "failed")
        public = repr(saved)
        self.assertNotIn("D:/private/runs", public)
        self.assertNotIn("secret.json", public)
        self.assertNotIn("not-for-client", public)
        self.assertNotIn("stderr", public)
        self.assertEqual(saved["result"]["details"]["expected_frames"], 150)

    def test_needs_review_registers_only_owned_retained_outputs(self):
        job = self.store.create("validate", {"source": str(self.source)})
        self.store.set_state(job["id"], "running", stage="validating", progress=None, message="Checking")
        run_dir = self.store.get_run_dir(job["id"])
        retained = run_dir / "mismatched-trim.mp4"
        retained.write_bytes(b"retained-render")
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"not-an-artifact")

        def run_validation(request, workdir, toolchain, cancel, on_event):
            raise NeedsReviewError("Frame/time mapping needs review.", {
                "expected_frames": 150,
                "outputs": [
                    {"path": retained, "label": "Retained diagnostic render", "kind": "diagnostic", "mime": "video/mp4"},
                    {"path": outside, "label": "Unsafe external path", "kind": "video", "mime": "video/mp4"},
                ],
            })

        module = SimpleNamespace(run_validation=run_validation)
        with patch("cha_stabilizer.job_runner.importlib.import_module", return_value=module):
            self.runner._execute(job["id"], [self.source.resolve()], threading.Event())

        saved = self.store.get(job["id"])
        self.assertEqual(saved["state"], "needs_review")
        self.assertEqual(len(saved["artifacts"]), 1)
        self.assertEqual(saved["artifacts"][0]["label"], "Retained diagnostic render")
        self.assertNotIn("outputs", saved["result"]["details"])
        self.assertEqual(len(saved["result"]["retained_artifact_ids"]), 1)
        self.assertTrue(self.source.is_file())


if __name__ == "__main__":
    unittest.main()
