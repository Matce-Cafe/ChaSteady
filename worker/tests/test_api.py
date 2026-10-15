import http.client
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cha_stabilizer.errors import AppError
from cha_stabilizer.local_server import RangeNotSatisfiable, _parse_range, create_server
from cha_stabilizer.models import RequestValidationError, validate_job_request
from cha_stabilizer.owned_processes import spawn_owned_process


class LocalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        static = self.root / "ui" / "build" / "web"
        static.mkdir(parents=True)
        (static / "index.html").write_text("<!doctype html><title>local UI</title>", encoding="utf-8")
        self.server = create_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.base_host = "127.0.0.1:{}".format(self.server.server_port)
        self.auth = {"Authorization": "Bearer " + self.server.app.nonce}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, route, *, headers=None, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = dict(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, route, body=body, headers=request_headers)
        response = connection.getresponse()
        body_bytes = response.read()
        result = (response.status, dict(response.getheaders()), body_bytes)
        connection.close()
        return result

    def test_static_ui_is_public_but_api_requires_bearer(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"local UI", body)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

        status, _, body = self.request("GET", "/api/health")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")

        status, headers, body = self.request("GET", "/api/health", headers=self.auth)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"version": "0.1.0", "session_ready": True})
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))

    def test_unbuilt_ui_never_serves_flutter_source_template(self):
        source_web = self.root / "unbuilt-app" / "ui" / "web"
        source_web.mkdir(parents=True)
        (source_web / "index.html").write_text("template source, not a build", encoding="utf-8")
        self.server.app.static_root = self.root / "unbuilt-app" / "ui" / "build" / "web"
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)["error"]["code"], "ui_not_built")
        self.assertNotIn(b"template source", body)

    def test_api_root_and_query_nonce_do_not_bypass_bearer(self):
        for route in ("/api", "/api/health?nonce={}".format(self.server.app.nonce)):
            status, _, body = self.request("GET", route)
            self.assertEqual(status, 401)
            self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")
        status, _, body = self.request("HEAD", "/api/health")
        self.assertEqual(status, 401)
        self.assertEqual(body, b"")

        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.putrequest("GET", "/api/health")
        token = "Bearer " + self.server.app.nonce
        connection.putheader("Authorization", token)
        connection.putheader("Authorization", token)
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 401)
        response.read()
        connection.close()

    def test_get_api_routes_have_no_storage_side_effects(self):
        prefs_file = self.root / "private" / "preferences.json"
        runs_root = self.root / "private" / "runs"
        initial_runs = set(item.name for item in runs_root.iterdir())
        self.assertFalse(prefs_file.exists())
        for route in ("/api/health", "/api/capabilities", "/api/preferences", "/api/jobs"):
            status, _, _ = self.request("GET", route, headers=self.auth)
            self.assertEqual(status, 200)
        self.assertFalse(prefs_file.exists())
        self.assertEqual(set(item.name for item in runs_root.iterdir()), initial_runs)

    def test_range_parser_accepts_only_single_ascii_byte_ranges(self):
        self.assertEqual(_parse_range("bytes=2-4", 10), (2, 4))
        self.assertEqual(_parse_range("bytes=7-", 10), (7, 9))
        self.assertEqual(_parse_range("bytes=-3", 10), (7, 9))
        for header in (
            "bytes=+1-2", "bytes= 1-2", "bytes=1 -2", "bytes=2-1",
            "bytes=10-", "bytes=0-1,4-5", "bytes=١-٢", "bytes=-",
            "bytes=" + ("9" * 21) + "-",
        ):
            with self.subTest(header=header):
                with self.assertRaises(RangeNotSatisfiable):
                    _parse_range(header, 10)

    def test_foreign_host_and_origin_are_rejected(self):
        status, _, body = self.request("GET", "/api/health", headers=dict(self.auth, Host="attacker.example"))
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_host")

        headers = dict(self.auth, Origin="http://attacker.example", **{"Sec-Fetch-Site": "cross-site"})
        status, _, body = self.request("GET", "/api/health", headers=headers)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_origin")

        status, _, body = self.request("GET", "/", headers={"Origin": "http://attacker.example"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_origin")

    def test_shutdown_stops_only_owned_media_inspection_child(self):
        source = self.root / "probe-source.mp4"
        source.write_bytes(b"source")
        self.server.app.preferences.update({"tool_paths": {"ffprobe": sys.executable}})
        started = threading.Event()
        child = {}
        failures = []

        def slow_probe(path, ffprobe, count=False, cancel=None):
            child["process"] = spawn_owned_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            started.set()
            cancel.wait(10)
            return {"width": 10, "height": 10, "fps": 30}

        def inspect():
            try:
                self.server.app.inspect_media(str(source))
            except Exception as exc:
                failures.append(exc)

        with patch("cha_stabilizer.core.media.probe", side_effect=slow_probe):
            thread = threading.Thread(target=inspect, daemon=True)
            thread.start()
            self.assertTrue(started.wait(5))
            self.server.app.close()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertTrue(failures)
        self.assertIsNotNone(child["process"].poll())

    def test_http_errors_redact_local_paths_and_tool_stderr(self):
        source = self.root / "source.mp4"
        source.write_bytes(b"not-probed")
        failure = AppError(
            "ffprobe failed for D:/private/runs/secret/source.mp4",
            {"stderr": "could not open D:/private/runs/secret/source.mp4", "path": str(source), "return_code": 1},
        )
        with patch.object(self.server.app, "inspect_media", side_effect=failure):
            status, _, body = self.request(
                "POST", "/api/media/inspect", headers=self.auth, payload={"path": str(source)}
            )
        self.assertEqual(status, 422)
        serialized = body.decode("utf-8")
        self.assertNotIn("D:/private/runs", serialized)
        self.assertNotIn("source.mp4", serialized)
        self.assertNotIn("stderr", serialized)
        self.assertIn("return_code", serialized)

    def test_nonce_session_sets_separate_scoped_read_cookie(self):
        status, headers, body = self.request("POST", "/api/session", headers=self.auth, payload={})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["session_ready"])
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/api/artifacts/", cookie)
        self.assertNotIn("Authorization", cookie)

        status, _, body = self.request("POST", "/api/session", payload={})
        self.assertEqual(status, 401)

    def test_artifact_range_reads_only_registered_owned_file(self):
        job = self.server.app.jobs.create("validate", {"source": "not-used-in-this-test"})
        run_dir = self.server.app.jobs.get_run_dir(job["id"])
        media = run_dir / "preview.mp4"
        media.write_bytes(b"abcdefghij")
        artifact = self.server.app.jobs.add_artifact(
            job["id"], path=media, label="Preview", kind="preview", mime="video/mp4"
        )
        self.assertNotIn("path", artifact)

        _, session_headers, _ = self.request("POST", "/api/session", headers=self.auth, payload={})
        cookie = session_headers["Set-Cookie"].split(";", 1)[0]
        status, headers, body = self.request(
            "GET", artifact["url"],
            headers={"Cookie": cookie, "Range": "bytes=2-4", "Origin": "http://127.0.0.1:{}".format(self.server.server_port)},
        )
        self.assertEqual(status, 206)
        self.assertEqual(body, b"cde")
        self.assertEqual(headers.get("Content-Range"), "bytes 2-4/10")
        self.assertEqual(headers.get("Accept-Ranges"), "bytes")

        status, _, body = self.request("GET", artifact["url"])
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"]["code"], "media_session_required")

        status, headers, body = self.request(
            "GET", artifact["url"], headers={"Cookie": cookie, "Range": "bytes=100-200"}
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers.get("Content-Range"), "bytes */10")
        self.assertEqual(json.loads(body)["error"]["code"], "range_not_satisfiable")

        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.putrequest("GET", artifact["url"])
        connection.putheader("Cookie", cookie)
        connection.putheader("Range", "bytes=0-1")
        connection.putheader("Range", "bytes=2-3")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 416)
        self.assertIn(b"range_not_satisfiable", response.read())
        connection.close()

        status, _, body = self.request("GET", "/api/artifacts/not-a-file/content", headers={"Cookie": cookie})
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")

    def test_preferences_are_app_scoped_and_unknown_fields_rejected(self):
        original_settings = self.root / "claude_settings.json"
        original_settings.write_text("do not touch", encoding="utf-8")
        status, _, body = self.request(
            "PUT", "/api/preferences", headers=self.auth, payload={"theme_mode": "dark", "seed_color": 4278255360}
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["theme_mode"], "dark")
        self.assertTrue((self.root / "private" / "preferences.json").is_file())
        self.assertEqual(original_settings.read_text(encoding="utf-8"), "do not touch")

        status, _, body = self.request(
            "PUT", "/api/preferences", headers=self.auth, payload={"claude_settings": {"theme": "dark"}}
        )
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_request")

    def test_capabilities_do_not_overclaim_gyroflow_or_partial_ffmpeg(self):
        ffmpeg = self.root / "configured-ffmpeg.exe"
        ffmpeg.write_bytes(b"test placeholder, not executed")
        self.server.app.preferences.update({
            "tool_paths": {"ffmpeg": str(ffmpeg), "ffprobe": None, "gyroflow": str(ffmpeg)},
        })
        status, _, body = self.request("GET", "/api/capabilities", headers=self.auth)
        self.assertEqual(status, 200)
        capabilities = json.loads(body)
        self.assertFalse(capabilities["ffmpeg"]["detected"])
        self.assertFalse(capabilities["ffprobe"]["detected"])
        self.assertFalse(capabilities["gyroflow"]["prior_verified"])

        ffprobe = self.root / "configured-ffprobe.exe"
        ffprobe.write_bytes(b"test placeholder, not executed")
        self.server.app.preferences.update({"tool_paths": {"ffprobe": str(ffprobe)}})
        status, _, body = self.request("GET", "/api/capabilities", headers=self.auth)
        capabilities = json.loads(body)
        self.assertTrue(capabilities["ffmpeg"]["detected"])
        self.assertTrue(capabilities["ffprobe"]["detected"])

    def test_reference_fov_is_bounded_and_defaults_to_unscaled(self):
        request = {
            "kind": "fusion",
            "request": {
                "original": str(self.root / "original.mp4"),
                "ctb": str(self.root / "ctb.mp4"),
                "reference": str(self.root / "reference.mp4"),
                "start": 0,
                "end": 2,
            },
        }
        normalized = validate_job_request(request)
        self.assertEqual(normalized["request"]["reference_fov"], 1.0)
        request["request"]["reference_fov"] = 2.0
        self.assertEqual(validate_job_request(request)["request"]["reference_fov"], 2.0)
        request["request"]["reference_fov"] = 4.01
        with self.assertRaises(RequestValidationError):
            validate_job_request(request)
        request["request"]["reference_fov"] = 10 ** 10000
        with self.assertRaises(RequestValidationError):
            validate_job_request(request)
        request["request"].pop("reference_fov")
        request["request"]["quiet_sigma_seconds"] = 10.0
        self.assertEqual(validate_job_request(request)["request"]["quiet_sigma_seconds"], 10.0)
        request["request"]["quiet_sigma_seconds"] = 1_000_000.0
        with self.assertRaises(RequestValidationError):
            validate_job_request(request)

    def test_gyroflow_output_preset_is_allowlisted_and_full_source_is_explicit(self):
        base = {"kind": "gyroflow_export", "request": {"original": str(self.root / "original.mp4")}}
        bounded = dict(base, request=dict(base["request"], start=0.0, end=3.0))
        normalized = validate_job_request(bounded)["request"]
        self.assertEqual(normalized["output_preset"], "reference_1080p")
        self.assertFalse(normalized["full_source"])
        trimmed_roundtrip = validate_job_request({"kind": "gyroflow_export", "request": normalized})["request"]
        self.assertEqual(trimmed_roundtrip, normalized)

        bounded_720 = dict(base, request=dict(base["request"], start=0.0, end=3.0, output_preset="reference_720p"))
        self.assertEqual(validate_job_request(bounded_720)["request"]["output_preset"], "reference_720p")

        for unsupported in (
            "reference_4k", "custom", "",
        ):
            payload = dict(base, request=dict(base["request"], start=0.0, end=3.0, output_preset=unsupported))
            with self.subTest(output_preset=unsupported), self.assertRaises(RequestValidationError):
                validate_job_request(payload)
        for unsupported_fields in (
            {"width": 3840, "height": 2160},
            {"width": 1280},
            {"codec": "h264"},
            {"output_path": str(self.root / "arbitrary.mp4")},
            {"command": ["ffmpeg", "-y"]},
        ):
            payload = dict(base, request=dict(base["request"], start=0.0, end=3.0, **unsupported_fields))
            with self.subTest(fields=unsupported_fields), self.assertRaises(RequestValidationError):
                validate_job_request(payload)

        with self.assertRaises(RequestValidationError):
            validate_job_request(base)  # no bounds cannot silently mean full source
        full_source = dict(base, request=dict(base["request"], full_source=True))
        full_normalized = validate_job_request(full_source)["request"]
        self.assertTrue(full_normalized["full_source"])
        self.assertNotIn("start", full_normalized)
        self.assertNotIn("end", full_normalized)
        full_roundtrip = validate_job_request({"kind": "gyroflow_export", "request": full_normalized})["request"]
        self.assertEqual(full_roundtrip, full_normalized)
        for bounds in ({"start": None}, {"end": None}, {"start": 0, "end": 3}):
            payload = dict(base, request=dict(base["request"], full_source=True, **bounds))
            with self.subTest(bounds=bounds), self.assertRaises(RequestValidationError):
                validate_job_request(payload)

    def test_job_schema_rejects_untrusted_commands_and_url_paths(self):
        status, _, body = self.request("POST", "/api/jobs", headers=self.auth, payload={"kind": "shell", "request": {"command": "whoami"}})
        self.assertEqual(status, 422)
        status, _, body = self.request(
            "POST", "/api/media/inspect", headers=self.auth, payload={"path": "https://example.invalid/video.mp4"}
        )
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_request")

    def test_catalyst_job_is_always_needs_manual_without_launching_automation(self):
        original = self.root / "source.mp4"
        original.write_bytes(b"original-read-only")
        status, _, body = self.request(
            "POST", "/api/jobs", headers=self.auth,
            payload={"kind": "catalyst_assisted", "request": {"original": str(original)}},
        )
        self.assertEqual(status, 202)
        job_id = json.loads(body)["job"]["id"]
        for _ in range(100):
            status, _, body = self.request("GET", "/api/jobs/{}".format(job_id), headers=self.auth)
            self.assertEqual(status, 200)
            job = json.loads(body)
            if job["state"] == "needs_manual":
                break
            time.sleep(0.01)
        self.assertEqual(job["state"], "needs_manual")
        self.assertIn("no Catalyst process", job["message"])
        self.assertTrue(job["result"]["next_steps"]["steps"])
        self.assertEqual(original.read_bytes(), b"original-read-only")

    def test_options_preflight_has_no_cors_permission(self):
        status, headers, body = self.request("OPTIONS", "/api/health", headers={"Origin": "http://127.0.0.1:{}".format(self.server.server_port)})
        self.assertEqual(status, 401)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))
        self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")


if __name__ == "__main__":
    unittest.main()
