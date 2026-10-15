import ctypes
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cha_stabilizer.job_store import JobStore, PreferenceStore
from cha_stabilizer.paths import UnsafePathError


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"read-only-source")

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows protected DACL check")
    def test_new_run_and_preferences_objects_have_protected_dacls(self):
        preferences = PreferenceStore(self.root)
        preferences.update({"theme_mode": "dark"})
        store = JobStore(self.root)
        job = store.create("validate", {"source": str(self.source)})
        run_dir = store.get_run_dir(job["id"])
        paths = [run_dir, run_dir / "job.json", self.root / "private" / "preferences.json"]
        for path in paths:
            result = subprocess.run(
                ["icacls", str(path)], check=True, capture_output=True, text=True,
                encoding="cp{}".format(ctypes.windll.kernel32.GetOEMCP()),
            )
            acl = result.stdout
            self.assertNotIn("Authenticated Users", acl)
            self.assertNotIn("BUILTIN\\Users", acl)
            self.assertIn("SYSTEM", acl)
            self.assertIn("Administrators", acl)

    @unittest.skipUnless(os.name == "nt", "Windows existing preferences ACL preservation")
    def test_preferences_atomic_update_preserves_existing_dacl(self):
        private = self.root / "private"
        private.mkdir()
        preference_path = private / "preferences.json"
        preference_path.write_text(json.dumps(PreferenceStore.DEFAULTS), encoding="utf-8")

        encoding = "cp{}".format(ctypes.windll.kernel32.GetOEMCP())

        def acl_text():
            return subprocess.run(
                ["icacls", str(preference_path)], check=True, capture_output=True,
                text=True, encoding=encoding,
            ).stdout

        before = acl_text()
        preferences = PreferenceStore(self.root)
        preferences.update({"theme_mode": "dark"})
        after = acl_text()
        self.assertEqual(after, before)

    def test_preferences_live_only_in_app_private_directory(self):
        settings = self.root / "settings.json"
        settings.write_text("unchanged", encoding="utf-8")
        preferences = PreferenceStore(self.root)
        defaults = preferences.get()
        self.assertEqual(defaults["theme_mode"], "system")
        updated = preferences.update({"theme_mode": "dark", "tool_paths": {"gyroflow": None}})
        self.assertEqual(updated["theme_mode"], "dark")
        self.assertIsNone(updated["tool_paths"]["gyroflow"])
        self.assertTrue((self.root / "private" / "preferences.json").is_file())
        self.assertEqual(settings.read_text(encoding="utf-8"), "unchanged")

        reopened = PreferenceStore(self.root)
        self.assertEqual(reopened.get(), updated)

    def test_private_json_rejects_hardlink_aliases(self):
        from cha_stabilizer.job_store import _read_json_regular

        source_json = self.root / "state.json"
        source_json.write_text("{}", encoding="utf-8")
        alias = self.root / "state-alias.json"
        try:
            os.link(str(source_json), str(alias))
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable in this test environment")
        with self.assertRaises(ValueError):
            _read_json_regular(alias)

    def test_restart_marks_inflight_jobs_interrupted_without_deleting_sources(self):
        store = JobStore(self.root)
        job = store.create("validate", {"source": str(self.source)})
        store.set_state(job["id"], "running", stage="decoding", progress=None, message="Decoding")
        job_file = store.get_run_dir(job["id"]) / "job.json"
        self.assertTrue(job_file.is_file())

        reopened = JobStore(self.root)
        loaded = reopened.get(job["id"])
        self.assertEqual(loaded["state"], "failed")
        self.assertEqual(loaded["error"]["code"], "worker_interrupted")
        self.assertTrue(self.source.is_file())
        self.assertEqual(self.source.read_bytes(), b"read-only-source")

    def test_corrupt_artifact_index_does_not_crash_job_store_recovery(self):
        store = JobStore(self.root)
        job = store.create("validate", {"source": str(self.source)})
        job_file = store.get_run_dir(job["id"]) / "job.json"
        record = json.loads(job_file.read_text(encoding="utf-8"))["record"]
        record["artifact_paths"] = None
        job_file.write_text(json.dumps({"record": record}), encoding="utf-8")

        reopened = JobStore(self.root)
        recovered = reopened.get(job["id"])
        self.assertEqual(recovered["state"], "failed")
        self.assertEqual(recovered["error"]["code"], "worker_interrupted")
        self.assertEqual(recovered["artifacts"], [])

    def test_public_jobs_redact_legacy_run_paths_from_persisted_fields(self):
        store = JobStore(self.root)
        job = store.create("validate", {"source": str(self.source)})
        store.set_state(job["id"], "running", stage="starting", progress=None, message="Started")
        run_dir = store.get_run_dir(job["id"])
        store.set_state(
            job["id"], "needs_review", stage="needs_review", progress=None,
            message="failed at {}".format(run_dir / "secret.json"),
            error={"code": "needs_review", "message": "see {}".format(run_dir / "secret.json")},
            result={"details": {"worker_path": str(run_dir / "secret.json"), "expected_frames": 150}},
        )
        public = store.get(job["id"])
        self.assertNotIn(str(run_dir), repr(public))
        self.assertNotIn("secret.json", repr(public))
        self.assertEqual(public["result"]["details"]["expected_frames"], 150)
        reopened = JobStore(self.root)
        recovered = reopened.get(job["id"])
        self.assertNotIn(str(run_dir), repr(recovered))
        self.assertEqual(recovered["state"], "needs_review")

    def test_job_state_transitions_are_truthful_and_terminal(self):
        store = JobStore(self.root)
        job = store.create("validate", {"source": str(self.source)})
        self.assertIn("error", job)
        self.assertIsNone(job["error"])
        self.assertIn("result", job)
        self.assertIsNone(job["result"])
        store.set_state(job["id"], "running", stage="starting", progress=None, message="Started")
        store.set_state(
            job["id"], "needs_review", stage="needs_review", progress=None,
            message="Evidence was insufficient", error={"code": "needs_review", "message": "Evidence was insufficient"},
        )
        self.assertEqual(store.get(job["id"])["state"], "needs_review")
        with self.assertRaises(ValueError):
            store.set_state(job["id"], "verified_media", stage="verified_media", progress=1.0)

    def test_get_run_dir_rejects_a_reparse_replacement(self):
        store = JobStore(self.root)
        job = store.create("validate", {"source": str(self.source)})
        run_dir = store.get_run_dir(job["id"])
        moved = self.root / job["id"]
        run_dir.rename(moved)
        try:
            run_dir.symlink_to(moved, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory reparse points are unavailable in this test environment")
        with self.assertRaises(UnsafePathError):
            store.get_run_dir(job["id"])

    def test_artifact_metadata_hides_paths_and_rejects_escapes(self):
        store = JobStore(self.root)
        job = store.create("preview", {"source": str(self.source)})
        run_dir = store.get_run_dir(job["id"])
        artifact_file = run_dir / "preview.mp4"
        artifact_file.write_bytes(b"owned-media")
        artifact = store.add_artifact(
            job["id"], path=artifact_file, label="Preview", kind="preview", mime="video/mp4",
            metadata={"path": str(self.source), "width": 1280}, inputs=[self.source]
        )
        self.assertNotIn("path", artifact)
        self.assertNotIn("path", artifact["media_metadata"])
        self.assertEqual(artifact["media_metadata"]["width"], 1280)
        self.assertEqual(artifact["url"], "/api/artifacts/{}/content".format(artifact["id"]))
        saved, resolved, stored_run, stored_inputs = store.get_artifact(artifact["id"])
        self.assertEqual(resolved, artifact_file.resolve())
        self.assertEqual(stored_run, run_dir)
        self.assertEqual(stored_inputs, [self.source.resolve()])
        self.assertEqual(saved["id"], artifact["id"])

        outside = self.root / "outside.mp4"
        outside.write_bytes(b"not-owned")
        with self.assertRaises(UnsafePathError):
            store.add_artifact(job["id"], path=outside, label="Escape", kind="video", mime="video/mp4")

    def test_artifact_cannot_alias_source_or_prior_artifact(self):
        store = JobStore(self.root)
        job = store.create("preview", {"source": str(self.source)})
        run_dir = store.get_run_dir(job["id"])
        output = run_dir / "one.mp4"
        output.write_bytes(b"owned")
        store.add_artifact(job["id"], path=output, label="One", kind="video", mime="video/mp4", inputs=[self.source])
        with self.assertRaises(UnsafePathError):
            store.add_artifact(job["id"], path=output, label="Alias", kind="video", mime="video/mp4", inputs=[self.source])

        linked = run_dir / "source-link.mp4"
        try:
            os.link(str(self.source), str(linked))
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable in this test environment")
        with self.assertRaises(UnsafePathError):
            store.add_artifact(job["id"], path=linked, label="Input alias", kind="video", mime="video/mp4", inputs=[self.source])


if __name__ == "__main__":
    unittest.main()
