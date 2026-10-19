"""真实认证 HTTP 的单原片请求契约测试；输入是假媒体，不冒称引擎 E2E。"""
import http.client
import json
from pathlib import Path
import tempfile
import sys
import threading
import time
import unittest
from unittest.mock import patch

from cha_stabilizer.local_server import create_server
from cha_stabilizer.models import STABILIZE_PARAMETERS


class StabilizeHttpContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"fake original for HTTP contract only")
        self.ctb = self.root / "manual.mp4"
        self.ctb.write_bytes(b"fake manual CTB for HTTP contract only")
        self.server = create_server(self.root)
        self.server.app.preferences.update({"tool_paths": {"ffprobe": sys.executable}})
        self.probe = patch("cha_stabilizer.core.stabilize.probe", return_value={
            "fps": 50.0, "duration": 0.1, "frames": 5, "width": 1280, "height": 720,
            "cfr_status": "metadata_consistent", "start_time": 0.0,
            "color_transfer": "bt709", "color_primaries": "bt709", "raw_streams": [{"codec_type": "video"}],
        })
        self.probe.start()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.probe.stop()
        self.temp.cleanup()

    def request(self, method, route, payload=None, *, authorized=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Authorization": "Bearer " + self.server.app.nonce} if authorized else {}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        connection.request(method, route, body=body, headers=headers)
        response = connection.getresponse()
        status, data = response.status, json.loads(response.read())
        connection.close()
        return status, data

    def wait_terminal(self, job_id):
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            status, value = self.request("GET", "/api/jobs/" + job_id)
            self.assertEqual(status, 200)
            if value["state"] not in ("queued", "running"):
                return value
            time.sleep(0.02)
        self.fail("the bounded fake-data HTTP job did not reach a terminal state")

    def parent(self):
        status, value = self.request("POST", "/api/jobs", {"kind": "stabilize", "request": {"original": str(self.source)}})
        self.assertEqual(status, 202)
        return self.wait_terminal(value["job"]["id"])

    def test_capability_is_authenticated_and_explicitly_blocks_ctb(self):
        status, _ = self.request("GET", "/api/capabilities", authorized=False)
        self.assertEqual(status, 401)
        status, value = self.request("GET", "/api/capabilities")
        self.assertEqual(status, 200)
        self.assertFalse(value["stabilize"]["available"])
        self.assertEqual(value["stabilize"]["automatic_ctb_exports"], 0)
        self.assertIn("ctb_executor_unavailable", value["stabilize"]["blocking_codes"])
        self.assertIn("gyroflow_template_unavailable", value["stabilize"]["blocking_codes"])
        self.assertEqual(value["stabilize"]["profiles"][0]["parameters"], STABILIZE_PARAMETERS)
        self.assertEqual(len(self.server.app.jobs.list()), 0)

    def test_new_contract_preserves_old_public_job_fields_and_adds_workflow(self):
        job = self.parent()
        self.assertEqual(job["kind"], "stabilize")
        self.assertEqual(job["state"], "needs_manual")
        for key in ("id", "stage", "progress", "message", "message_key", "args", "artifacts", "warnings", "error", "result"):
            self.assertIn(key, job)
        self.assertEqual(job["workflow"]["schema_version"], 1)
        self.assertEqual(job["workflow"]["profile"], "recommended-v1")
        self.assertEqual(job["workflow"]["stages"][1]["state"], "blocked")
        self.assertIsNone(job["workflow"]["parent_job_id"])
        self.assertNotIn(str(self.source), json.dumps(job))

    def test_continue_is_new_uuid_and_cannot_override_parent_fields(self):
        parent = self.parent()
        before = (self.server.app.jobs.get_run_dir(parent["id"]) / "job.json").read_bytes()
        continuation = {"parent_job_id": parent["id"], "manual_ctb": {
            "source": str(self.ctb), "origin_seconds": 0.0, "declared_at": "2026-10-19T02:00:00Z"}}
        status, value = self.request("POST", "/api/jobs", {"kind": "stabilize_continue", "request": dict(continuation, original=str(self.ctb))})
        self.assertEqual(status, 422)
        self.assertEqual(value["error"]["code"], "invalid_request")
        self.assertEqual(len(self.server.app.jobs.list()), 1)
        status, value = self.request("POST", "/api/jobs", {"kind": "stabilize_continue", "request": continuation})
        self.assertEqual(status, 202)
        child = self.wait_terminal(value["job"]["id"])
        self.assertNotEqual(child["id"], parent["id"])
        self.assertEqual(child["workflow"]["parent_job_id"], parent["id"])
        self.assertEqual(child["workflow"]["ctb_origin"], "manual_import")
        self.assertEqual(self.server.app.jobs.get_request(child["id"])["original"], str(self.source.resolve()))
        self.assertEqual((self.server.app.jobs.get_run_dir(parent["id"]) / "job.json").read_bytes(), before)

    def test_continue_rejects_alias_before_creating_workspace(self):
        parent = self.parent()
        status, _ = self.request("POST", "/api/jobs", {"kind": "stabilize_continue", "request": {
            "parent_job_id": parent["id"], "manual_ctb": {"source": str(self.source), "origin_seconds": 0.0,
                                                         "declared_at": "2026-10-19T02:00:00Z"}}})
        self.assertEqual(status, 422)
        self.assertEqual(len(self.server.app.jobs.list()), 1)


if __name__ == "__main__":
    unittest.main()
