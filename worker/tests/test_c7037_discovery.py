import hashlib
import http.client
import json
import tempfile
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from cha_stabilizer.errors import NeedsReviewError
from cha_stabilizer.job_runner import (
    JobRunner,
    _known_c7037_presets,
    discover_c7037_presets,
    validate_cached_v9_discovery,
)
from cha_stabilizer.job_store import JobStore, PreferenceStore
from cha_stabilizer.local_server import create_server
from cha_stabilizer.models import RequestValidationError
from cha_stabilizer.core.cache import load_legacy


class C7037DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.experiment = self.root / "Frontier_Stabilization_20261012_150110"
        self.experiment.mkdir()
        self.data_root = self.root
        raw_presets = _known_c7037_presets(self.data_root)
        for index, preset in enumerate(raw_presets):
            request = preset["request"]
            for key in ("original", "ctb", "reference"):
                path = Path(request[key])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("source-{}-{}".format(index, key)).encode("ascii"))
            count = round((request["end"] - request["start"]) * 50.0)
            quiet = np.zeros((count, 2, 3), dtype=np.float64)
            reference = np.zeros((count, 2, 3), dtype=np.float64)
            quiet[:, 0, 0] = quiet[:, 1, 1] = 1.0
            reference[:, 0, 0] = reference[:, 1, 1] = 1.0
            quiet_path = Path(request["legacy_quiet_cache"])
            quiet_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                str(quiet_path), corrections=quiet, tracking_width=1280, tracking_height=720, fps=50.0,
            )
            reference_path = Path(request["legacy_reference_cache"])
            reference_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                str(reference_path), all_frames_qualified=True, unit_se2_all_frames=True, fps=50.0,
                start_seconds=request["start"], end_seconds=request["end"],
                render_source_origin_unit_affines_1280=reference,
            )
        self.cache_pins = {}
        for preset in raw_presets:
            for key in ("legacy_quiet_cache", "legacy_reference_cache"):
                path = Path(preset["request"][key])
                self.cache_pins[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.data_dir = self.root / "worker-data"
        self.data_dir.mkdir()
        self.store = JobStore(self.data_dir)
        self.preferences = PreferenceStore(self.data_dir, desktop=True)
        self.runner = JobRunner(self.store, self.preferences)

    def tearDown(self):
        self.runner.shutdown()
        self.temp.cleanup()

    def test_discovery_uses_only_user_root_relative_layout_and_exact_cache_sha_pins(self):
        with patch("cha_stabilizer.core.cache.HASHES", self.cache_pins):
            discovered = discover_c7037_presets(str(self.experiment))
            self.assertEqual(len(discovered), 3)
            for preset in discovered:
                self.assertEqual(preset["mode"], "cached_v9")
                self.assertTrue(preset["source_binding"])
                self.assertEqual(len(preset["cache_hashes"]), 2)
                for path in preset["request"].values():
                    if isinstance(path, str) and path.endswith((".MP4", ".mp4", ".npz")):
                        self.assertTrue(Path(path).is_relative_to(self.root))
            self.runner.register_discovered_presets(discovered)
            selected = discovered[0]["request"]
            binding = self.runner._validate_cached_v9(selected)
            validate_cached_v9_discovery(selected, binding)
            with self.assertRaises(NeedsReviewError):
                load_legacy(selected, (1280, 720), 50.0)
            quiet, reference, provenance = load_legacy(
                selected, (1280, 720), 50.0, discovery_binding=binding
            )
            self.assertEqual(quiet.shape, (800, 2, 3))
            self.assertEqual(reference.shape, (800, 2, 3))
            self.assertFalse(provenance["fresh_measurement"])

    def test_authenticated_post_discovery_registers_presets_for_session_submission(self):
        server = create_server(app_root=self.data_dir, port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            with patch("cha_stabilizer.core.cache.HASHES", self.cache_pins):
                body = json.dumps({"experiment_root": str(self.experiment)}).encode("utf-8")
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request(
                    "POST", "/api/presets/discover", body=body,
                    headers={
                        "Authorization": "Bearer " + server.app.nonce,
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                result = json.loads(response.read().decode("utf-8"))
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertEqual(len(result["presets"]), 3)
                selected = result["presets"][0]
                binding = server.app.runner._validate_cached_v9(selected["request"])
                self.assertEqual(binding["id"], selected["id"])
                server.app.preferences.update({"tool_paths": {"ffmpeg": sys.executable, "ffprobe": sys.executable}})
                invoked = threading.Event()
                captured = {}

                def fake_fusion(request, workdir, toolchain, cancel, on_event):
                    captured["binding"] = toolchain.get("_cached_v9_discovery_binding")
                    invoked.set()
                    raise NeedsReviewError("Synthetic test stop; no media work is performed.")

                with patch(
                    "cha_stabilizer.job_runner.importlib.import_module",
                    return_value=SimpleNamespace(run_fusion=fake_fusion),
                ):
                    job = server.app.runner.submit({"kind": "fusion", "request": selected["request"]})
                    self.assertTrue(invoked.wait(5))
                    for _ in range(100):
                        if server.app.jobs.get(job["id"])["state"] == "needs_review":
                            break
                        time.sleep(0.01)
                self.assertEqual(captured["binding"]["source_binding"], selected["source_binding"])
                self.assertEqual(server.app.jobs.get(job["id"])["state"], "needs_review")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_changed_cache_or_source_fingerprint_invalidates_session_binding(self):
        with patch("cha_stabilizer.core.cache.HASHES", self.cache_pins):
            discovered = discover_c7037_presets(str(self.experiment))
            self.runner.register_discovered_presets(discovered)
            request = discovered[0]["request"]
            self.runner._validate_cached_v9(request)
            Path(request["original"]).write_bytes(b"changed source size")
            with self.assertRaises(RequestValidationError):
                self.runner._validate_cached_v9(request)

            discovered = discover_c7037_presets(str(self.experiment))
            self.runner.register_discovered_presets(discovered)
            request = discovered[0]["request"]
            self.runner._validate_cached_v9(request)
            Path(request["legacy_quiet_cache"]).write_bytes(b"changed cache bytes")
            with self.assertRaises(RequestValidationError):
                self.runner._validate_cached_v9(request)

        other = JobRunner(self.store, self.preferences)
        try:
            with self.assertRaises(RequestValidationError):
                other._validate_cached_v9(request)
        finally:
            other.shutdown()

    def test_discovery_rejects_nonselected_or_reparse_root(self):
        with self.assertRaises(RequestValidationError):
            discover_c7037_presets(str(self.root))
        link = self.root / "linked-experiment"
        try:
            link.symlink_to(self.experiment, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory reparse points are unavailable")
        with self.assertRaises((RequestValidationError, ValueError)):
            discover_c7037_presets(str(link))


if __name__ == "__main__":
    unittest.main()
