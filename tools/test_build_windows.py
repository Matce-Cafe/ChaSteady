"""Test packaging guards without running Flutter, MSVC or any executable fixture."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_windows import bundle_metadata, copy_directory, copy_windows_source, flutter_commands, verify_worker_inventory


ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / "private/test-temp"
TEMP.mkdir(exist_ok=True)


class WindowsPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bundle-tests-", dir=str(TEMP))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_build_only_omits_analysis_tests_and_runtime_launches(self):
        commands = flutter_commands(build_only=True)
        self.assertEqual([label for label, _ in commands], ["pub", "l10n", "windows", "web"])
        self.assertEqual(commands[2][1], ["build", "windows", "--release"])
        self.assertFalse(any(arguments[0] in ("analyze", "test", "run", "drive")
                             for _, arguments in commands))

    def test_default_keeps_existing_prebuild_checks(self):
        self.assertEqual([label for label, _ in flutter_commands()],
                         ["pub", "l10n", "analyze", "test", "windows", "web"])

    def test_existing_destination_is_not_overwritten(self):
        source = self.root / "source"
        source.mkdir()
        (source / "app.dll").write_bytes(b"fixture, not an executable")
        destination = self.root / "destination"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_text("retained", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            copy_directory(source, destination)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "retained")
        self.assertFalse((destination / "app.dll").exists())

    def test_media_and_crash_dumps_are_rejected_before_copy(self):
        for suffix in (".mp4", ".MOV", ".mxf", ".m4v", ".mkv", ".avi", ".webm",
                       ".wav", ".aac", ".mp3", ".dmp"):
            with self.subTest(suffix=suffix):
                source = self.root / ("source" + suffix)
                source.mkdir()
                (source / ("private" + suffix)).write_bytes(b"fixture")
                destination = self.root / ("destination" + suffix)
                with self.assertRaises(RuntimeError):
                    copy_directory(source, destination)
                self.assertFalse(destination.exists())

    def test_release_copy_omits_debug_artifacts_but_keeps_runtime_and_notices(self):
        source = self.root / "source"
        source.mkdir()
        names = ("app.dll", "app.exe", "app.aot", "LICENSE.txt", "app.pdb",
                 "app.ilk", "app.exp", "app.lib")
        for name in names:
            (source / name).write_bytes(b"fixture")
        destination = self.root / "destination"
        copy_directory(source, destination, omit_debug=True)
        self.assertEqual({path.name for path in destination.iterdir()},
                         {"app.dll", "app.exe", "app.aot", "LICENSE.txt"})
        self.assertTrue((source / "app.pdb").exists())

    def test_windows_source_excludes_ephemeral_caches_and_developer_paths(self):
        source = self.root / "windows"
        runner = source / "runner"
        runner.mkdir(parents=True)
        (runner / "main.cpp").write_text("// fixture", encoding="utf-8")
        (source / "CMakeLists.txt").write_text("# fixture", encoding="utf-8")
        managed = source / "flutter"
        managed.mkdir()
        for name in ("CMakeLists.txt", "generated_plugin_registrant.h",
                     "generated_plugin_registrant.cc", "generated_plugins.cmake"):
            (managed / name).write_text("fixture", encoding="utf-8")
        ephemeral = managed / "ephemeral"
        ephemeral.mkdir()
        (ephemeral / "generated_config.cmake").write_text("C:/APPS/developer-only", encoding="utf-8")
        cache = source / ".vs"
        cache.mkdir()
        (cache / "cache.txt").write_text("developer-only", encoding="utf-8")
        destination = self.root / "copy"
        copy_windows_source(source, destination)
        self.assertTrue((destination / "runner/main.cpp").is_file())
        self.assertTrue((destination / "flutter/generated_plugins.cmake").is_file())
        self.assertFalse((destination / "flutter/ephemeral").exists())
        self.assertFalse((destination / ".vs").exists())

    def worker_fixture(self):
        bundle = self.root / "Worker"
        bundle.mkdir()
        payload = b"fixture only, never executed"
        (bundle / "Worker.exe").write_bytes(payload)
        report = {"freeze": {"status": "built_and_smoke_tested"}, "test_facts": {
            "frozen_worker": {"passed": True, "inventory": {"files": [
                {"path": "Worker.exe", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
            ]}}}}
        return bundle, report

    def test_worker_inventory_matches_bytes_without_claiming_native_acceptance(self):
        bundle, report = self.worker_fixture()
        evidence = verify_worker_inventory(bundle, report)
        self.assertTrue(evidence["sha256_inventory_matches"])
        self.assertFalse(evidence["native_application_runtime_verified"])
        self.assertEqual(evidence["file_count"], 1)

    def test_changed_or_extra_worker_files_are_rejected(self):
        bundle, report = self.worker_fixture()
        original = (bundle / "Worker.exe").read_bytes()
        (bundle / "Worker.exe").write_bytes(b"modified")
        with self.assertRaises(RuntimeError):
            verify_worker_inventory(bundle, report)
        (bundle / "Worker.exe").write_bytes(original)
        (bundle / "unexpected.dll").write_bytes(b"fixture")
        with self.assertRaises(RuntimeError):
            verify_worker_inventory(bundle, report)

    def test_worker_inventory_rejects_escaping_and_duplicate_names(self):
        bundle, report = self.worker_fixture()
        rows = report["test_facts"]["frozen_worker"]["inventory"]["files"]
        row = dict(rows[0])
        for name in ("../Worker.exe", "/Worker.exe", "C:/Worker.exe", "./Worker.exe", "Worker\\\\Worker.exe"):
            with self.subTest(name=name):
                rows[0] = {**row, "path": name}
                with self.assertRaises(RuntimeError):
                    verify_worker_inventory(bundle, report)
        rows[:] = [row, {**row, "path": "worker.EXE"}]
        with self.assertRaises(RuntimeError):
            verify_worker_inventory(bundle, report)

    def test_worker_inventory_requires_completed_build_protocol_evidence(self):
        bundle, report = self.worker_fixture()
        report["freeze"]["status"] = "tests_running"
        with self.assertRaises(RuntimeError):
            verify_worker_inventory(bundle, report)

    def test_manifest_does_not_promote_inventory_to_runtime_or_release_clearance(self):
        bundle = self.root / "app"
        bundle.mkdir()
        payload = b"fixture"
        (bundle / "app.dll").write_bytes(payload)
        metadata = bundle_metadata(bundle, worker_present=False)
        self.assertFalse(metadata["worker_packaged"])
        self.assertFalse(metadata["runtime_acceptance_verified"])
        self.assertFalse(metadata["web_menu_shared_backend_runtime_verified"])
        self.assertFalse(metadata["public_distribution_cleared"])
        self.assertFalse(metadata["signed"])
        self.assertEqual(metadata["files"], [{"path": "app.dll", "bytes": len(payload),
                                             "sha256": hashlib.sha256(payload).hexdigest()}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
