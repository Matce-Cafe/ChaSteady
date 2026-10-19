"""六项独立复核缺陷的红绿回归；所有进程与媒体引擎均为模拟元数据。"""
import contextlib
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cha_stabilizer.adapters import gyroflow
from cha_stabilizer.core import stabilize
from cha_stabilizer.errors import CancelledError, NeedsReviewError
from cha_stabilizer.job_store import JobStore, _atomic_json_write, _read_json_regular
from cha_stabilizer.local_server import create_server
from cha_stabilizer.models import validate_job_request


class _Call:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


class _ProcessMetadataAPI:
    def __init__(self, image, name="GF-nightly.exe", *, query_ok=True):
        self.image = str(image)
        self.name = name
        self.query_ok = query_ok
        self.CreateToolhelp32Snapshot = _Call(lambda *args: 101)
        self.Process32FirstW = _Call(self.first)
        self.Process32NextW = _Call(self.next)
        self.OpenProcess = _Call(lambda *args: 202 if self.query_ok else 0)
        self.QueryFullProcessImageNameW = _Call(self.query)
        self.CloseHandle = _Call(lambda *args: 1)

    def first(self, handle, pointer):
        entry = pointer._obj
        entry.th32ProcessID = 4321
        entry.szExeFile = self.name
        return True

    def next(self, *args):
        if hasattr(gyroflow.ctypes, "set_last_error"):
            gyroflow.ctypes.set_last_error(18)
        return False

    def query(self, handle, flags, buffer, length):
        if not self.query_ok:
            return False
        buffer.value = self.image
        length._obj.value = len(self.image)
        return True


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        from test_stabilize import StabilizeWorkflowTests
        from test_gyroflow import GyroflowAdapterTests
        self.workflow = StabilizeWorkflowTests()
        self.workflow.setUp()
        self.addCleanup(self.workflow.tearDown)
        self.gf = GyroflowAdapterTests()
        self.gf.setUp()
        self.addCleanup(self.gf.tearDown)

    def _gyroflow_context(self, *, process_ids=True, launch=None):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(gyroflow, "_root", return_value=self.gf.root))
        stack.enter_context(patch.object(gyroflow, "_profile_roots", return_value=[("test_profile", self.gf.profile)]))
        stack.enter_context(patch.object(gyroflow, "_binary_identity", side_effect=lambda *args: self.gf._nightly_identity()))
        if process_ids:
            stack.enter_context(patch.object(gyroflow, "_gyroflow_process_ids", return_value=[]))
        mocked_launch = stack.enter_context(patch.object(gyroflow, "_launch_cli", side_effect=launch or self.gf._fake_launch()))
        stack.enter_context(patch.object(gyroflow, "_probe_media", side_effect=[self.gf._source_probe(), self.gf._output_probe()]))
        stack.enter_context(patch.object(gyroflow, "_decode_output", return_value={"passed": True, "error": None}))
        from cha_stabilizer.owned_processes import registry_scope
        stack.enter_context(registry_scope(self.gf.registry))
        return stack, mocked_launch

    def _gyroflow_export(self):
        return gyroflow.run_export({"original": str(self.gf.source), "project_template": str(self.gf.template),
                                    "start": 212, "end": 215}, self.gf.run_dir,
                                   {"gyroflow": self.gf.exe, "ffprobe": self.gf.ffprobe, "ffmpeg": self.gf.ffmpeg},
                                   self.gf.cancel, None)

    @unittest.skipUnless(os.name == "nt", "the mocked metadata ABI is Windows-specific")
    def test_selected_renamed_running_engine_blocks_before_launch(self):
        renamed = self.gf.tool_dir / "GF-nightly.exe"
        self.gf.exe.rename(renamed)
        self.gf.exe = renamed
        api = _ProcessMetadataAPI(renamed)
        stack, launch = self._gyroflow_context(process_ids=False)
        with stack, patch.object(gyroflow.ctypes, "WinDLL", return_value=api):
            with self.assertRaises(NeedsReviewError):
                self._gyroflow_export()
        launch.assert_not_called()
        self.assertEqual((self.gf.profile / "gyroflow.log").read_bytes(), b"previous profile log")

    @unittest.skipUnless(os.name == "nt", "the mocked metadata ABI is Windows-specific")
    def test_unknown_process_image_is_not_a_clear_concurrency_proof(self):
        api = _ProcessMetadataAPI("unreadable", name="opaque.exe", query_ok=False)
        stack, launch = self._gyroflow_context(process_ids=False)
        with stack, patch.object(gyroflow.ctypes, "WinDLL", return_value=api):
            with self.assertRaises(NeedsReviewError):
                self._gyroflow_export()
        launch.assert_not_called()
        self.assertEqual((self.gf.profile / "gyroflow.log").read_bytes(), b"previous profile log")

    def test_opaque_copy_is_detected_by_selected_image_digest_not_name(self):
        copied = self.gf.root / "opaque-engine.exe"
        copied.write_bytes(self.gf.exe.read_bytes())
        digest = hashlib.sha256(self.gf.exe.read_bytes()).hexdigest()
        rows = [{"pid": 7654, "name": "opaque-engine.exe", "image_path": str(copied)}]
        with patch.object(gyroflow, "_windows_process_images", return_value=rows), \
                patch.object(gyroflow, "_pe_resource", side_effect=AssertionError("exact copied image must be recognized by its audited digest")):
            self.assertEqual(gyroflow._gyroflow_process_ids(self.gf.exe, digest), [7654])

    def test_unknown_postlaunch_image_blocks_profile_log_restoration(self):
        stack, launch = self._gyroflow_context()
        with stack, patch.object(gyroflow, "_gyroflow_process_ids", side_effect=[
            [], [], OSError("process_image_unknown: pid=7654"),
            OSError("process_image_unknown: pid=7654"), OSError("process_image_unknown: pid=7654"),
        ]):
            with self.assertRaises(NeedsReviewError) as caught:
                self._gyroflow_export()
        self.assertEqual((self.gf.profile / "gyroflow.log").read_bytes(), b"new CLI log contents")
        self.assertEqual(caught.exception.details["concurrent_process_check"], "unverifiable")
        manifest = json.loads(Path(caught.exception.details["manifest"]).read_text(encoding="utf-8"))
        self.assertTrue(manifest["audit"]["concurrency_audit_errors"])
        self.assertIn("not_absolute_exclusion", manifest["audit"]["concurrency_audit_scope"])

    def test_large_validation_tags_do_not_make_a_terminal_job_unreadable(self):
        fixture = self.workflow
        job_id = fixture.create_running()
        directory = fixture.store.get_run_dir(job_id)
        validation = {"status": "verified_media", "scope": "media_only", "full_decode_passed": True,
                      "frame_count_verified": True, "frame_timestamp_spacing_verified": True,
                      "decode_scope": "all_non_attached_video_and_all_audio_streams",
                      "metadata": dict(fixture.metadata(), format={"tags": {"comment": "x" * (3 * 1024 ** 2)}}),
                      "frame_timestamps": {"sampled_frames": 5, "maximum_step_error": 0.0,
                                           "first_timestamp": 0.0, "last_timestamp": 0.08,
                                           "scope": "all_selected_interval_frame_timestamps"}}
        manual = fixture.manual_request("unused")["manual_ctb"]
        with patch.object(stabilize, "verify_output", return_value=validation):
            stabilize._accept_manual(manual, fixture.source, directory, fixture.metadata(), fixture.runner._toolchain(job_id),
                                      fixture.cancel, fixture.store, job_id)
        fixture.store.set_state(job_id, "needs_manual")
        self.assertLess((directory / "job.json").stat().st_size, 2 * 1024 ** 2)
        reloaded = JobStore(fixture.root)
        self.assertEqual(reloaded.get(job_id)["state"], "needs_manual")
        summary = reloaded.get_workflow_identity(job_id)["manual_ctb_validation"]
        self.assertTrue(summary["full_decode_passed"])
        self.assertEqual(summary["metadata"]["frames"], 5)
        self.assertNotIn("format", summary["metadata"])
        self.assertNotIn("raw_streams", summary["metadata"])
        self.assertEqual(len(validation["metadata"]["format"]["tags"]["comment"]), 3 * 1024 ** 2)

    def test_stored_json_write_ceiling_matches_read_ceiling(self):
        path = self.workflow.root / "bounded.json"
        _atomic_json_write(path, {"old": True})
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            _atomic_json_write(path, {"tag": "x" * (2 * 1024 ** 2)})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(_read_json_regular(path), {"old": True})

    def test_oversize_identity_rejection_keeps_memory_and_disk_record_readable(self):
        fixture = self.workflow
        job_id = fixture.create_running()
        record_path = fixture.store.get_run_dir(job_id) / "job.json"
        before = record_path.read_bytes()
        with self.assertRaises(ValueError):
            fixture.store.bind_workflow_identity(job_id, "oversize", {"tag": "x" * (2 * 1024 ** 2)})
        self.assertNotIn("oversize", fixture.store.get_workflow_identity(job_id))
        self.assertEqual(record_path.read_bytes(), before)
        self.assertEqual(_read_json_regular(record_path)["record"]["job"]["id"], job_id)

    def test_rounded_60fps_container_duration_is_metadata_not_a_false_grid_failure(self):
        fixture = self.workflow
        job_id = fixture.create_running()
        metadata = fixture.metadata()
        metadata.update(fps=60.0, frames=100, duration=1.666667)
        metadata["raw_streams"][0].update(avg_frame_rate="60/1", r_frame_rate="60/1", duration="1.666667", nb_frames="100")
        with patch.object(stabilize, "probe", return_value=metadata):
            fixture.runner._execute(job_id, [fixture.source], fixture.cancel)
        job = fixture.store.get(job_id)
        self.assertEqual(job["state"], "needs_manual")
        self.assertEqual(job["error"]["code"], "ctb_executor_unavailable")
        source_range = fixture.store.get_workflow_identity(job_id)["source_range"]
        self.assertEqual(source_range["frames"], 100)
        self.assertAlmostEqual(source_range["end"], 100 / 60)
        self.assertFalse(source_range["frame_count_verified"])

    def test_inconsistent_container_frame_count_is_still_review_not_resampling(self):
        fixture = self.workflow
        job_id = fixture.create_running()
        metadata = fixture.metadata()
        metadata.update(fps=60.0, frames=99, duration=1.666667)
        metadata["raw_streams"][0].update(duration="1.666667", nb_frames="99")
        with patch.object(stabilize, "probe", return_value=metadata):
            fixture.runner._execute(job_id, [fixture.source], fixture.cancel)
        self.assertEqual(fixture.store.get(job_id)["state"], "needs_review")

    def test_duration_preflight_does_not_allow_more_than_decimal_rounding(self):
        metadata = self.workflow.metadata()
        metadata.update(fps=60.0, frames=100, duration=1.666668)
        metadata["raw_streams"][0]["duration"] = "1.666668"
        with self.assertRaises(NeedsReviewError):
            stabilize._source_timeline(metadata)

    def test_unknown_container_frame_count_is_not_estimated_as_verified(self):
        metadata = self.workflow.metadata()
        metadata["frames"] = None
        with self.assertRaises(NeedsReviewError):
            stabilize._source_timeline(metadata)

    def test_overlapping_tool_backup_fails_before_copy_or_target_creation(self):
        cache = self.gf.tool_dir / "cache"
        cache.mkdir()
        (cache / "seed.bin").write_bytes(b"cache seed")
        target = cache / "DesktopData/private/runs/job/tool-directory-backup"
        with patch.object(gyroflow.shutil, "copyfileobj", side_effect=AssertionError("overlap must be rejected before copying")) as copied:
            with self.assertRaises(NeedsReviewError):
                gyroflow._tool_directory_snapshot(self.gf.exe, target)
        copied.assert_not_called()
        self.assertFalse(target.exists())

    def test_tool_snapshot_cancellation_and_total_byte_budget_are_fail_closed(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(CancelledError):
            gyroflow._tool_directory_snapshot(self.gf.exe, self.gf.root / "cancelled-backup", cancel=cancelled)
        self.assertFalse((self.gf.root / "cancelled-backup").exists())
        with self.assertRaises(NeedsReviewError):
            gyroflow._tool_directory_snapshot(self.gf.exe, self.gf.root / "budget-backup", max_bytes=4)

    def test_missing_math_dependency_degrades_only_stabilize_capability(self):
        server = create_server(self.workflow.root)
        self.addCleanup(server.server_close)
        original_import = __import__
        original_module = importlib.import_module

        def importing(name, *args, **kwargs):
            if name.endswith("core.stabilize"):
                raise ModuleNotFoundError("missing mathematical dependency", name="numpy")
            return original_import(name, *args, **kwargs)

        def module(name, *args, **kwargs):
            if name.endswith("core.stabilize"):
                raise ModuleNotFoundError("missing mathematical dependency", name="numpy")
            return original_module(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=importing), patch("cha_stabilizer.local_server.importlib.import_module", side_effect=module):
            capabilities = server.app.capabilities()
        self.assertIn("ffmpeg", capabilities)
        self.assertIn("preset_catalog", capabilities)
        self.assertFalse(capabilities["stabilize"]["available"])
        self.assertIn("worker_math_dependencies_unavailable", capabilities["stabilize"]["blocking_codes"])

    def test_unrelated_import_bug_is_not_silently_disguised_as_missing_math(self):
        server = create_server(self.workflow.root)
        self.addCleanup(server.server_close)
        original_import = __import__
        original_module = importlib.import_module

        def importing(name, *args, **kwargs):
            if name.endswith("core.stabilize"):
                raise ModuleNotFoundError("unrelated defect", name="cha_stabilizer.unexpected_bug")
            return original_import(name, *args, **kwargs)

        def module(name, *args, **kwargs):
            if name.endswith("core.stabilize"):
                raise ModuleNotFoundError("unrelated defect", name="cha_stabilizer.unexpected_bug")
            return original_module(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=importing), patch("cha_stabilizer.local_server.importlib.import_module", side_effect=module):
            with self.assertRaises(ModuleNotFoundError):
                server.app.capabilities()

    def test_external_template_change_cannot_be_attributed_as_actual_used_template(self):
        fixture = self.workflow
        parent = fixture.run_parent()
        accepted = fixture.runner._continuation_request(fixture.manual_request(parent))
        job_id = fixture.create_running("stabilize_continue", accepted)
        template = fixture.root / "changing-template.gyroflow"
        template_a = b'{"version":"A","gyro_source":{},"output":{}}'
        template_b = b'{"version":"B","gyro_source":{},"output":{}}'
        template.write_bytes(template_a)
        seen = {}

        def export(request, directory, tools, cancel, notify):
            seen["actual_template"] = Path(request["project_template"]).read_bytes()
            template.write_bytes(template_b)
            output = Path(directory) / "fresh-gf.mp4"
            output.write_bytes(b"fake rendered media from A")
            return {"outputs": [{"path": output, "mime": "video/mp4"}],
                    "validation": {"status": "verified_media", "content_correspondence_verified": False}}

        tools = fixture.runner._toolchain(job_id)
        tools["gyroflow"] = self.gf.exe
        with patch.object(stabilize, "probe", return_value=fixture.metadata()), \
                patch.object(stabilize, "verify_output", return_value={"status": "verified_media"}), \
                patch.object(stabilize, "capability", return_value={"blocking_codes": ["ctb_executor_unavailable"]}), \
                patch.object(stabilize, "_template", return_value=template), \
                patch.object(stabilize, "_tool_identity", return_value={"sha256": "fake-tool"}), \
                patch.object(fixture.runner, "_toolchain", return_value=tools), \
                patch.object(gyroflow, "run_export", side_effect=export):
            fixture.runner._execute(job_id, [fixture.source, fixture.manual], fixture.cancel)
        self.assertEqual(seen["actual_template"], template_a)
        self.assertEqual(template.read_bytes(), template_b)
        identity = fixture.store.get_workflow_identity(job_id)
        self.assertEqual(identity["gf"]["template_sha256"], hashlib.sha256(template_a).hexdigest())
        self.assertEqual(fixture.store.get(job_id)["state"], "needs_review")
        self.assertNotEqual(fixture.store.get(job_id)["error"]["code"], "full_content_correspondence_unverified")

    def test_adapter_retains_used_template_snapshot_and_does_not_verify_changed_source(self):
        template_a = self.gf.template.read_bytes()
        original_launch = self.gf._fake_launch()

        def changing_launch(*args):
            result = original_launch(*args)
            self.gf.template.write_bytes(b'{"changed":"B"}')
            return result

        stack, launch = self._gyroflow_context(launch=changing_launch)
        with stack:
            with self.assertRaises(NeedsReviewError) as caught:
                self._gyroflow_export()
        manifest = json.loads(Path(caught.exception.details["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["request"]["template_used_sha256"], hashlib.sha256(template_a).hexdigest())
        snapshot = Path(manifest["request"]["template_snapshot"])
        self.assertEqual(snapshot.read_bytes(), template_a)
        self.assertFalse(caught.exception.details["validation"]["template_source_unchanged"])


if __name__ == "__main__":
    unittest.main()
