"""Test packaging guards without running Flutter, MSVC or any executable fixture."""
import ast
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_windows
from build_windows import bundle_metadata, copy_directory, copy_windows_source, flutter_commands, verify_worker_inventory


ROOT = Path(__file__).resolve().parents[1]
TEMP = Path(tempfile.gettempdir())


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

    def pubspec_fixture(self, content="name: fixture\nversion: 0.2.0+2\n"):
        path = self.root / "pubspec.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def fixed_version_fixture(self, file_version=(0, 2, 0, 2), product_version=None):
        product_version = file_version if product_version is None else product_version
        def words(value):
            return (value[0] << 16) | value[1], (value[2] << 16) | value[3]
        return struct.pack("<13I", 0xFEEF04BD, 0x00010000, *words(file_version),
                           *words(product_version), 0x3F, 0, 0x40004, 1, 0, 0, 0)

    def test_pubspec_version_is_bounded_canonical_and_separate_from_worker(self):
        version = build_windows.read_product_version(self.pubspec_fixture(
            "# version: 9.9.9+9\nname: fixture\nversion: 0.2.0+2 # product only\n"
            "dependencies:\n  version: ^4.0.0\n"))
        self.assertEqual(version.windows_version, (0, 2, 0, 2))
        self.assertEqual(version.metadata(), {
            "product_version": "0.2.0", "build_number": "2", "pubspec_version": "0.2.0+2",
            "version_source": "ui/pubspec.yaml", "package_stem": "ChaSteady-0.2.0+2-Windows-x64"})
        for value in ("0.0.0+0", "65535.65535.65535+65535"):
            with self.subTest(value=value):
                self.assertEqual(build_windows.parse_product_version(value).pubspec_version, value)
        self.assertFalse(any("worker" in key or "protocol" in key for key in version.metadata()))

    def test_product_version_rejects_invalid_unbounded_or_injected_components(self):
        values = (None, 2, "", "0.2.0", "v0.2.0+2", "0.02.0+2", "0.2.0+02", "0.2.0-rc.1+2",
                  "0.2.0+build", "0.2.0+-2", "65536.2.0+2", "0.65536.0+2", "0.2.65536+2",
                  "0.2.0+65536", "9" * 1000 + ".2.0+2", "0.2.0+2 --dart-define=EVIL=1",
                  "0.2.0+2\n", "0.2.0+2;exit", "0.2.0+$(whoami)", "０.2.0+2")
        for value in values:
            with self.subTest(value=value), self.assertRaises(build_windows.ProductVersionError):
                build_windows.parse_product_version(value)
        for parts in ((True, 2, 0, 2), (0, 2, 0, -1), (0, 2, 0, 65536), (0, 2, 0, "2")):
            with self.subTest(parts=parts), self.assertRaises(build_windows.ProductVersionError):
                build_windows.ProductVersion(*parts)
        with self.assertRaises(build_windows.ProductVersionError):
            flutter_commands(product_version="0.2.0+2")

    def test_pubspec_rejects_duplicates_yaml_ambiguity_and_version_injection(self):
        cases = ("name: fixture\n", "version: 0.2.0+2\nversion: 0.3.0+3\n",
                 "name: fixture\nname: duplicate\nversion: 0.2.0+2\n",
                 "version: 0.2.0+2\n'version': 0.3.0+3\n",
                 'version: 0.2.0+2\n"ver\\u0073ion": 0.3.0+3\n',
                 "version: '0.2.0+2'\n", 'version: "0.2.0+2"\n', "version: &v 0.2.0+2\n",
                 "base: &base\n  version: 0.2.0+2\n<<: *base\n", "version: *alias\n",
                 "version:\n  nested: 0.2.0+2\n", "version: |\n  0.2.0+2\n",
                 "version: 0.2.0+2\n---\nversion: 0.3.0+3\n", "{version: 0.2.0+2}\n",
                 "version: 0.2.0+2\n...\n", "%YAML 1.2\nversion: 0.2.0+2\n",
                 "version: 0.2.0+2 --build-number=8\n", "version: 0.2.0+2;exit\n",
                 "version: 0.2.0+2\n  continuation\n", "version: 0.2.0+2\n  # comment\n  injected\n",
                 "version:\t0.2.0+2\n", "version: 0.2.0+2\x00\n", "version: 0.2.0+2\rname: x\n")
        for content in cases:
            with self.subTest(content=content), self.assertRaises(build_windows.ProductVersionError):
                build_windows.read_product_version(self.pubspec_fixture(content))

    def test_pubspec_reader_rejects_missing_directory_oversize_and_invalid_utf8(self):
        path = self.root / "pubspec.yaml"
        with self.assertRaises(build_windows.ProductVersionError):
            build_windows.read_product_version(path)
        with self.assertRaises(build_windows.ProductVersionError):
            build_windows.read_product_version(self.root)
        for raw in (b"", b"\xff", b"version: 0.2.0+2\n#" + b"x" * 65536):
            path.write_bytes(raw)
            with self.subTest(size=len(raw)), self.assertRaises(build_windows.ProductVersionError):
                build_windows.read_product_version(path)
        path.write_bytes(b"name: fixture\r\nversion: 0.2.0+2\r\n")
        self.assertEqual(build_windows.read_product_version(path).pubspec_version, "0.2.0+2")
        with mock.patch.object(build_windows, "_assert_no_reparse_components", side_effect=ValueError("fixture reparse")), \
                self.assertRaises(build_windows.ProductVersionError):
            build_windows.read_product_version(path)

    def test_product_defines_reach_test_and_both_builds_but_not_analysis_pub_or_l10n(self):
        version = build_windows.read_product_version(self.pubspec_fixture())
        defines = ["--dart-define=CHASTEADY_PRODUCT_VERSION=0.2.0", "--dart-define=CHASTEADY_BUILD_NUMBER=2"]
        build = ["--build-name=0.2.0", "--build-number=2"]
        commands = dict(flutter_commands(product_version=version))
        self.assertEqual(commands["pub"], ["pub", "get", "--enforce-lockfile"])
        self.assertEqual(commands["l10n"], ["gen-l10n"])
        self.assertEqual(commands["analyze"], ["analyze", "--no-pub"])
        self.assertEqual(commands["test"], ["test", "--no-pub", "--reporter", "expanded"] + defines)
        self.assertEqual(commands["windows"], ["build", "windows", "--release"] + build + defines)
        self.assertEqual(commands["web"], ["build", "web", "--release", "--no-web-resources-cdn",
                                           "--pwa-strategy=none"] + build + defines)
        self.assertEqual(dict(flutter_commands(build_only=True, product_version=version)),
                         {key: value for key, value in commands.items() if key not in ("analyze", "test")})

    def test_version_summary_cli_reads_source_without_running_builds(self):
        ui = self.root / "ui"
        ui.mkdir()
        (ui / "pubspec.yaml").write_text("version: 0.2.0+2\n", encoding="utf-8")
        output = io.StringIO()
        with mock.patch.object(build_windows, "ROOT", self.root), \
                mock.patch.object(sys, "argv", ["build_windows.py", "--version-summary"]), \
                mock.patch.object(build_windows, "spawn_owned_process") as spawn, redirect_stdout(output):
            build_windows.main()
        spawn.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()), build_windows.parse_product_version("0.2.0+2").metadata())
        self.assertEqual(set(path.name for path in self.root.iterdir()), {"ui"})

    def test_invalid_version_summary_cli_fails_without_echoing_source_or_running_builds(self):
        ui = self.root / "ui"
        ui.mkdir()
        (ui / "pubspec.yaml").write_text("version: bearer=never-public\n", encoding="utf-8")
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(build_windows, "ROOT", self.root), \
                mock.patch.object(sys, "argv", ["build_windows.py", "--version-summary"]), \
                mock.patch.object(build_windows, "spawn_owned_process") as spawn, \
                redirect_stdout(output), redirect_stderr(errors), self.assertRaises(SystemExit) as failure:
            build_windows.main()
        self.assertEqual(failure.exception.code, 2)
        spawn.assert_not_called()
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Product pubspec is missing or invalid", errors.getvalue())
        self.assertNotIn("never-public", errors.getvalue())
        self.assertNotIn(str(self.root), errors.getvalue())

    def test_local_real_build_reads_staged_pubspec_and_forwards_product_version(self):
        module = ast.parse(Path(build_windows.__file__).read_text(encoding="utf-8"))
        main = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        version_assignment = next(node for node in main.body if isinstance(node, ast.Assign)
                                  and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                                  and node.value.func.id == "read_product_version")
        self.assertEqual(ast.unparse(version_assignment.value.args[0]), "source / 'pubspec.yaml'")
        call = next(node for node in ast.walk(main) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "flutter_commands")
        self.assertGreater(call.lineno, version_assignment.lineno)
        self.assertEqual([(keyword.arg, ast.unparse(keyword.value)) for keyword in call.keywords],
                         [("product_version", "product_version")])
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == "verify_windows_product_version" for node in ast.walk(main)))

    def test_fixed_pe_parser_uses_numeric_file_and_product_versions_including_build(self):
        self.assertEqual(build_windows.parse_fixed_file_info(self.fixed_version_fixture()),
                         {"file_version": (0, 2, 0, 2), "product_version": (0, 2, 0, 2)})
        maximum = (65535, 65535, 65535, 65535)
        self.assertEqual(build_windows.parse_fixed_file_info(self.fixed_version_fixture(maximum)),
                         {"file_version": maximum, "product_version": maximum})
        self.assertEqual(build_windows.parse_fixed_file_info(self.fixed_version_fixture(product_version=(1, 2, 3, 4)))[
            "product_version"], (1, 2, 3, 4))

    def test_fixed_pe_parser_rejects_truncated_oversize_wrong_signature_and_structure(self):
        raw = self.fixed_version_fixture()
        for value in (None, bytearray(raw), raw[:51], raw + b"\0", b"\0" * 52,
                      struct.pack("<I", 0) + raw[4:], raw[:4] + struct.pack("<I", 0) + raw[8:]):
            with self.subTest(value_type=type(value)), self.assertRaises(build_windows.ProductVersionError):
                build_windows.parse_fixed_file_info(value)

    def test_pe_guard_with_mocked_resource_reader_checks_both_numeric_versions_without_execution(self):
        executable = self.root / "ChaSteady.exe"
        executable.write_bytes(b"fixture only; not a real PE and never executed")
        version = build_windows.parse_product_version("0.2.0+2")
        with mock.patch.object(build_windows, "_read_windows_fixed_file_info",
                               return_value=self.fixed_version_fixture()) as reader, \
                mock.patch.object(build_windows, "spawn_owned_process") as spawn:
            result = build_windows.verify_windows_product_version(self.root, version)
        reader.assert_called_once_with(executable.resolve())
        spawn.assert_not_called()
        self.assertEqual(result["fixed_file_version"], "0.2.0.2")
        self.assertEqual(result["fixed_product_version"], "0.2.0.2")
        self.assertTrue(result["matches_pubspec"])
        self.assertFalse(result["runtime_acceptance_verified"])
        self.assertFalse(result["executable_executed"])
        for raw in (self.fixed_version_fixture(file_version=(0, 2, 0, 1), product_version=(0, 2, 0, 2)),
                    self.fixed_version_fixture(product_version=(0, 2, 0, 1))):
            with self.subTest(raw=raw), mock.patch.object(build_windows, "_read_windows_fixed_file_info", return_value=raw), \
                    self.assertRaises(build_windows.ProductVersionError):
                build_windows.verify_windows_product_version(self.root, version)

    def test_pe_guard_rejects_missing_or_reparse_input_before_system_api(self):
        version = build_windows.parse_product_version("0.2.0+2")
        with mock.patch.object(build_windows, "_read_windows_fixed_file_info") as reader:
            with self.assertRaises(build_windows.ProductVersionError):
                build_windows.verify_windows_product_version(self.root, version)
            reader.assert_not_called()
        (self.root / "ChaSteady.exe").write_bytes(b"fixture only")
        with mock.patch.object(build_windows, "_read_windows_fixed_file_info") as reader, \
                mock.patch.object(build_windows, "_assert_no_reparse_components", side_effect=ValueError("reparse")), \
                self.assertRaises(build_windows.ProductVersionError):
            build_windows.verify_windows_product_version(self.root, version)
        reader.assert_not_called()

    def test_non_windows_resource_reader_fails_closed_instead_of_claiming_pe_validation(self):
        with mock.patch.object(build_windows.os, "name", "posix"), \
                self.assertRaises(build_windows.ProductVersionError):
            build_windows._read_windows_fixed_file_info("not-an-executable")

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
