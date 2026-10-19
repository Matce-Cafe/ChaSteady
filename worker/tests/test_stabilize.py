"""单原片契约、不可变来源与真实阻塞的单元测试；不运行真实 GF 或 CTB。"""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from cha_stabilizer.adapters import gyroflow
from cha_stabilizer.core import stabilize
from cha_stabilizer.errors import NeedsReviewError
from cha_stabilizer.job_runner import JobRunner
from cha_stabilizer.job_store import JobStore, PreferenceStore
from cha_stabilizer.models import (
    RequestValidationError, STABILIZE_PARAMETERS, STABILIZE_PARAMETER_BOUNDS,
    STABILIZE_STAGES, validate_job_request,
)
from cha_stabilizer.runtime_context import RunnerContext


class StabilizeModelTests(unittest.TestCase):
    def setUp(self):
        self.original = str(Path(tempfile.gettempdir()).resolve() / "source.mp4")
        self.ctb = str(Path(tempfile.gettempdir()).resolve() / "manual.mp4")

    def test_default_is_versioned_full_source_with_six_parameters(self):
        request = validate_job_request({"kind": "stabilize", "request": {"original": self.original}})["request"]
        self.assertEqual(request["profile"], "recommended-v1")
        self.assertIs(request["full_source"], True)
        self.assertEqual(request["parameters"], STABILIZE_PARAMETERS)
        self.assertEqual(validate_job_request({"kind": "stabilize", "request": request})["request"], request)

    def test_parameter_units_and_bounded_overrides(self):
        for key, bounds in STABILIZE_PARAMETER_BOUNDS.items():
            with self.subTest(key=key):
                normalized = validate_job_request({"kind": "stabilize", "request": {
                    "original": self.original, "parameters": {key: bounds["max"]}}})["request"]
                self.assertEqual(normalized["parameters"][key], bounds["max"])
                self.assertTrue(bounds["unit"])
                for value in (True, float("nan"), float("inf"), bounds["max"] + 1, -1):
                    with self.assertRaises(RequestValidationError):
                        validate_job_request({"kind": "stabilize", "request": {
                            "original": self.original, "parameters": {key: value}}})

    def test_no_client_executor_trim_gate_cache_or_root_overrides(self):
        for extra in ({"start": 0}, {"end": 1}, {"full_source": False}, {"full_source": 1},
                      {"profile": "unknown"}, {"executable": self.original}, {"data_root": self.original},
                      {"skip_gates": True}, {"legacy_quiet_cache": self.ctb}, {"project_template": self.ctb},
                      {"parameters": {"content_verified": True}}):
            with self.subTest(extra=extra), self.assertRaises(RequestValidationError):
                validate_job_request({"kind": "stabilize", "request": dict(original=self.original, **extra)})

    def test_continue_has_only_parent_and_explicit_manual_declaration(self):
        request = {"parent_job_id": str(uuid.uuid4()), "manual_ctb": {
            "source": self.ctb, "origin_seconds": 0.0, "declared_at": "2026-10-19T01:02:03.123456Z"}}
        self.assertEqual(validate_job_request({"kind": "stabilize_continue", "request": request})["request"], request)
        for key in request["manual_ctb"]:
            bad = copy.deepcopy(request)
            bad["manual_ctb"].pop(key)
            with self.assertRaises(RequestValidationError):
                validate_job_request({"kind": "stabilize_continue", "request": bad})
        for extra in ({"original": self.original}, {"parameters": {}}, {"profile": "recommended-v1"}):
            with self.assertRaises(RequestValidationError):
                validate_job_request({"kind": "stabilize_continue", "request": dict(request, **extra)})
        for stamp in ("2026-10-19", "2026-10-19T01:00:00+00:00", "badZ", True):
            bad = copy.deepcopy(request)
            bad["manual_ctb"]["declared_at"] = stamp
            with self.assertRaises(RequestValidationError):
                validate_job_request({"kind": "stabilize_continue", "request": bad})

    def test_fresh_fusion_controller_parameters_do_not_change_legacy_normalization(self):
        old = {"original": self.original, "ctb": self.ctb, "reference": self.ctb + ".other.mp4", "start": 0, "end": 1}
        normalized = validate_job_request({"kind": "fusion", "request": old})["request"]
        self.assertNotIn("alignment_tau_seconds", normalized)
        for key in ("alignment_tau_seconds", "minimum_weight_transition_seconds", "weight_corner_speed", "anchor_corner_speed"):
            new = validate_job_request({"kind": "fusion", "request": dict(old, **{key: STABILIZE_PARAMETERS[key]})})["request"]
            self.assertEqual(new[key], STABILIZE_PARAMETERS[key])


class StabilizeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"immutable original bytes")
        self.manual = self.root / "manual.mp4"
        self.manual.write_bytes(b"manual CTB bytes")
        self.store = JobStore(self.root)
        self.preferences = PreferenceStore(self.root)
        self.preferences.update({"tool_paths": {"ffmpeg": sys.executable, "ffprobe": sys.executable}})
        self.runner = JobRunner(self.store, self.preferences)
        self.cancel = threading.Event()
        self.request = validate_job_request({"kind": "stabilize", "request": {"original": str(self.source)}})["request"]

    def tearDown(self):
        self.runner.shutdown()
        self.temp.cleanup()

    @staticmethod
    def metadata():
        return {"fps": 50.0, "duration": 0.1, "frames": 5, "width": 1280, "height": 720,
                "cfr_status": "metadata_consistent", "start_time": 0.0,
                "color_transfer": "bt709", "color_primaries": "bt709",
                "raw_streams": [{"codec_type": "video", "sample_aspect_ratio": "1:1", "field_order": "progressive"}]}

    def create_running(self, kind="stabilize", request=None):
        job = self.store.create(kind, request or self.request)
        self.store.set_state(job["id"], "running", stage="starting")
        return job["id"]

    def run_parent(self):
        job_id = self.create_running()
        with patch.object(stabilize, "probe", return_value=self.metadata()), \
                patch.object(gyroflow, "run_export", side_effect=AssertionError("GF must not run before legal CTB")):
            self.runner._execute(job_id, [self.source], self.cancel)
        return job_id

    def manual_request(self, parent):
        return {"parent_job_id": parent, "manual_ctb": {"source": str(self.manual), "origin_seconds": 0.0,
                                                       "declared_at": "2026-10-19T01:00:00Z"}}

    def test_automatic_preflight_blocks_without_fake_later_stages(self):
        parent_id = self.run_parent()
        job = self.store.get(parent_id)
        self.assertEqual(job["state"], "needs_manual")
        self.assertEqual(job["error"]["code"], "ctb_executor_unavailable")
        self.assertEqual(job["error"]["message_key"], "job.error.ctbExecutorUnavailable")
        self.assertEqual(job["workflow"]["stages"][0]["state"], "passed")
        self.assertEqual(job["workflow"]["stages"][1]["state"], "blocked")
        self.assertTrue(all(stage["state"] == "pending" for stage in job["workflow"]["stages"][2:]))
        identity = self.store.get_workflow_identity(parent_id)
        self.assertEqual(identity["original"]["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(identity["original"]["hash_scope"], "full_file")
        self.assertEqual(job["result"]["next_steps"]["automatic_ctb_exports"], 0)
        self.assertNotIn(str(self.source), json.dumps(job))
        self.assertIsNone(job["progress"])
        self.assertEqual(job["workflow"]["preview"]["state"], "not_requested")

    def test_missing_inspector_does_not_fake_source_acceptance(self):
        self.preferences.update({"tool_paths": {"ffprobe": None}})
        job_id = self.create_running()
        self.runner._execute(job_id, [self.source], self.cancel)
        job = self.store.get(job_id)
        self.assertEqual(job["state"], "needs_manual")
        self.assertEqual(job["workflow"]["stages"][0]["state"], "blocked")
        self.assertTrue(all(stage["state"] == "pending" for stage in job["workflow"]["stages"][1:]))
        self.assertIn("ffprobe_unavailable", job["result"]["next_steps"]["blocking_codes"])

    def test_continuation_uses_server_parent_and_new_uuid_without_reopening_parent(self):
        parent_id = self.run_parent()
        parent_before = (self.store.get_run_dir(parent_id) / "job.json").read_bytes()
        accepted = self.runner._continuation_request(self.manual_request(parent_id))
        self.assertEqual(accepted["original"], str(self.source))
        self.assertEqual(accepted["parameters"], self.request["parameters"])
        new_id = self.create_running("stabilize_continue", accepted)
        self.assertNotEqual(new_id, parent_id)
        self.assertEqual(self.store.get(new_id)["workflow"]["ctb_origin"], "manual_import")
        self.assertEqual((self.store.get_run_dir(parent_id) / "job.json").read_bytes(), parent_before)
        accepted["parameters"]["anchor_corner_speed"] = 99
        self.assertEqual(self.store.get_request(parent_id)["parameters"]["anchor_corner_speed"], 5.0)

    def test_changed_parent_source_fails_full_hash_before_manual_import(self):
        parent_id = self.run_parent()
        accepted = self.runner._continuation_request(self.manual_request(parent_id))
        self.source.write_bytes(b"changed original source")
        new_id = self.create_running("stabilize_continue", accepted)
        with patch.object(stabilize, "_copy_manual", side_effect=AssertionError("must reject before import")):
            self.runner._execute(new_id, [self.source, self.manual], self.cancel)
        self.assertEqual(self.store.get(new_id)["state"], "needs_review")
        self.assertEqual(self.store.get(parent_id)["state"], "needs_manual")
        self.assertEqual(self.store.get(new_id)["artifacts"], [])

    def test_manual_import_is_owned_even_if_production_template_is_unavailable(self):
        parent_id = self.run_parent()
        accepted = self.runner._continuation_request(self.manual_request(parent_id))
        new_id = self.create_running("stabilize_continue", accepted)
        validation = {"status": "verified_media", "scope": "media_only", "full_decode_passed": True}
        with patch.object(stabilize, "probe", return_value=self.metadata()), \
                patch.object(stabilize, "verify_output", return_value=validation), \
                patch.object(gyroflow, "run_export", side_effect=AssertionError("GF unavailable")):
            self.runner._execute(new_id, [self.source, self.manual], self.cancel)
        job = self.store.get(new_id)
        self.assertEqual(job["state"], "needs_manual")
        self.assertIn("gyroflow_template_unavailable", job["result"]["next_steps"]["blocking_codes"])
        self.assertEqual(len(job["artifacts"]), 1)
        artifact, imported, _, _ = self.store.get_artifact(job["artifacts"][0]["id"])
        self.assertNotEqual(imported, self.manual)
        self.assertEqual(imported.read_bytes(), self.manual.read_bytes())
        self.assertEqual(artifact["media_metadata"]["origin"], "manual_import")
        self.assertEqual(self.store.get_workflow_identity(new_id)["manual_ctb"]["owned"]["hash_scope"], "full_file")
        self.assertEqual(job["workflow"]["stages"][2]["state"], "pending")

    def test_same_original_goes_to_gf_and_content_unknown_stays_review(self):
        parent_id = self.run_parent()
        accepted = self.runner._continuation_request(self.manual_request(parent_id))
        new_id = self.create_running("stabilize_continue", accepted)
        template = self.root / "template.gyroflow"
        template.write_bytes(b"{}")
        observed = {}

        def export(request, workdir, tools, cancel, notify):
            observed.update(request)
            path = Path(workdir) / "fresh-gf.mp4"
            path.write_bytes(b"fake freshly exported GF")
            return {"outputs": [{"path": path, "mime": "video/mp4"}],
                    "validation": {"status": "verified_media", "trim_mapping_verified": True,
                                   "full_decode_verified": True, "content_correspondence_verified": False}}

        tools = self.runner._toolchain(new_id)
        tools["gyroflow"] = Path(sys.executable)
        report = {"blocking_codes": ["ctb_executor_unavailable"], "automatic_ctb_exports": 0}
        with patch.object(stabilize, "probe", return_value=self.metadata()), \
                patch.object(stabilize, "verify_output", return_value={"status": "verified_media"}), \
                patch.object(stabilize, "capability", return_value=report), \
                patch.object(stabilize, "_template", return_value=template), \
                patch.object(stabilize, "_tool_identity", side_effect=lambda name, path, cancel: {"sha256": name, "actual_version": "fakeexec"}), \
                patch.object(self.runner, "_toolchain", return_value=tools), \
                patch.object(gyroflow, "run_export", side_effect=export):
            self.runner._execute(new_id, [self.source, self.manual], self.cancel)
        job = self.store.get(new_id)
        self.assertEqual(observed["original"], str(self.source.resolve()))
        self.assertTrue(observed["full_source"])
        self.assertNotIn("start", observed)
        self.assertNotIn("end", observed)
        self.assertNotEqual(observed["original"], str(self.store.get_run_dir(new_id) / "manual-ctb.mp4"))
        self.assertEqual(job["state"], "needs_review")
        self.assertEqual(job["error"]["code"], "full_content_correspondence_unverified")
        self.assertEqual(job["workflow"]["stages"][4]["state"], "needs_review")
        self.assertTrue(all(item["state"] == "pending" for item in job["workflow"]["stages"][5:]))
        self.assertEqual(job["workflow"]["preview"]["state"], "not_requested")
        self.assertEqual(len(self.store.list()), 2)

    def test_stage_order_and_immutable_identity_cannot_be_overwritten(self):
        job_id = self.create_running()
        with self.assertRaises(ValueError):
            self.store.workflow_stage(job_id, "gf", "running")
        self.store.workflow_stage(job_id, "source_acceptance", "running")
        self.store.bind_workflow_identity(job_id, "original", {"sha256": "one"})
        with self.assertRaises(ValueError):
            self.store.bind_workflow_identity(job_id, "original", {"sha256": "two"})
        self.store.set_state(job_id, "needs_review")
        with self.assertRaises(ValueError):
            self.store.workflow_stage(job_id, "source_acceptance", "passed")
        with self.assertRaises(ValueError):
            self.store.set_state(job_id, "running")
        reloaded = JobStore(self.root)
        self.assertEqual(reloaded.get(job_id)["state"], "needs_review")
        self.assertEqual(reloaded.get(job_id)["workflow"]["stages"][0]["state"], "needs_review")
        self.assertEqual(reloaded.get_workflow_identity(job_id)["original"]["sha256"], "one")

    def test_interrupted_stage_is_failed_not_requeued(self):
        job_id = self.create_running()
        self.store.workflow_stage(job_id, "source_acceptance", "running")
        reloaded = JobStore(self.root)
        self.assertEqual(reloaded.get(job_id)["state"], "failed")
        stage = reloaded.get(job_id)["workflow"]["stages"][0]
        self.assertEqual(stage["state"], "failed")
        self.assertIsNotNone(stage["attempts"][0]["finished_at"])

    def test_profile_composition_is_fresh_and_passes_all_six_values(self):
        request = copy.deepcopy(self.request)
        request["parameters"].update(alignment_tau_seconds=0.2, weight_corner_speed=8.0)
        fusion = stabilize.fusion_request_for_profile(request, ctb=self.manual, reference=self.root / "gf.mp4", duration=0.1)
        normalized = validate_job_request({"kind": "fusion", "request": fusion})["request"]
        for key, value in request["parameters"].items():
            self.assertEqual(normalized[key], value)
        self.assertEqual(normalized["mode"], "fresh")
        self.assertEqual(normalized["reference_intervals"], [])
        self.assertIsNone(normalized["legacy_quiet_cache"])

    def verified_parent(self):
        job_id = self.create_running()
        for stage in STABILIZE_STAGES:
            self.store.workflow_stage(job_id, stage, "running")
            self.store.workflow_stage(job_id, stage, "passed")
        directory = self.store.get_run_dir(job_id)
        (directory / "manifest.json").write_text("{}", encoding="utf-8")
        (directory / "final.mp4").write_bytes(b"fake gated media")
        self.runner._finish_result(job_id, {
            "outputs": [{"path": directory / "final.mp4", "kind": "stabilized_media", "mime": "video/mp4"}],
            "manifest": directory / "manifest.json",
            "validation": {"status": "verified_media", "scope": "stabilize_full_source_declared_gates_and_media",
                           "content_correspondence_verified": True, "fresh_measurement_verified": True},
        }, [self.source])
        return job_id

    def test_independent_preview_is_queued_once_without_waiting_or_weakening_lease(self):
        parent_id = self.verified_parent()
        with patch.object(self.runner._queue, "put") as enqueue:
            self.runner._schedule_preview(parent_id)
            self.runner._schedule_preview(parent_id)
        self.assertEqual(enqueue.call_count, 1)
        parent = self.store.get(parent_id)
        preview_id = parent["workflow"]["preview"]["job_id"]
        self.assertIsNotNone(preview_id)
        self.assertNotEqual(parent_id, preview_id)
        self.assertEqual(self.store.get(preview_id)["kind"], "preview")
        self.assertEqual(self.store.get(preview_id)["state"], "queued")
        with self.assertRaises(KeyError):
            self.store.get_artifact(parent["artifacts"][0]["id"], verified_preview=True)
        self.store.set_state(preview_id, "running")
        self.assertEqual(self.store.get(parent_id)["workflow"]["preview"]["state"], "running")
        directory = self.store.get_run_dir(preview_id)
        (directory / "preview.mp4").write_bytes(b"fake validated playback proxy")
        artifact = self.store.add_artifact(preview_id, path=directory / "preview.mp4", label="preview", kind="preview",
                                           mime="video/mp4", validation_scope="preview_media_only")
        self.store.set_state(preview_id, "verified_media")
        parent = self.store.get(parent_id)
        self.assertEqual(parent["workflow"]["preview"], {"state": "ready", "job_id": preview_id, "artifact_id": artifact["id"]})
        self.assertEqual(self.store.get_artifact(artifact["id"], verified_preview=True)[0]["id"], artifact["id"])

    def test_preview_failure_and_restart_are_independent_from_parent_state(self):
        parent_id = self.verified_parent()
        with patch.object(self.runner._queue, "put"):
            self.runner._schedule_preview(parent_id)
        child_id = self.store.get(parent_id)["workflow"]["preview"]["job_id"]
        self.store.set_state(child_id, "running")
        self.store.set_state(child_id, "failed", error={"code": "processing_failed", "message": "fake encoder failure"})
        self.assertEqual(self.store.get(parent_id)["state"], "verified_media")
        self.assertEqual(self.store.get(parent_id)["workflow"]["preview"]["state"], "failed")
        reloaded = JobStore(self.root)
        self.assertEqual(reloaded.get(child_id)["state"], "failed")
        self.assertEqual(reloaded.get(parent_id)["workflow"]["preview"]["state"], "failed")
        self.assertEqual(reloaded.get(parent_id)["state"], "verified_media")

    def test_full_identity_compares_handle_ctime_not_path_creation_time(self):
        from types import SimpleNamespace
        handle_stat = self.source.stat()
        path_stat = SimpleNamespace(st_size=handle_stat.st_size, st_mtime_ns=handle_stat.st_mtime_ns,
                                    st_dev=handle_stat.st_dev, st_ino=handle_stat.st_ino, st_ctime_ns=-1)
        source = self.source

        class Input:
            def open(self, *args):
                return source.open(*args)

            def stat(self):
                return path_stat

            def __str__(self):
                return str(source)

        with patch.object(stabilize, "resolve_local_input", return_value=Input()):
            identity = stabilize.full_file_identity(source)
        self.assertEqual(identity["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertNotEqual(identity["ctime_ns"], -1)

    def test_verified_adapter_flag_does_not_bypass_workflow_gates_or_create_preview(self):
        job_id = self.create_running()
        directory = self.store.get_run_dir(job_id)
        (directory / "manifest.json").write_text("{}", encoding="utf-8")
        (directory / "output.mp4").write_bytes(b"fake output")
        self.runner._finish_result(job_id, {"outputs": [{"path": directory / "output.mp4", "mime": "video/mp4"}],
                                           "manifest": directory / "manifest.json",
                                           "validation": {"status": "verified_media", "scope": "media_only"}}, [self.source])
        self.assertEqual(self.store.get(job_id)["state"], "needs_review")
        self.assertEqual(len(self.store.list()), 1)


class FusionParameterWiringTests(unittest.TestCase):
    def test_profile_values_reach_tracking_registration_and_controller(self):
        import numpy as np
        from cha_stabilizer.core import pipeline
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {key: root / (key + ".mp4") for key in ("original", "ctb", "reference")}
            matrices = np.tile(np.array([[1., 0., 0.], [0., 1., 0.]]), (5, 1, 1))
            meta = StabilizeWorkflowTests.metadata()
            request = dict({key: str(value) for key, value in paths.items()}, start=0.0, end=0.1,
                           ctb_origin=0.0, reference_origin=0.0, reference_intervals=[{"start": 0.0, "end": 0.1}],
                           quiet_sigma_seconds=2.1, reference_fov=1.5, alignment_tau_seconds=0.2,
                           minimum_weight_transition_seconds=0.8, weight_corner_speed=30.0, anchor_corner_speed=6.0)

            class StopAfterWiring(Exception):
                pass

            def blend(quiet, reference, gains, fps, size, settings):
                self.assertEqual(settings.alignment_tau_seconds, 0.2)
                self.assertEqual(settings.minimum_weight_transition_seconds, 0.8)
                self.assertEqual(settings.weight_corner_speed, 30.0)
                self.assertEqual(settings.anchor_corner_speed, 6.0)
                raise StopAfterWiring()

            with patch.object(pipeline, "require_tools", return_value={"ffmpeg": Path(sys.executable), "ffprobe": Path(sys.executable)}), \
                    patch.object(pipeline, "local_file", side_effect=lambda path, *args: Path(path)), \
                    patch.object(pipeline, "safe_workdir", return_value=root), \
                    patch.object(pipeline, "ensure_not_alias"), \
                    patch.object(pipeline, "probe", return_value=meta), \
                    patch.object(pipeline, "fingerprint", return_value={}), \
                    patch.object(pipeline, "check_cfr", return_value={}), \
                    patch.object(pipeline, "quiet_trajectory", return_value=(matrices, {}, [])) as quiet, \
                    patch.object(pipeline, "register_videos", return_value=(matrices, {})) as registration, \
                    patch.object(pipeline, "write_json"), \
                    patch.object(pipeline, "anchored_blend", side_effect=blend):
                with self.assertRaises(StopAfterWiring):
                    pipeline.run_fusion(request, root, {}, threading.Event(), lambda *args: None)
            self.assertEqual(quiet.call_args.args[6], 2.1)
            self.assertEqual(registration.call_args.kwargs["reference_fov"], 1.5)


class ProductionGyroflowIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "DesktopData"
        self.data.mkdir()
        self.store = JobStore(self.data)
        self.job = self.store.create("validate", {"source": str(self.root / "source.mp4")})
        self.context = RunnerContext(self.data, self.store.runs_root, self.root, self.job["id"], True)
        self.exe = self.root / "arbitrary-name.exe"
        self.exe.write_bytes(b"not a trusted binary")

    def tearDown(self):
        self.temp.cleanup()

    def test_desktop_run_context_does_not_infer_source_private_runs(self):
        run_dir = self.store.get_run_dir(self.job["id"])
        with patch.object(gyroflow, "_root", return_value=self.root / "unrelated-resources"):
            self.assertEqual(gyroflow._validated_run_dir(run_dir, self.context), run_dir)
        another = self.store.create("validate", {"source": "unused"})
        with self.assertRaises(NeedsReviewError):
            gyroflow._validated_run_dir(self.store.get_run_dir(another["id"]), self.context)

    @unittest.skipUnless(os.name == "nt", "PE version resources require Windows")
    def test_read_actual_trusted_python_pe_version_without_launching_an_engine(self):
        version = gyroflow._pe_version(Path(sys.executable))
        self.assertIsNotNone(version)
        self.assertEqual([int(value) for value in version.split(".")[:2]], list(sys.version_info[:2]))

    def test_production_requires_both_reviewed_hash_and_actual_version(self):
        with patch.object(gyroflow, "_pe_version", return_value="1.6.3.0"):
            self.assertIsNone(gyroflow._production_binary_identity(self.exe, "0" * 64))
            identity = gyroflow._production_binary_identity(self.exe, gyroflow._NIGHTLY_SHA256)
        self.assertEqual(identity["actual_file_version"], "1.6.3.0")
        self.assertTrue(identity["direct_cli_launch_supported"])
        with patch.object(gyroflow, "_pe_version", return_value="9.0.0.0"):
            self.assertIsNone(gyroflow._production_binary_identity(self.exe, gyroflow._NIGHTLY_SHA256))
        with patch.object(gyroflow, "_pe_version", return_value=None):
            self.assertIsNone(gyroflow._production_binary_identity(self.exe, gyroflow._NIGHTLY_SHA256))

    def test_production_does_not_trust_development_identity_or_web_flags(self):
        with patch.object(gyroflow, "_pe_version", return_value=None), \
                patch.object(gyroflow, "_binary_identity", side_effect=AssertionError("development must not authorize production")):
            identity = gyroflow._identity_for_toolchain(self.exe, gyroflow._NIGHTLY_SHA256, {
                "_runner_context": self.context, "development_identity": {"nightly_executable": str(self.exe)},
                "verified": True, "export_verified": True})
        self.assertIsNone(identity)
        with self.assertRaises(Exception):
            self.context.job_id = str(uuid.uuid4())

    def test_new_source_project_discards_stale_source_metadata_and_motion(self):
        source = self.root / "fresh-original.mp4"
        source.write_bytes(b"fresh source")
        template = self.root / "template.gyroflow"
        template.write_text(json.dumps({
            "video_info": {"num_frames": 999}, "raw_imu": [1], "quaternions": [2],
            "gyro_source": {"filepath": "file:///old.mp4", "file_metadata": {"old": True}, "quaternions": [3]},
            "keyframes": {"old": 1}, "offsets": {"old": 2}, "output": {},
        }), encoding="utf-8")
        output = self.root / "new-project-output"
        output.mkdir()
        project = self.root / "fresh.gyroflow"
        gyroflow._build_project(template, source, output, project, None, None, True,
                                "reference_1080p", fresh_source=True)
        value = json.loads(project.read_text(encoding="utf-8"))
        self.assertNotIn("video_info", value)
        self.assertNotIn("raw_imu", value)
        self.assertNotIn("quaternions", value)
        self.assertNotIn("file_metadata", value["gyro_source"])
        self.assertNotIn("quaternions", value["gyro_source"])
        self.assertEqual(value["gyro_source"]["filepath"], source.as_uri())
        self.assertEqual(value["videofile"], source.as_uri())
        self.assertEqual(value["trim_ranges_ms"], [])
        self.assertEqual(value["keyframes"], {})
        self.assertEqual(value["offsets"], {})

    def test_production_capability_does_not_reuse_historical_export_claim(self):
        with patch.object(gyroflow, "_sha256_file", return_value=gyroflow._NIGHTLY_SHA256), \
                patch.object(gyroflow, "_pe_version", return_value="1.6.3.0"):
            result = gyroflow.capabilities({"executable": self.exe, "_runner_context": self.context,
                                            "development_identity": {}, "export_verified": True})
        self.assertTrue(result["identity_verified"])
        self.assertTrue(result["execution_supported"])
        self.assertFalse(result["export_verified"])
        self.assertFalse(result["content_correspondence_verified"])
        self.assertIsNone(stabilize._template({"_runner_context": self.context,
                                             "development_identity": {"default_template": str(self.exe)}}))


if __name__ == "__main__":
    unittest.main()
