import ctypes
import http.client
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cha_stabilizer import cli
from cha_stabilizer.desktop_protocol import MAX_REQUEST_BYTES, run_desktop_protocol
from cha_stabilizer.job_store import JobStore, PreferenceStore
from cha_stabilizer.local_server import create_server
from cha_stabilizer.media_leases import (
    MediaLeaseError,
    MediaLeaseRegistry,
    _windows_handle_identity_matches,
)
from cha_stabilizer.models import RequestValidationError, validate_preferences_update
from cha_stabilizer.paths import ensure_desktop_data_root


class DesktopWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.resource = self.root / "bundle"
        self.resource.mkdir()
        web = self.resource / "ui" / "build" / "web"
        web.mkdir(parents=True)
        (web / "index.html").write_text("bundle UI", encoding="utf-8")
        self.data = ensure_desktop_data_root(self.root / "private-data")

    def tearDown(self):
        self.temp.cleanup()

    def _server(self):
        return create_server(resource_root=self.resource, data_root=self.data, desktop=True)

    @staticmethod
    def _verified_preview(store, *, metadata=None, state="verified_media", kind="preview"):
        job = store.create("preview", {})
        store.set_state(job["id"], "running", stage="starting", message="Started")
        run_dir = store.get_run_dir(job["id"])
        path = run_dir / "preview.mp4"
        path.write_bytes(b"owned preview bytes")
        values = metadata or {
            "width": 1280,
            "height": 720,
            "video_codec": "h264",
            "pixel_format": "yuv420p",
            "bit_depth": 8,
            "audio_codec": "aac",
        }
        artifact = store.add_artifact(
            job["id"], path=path, label="Preview", kind=kind, mime="video/mp4",
            metadata=values, validation_scope="preview_media_only",
        )
        store.set_state(job["id"], state, stage=state, message="Finished")
        return artifact, path

    def test_resource_and_data_roots_cannot_overlap(self):
        nested = self.resource / "nested-data"
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            status = cli.main([
                "--desktop", "--resource-root", str(self.resource), "--data-root", str(nested),
            ])
        self.assertEqual(status, 2)
        self.assertFalse(nested.exists())

        with self.assertRaises(ValueError):
            create_server(resource_root=self.resource, data_root=self.resource, desktop=True)

    def test_resource_root_app_web_layout_is_served_by_the_local_backend(self):
        web = self.resource / "web"
        web.mkdir()
        (web / "index.html").write_text("staged offline UI", encoding="utf-8")
        server = self._server()
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            self.assertEqual(server.app.static_root, web)
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/")
            response = connection.getresponse()
            body = response.read()
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertIn(b"staged offline UI", body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_data_root_is_separate_from_readonly_resources_and_release_defaults_are_empty(self):
        server = self._server()
        try:
            self.assertEqual(server.app.static_root, self.resource / "ui" / "build" / "web")
            self.assertEqual(server.app.jobs.app_root, self.data)
            self.assertEqual(server.app.preferences.app_root, self.data)
            self.assertFalse((self.resource / "private").exists())
            self.assertEqual(
                server.app.preferences.get()["tool_paths"],
                {"ffmpeg": None, "ffprobe": None, "gyroflow": None, "catalyst": None},
            )
            self.assertFalse(any(str(value).startswith("C:/APPS/") for value in server.app.preferences.get()["tool_paths"].values() if value))
            report = server.app._gyroflow_capability((None, None))["probe_report"]
            self.assertEqual(Path(report), self.resource / "docs" / "gyroflow_export_probe.json")
        finally:
            server.server_close()

    def test_new_windows_data_root_has_protective_dacl(self):
        if os.name != "nt":
            self.skipTest("Windows protected DACL check")
        root = ensure_desktop_data_root(self.root / "new-secure-data")
        acl = subprocess.run(
            ["icacls", str(root)], check=True, capture_output=True, text=True,
            encoding="cp{}".format(ctypes.windll.kernel32.GetOEMCP()),
        ).stdout
        self.assertNotIn("Authenticated Users", acl)
        self.assertNotIn("BUILTIN\\Users", acl)
        self.assertIn("SYSTEM", acl)
        self.assertIn("Administrators", acl)

    def test_existing_data_root_acl_is_not_rewritten(self):
        if os.name != "nt":
            self.skipTest("Windows ACL check")
        existing = self.root / "existing-data"
        existing.mkdir()
        encoding = "cp{}".format(ctypes.windll.kernel32.GetOEMCP())
        before = subprocess.run(
            ["icacls", str(existing)], check=True, capture_output=True, text=True, encoding=encoding,
        ).stdout
        ensure_desktop_data_root(existing)
        after = subprocess.run(
            ["icacls", str(existing)], check=True, capture_output=True, text=True, encoding=encoding,
        ).stdout
        self.assertEqual(after, before)

    def test_frozen_worker_refuses_development_cli_without_desktop_roots(self):
        stderr = io.StringIO()
        with patch.object(sys, "frozen", True, create=True):
            with patch("sys.stderr", stderr):
                with self.assertRaises(SystemExit) as caught:
                    cli.main([])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("frozen Worker.exe must be started with --desktop", stderr.getvalue())

    def test_desktop_cli_duplicate_data_lock_precedes_server_creation(self):
        stderr = io.StringIO()
        with patch("cha_stabilizer.cli.LocalInstanceLock") as lock_class:
            with patch("cha_stabilizer.cli.create_server") as create_server:
                with patch("sys.stderr", stderr):
                    lock_class.return_value.acquire.return_value = False
                    status = cli.main([
                        "--desktop", "--resource-root", str(self.resource),
                        "--data-root", str(self.root / "locked-data"),
                    ])
        self.assertEqual(status, 2)
        lock_class.assert_called_once()
        create_server.assert_not_called()
        self.assertIn("already running", stderr.getvalue())

    def test_real_desktop_cli_emits_only_ready_before_eof_shutdown(self):
        stdout, stderr = io.BytesIO(), io.BytesIO()
        with patch("sys.stdin", io.BytesIO()):
            with patch("sys.stdout", stdout):
                with patch("sys.stderr", stderr):
                    status = cli.main([
                        "--desktop", "--resource-root", str(self.resource),
                        "--data-root", str(self.root / "real-cli-data"),
                    ])
        self.assertEqual(status, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        ready = json.loads(lines[0])
        self.assertEqual(ready["type"], "ready")
        self.assertEqual(ready["protocol"], 1)
        self.assertTrue(ready["origin"].startswith("http://127.0.0.1:"))
        self.assertTrue(ready["bearer"])
        self.assertTrue(ready["native_capability"])
        self.assertEqual(stderr.getvalue(), b"")

    def test_desktop_cli_uses_explicit_roots_and_private_stdio_entry(self):
        captured = {}

        def fake_protocol(server, capability, *, on_end=None, **kwargs):
            captured["resource_root"] = server.resource_root
            captured["data_root"] = server.data_root
            captured["desktop"] = server.app.desktop
            captured["capability"] = capability
            if on_end:
                on_end()

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("cha_stabilizer.cli.run_desktop_protocol", side_effect=fake_protocol), \
                patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            status = cli.main([
                "--desktop", "--resource-root", str(self.resource),
                "--data-root", str(self.root / "cli-data"), "--no-browser",
            ])
        self.assertEqual(status, 0)
        self.assertEqual(captured["resource_root"], self.resource)
        self.assertEqual(captured["data_root"], self.root / "cli-data")
        self.assertTrue(captured["desktop"])
        self.assertTrue(captured["capability"])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_private_development_defaults_never_load_in_desktop_mode(self):
        private = self.data / "private"
        private.mkdir()
        config = {
            "schema_version": 1,
            "c7037_data_root": None,
            "tool_paths": {"ffmpeg": "D:/dev/ffmpeg.exe", "ffprobe": "D:/dev/ffprobe.exe"},
            "gyroflow_identity": {
                "msix_executable": "D:/dev/Gyroflow.exe",
                "nightly_executable": "D:/dev/GyroflowNightly.exe",
                "default_template": "D:/dev/template.gyroflow",
            },
        }
        (private / "dev_worker_config.json").write_text(json.dumps(config), encoding="utf-8")
        development = PreferenceStore(self.data, desktop=False)
        desktop = PreferenceStore(self.data, desktop=True)
        self.assertEqual(development.get()["tool_paths"]["ffmpeg"], "D:/dev/ffmpeg.exe")
        self.assertEqual(development.development_config["gyroflow_identity"]["default_template"], "D:/dev/template.gyroflow")
        self.assertEqual(
            desktop.get()["tool_paths"],
            {"ffmpeg": None, "ffprobe": None, "gyroflow": None, "catalyst": None},
        )
        self.assertEqual(desktop.development_config["gyroflow_identity"]["default_template"], None)
        with patch.object(sys, "frozen", True, create=True):
            frozen = PreferenceStore(self.data, desktop=False)
        self.assertIsNone(frozen.get()["tool_paths"]["ffmpeg"])
        self.assertIsNone(frozen.development_config["c7037_data_root"])

    def test_preferences_migrate_exact_legacy_schema_and_preserve_partial_patches(self):
        private = self.data / "private"
        private.mkdir()
        preference_file = private / "preferences.json"
        legacy = {
            "theme_mode": "dark",
            "seed_color": 4278255360,
            "tool_paths": {"ffmpeg": None, "ffprobe": "D:/tools/ffprobe.exe", "gyroflow": None, "catalyst": None},
        }
        preference_file.write_text(json.dumps(legacy), encoding="utf-8")

        store = PreferenceStore(self.data, desktop=True)
        loaded = store.get()
        self.assertEqual(loaded["theme_mode"], "dark")
        self.assertEqual(loaded["tool_paths"]["ffprobe"], "D:/tools/ffprobe.exe")
        self.assertEqual(loaded["language_mode"], "system")
        migrated = json.loads(preference_file.read_text(encoding="utf-8"))
        self.assertEqual(set(migrated), {"theme_mode", "seed_color", "tool_paths", "language_mode"})
        store.update({"language_mode": "zh"})
        patched = store.get()
        self.assertEqual(patched["language_mode"], "zh")
        self.assertEqual(patched["theme_mode"], "dark")
        self.assertEqual(patched["tool_paths"]["ffprobe"], "D:/tools/ffprobe.exe")
        self.assertEqual(PreferenceStore(self.data, desktop=True).get(), patched)

    def test_invalid_preference_schema_is_preserved_and_language_mode_is_strict(self):
        private = self.data / "private"
        private.mkdir()
        preference_file = private / "preferences.json"
        raw = b'{"theme_mode":"dark","seed_color":1,"tool_paths":{},"unexpected":true}'
        preference_file.write_bytes(raw)
        store = PreferenceStore(self.data, desktop=True)
        self.assertEqual(preference_file.read_bytes(), raw)
        self.assertEqual(store.get()["language_mode"], "system")
        for invalid in ("auto", "zh-CN", "", None, 1):
            with self.subTest(language_mode=invalid), self.assertRaises(RequestValidationError):
                validate_preferences_update({"language_mode": invalid})
        self.assertEqual(validate_preferences_update({"language_mode": "en"}), {"language_mode": "en"})

    def test_known_errors_and_progress_expose_typed_keys_without_changing_stage_names(self):
        store = JobStore(self.data)
        job = store.create("validate", {})
        store.set_state(job["id"], "running", stage="starting", message="Started")
        store.update_progress(job["id"], "render", 0.7, "渲染 7/10 帧")
        progress = store.get(job["id"])
        self.assertEqual(progress["stage"], "render")
        self.assertEqual(progress["message_key"], "job.progress.render")
        self.assertEqual(progress["args"], {"current": 7, "total": 10})
        store.set_state(
            job["id"], "needs_review", stage="needs_review", message="Needs review",
            error={"code": "needs_review", "message": "Needs review"},
        )
        error = store.get(job["id"])["error"]
        self.assertEqual(error["message_key"], "job.error.needsReview")
        self.assertEqual(error["args"], {})

    def test_protocol_ready_web_session_capability_and_shutdown(self):
        server = self._server()
        capability = "private-test-capability"
        requests = [
            {"protocol": 1, "request_id": "web-1", "capability": capability, "action": "web_session"},
            {"protocol": 1, "request_id": "stop-2", "capability": capability, "action": "shutdown"},
        ]
        stdin = io.BytesIO(b"".join(json.dumps(item).encode("utf-8") + b"\n" for item in requests))
        stdout, stderr = io.BytesIO(), io.BytesIO()
        ended = []
        try:
            run_desktop_protocol(server, capability, stdin=stdin, stdout=stdout, stderr=stderr,
                                 on_end=lambda: (ended.append(True), server.app.close()))
            lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
            self.assertEqual([item["type"] for item in lines[:1]], ["ready"])
            self.assertEqual(set(lines[0]), {"type", "protocol", "pid", "origin", "bearer", "native_capability"})
            self.assertEqual(lines[0]["protocol"], 1)
            self.assertEqual(lines[0]["native_capability"], capability)
            self.assertEqual(lines[0]["origin"], "http://127.0.0.1:{}".format(server.server_port))
            self.assertEqual(lines[1]["request_id"], "web-1")
            self.assertEqual(lines[1]["result"]["url"], server.session_url)
            self.assertEqual(lines[2]["request_id"], "stop-2")
            self.assertTrue(lines[2]["result"]["shutting_down"])
            self.assertEqual(ended, [True])
            self.assertEqual(stderr.getvalue(), b"")
        finally:
            server.server_close()

    def test_protocol_rejects_bad_capability_wrong_version_extra_fields_and_duplicate_keys(self):
        server = self._server()
        capability = "private-cap"
        valid_envelope = {"protocol": 1, "request_id": "r-1", "capability": "wrong", "action": "web_session"}
        wrong_version = dict(valid_envelope, request_id="r-2", capability=capability, protocol=2)
        extra_field = dict(valid_envelope, request_id="r-3", capability=capability, path="D:/secret.mp4")
        input_lines = [valid_envelope, wrong_version, extra_field]
        stdin = io.BytesIO(b"".join(json.dumps(item).encode("utf-8") + b"\n" for item in input_lines)
                           + b'{"protocol":1,"request_id":"dup","request_id":"dupe","capability":"private-cap","action":"web_session"}\n')
        stdout, stderr = io.BytesIO(), io.BytesIO()
        try:
            run_desktop_protocol(server, capability, stdin=stdin, stdout=stdout, stderr=stderr,
                                 on_end=server.app.close)
            lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
            self.assertEqual(len(lines), 4)  # ready and three request responses
            self.assertEqual(lines[1]["error"]["code"], "unauthorized")
            self.assertEqual(lines[2]["error"]["code"], "unsupported_protocol")
            self.assertEqual(lines[3]["error"]["code"], "invalid_request")
            self.assertIn(b"rejected", stderr.getvalue())
            self.assertNotIn(b"D:/secret.mp4", stdout.getvalue())
        finally:
            server.server_close()

    def test_protocol_line_limit_and_missing_request_id_fail_closed(self):
        huge_server = self._server()
        huge = b"{" + b" " * MAX_REQUEST_BYTES + b"}\n"
        stdout, stderr = io.BytesIO(), io.BytesIO()
        try:
            run_desktop_protocol(huge_server, "cap", stdin=io.BytesIO(huge), stdout=stdout, stderr=stderr,
                                 on_end=huge_server.app.close)
            self.assertEqual(len(stdout.getvalue().splitlines()), 1)
            self.assertIn(b"rejected", stderr.getvalue())
        finally:
            huge_server.server_close()

        missing_id_server = self._server()
        stdout, stderr = io.BytesIO(), io.BytesIO()
        try:
            malformed = b'{"protocol":1,"capability":"cap","action":"web_session"}\n'
            run_desktop_protocol(missing_id_server, "cap", stdin=io.BytesIO(malformed),
                                 stdout=stdout, stderr=stderr, on_end=missing_id_server.app.close)
            self.assertEqual(len(stdout.getvalue().splitlines()), 1)
            self.assertIn(b"rejected", stderr.getvalue())
        finally:
            missing_id_server.server_close()

    def test_protocol_acquire_and_release_return_only_an_owned_handle(self):
        server = self._server()
        artifact, path = self._verified_preview(server.app.jobs)
        capability = "lease-capability"
        stdout = io.BytesIO()

        class Commands:
            def __init__(self):
                self.index = 0

            def readline(self, _limit=-1):
                if self.index == 0:
                    command = {"protocol": 1, "request_id": "acq", "capability": capability,
                               "action": "acquire_media", "artifact_id": artifact["id"]}
                elif self.index == 1:
                    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
                    lease_id = responses[-1]["result"]["lease_id"]
                    command = {"protocol": 1, "request_id": "rel", "capability": capability,
                               "action": "release_media", "lease_id": lease_id}
                else:
                    return b""
                self.index += 1
                return json.dumps(command).encode("utf-8") + b"\n"

        try:
            run_desktop_protocol(server, capability, stdin=Commands(), stdout=stdout, stderr=io.BytesIO(),
                                 on_end=server.app.close)
            lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
            result = lines[1]["result"]
            self.assertEqual(set(result), {"lease_id", "handle", "width", "height", "audio_present"})
            self.assertIsInstance(result["handle"], int)
            self.assertEqual(result["width"], 1280)
            self.assertEqual(result["height"], 720)
            self.assertEqual(lines[2]["result"], {"released": True})
            self.assertNotIn(str(path), stdout.getvalue().decode("utf-8"))
        finally:
            server.server_close()

    def test_windows_file_id_matches_legacy_and_modern_stat_layouts_and_rejects_tampering(self):
        legacy_volume = 0xE6B7A1C7
        modern_volume = 0x754B28E3E6B7A1C7
        legacy_file_index = 0x0001000000311424
        file_id_128 = legacy_file_index.to_bytes(8, "little") + bytes.fromhex("FFEEDDCCBBAA9988")

        # Older CPython reports the legacy volume/index pair.
        self.assertTrue(_windows_handle_identity_matches(
            legacy_volume, legacy_file_index, legacy_volume, legacy_file_index, modern_volume, file_id_128,
        ))
        # Newer CPython reports a 64-bit volume serial and the low 64-bit file ID.
        self.assertTrue(_windows_handle_identity_matches(
            modern_volume, legacy_file_index, legacy_volume, legacy_file_index, modern_volume, file_id_128,
        ))
        # Controlled legacy fallback only accepts the legacy stat layout.
        self.assertTrue(_windows_handle_identity_matches(
            legacy_volume, legacy_file_index, legacy_volume, legacy_file_index, None, None,
        ))
        self.assertFalse(_windows_handle_identity_matches(
            modern_volume, legacy_file_index, legacy_volume, legacy_file_index, None, None,
        ))
        self.assertFalse(_windows_handle_identity_matches(
            modern_volume, legacy_file_index + 1, legacy_volume, legacy_file_index, modern_volume, file_id_128,
        ))
        self.assertFalse(_windows_handle_identity_matches(
            modern_volume + 1, legacy_file_index, legacy_volume, legacy_file_index, modern_volume, file_id_128,
        ))

    def test_registered_preview_lease_holds_real_read_handle_until_release(self):
        store = JobStore(self.data)
        artifact, path = self._verified_preview(store)
        leases = MediaLeaseRegistry(store)
        result = leases.acquire(artifact["id"])
        try:
            self.assertEqual(set(result), {"lease_id", "handle", "width", "height", "audio_present"})
            self.assertEqual(result["width"], 1280)
            self.assertEqual(result["height"], 720)
            self.assertTrue(result["audio_present"])
            self.assertNotIn(str(path), repr(result))
            if os.name == "nt":
                with self.assertRaises(OSError):
                    open(str(path), "r+b")
        finally:
            self.assertTrue(leases.release(result["lease_id"]))
        self.assertEqual(leases.active_count, 0)
        if os.name == "nt":
            with open(str(path), "r+b"):
                pass

    def test_lease_open_race_is_returned_as_a_controlled_error(self):
        store = JobStore(self.data)
        artifact, _path = self._verified_preview(store)
        leases = MediaLeaseRegistry(store)
        with patch("cha_stabilizer.media_leases._open_readonly_handle", side_effect=PermissionError("denied")):
            with self.assertRaises(MediaLeaseError):
                leases.acquire(artifact["id"])
        self.assertEqual(leases.active_count, 0)

    def test_registered_preview_lease_accepts_eight_bit_h264_without_audio(self):
        store = JobStore(self.data)
        artifact, _path = self._verified_preview(store, metadata={
            "width": 1280, "height": 720, "video_codec": "h264", "pixel_format": "yuv420p",
            "bit_depth": 8, "audio_codec": None,
        })
        leases = MediaLeaseRegistry(store)
        result = leases.acquire(artifact["id"])
        self.assertFalse(result["audio_present"])
        self.assertTrue(leases.release(result["lease_id"]))

    def test_leases_reject_nonpreview_unverified_wrong_codec_and_aliases(self):
        store = JobStore(self.data)
        leases = MediaLeaseRegistry(store)
        artifact, path = self._verified_preview(store, metadata={
            "width": 1280, "height": 720, "video_codec": "hevc", "pixel_format": "yuv420p",
            "bit_depth": 8, "audio_codec": None,
        })
        with self.assertRaises(MediaLeaseError):
            leases.acquire(artifact["id"])

        not_verified, _ = self._verified_preview(store, state="needs_review")
        with self.assertRaises(MediaLeaseError):
            leases.acquire(not_verified["id"])

        other_artifact, _ = self._verified_preview(store, kind="manifest")
        with self.assertRaises(MediaLeaseError):
            leases.acquire(other_artifact["id"])

        linked = self.root / "preview-hardlink.mp4"
        try:
            os.link(str(path), str(linked))
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable in this test environment")
        try:
            with self.assertRaises(MediaLeaseError):
                leases.acquire(artifact["id"])
        finally:
            linked.unlink()
            leases.close_all()

    def test_pipe_eof_releases_leases_and_closes_owned_inspections(self):
        server = self._server()
        source = self.root / "probe-source.mp4"
        source.write_bytes(b"source")
        server.app.preferences.update({"tool_paths": {"ffprobe": os.path.abspath(os.sys.executable)}})
        artifact, _preview_path = self._verified_preview(server.app.jobs)
        capability = "eof-capability"
        command = {
            "protocol": 1, "request_id": "acq", "capability": capability,
            "action": "acquire_media", "artifact_id": artifact["id"],
        }
        started = threading.Event()
        child = {}
        failures = []
        registries = []
        base_registry = MediaLeaseRegistry

        class TrackedRegistry(base_registry):
            def __init__(self, store):
                super().__init__(store)
                registries.append(self)

        def slow_probe(path, ffprobe, count=False, cancel=None):
            from cha_stabilizer.owned_processes import spawn_owned_process
            import sys
            child["process"] = spawn_owned_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            started.set()
            cancel.wait(10)
            return {"width": 8, "height": 8, "fps": 30}

        def inspect():
            try:
                server.app.inspect_media(str(source))
            except Exception as exc:
                failures.append(exc)

        try:
            with patch("cha_stabilizer.core.media.probe", side_effect=slow_probe):
                with patch("cha_stabilizer.desktop_protocol.MediaLeaseRegistry", TrackedRegistry):
                    thread = threading.Thread(target=inspect, daemon=True)
                    thread.start()
                    self.assertTrue(started.wait(5))
                    output = io.BytesIO()
                    run_desktop_protocol(
                        server, capability,
                        stdin=io.BytesIO(json.dumps(command).encode("utf-8") + b"\n"),
                        stdout=output, stderr=io.BytesIO(), on_end=server.app.close,
                    )
                    thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertTrue(failures)
            self.assertIsNotNone(child["process"].poll())
            self.assertEqual(len(registries), 1)
            self.assertEqual(registries[0].active_count, 0)
            response = json.loads(output.getvalue().splitlines()[1])
            self.assertEqual(response["request_id"], "acq")
            self.assertIn("handle", response["result"])
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
