import hashlib
import json
import tempfile
import threading
import unittest
import uuid
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from cha_stabilizer.adapters import gyroflow
from cha_stabilizer.errors import NeedsManualError, NeedsReviewError
from cha_stabilizer.models import validate_job_request
from cha_stabilizer.owned_processes import OwnedProcessRegistry, registry_scope


class GyroflowAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_id = str(uuid.uuid4())
        self.run_dir = self.root / "private" / "runs" / self.run_id
        self.run_dir.mkdir(parents=True)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"immutable-source")
        self.template = self.root / "template.gyroflow"
        self.template.write_text(json.dumps({
            "title": "template",
            "version": 3,
            "videofile": "file:///old/source.mp4",
            "video_info": {"width": 3840, "height": 2160, "fps": 50.0, "num_frames": 17592},
            "calibration_data": {"stale": True},
            "gyro_source": {
                "filepath": "file:///old/source.mp4",
                "file_metadata": {"raw_imu": [1, 2, 3]},
                "raw_imu": [1, 2, 3],
            },
            "trim_ranges_ms": [],
            "output": {"output_filename": "old.mp4", "output_folder": "C:/old"},
            "offsets": {"old": 1},
            "keyframes": {"old": 1},
        }), encoding="utf-8")
        self.tool_dir = self.root / "tool"
        self.tool_dir.mkdir()
        self.exe = self.tool_dir / "Gyroflow.exe"
        self.exe.write_bytes(b"test executable placeholder")
        self.ffmpeg = self.root / "ffmpeg.exe"
        self.ffmpeg.write_bytes(b"ffmpeg placeholder")
        self.ffprobe = self.root / "ffprobe.exe"
        self.ffprobe.write_bytes(b"ffprobe placeholder")
        self.tool_presets = self.tool_dir / "camera_presets"
        self.tool_presets.mkdir()
        (self.tool_presets / "profiles.cbor.gz").write_bytes(b"portable lens profile database")
        self.profile = self.root / "profile"
        self.profile.mkdir()
        (self.profile / "settings.json").write_bytes(b'{"user_setting":1}')
        (self.profile / "gyroflow.log").write_bytes(b"previous profile log")
        (self.profile / "lens_profiles").mkdir()
        (self.profile / "lens_profiles" / "profiles.cbor.gz").write_bytes(b"profile bytes")
        self.cancel = threading.Event()
        self.registry = OwnedProcessRegistry(self.cancel)
        self.original_source_bytes = self.source.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def _nightly_identity(self):
        return {
            "build_id": "official_nightly_gh2811",
            "path": str(self.exe.resolve()),
            "version": "1.6.3 (gh2811)",
            "sha256": gyroflow._NIGHTLY_SHA256,
            "package_family": None,
            "commit": gyroflow._NIGHTLY_COMMIT,
            "direct_cli_launch_supported": True,
        }

    def _stable_identity(self, digest):
        return {
            "build_id": "stable_msix_1.6.3",
            "path": str(self.exe.resolve()),
            "version": "1.6.3",
            "sha256": digest,
            "package_family": "29160AdrianRoss.Gyroflow_q81n4e8pq4bra",
            "commit": None,
            "direct_cli_launch_supported": False,
        }

    def _source_probe(self):
        base_tick = 212 * 50000
        frames = [
            {"best_effort_timestamp": str(base_tick + index * 1000), "best_effort_timestamp_time": "{:.6f}".format(212 + index / 50)}
            for index in range(150)
        ]
        return {
            "stream": {"codec_name": "h264", "width": 3840, "height": 2160, "pix_fmt": "yuv420p", "avg_frame_rate": "50/1", "time_base": "1/50000"},
            "format": {"duration": "351.840000"},
            "frames": frames,
            "pts": [Fraction(base_tick + index * 1000, 50000) for index in range(150)],
        }

    @staticmethod
    def _output_probe(count=150):
        frames = [
            {"best_effort_timestamp": str(index * 20), "best_effort_timestamp_time": "{:.3f}".format(index / 50)}
            for index in range(count)
        ]
        return {
            "stream": {"codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p", "avg_frame_rate": "50/1", "time_base": "1/1000"},
            "format": {"duration": "3.000000" if count == 150 else "3.040000"},
            "frames": frames,
            "pts": [Fraction(index * 20, 1000) for index in range(count)],
        }

    def _fake_launch(self, *, count=150, change_settings=False, change_tool_directory=False):
        def launch(executable, project_path, cwd, log_path, cancel, on_event):
            project = json.loads(project_path.read_text(encoding="utf-8"))
            output = Path(project["output"]["output_folder"]) / project["output"]["output_filename"]
            output.write_bytes(b"owned rendered media")
            log_path.write_bytes(b"CLI standard output\n")
            (self.profile / "gyroflow.log").write_bytes(b"new CLI log contents")
            if change_settings:
                (self.profile / "settings.json").write_bytes(b'{"user_setting":2}')
            if change_tool_directory:
                (self.tool_presets / "profiles.cbor.gz").write_bytes(b"modified lens profile database")
            self.last_project = project
            self.last_output = output
            return {"exit_code": 0, "tail": ["render complete"], "foreign_process_seen": False, "reader_error": None}
        return launch

    def _run(self, *, count=150, change_settings=False, change_tool_directory=False, active_processes=None, output_preset="reference_1080p"):
        process_list = [] if active_processes is None else active_processes
        sha_impl = gyroflow._sha256_file

        def sha_side_effect(path):
            if Path(path) == self.exe:
                return hashlib.sha256(self.exe.read_bytes()).hexdigest()
            return sha_impl(path)

        def identity_side_effect(path, digest=None):
            if Path(path) == self.exe:
                return self._nightly_identity()
            return None

        with patch.object(gyroflow, "_root", return_value=self.root), \
             patch.object(gyroflow, "_profile_roots", return_value=[("test_profile", self.profile)]), \
             patch.object(gyroflow, "_gyroflow_process_ids", return_value=process_list), \
             patch.object(gyroflow, "_binary_identity", side_effect=identity_side_effect), \
             patch.object(gyroflow, "_sha256_file", side_effect=sha_side_effect), \
             patch.object(gyroflow, "_launch_cli", side_effect=self._fake_launch(count=count, change_settings=change_settings, change_tool_directory=change_tool_directory)), \
             patch.object(gyroflow, "_probe_media", side_effect=[self._source_probe(), self._output_probe(count)]), \
             patch.object(gyroflow, "_decode_output", return_value={"passed": True, "error": None}):
            with registry_scope(self.registry):
                return gyroflow.run_export(
                    {"original": str(self.source), "project_template": str(self.template), "start": 212, "end": 215, "output_preset": output_preset},
                    self.run_dir,
                    {"gyroflow": self.exe, "ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe},
                    self.cancel,
                    None,
                )

    def test_bounded_success_builds_fresh_project_and_restores_known_log(self):
        result = self._run()
        self.assertEqual(result["validation"]["status"], "verified_media")
        self.assertTrue(result["validation"]["trim_mapping_verified"])
        self.assertEqual(len(result["outputs"]), 1)
        self.assertTrue(result["outputs"][0]["path"].is_file())
        self.assertEqual(self.source.read_bytes(), self.original_source_bytes)
        self.assertEqual((self.profile / "gyroflow.log").read_bytes(), b"previous profile log")
        self.assertEqual((self.profile / "settings.json").read_bytes(), b'{"user_setting":1}')
        self.assertEqual(self.last_project["videofile"], self.source.as_uri())
        self.assertEqual(self.last_project["gyro_source"]["filepath"], self.source.as_uri())
        self.assertNotIn("file_metadata", self.last_project["gyro_source"])
        self.assertNotIn("calibration_data", self.last_project)
        self.assertEqual(self.last_project["video_info"]["num_frames"], 17592)
        self.assertEqual(self.last_project["trim_ranges_ms"], [[212000.0, 215000.0]])
        self.assertEqual(self.last_project["output"]["output_width"], 1920)
        self.assertEqual(self.last_output.parent.parent.parent, self.run_dir)
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertTrue(manifest["audit"]["profile_backup_verified"])
        self.assertTrue(manifest["audit"]["profile_post_matches_pre"])
        self.assertTrue(manifest["audit"]["tool_directory_backup_verified"])
        self.assertTrue(manifest["audit"]["tool_directory_post_matches_pre"])
        self.assertTrue(manifest["export_probe"]["trim_mapping_verified"])
        self.assertTrue(self.tool_presets.joinpath("profiles.cbor.gz").is_file())

    def test_release_mode_requires_explicit_template_executable_and_identity_pins(self):
        request = {"original": str(self.source), "start": 0, "end": 3}
        with self.assertRaises(NeedsManualError):
            gyroflow._validate_request(request, development_identity={})
        development = gyroflow._validate_request(
            request, development_identity={"default_template": str(self.template)}
        )
        self.assertEqual(development["project_template"], self.template.resolve())
        self.assertIsNone(gyroflow._configured_executable({}))
        self.assertIsNone(gyroflow._binary_identity(self.exe, gyroflow._MSIX_SHA256, {}))
        self.assertIsNone(gyroflow._binary_identity(self.exe, gyroflow._MSIX_SHA256))
        pinned = gyroflow._binary_identity(
            self.exe,
            gyroflow._MSIX_SHA256,
            {"msix_executable": str(self.exe)},
        )
        self.assertEqual(pinned["build_id"], "stable_msix_1.6.3")
        self.assertFalse(pinned["direct_cli_launch_supported"])

    def test_reference_720p_preset_maps_explicit_full_source_project_only(self):
        validated = gyroflow._validate_request({
            "original": str(self.source),
            "project_template": str(self.template),
            "full_source": True,
            "output_preset": "reference_720p",
        })
        self.assertTrue(validated["full_source"])
        self.assertIsNone(validated["start"])
        self.assertIsNone(validated["end"])
        output_dir = self.root / "preset-export"
        output_dir.mkdir()
        project_path = self.root / "reference-720p.gyroflow"
        output_path = gyroflow._build_project(
            validated["project_template"], validated["original"], output_dir, project_path,
            validated["start"], validated["end"], validated["full_source"], validated["output_preset"],
        )
        project = json.loads(project_path.read_text(encoding="utf-8"))
        self.assertEqual(project["trim_ranges_ms"], [])
        self.assertEqual(project["output"]["codec"], "H.264/AVC")
        self.assertEqual(project["output"]["output_width"], 1280)
        self.assertEqual(project["output"]["output_height"], 720)
        self.assertEqual(project["output"]["pixel_format"], "yuv420p")
        self.assertEqual(project["output"]["bitrate"], 8.0)
        self.assertEqual(output_path.parent, output_dir)
        self.assertFalse(output_path.exists())

    def test_normalized_full_source_job_request_is_adapter_idempotent(self):
        normalized = validate_job_request({
            "kind": "gyroflow_export",
            "request": {
                "original": str(self.source),
                "project_template": str(self.template),
                "full_source": True,
                "output_preset": "reference_720p",
            },
        })["request"]
        self.assertNotIn("start", normalized)
        self.assertNotIn("end", normalized)
        adapter_request = gyroflow._validate_request(normalized)
        self.assertTrue(adapter_request["full_source"])
        self.assertIsNone(adapter_request["start"])
        self.assertIsNone(adapter_request["end"])
        self.assertEqual(adapter_request["output_preset"], "reference_720p")

    def test_unknown_output_preset_is_rejected(self):
        with self.assertRaises(NeedsReviewError):
            gyroflow._validate_request({
                "original": str(self.source),
                "project_template": str(self.template),
                "start": 212,
                "end": 215,
                "output_preset": "1920x1080-custom",
            })

    def test_152_frame_trim_is_needs_review_and_output_is_retained(self):
        with self.assertRaises(NeedsReviewError) as caught:
            self._run(count=152)
        details = caught.exception.details
        self.assertEqual(details["frame_mapping"]["expected_frames"], 150)
        self.assertEqual(details["frame_mapping"]["actual_frames"], 152)
        self.assertFalse(details["frame_mapping"]["trim_mapping_verified"])
        self.assertGreaterEqual(len(details["outputs"]), 4)
        retained = details["outputs"][0]
        self.assertEqual(retained["kind"], "diagnostic_video")
        self.assertTrue(retained["path"].is_file())
        self.assertIn("path", retained)
        self.assertIn("label", retained)
        self.assertIn("kind", retained)
        self.assertIn("mime", retained)
        self.assertIn("metadata", retained)
        self.assertIn("warnings", retained)

    def test_active_gyroflow_process_blocks_export_before_backup_or_launch(self):
        with patch.object(gyroflow, "_root", return_value=self.root), \
             patch.object(gyroflow, "_profile_roots", return_value=[("test_profile", self.profile)]), \
             patch.object(gyroflow, "_binary_identity", side_effect=lambda path, digest=None: self._nightly_identity()), \
             patch.object(gyroflow, "_gyroflow_process_ids", return_value=[321]), \
             patch.object(gyroflow, "_launch_cli") as launch:
            with self.assertRaises(NeedsReviewError):
                with registry_scope(self.registry):
                    gyroflow.run_export(
                        {"original": str(self.source), "project_template": str(self.template), "start": 212, "end": 215},
                        self.run_dir,
                        {"gyroflow": self.exe, "ffmpeg": self.ffmpeg, "ffprobe": self.ffprobe},
                        self.cancel,
                        None,
                    )
        launch.assert_not_called()
        self.assertEqual((self.profile / "settings.json").read_bytes(), b'{"user_setting":1}')

    def test_settings_change_is_not_blindly_restored_and_output_requires_review(self):
        with self.assertRaises(NeedsReviewError) as caught:
            self._run(change_settings=True)
        self.assertFalse(caught.exception.details["profile_post_matches_pre"])
        self.assertEqual((self.profile / "settings.json").read_bytes(), b'{"user_setting":2}')
        self.assertEqual((self.profile / "gyroflow.log").read_bytes(), b"previous profile log")
        self.assertGreaterEqual(len(caught.exception.details["outputs"]), 4)

    def test_tool_directory_change_is_not_restored_and_requires_review(self):
        with self.assertRaises(NeedsReviewError) as caught:
            self._run(change_tool_directory=True)
        self.assertFalse(caught.exception.details["validation"]["tool_directory_post_matches_pre"])
        self.assertEqual((self.tool_presets / "profiles.cbor.gz").read_bytes(), b"modified lens profile database")
        self.assertGreaterEqual(len(caught.exception.details["outputs"]), 4)

    def test_capabilities_matches_exact_executable_report_and_separates_trim_status(self):
        docs = self.root / "docs"
        docs.mkdir()
        report = docs / "gyroflow_export_probe.json"
        report.write_text(json.dumps({
            "installation": {"path": str(self.exe.resolve()), "version": "1.6.3", "sha256": hashlib.sha256(self.exe.read_bytes()).hexdigest()},
            "audit": {"cli_invocation_verified": True, "cli_exit_code": 0, "profile_backup_verified": True, "profile_post_matches_pre": True, "tool_directory_post_matches_pre": True, "concurrent_process_check": "clear"},
            "export_probe": {"media_export_verified": False, "trim_mapping_verified": False, "validation_status": "needs_review"},
        }), encoding="utf-8")
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        with patch.object(gyroflow, "_root", return_value=self.root), \
             patch.object(gyroflow, "_binary_identity", side_effect=lambda path, sha=None: self._stable_identity(digest)), \
             patch.object(gyroflow, "_sha256_file", return_value=digest):
            result = gyroflow.capabilities({"executable": self.exe, "probe_report": report})
        self.assertTrue(result["detected"])
        self.assertTrue(result["prior_verified"])
        self.assertFalse(result["export_verified"])
        self.assertFalse(result["trim_mapping_verified"])
        self.assertEqual(result["validation_status"], "needs_review")
        self.assertEqual(result["version"], "1.6.3")

    def test_capabilities_fails_closed_for_report_binary_mismatch(self):
        docs = self.root / "docs"
        docs.mkdir()
        report = docs / "gyroflow_export_probe.json"
        report.write_text(json.dumps({
            "installation": {"path": str(self.exe.resolve()), "version": "1.6.3", "sha256": "0" * 64},
            "audit": {"cli_invocation_verified": True, "cli_exit_code": 0, "profile_backup_verified": True, "profile_post_matches_pre": True, "tool_directory_post_matches_pre": True, "concurrent_process_check": "clear"},
            "export_probe": {"validation_status": "verified_media", "media_export_verified": True, "trim_mapping_verified": True},
        }), encoding="utf-8")
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        with patch.object(gyroflow, "_root", return_value=self.root), \
             patch.object(gyroflow, "_binary_identity", side_effect=lambda path, sha=None: self._stable_identity(digest)), \
             patch.object(gyroflow, "_sha256_file", return_value=digest):
            result = gyroflow.capabilities({"executable": self.exe, "probe_report": report})
        self.assertTrue(result["detected"])
        self.assertFalse(result["prior_verified"])
        self.assertFalse(result["export_verified"])
        self.assertFalse(result["trim_mapping_verified"])

    def test_capabilities_marks_installed_but_blocked_cli_separately(self):
        docs = self.root / "docs"
        docs.mkdir()
        report = docs / "gyroflow_export_probe.json"
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        report.write_text(json.dumps({
            "installation": {"path": str(self.exe.resolve()), "version": "1.6.3", "sha256": digest},
            "audit": {
                "cli_invocation_verified": False,
                "cli_launch_status": "blocked_before_process_creation",
                "cli_process_started": False,
                "cli_launch_error_type": "PermissionError",
                "profile_backup_verified": True,
                "profile_post_matches_pre": True,
                "concurrent_process_check": "clear",
            },
            "export_probe": {"media_export_verified": False, "trim_mapping_verified": False, "validation_status": "cli_blocked"},
        }), encoding="utf-8")
        with patch.object(gyroflow, "_root", return_value=self.root), \
             patch.object(gyroflow, "_binary_identity", side_effect=lambda path, sha=None: self._stable_identity(digest)), \
             patch.object(gyroflow, "_sha256_file", return_value=digest):
            result = gyroflow.capabilities({"executable": self.exe, "probe_report": report})
        self.assertTrue(result["detected"])
        self.assertEqual(result["cli_status"], "blocked")
        self.assertEqual(result["status"], "installed_cli_blocked")
        self.assertFalse(result["prior_verified"])
        self.assertFalse(result["export_verified"])
        self.assertFalse(result["trim_mapping_verified"])
        self.assertEqual(result["validation_status"], "cli_blocked")


if __name__ == "__main__":
    unittest.main()
