"""系统身份与记录写入原子性的残余红绿测试；不启动真实媒体引擎。"""
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from cha_stabilizer.adapters import gyroflow
from cha_stabilizer.errors import AppError
from cha_stabilizer.job_store import JobStore
import cha_stabilizer.job_store as store_module


_USER_SID = "S-1-5-21-100-200-300-1001"


class ResidualProcessIdentityTests(unittest.TestCase):
    def setUp(self):
        from test_gyroflow import GyroflowAdapterTests
        self.fixture = GyroflowAdapterTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.digest = hashlib.sha256(self.fixture.exe.read_bytes()).hexdigest()
        self.other = self.fixture.root / "ordinary.exe"
        self.other.write_bytes(b"ordinary unrelated executable image")

    def context(self, owners, *, current_sid=_USER_SID, session=1):
        return {"current_user_sid": current_sid, "current_session_id": session, "owners": owners}

    def run_audit(self, rows, context):
        with patch.object(gyroflow, "_windows_process_images", return_value=rows), \
                patch.object(gyroflow, "_process_owner_context", create=True, return_value=context), \
                patch.object(gyroflow, "_pe_resource", return_value=None):
            return gyroflow._gyroflow_process_ids(self.fixture.exe, self.digest)

    def test_no_gf_with_verified_protected_system_identities_is_not_blocked(self):
        rows = [
            {"pid": 4, "name": "System", "image_path": None, "query_error": 5},
            {"pid": 128, "name": "csrss.exe", "image_path": None, "query_error": 5},
            {"pid": 256, "name": "protected-service.exe", "image_path": None, "query_error": 5},
            {"pid": 512, "name": "ordinary.exe", "image_path": str(self.other)},
        ]
        owners = {
            4: {"sid": "S-1-5-18", "session_id": 0, "name": "System"},
            128: {"sid": "S-1-5-18", "session_id": 1, "name": "csrss.exe"},
            256: {"sid": "S-1-5-19", "session_id": 0, "name": "protected-service.exe"},
            512: {"sid": _USER_SID, "session_id": 1, "name": "ordinary.exe"},
        }
        self.assertEqual(self.run_audit(rows, self.context(owners)), [])

    def test_user_engine_disguised_as_csrss_is_still_unknown_not_excluded(self):
        rows = [{"pid": 128, "name": "csrss.exe", "image_path": None, "query_error": 5}]
        context = self.context({128: {"sid": _USER_SID, "session_id": 1, "name": "csrss.exe"}})
        with self.assertRaises(OSError):
            self.run_audit(rows, context)

    def test_null_sid_or_missing_session_is_not_system_identity(self):
        row = {"pid": 4, "name": "System", "image_path": None, "query_error": 5}
        for owner in ({"sid": None, "session_id": 0, "name": "System"},
                      {"sid": "S-1-5-18", "session_id": None, "name": "System"}):
            with self.subTest(owner=owner), self.assertRaises(OSError):
                self.run_audit([row], self.context({4: owner}))

    def test_snapshot_owner_mismatch_is_not_excluded(self):
        row = {"pid": 128, "name": "csrss.exe", "image_path": None, "query_error": 5}
        owner = {"sid": "S-1-5-18", "session_id": 1, "name": "different-process.exe"}
        with self.assertRaises(OSError):
            self.run_audit([row], self.context({128: owner}))

    def test_system_worker_does_not_exclude_its_own_state_domain(self):
        row = {"pid": 128, "name": "csrss.exe", "image_path": None, "query_error": 5}
        owner = {"sid": "S-1-5-18", "session_id": 0, "name": "csrss.exe"}
        with self.assertRaises(OSError):
            self.run_audit([row], self.context({128: owner}, current_sid="S-1-5-18", session=0))

    def test_readable_selected_engine_is_detected_even_under_system_owner(self):
        row = {"pid": 128, "name": "csrss.exe", "image_path": str(self.fixture.exe)}
        owner = {"sid": "S-1-5-18", "session_id": 0, "name": "csrss.exe"}
        self.assertEqual(self.run_audit([row], self.context({128: owner})), [128])

    def test_protected_system_pe_access_denied_can_use_independent_owner_proof(self):
        row = {"pid": 256, "name": "protected-service.exe", "image_path": str(self.other)}
        owner = {"sid": "S-1-5-19", "session_id": 0, "name": "protected-service.exe"}
        error = PermissionError("simulated readonly PE access denied")
        error.winerror = 5
        with patch.object(gyroflow, "_windows_process_images", return_value=[row]), \
                patch.object(gyroflow, "_process_owner_context", return_value=self.context({256: owner})), \
                patch.object(gyroflow, "_pe_resource", side_effect=error):
            self.assertEqual(gyroflow._gyroflow_process_ids(self.fixture.exe, self.digest), [])

    def test_user_pe_access_denied_is_not_excluded_by_system_like_name(self):
        row = {"pid": 256, "name": "protected-service.exe", "image_path": str(self.other)}
        owner = {"sid": _USER_SID, "session_id": 1, "name": "protected-service.exe"}
        error = PermissionError("simulated readonly PE access denied")
        error.winerror = 5
        with patch.object(gyroflow, "_windows_process_images", return_value=[row]), \
                patch.object(gyroflow, "_process_owner_context", return_value=self.context({256: owner})), \
                patch.object(gyroflow, "_pe_resource", side_effect=error):
            with self.assertRaises(OSError):
                gyroflow._gyroflow_process_ids(self.fixture.exe, self.digest)

    def test_unknown_owner_api_failure_stays_fail_closed(self):
        rows = [{"pid": 128, "name": "csrss.exe", "image_path": None, "query_error": 5}]
        with patch.object(gyroflow, "_windows_process_images", return_value=rows), \
                patch.object(gyroflow, "_process_owner_context", create=True, side_effect=OSError("owner metadata unavailable")):
            with self.assertRaises(OSError):
                gyroflow._gyroflow_process_ids(self.fixture.exe, self.digest)


class ResidualPublicContractTests(unittest.TestCase):
    @staticmethod
    def sanitizers():
        from cha_stabilizer.job_runner import _public_error_details
        return (store_module._public_job_value, _public_error_details)

    def test_exact_full_source_boolean_is_preserved_by_both_public_sanitizers(self):
        for sanitizer in self.sanitizers():
            for value in (True, False):
                with self.subTest(sanitizer=sanitizer.__name__, value=value):
                    public = sanitizer({"workflow": {"full_source": value}})
                    self.assertIs(public["workflow"]["full_source"], value)

    def test_full_source_nonboolean_and_other_source_keys_remain_redacted(self):
        for sanitizer in self.sanitizers():
            for value in (1, 0, "true", "D:/private/source.mp4", {"path": "private"}, [True], None):
                with self.subTest(sanitizer=sanitizer.__name__, value=value):
                    self.assertNotIn("full_source", sanitizer({"full_source": value}))
            public = sanitizer({"Full_Source": True, "manual_source": True,
                                "original_source": "D:/private/source.mp4", "other_source": {"safe": True}})
            self.assertEqual(public, {})


class ResidualRecordAtomicityTests(unittest.TestCase):
    def setUp(self):
        from test_stabilize import StabilizeWorkflowTests
        self.fixture = StabilizeWorkflowTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def new_job(self):
        job_id = self.fixture.create_running()
        record_path = self.fixture.store.get_run_dir(job_id) / "job.json"
        return job_id, record_path

    def test_oversize_terminal_result_does_not_leave_memory_verified(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            fixture.store.set_state(job_id, "verified_media", result={"tag": "x" * (2 * 1024 ** 2)})
        self.assertEqual(fixture.store.get(job_id)["state"], "running")
        self.assertEqual(path.read_bytes(), before)
        reloaded = JobStore(fixture.root)
        self.assertEqual(reloaded.get(job_id)["state"], "failed")
        self.assertEqual(reloaded.get(job_id)["error"]["code"], "worker_interrupted")

    def test_oversize_artifact_metadata_does_not_pollute_index_or_block_retry(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        media = fixture.store.get_run_dir(job_id) / "owned.mp4"
        media.write_bytes(b"owned fake media")
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            fixture.store.add_artifact(job_id, path=media, label="fake", kind="diagnostic", mime="video/mp4",
                                       metadata={"tag": "x" * (2 * 1024 ** 2)})
        self.assertEqual(fixture.store.get(job_id)["artifacts"], [])
        self.assertEqual(len(fixture.store._records[job_id]["artifact_paths"]), 0)
        self.assertEqual(path.read_bytes(), before)
        accepted = fixture.store.add_artifact(job_id, path=media, label="fake", kind="diagnostic", mime="video/mp4")
        fixture.store.set_state(job_id, "needs_review")
        self.assertEqual(JobStore(fixture.root).get(job_id)["artifacts"][0]["id"], accepted["id"])

    def test_json_write_failure_keeps_every_record_mutator_unchanged(self):
        fixture = self.fixture
        operations = ("set_state", "add_artifact", "update_progress", "workflow_stage", "set_workflow_preview", "add_warning", "bind_identity")
        for operation in operations:
            with self.subTest(operation=operation):
                job_id, path = self.new_job()
                media = fixture.store.get_run_dir(job_id) / "owned.mp4"
                media.write_bytes(b"owned fake media")
                before = copy.deepcopy(fixture.store._records[job_id])
                disk = path.read_bytes()
                with patch.object(store_module, "_atomic_json_write", side_effect=OSError("simulated JSON write failure")):
                    with self.assertRaises(OSError):
                        if operation == "set_state":
                            fixture.store.set_state(job_id, "verified_media", result={"validation": {"scope": "media_only"}})
                        elif operation == "add_artifact":
                            fixture.store.add_artifact(job_id, path=media, label="fake", kind="diagnostic", mime="video/mp4")
                        elif operation == "update_progress":
                            fixture.store.update_progress(job_id, "render", 0.5, "new progress")
                        elif operation == "workflow_stage":
                            fixture.store.workflow_stage(job_id, "source_acceptance", "running")
                        elif operation == "set_workflow_preview":
                            fixture.store.set_workflow_preview(job_id, "blocked")
                        elif operation == "add_warning":
                            fixture.store.add_warning(job_id, "new warning")
                        else:
                            fixture.store.bind_workflow_identity(job_id, "new_identity", {"sha256": "fake"})
                self.assertEqual(fixture.store._records[job_id], before)
                self.assertEqual(path.read_bytes(), disk)

    def test_create_write_failure_does_not_publish_a_phantom_job(self):
        fixture = self.fixture
        before = len(fixture.store.list())
        with patch.object(store_module, "_atomic_json_write", side_effect=OSError("simulated create failure")):
            with self.assertRaises(OSError):
                fixture.store.create("stabilize", fixture.request)
        self.assertEqual(len(fixture.store.list()), before)

    def test_preview_parent_sync_failure_keeps_parent_record_unchanged(self):
        fixture = self.fixture
        parent_id = fixture.verified_parent()
        artifact_id = fixture.store.get(parent_id)["artifacts"][0]["id"]
        child = fixture.store.create_linked_preview(parent_id, artifact_id)
        child_record = copy.deepcopy(fixture.store._records[child["id"]])
        child_record["job"]["state"] = "running"
        before = copy.deepcopy(fixture.store._records[parent_id])
        path = fixture.store.get_run_dir(parent_id) / "job.json"
        disk = path.read_bytes()
        with patch.object(store_module, "_atomic_json_write", side_effect=OSError("simulated parent sync failure")):
            with self.assertRaises(OSError):
                fixture.store._sync_preview_parent(child_record)
        self.assertEqual(fixture.store._records[parent_id], before)
        self.assertEqual(path.read_bytes(), disk)

    def test_safe_terminal_limit_failure_persists_one_small_failed_summary(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        fixture.runner._safe_set_state(job_id, "verified_media", stage="verified_media",
                                        result={"tag": "x" * (2 * 1024 ** 2)})
        self.assertEqual(fixture.store.get(job_id)["state"], "failed")
        stored = json.loads(path.read_text(encoding="utf-8"))["record"]["job"]
        self.assertEqual(stored["state"], "failed")
        self.assertLess(path.stat().st_size, 2 * 1024 ** 2)
        self.assertEqual(JobStore(fixture.root).get(job_id)["state"], "failed")

    def test_transient_json_failure_is_not_silently_verified(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        real = store_module._atomic_json_write
        calls = []

        def failing_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("simulated initial write failure")
            return real(*args, **kwargs)

        with patch.object(store_module, "_atomic_json_write", side_effect=failing_once):
            fixture.runner._safe_set_state(job_id, "verified_media", result={"validation": {"scope": "media_only"}})
        self.assertEqual(len(calls), 2)
        self.assertEqual(fixture.store.get(job_id)["state"], "failed")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["record"]["job"]["state"], "failed")

    def test_persistent_io_failure_is_explicit_and_healthy_job_remains_available(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        healthy = fixture.store.create("validate", {"source": str(fixture.source)})
        before = path.read_bytes()
        with patch.object(store_module, "_atomic_json_write", side_effect=OSError("simulated persistent storage failure")) as write:
            fixture.runner._safe_set_state(job_id, "verified_media", result={"validation": {"scope": "media_only"}})
        self.assertEqual(write.call_count, 2)
        self.assertEqual(fixture.store._records[job_id]["job"]["state"], "running")
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(AppError):
            fixture.store.get(job_id)
        with self.assertRaises(AppError):
            fixture.store.list()
        self.assertEqual(fixture.store.get(healthy["id"])["state"], "queued")
        reloaded = JobStore(fixture.root)
        self.assertEqual(reloaded.get(job_id)["state"], "failed")
        self.assertEqual(reloaded.get(job_id)["error"]["code"], "worker_interrupted")

    def test_shutdown_does_not_require_a_faked_successful_state_write(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        fixture.runner._events[job_id] = threading.Event()
        with patch.object(store_module, "_atomic_json_write", side_effect=OSError("simulated persistent storage failure")):
            fixture.runner._safe_set_state(job_id, "verified_media", result={"validation": {"scope": "media_only"}})
            fixture.runner.shutdown(wait=2.0)
        self.assertFalse(fixture.runner._thread.is_alive())
        with self.assertRaises(AppError):
            fixture.store.get(job_id)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["record"]["job"]["state"], "running")

    def test_startup_recovery_write_failure_preserves_record_and_isolates_healthy_job(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        before = path.read_bytes()
        healthy = fixture.store.create("validate", {"source": str(fixture.source)})
        fixture.store.set_state(healthy["id"], "failed")
        with patch.object(store_module, "_atomic_json_write", side_effect=OSError("simulated recovery write failure")):
            recovered = JobStore(fixture.root)
        self.assertEqual(recovered._records[job_id]["job"]["state"], "running")
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(AppError):
            recovered.get(job_id)
        with self.assertRaises(AppError):
            recovered.list()
        self.assertEqual(recovered.get(healthy["id"])["state"], "failed")
        self.assertEqual(JobStore(fixture.root).get(job_id)["error"]["code"], "worker_interrupted")

    def test_storage_fault_does_not_self_clear_or_allow_nonterminal_writes(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        before = path.read_bytes()
        fixture.store.mark_storage_unavailable(job_id)
        for _ in range(2):
            with self.assertRaises(AppError):
                fixture.store.get(job_id)
        with self.assertRaises(AppError):
            fixture.store.update_progress(job_id, "processing", 0.5, "still running")
        self.assertEqual(path.read_bytes(), before)
        fixture.store.set_state(job_id, "failed", stage="record_write_failed")
        self.assertEqual(fixture.store.get(job_id)["state"], "failed")
        self.assertNotEqual(path.read_bytes(), before)

    def test_preview_parent_link_failure_has_no_restart_phantom_child(self):
        fixture = self.fixture
        parent_id = fixture.verified_parent()
        artifact_id = fixture.store.get(parent_id)["artifacts"][0]["id"]
        parent_path = fixture.store.get_run_dir(parent_id) / "job.json"
        before = parent_path.read_bytes()
        real = store_module._atomic_json_write

        def fail_parent(path, *args, **kwargs):
            if Path(path) == parent_path:
                raise OSError("simulated parent link write failure")
            return real(path, *args, **kwargs)

        with patch.object(store_module, "_atomic_json_write", side_effect=fail_parent):
            with self.assertRaises(OSError):
                fixture.store.create_linked_preview(parent_id, artifact_id)
        self.assertEqual(parent_path.read_bytes(), before)
        self.assertEqual(len(fixture.store.list()), 1)
        self.assertEqual(len(JobStore(fixture.root).list()), 1)
        provisional = list(fixture.store.runs_root.glob("*/uncommitted-preview.json"))
        self.assertEqual(len(provisional), 1)

    def test_unreadable_bounded_record_is_not_silently_omitted_on_restart(self):
        fixture = self.fixture
        job_id, path = self.new_job()
        healthy = fixture.store.create("validate", {"source": str(fixture.source)})
        fixture.store.set_state(healthy["id"], "failed")
        for payload in (b'{"record":', b" " * (2 * 1024 ** 2 + 1)):
            with self.subTest(payload_bytes=len(payload)):
                path.write_bytes(payload)
                recovered = JobStore(fixture.root)
                with self.assertRaises(AppError):
                    recovered.get(job_id)
                with self.assertRaises(AppError):
                    recovered.list()
                self.assertEqual(recovered.get(healthy["id"])["state"], "failed")
                self.assertEqual(path.read_bytes(), payload)

    def test_preview_metadata_write_failure_has_explicit_storage_diagnostic(self):
        fixture = self.fixture
        parent_id = fixture.verified_parent()
        before = copy.deepcopy(fixture.store._records[parent_id])
        path = fixture.store.get_run_dir(parent_id) / "job.json"
        disk = path.read_bytes()
        with patch.object(fixture.runner, "_stopping", True), \
                patch.object(store_module, "_atomic_json_write", side_effect=OSError("simulated preview status failure")):
            fixture.runner._schedule_preview(parent_id)
        self.assertEqual(fixture.store._records[parent_id], before)
        self.assertEqual(path.read_bytes(), disk)
        with self.assertRaises(AppError):
            fixture.store.get(parent_id)
        self.assertTrue(fixture.runner._queue.empty())

    def test_legacy_large_stream_tags_finish_with_truthful_bounded_persisted_status(self):
        fixture = self.fixture
        job_id = fixture.create_running("validate", {"source": str(fixture.source)})
        directory = fixture.store.get_run_dir(job_id)
        path = directory / "job.json"
        (directory / "manifest.json").write_text("{}", encoding="utf-8")
        tags = {"tag" + str(index): "x" * 1000 for index in range(100)}
        validation = {"status": "verified_media", "scope": "media_only",
                      "metadata": {"raw_streams": [{"tags": tags} for _ in range(40)]},
                      "full_decode_passed": True, "frame_count_verified": True}
        fixture.runner._finish_result(job_id, {
            "outputs": [{"path": directory / "manifest.json", "kind": "manifest", "mime": "application/json"}],
            "manifest": directory / "manifest.json", "validation": validation,
        }, [fixture.source])
        memory = fixture.store.get(job_id)
        disk = json.loads(path.read_text(encoding="utf-8"))["record"]["job"]
        self.assertNotIn(memory["state"], ("queued", "running"))
        self.assertEqual(memory["state"], disk["state"])
        self.assertLess(path.stat().st_size, 2 * 1024 ** 2)


if __name__ == "__main__":
    unittest.main()
