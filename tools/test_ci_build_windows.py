"""CI packaging/identity tests; executable-shaped fixture bytes are never run."""
import ast
import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_windows
import ci_build_windows as ci
import ci_prepare_assets
import provision_worker_runtime


class CiBuildWindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ci-build-helper-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_flutter_only_cli_routes_without_full_build_inputs(self):
        argv = ["--preflight-flutter-only", "--flutter-result", str(self.root / "flutter-result.json"),
                "--flutter-scratch", str(self.root / "scratch"), "--preflight-stage", str(self.root / "new-stage")]
        with mock.patch.object(ci, "run_flutter_preflight", return_value={}) as preflight, \
                mock.patch.object(ci, "run_build") as full:
            self.assertEqual(ci.main(argv), 0)
        full.assert_not_called()
        supplied = preflight.call_args.args[0]
        self.assertIsNone(supplied.toolchain_report)
        self.assertIsNone(supplied.worker_manifest)
        self.assertIsNone(supplied.font_result)
        self.assertIsNone(supplied.artifact_dir)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
            ci.main(["--flutter-result", str(self.root / "flutter-result.json"),
                     "--flutter-scratch", str(self.root / "scratch")])
        self.assertEqual(failure.exception.code, 2)

    def test_flutter_only_cli_rejects_full_build_inputs_or_artifact_output(self):
        base = ["--preflight-flutter-only", "--flutter-result", str(self.root / "result.json"),
                "--flutter-scratch", str(self.root / "scratch"), "--preflight-stage", str(self.root / "stage")]
        for forbidden in ("--toolchain-report", "--artifact-dir", "--worker-manifest", "--font-result"):
            with self.subTest(forbidden=forbidden), redirect_stderr(io.StringIO()), \
                    mock.patch.object(ci, "run_flutter_preflight") as preflight, self.assertRaises(SystemExit) as failure:
                ci.main(base + [forbidden, str(self.root / "private-input")])
            self.assertEqual(failure.exception.code, 2)
            preflight.assert_not_called()

    def test_flutter_only_gate_reuses_same_identity_function_in_a_new_isolated_stage(self):
        extraction = self.root / "extracted-sdk"
        sdk = extraction / "flutter"
        sdk.mkdir(parents=True)
        downloads = self.root / "downloaded-archive"
        downloads.mkdir()
        identity = {"flutter_version": "3.47.7", "dart_version": "3.13.5",
                    "framework_revision": "abaf9c523780a608bd46686fd5e53740a07077f8"}
        receipt = {"sdk_root": str(sdk), "extraction_directory": str(extraction),
                   "download_directory": str(downloads), "archive_sha256": ci.ci_provision_flutter.FLUTTER_SHA256}
        args = SimpleNamespace(root=self.root, flutter_result=self.root / "result.json",
                               flutter_scratch=self.root / "scratch", preflight_stage=self.root / "state" / "fresh")
        with mock.patch.object(ci, "ROOT", self.root), \
                mock.patch.object(ci, "validate_flutter_result", return_value=receipt) as validated, \
                mock.patch.object(ci, "create_flutter_environment", return_value={}), \
                mock.patch.object(ci, "flutter_version_check", return_value=identity) as version, \
                mock.patch.object(ci, "build_worker") as worker, redirect_stdout(io.StringIO()):
            result = ci.run_flutter_preflight(args)
            validated.assert_called_once_with(args.flutter_result, args.flutter_scratch)
            version.assert_called_once_with(sdk, self.root.resolve(strict=True), {},
                                            args.preflight_stage.resolve(strict=True))
            worker.assert_not_called()
            self.assertFalse(result["native_build_executed"])
            self.assertFalse(result["worker_tests_or_math_executed"])
            self.assertEqual(ci.read_json(args.preflight_stage / "flutter-preflight.json"), result)
            self.assertFalse(list(args.preflight_stage.rglob("*.zip")))
            with self.assertRaises(ci.ValidationError):
                ci.run_flutter_preflight(args)
            args.preflight_stage = sdk / "must-not-write-here"
            with self.assertRaises(ci.ValidationError):
                ci.run_flutter_preflight(args)
            self.assertFalse(args.preflight_stage.exists())
            self.assertEqual(version.call_count, 1)

    def test_workflow_verifies_flutter_identity_before_long_vs_sdk_update(self):
        workflow = (Path(ci.ROOT) / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
        early = workflow.index("- name: Verify Flutter executable identity before long toolchain updates")
        update = workflow.index("- name: Update official stable Visual Studio and Windows SDK")
        full = workflow.index("- name: Build, rerun backend tests, validate local math identity")
        self.assertLess(early, update)
        self.assertLess(update, full)
        for prerequisite in ("- name: Create fresh Worker runtime", "- name: Fetch and verify the pinned Noto font",
                             "- name: Download and verify the pinned official Flutter SDK"):
            self.assertLess(workflow.index(prerequisite), early)
        early_step = workflow[early:update]
        self.assertIn("--preflight-flutter-only", early_step)
        self.assertIn("--preflight-stage", early_step)
        self.assertNotIn("--toolchain-report", early_step)
        self.assertNotIn("--artifact-dir", early_step)
        module = ast.parse(Path(ci.__file__).read_text(encoding="utf-8"))
        for function_name in ("run_flutter_preflight", "run_build"):
            function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
            self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                                and node.func.id == "flutter_version_check" for node in ast.walk(function)))

    def test_ui_only_cli_requires_font_and_stage_and_rejects_build_inputs(self):
        base = ["--preflight-ui-only", "--flutter-result", str(self.root / "result.json"),
                "--flutter-scratch", str(self.root / "scratch")]
        required = {"--preflight-stage": "new-stage", "--font-result": "font.json", "--font-scratch": "font-scratch"}
        complete = base + [item for flag, value in required.items() for item in (flag, str(self.root / value))]
        with mock.patch.object(ci, "run_flutter_preflight", return_value={}) as preflight, \
                mock.patch.object(ci, "run_build") as full:
            self.assertEqual(ci.main(complete), 0)
        self.assertTrue(preflight.call_args.args[0].preflight_ui_only)
        full.assert_not_called()
        for missing in required:
            incomplete = base + [item for flag, value in required.items() if flag != missing
                                 for item in (flag, str(self.root / value))]
            with self.subTest(missing=missing), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                ci.main(incomplete)
        for forbidden in ("--toolchain-report", "--worker-manifest", "--math-sidecar", "--artifact-dir"):
            with self.subTest(forbidden=forbidden), redirect_stderr(io.StringIO()), \
                    mock.patch.object(ci, "run_flutter_preflight") as preflight, self.assertRaises(SystemExit):
                ci.main(complete + [forbidden, str(self.root / "forbidden")])
            preflight.assert_not_called()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ci.main(complete + ["--preflight-flutter-only"])

    def test_ui_only_gate_records_only_real_checks_and_cannot_run_builds(self):
        extraction = self.root / "extraction"
        sdk = extraction / "flutter"
        sdk.mkdir(parents=True)
        downloads = self.root / "downloads"
        downloads.mkdir()
        font_result = self.root / "font-result.json"
        font_result.write_text("{}", encoding="utf-8")
        font = self.root / "font-scratch" / "font.ttf"
        font.parent.mkdir()
        font.write_bytes(b"font fixture; never interpreted")
        args = SimpleNamespace(root=self.root, flutter_result=self.root / "result.json",
                               flutter_scratch=self.root / "scratch", preflight_stage=self.root / "new-stage",
                               preflight_ui_only=True, font_result=font_result, font_scratch=font.parent)
        provision = {"sdk_root": str(sdk), "extraction_directory": str(extraction),
                     "download_directory": str(downloads), "archive_sha256": "a" * 64}
        identity = {"flutter_version": "3.47.7", "dart_version": "3.13.5"}
        with mock.patch.object(ci, "ROOT", self.root), \
                mock.patch.object(ci, "validate_flutter_result", return_value=provision), \
                mock.patch.object(ci, "validate_font_result", return_value={"font_path_for_ephemeral_build_only": font}), \
                mock.patch.object(ci, "stage_flutter_source", return_value=args.preflight_stage / "ui") as staged, \
                mock.patch.object(ci, "create_flutter_environment", return_value={}), \
                mock.patch.object(ci, "flutter_version_check", return_value=identity), \
                mock.patch.object(ci, "run_flutter", return_value=b"") as run, \
                mock.patch.object(ci, "run_native_window_fixture") as native, \
                mock.patch.object(ci, "build_worker") as worker, redirect_stdout(io.StringIO()):
            result = ci.run_flutter_preflight(args)
            staged.assert_called_once_with(self.root.resolve(), args.preflight_stage.resolve(), font)
            self.assertEqual([call.args[0] for call in run.call_args_list], ["pub", "l10n", "analyze", "test"])
            self.assertEqual(result["scope"], "pinned_flutter_identity_and_ui_checks_only")
            self.assertTrue(all(result["ui_checks"].values()))
            self.assertFalse(result["native_build_executed"])
            self.assertFalse(result["runtime_acceptance_verified"])
            self.assertEqual(ci.read_json(args.preflight_stage / "flutter-ui-preflight.json"), result)
            native.assert_not_called()
            worker.assert_not_called()
            args.preflight_stage = font.parent / "must-not-write"
            with self.assertRaises(ci.ValidationError):
                ci.run_flutter_preflight(args)
            self.assertFalse(args.preflight_stage.exists())

    def test_ui_checks_only_stop_on_analysis_failure_and_never_report_success(self):
        def fail_analysis(label, *_args, **_kwargs):
            if label == "analyze":
                raise ci.ValidationError("Flutter analyze exited unsuccessfully; raw runner-local logs are not uploaded")
            return b""
        with mock.patch.object(ci, "run_flutter", side_effect=fail_analysis) as run, \
                redirect_stdout(io.StringIO()), self.assertRaises(ci.ValidationError):
            ci.run_flutter_ui_checks(SimpleNamespace(), self.root, self.root, {}, self.root)
        self.assertEqual([call.args[0] for call in run.call_args_list], ["pub", "l10n", "analyze"])

    def test_workflow_ui_checks_precede_updates_and_quick_mode_cannot_upload_bundle(self):
        workflow = (Path(ci.ROOT) / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
        early = workflow.index("- name: Analyze and test isolated UI before long toolchain updates")
        update = workflow.index("- name: Update official stable Visual Studio and Windows SDK")
        self.assertLess(early, update)
        self.assertIn("--preflight-ui-only", workflow[early:update])
        self.assertIn("--font-result", workflow[early:update])
        self.assertIn("type: boolean\n        default: false", workflow)
        for name in ("Create fresh Worker runtime", "Update official stable Visual Studio and Windows SDK",
                     "Build, rerun backend tests, validate local math identity"):
            step = workflow[workflow.index("- name: " + name):].split("      - name:", 1)[0]
            self.assertIn("if: ${{ !inputs.ui_checks_only }}", step)
        upload = workflow[workflow.index("- name: Upload only the app ZIP"):]
        self.assertIn("if: ${{ success() && !inputs.ui_checks_only }}", upload)

    def test_flutter_startup_diagnostic_reports_fixed_markers_and_explicit_known_codes_only(self):
        stderr = self.root / "stderr.log"
        private = b"D:\\private-fixture\\profile.json bearer=not-for-public-logs"
        stderr.write_bytes(b"ProcessException: The system cannot find the file specified\n" + private +
                           b"\nCommand: dartaotruntime.exe analysis_server_aot.dart.snapshot\n"
                           b"errorCode=2 errno=8675309 errorCode=222222222222222222222\n")
        output = io.StringIO()
        with redirect_stdout(output):
            ci.flutter_json_shape_diagnostic(b"", stderr, RuntimeError(), exit_code=1)
        text = output.getvalue()
        payload = json.loads(text.removeprefix("ChaSteady Flutter JSON diagnostic "))
        self.assertEqual(payload["process_exit_code"], 1)
        self.assertEqual(payload["known_os_error_codes"], [2])
        self.assertTrue(payload["startup_process_exception"])
        self.assertTrue(payload["startup_windows_file_not_found"])
        self.assertTrue(payload["startup_analysis_server_aot_snapshot"])
        self.assertNotIn("not-for-public-logs", text)
        self.assertNotIn("8675309", text)
        self.assertNotIn("D:\\private-fixture", text)
        stderr.write_bytes(b"ProcessException: The system cannot find the file specified\n")
        output = io.StringIO()
        with redirect_stdout(output):
            ci.flutter_json_shape_diagnostic(b"", stderr, RuntimeError())
        payload = json.loads(output.getvalue().removeprefix("ChaSteady Flutter JSON diagnostic "))
        self.assertEqual(payload["known_os_error_codes"], [])
        self.assertIsNone(payload["process_exit_code"])

    def test_flutter_json_shape_diagnostic_never_prints_vendor_text_paths_or_credentials(self):
        private = b"D:\\private-fixture\\profile.json bearer=not-for-public-logs"
        raw = b"\xef\xbb\xbf" + private
        stderr = self.root / "stderr.log"
        stderr.write_bytes(b"Building flutter tool...\nRunning pub upgrade...\n" + private)
        output = io.StringIO()
        with redirect_stdout(output):
            ci.flutter_json_shape_diagnostic(raw, stderr, json.JSONDecodeError("fixture-only", "", 0))
        text = output.getvalue()
        self.assertNotIn(private.decode("ascii"), text)
        self.assertNotIn("Building flutter tool...", text)
        self.assertNotIn("not-for-public-logs", text)
        payload = json.loads(text.removeprefix("ChaSteady Flutter JSON diagnostic "))
        self.assertEqual(payload["stdout_bytes"], len(raw))
        self.assertTrue(payload["stdout_utf8_bom"])
        self.assertTrue(payload["stderr_tool_build"])
        self.assertTrue(payload["stderr_pub_upgrade"])
        self.assertEqual(payload["json_error_pos"], 0)

    def test_safe_failure_diagnostic_uses_exact_author_message_codes(self):
        message = "Pinned Flutter SDK did not return its machine-readable version"
        diagnostic = ci.ci_failure_diagnostic(ci.ValidationError(message), "flutter_version")
        self.assertIn("code=CI_FLUTTER_VERSION_JSON", diagnostic)
        self.assertIn("stage=flutter_version", diagnostic)
        self.assertIn(message, diagnostic)
        exit_message = "Flutter version exited unsuccessfully; raw runner-local logs are not uploaded"
        self.assertIn("code=CI_FLUTTER_VERSION_EXIT",
                      ci.ci_failure_diagnostic(ci.ValidationError(exit_message), "flutter_version"))
        # Prefix matching would leak an appended private path or credential.
        augmented = message + r" D:\PRIVATE\profile.json bearer=do-not-print"
        diagnostic = ci.ci_failure_diagnostic(ci.ValidationError(augmented), "flutter_version")
        self.assertIn("code=CI_VALIDATION_FAILED", diagnostic)
        self.assertNotIn("D:\\PRIVATE", diagnostic)
        self.assertNotIn("do-not-print", diagnostic)

    def test_unknown_failure_and_stage_never_echo_paths_or_credentials(self):
        private = r"D:\PRIVATE\profile.json bearer=not-for-logs"
        for error in (ci.ValidationError(private), RuntimeError(private), ValueError(private)):
            with self.subTest(error_type=type(error).__name__):
                diagnostic = ci.ci_failure_diagnostic(error, private)
                self.assertIn("stage=unknown", diagnostic)
                self.assertNotIn(private, diagnostic)
                self.assertNotIn("not-for-logs", diagnostic)
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(ValueError):
            ci.mark_ci_stage(SimpleNamespace(), private)
        self.assertEqual(output.getvalue(), "")

    def test_main_reports_fixed_stage_and_code_not_raw_exception(self):
        def rejected(args):
            ci.mark_ci_stage(args, "flutter_version")
            raise ci.ValidationError(r"D:\PRIVATE\runtime.log bearer=not-for-logs")

        argv = []
        for flag in ("--toolchain-report", "--flutter-result", "--flutter-scratch", "--font-result",
                     "--font-scratch", "--worker-manifest", "--math-sidecar", "--artifact-dir"):
            argv.extend([flag, str(self.root / "private-fixture")])
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(ci, "run_build", side_effect=rejected), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = ci.main(argv)
        self.assertEqual(code, 1)
        self.assertIn("stage=flutter_version started", stdout.getvalue())
        self.assertIn("code=CI_VALIDATION_FAILED stage=flutter_version", stderr.getvalue())
        self.assertNotIn("not-for-logs", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn(str(self.root), stdout.getvalue() + stderr.getvalue())

    def test_run_build_identifies_toolchain_schema_failure_before_any_build(self):
        (self.root / ".git").mkdir()
        report = self.root / "toolchain.json"
        report.write_text("{}", encoding="utf-8")
        args = SimpleNamespace(root=self.root, toolchain_report=report)
        output = io.StringIO()
        with mock.patch.object(ci, "ROOT", self.root), \
                mock.patch.object(ci, "validate_flutter_result") as flutter_validation, \
                redirect_stdout(output), self.assertRaises(ci.ValidationError) as failure:
            ci.run_build(args)
        flutter_validation.assert_not_called()
        self.assertEqual(args._ci_stage, "toolchain_report")
        self.assertEqual(output.getvalue().splitlines(), [
            "ChaSteady CI stage=checkout started", "ChaSteady CI stage=toolchain_report started",
        ])
        diagnostic = ci.ci_failure_diagnostic(failure.exception, args._ci_stage)
        self.assertIn("code=CI_TOOLCHAIN_SCHEMA stage=toolchain_report", diagnostic)
        self.assertNotIn(str(self.root), diagnostic)

    @staticmethod
    def fake_wheels():
        return sorted([
            {"name": pin["name"], "version": pin["version"], "filename": pin["filename"],
             "sha256": pin["sha256"], "latest_release_verified": True}
            for pin in provision_worker_runtime.WHEELS
        ], key=lambda row: row["name"])

    @staticmethod
    def source_fixture():
        rows = [
            {"path": "tools/freeze_worker.py", "sha256": "1" * 64},
            {"path": "tools/regress_v9.py", "sha256": "2" * 64},
            {"path": "tools/worker_desktop_entry.py", "sha256": "3" * 64},
            {"path": "worker/cha_stabilizer/math/core.py", "sha256": "4" * 64},
        ]
        payload = ("\n".join(row["path"] + ":" + row["sha256"] for row in rows) + "\n").encode("utf-8")
        return {"canonicalization": "utf-8-lf-v1", "inventory_sha256": hashlib.sha256(payload).hexdigest(),
                "files": rows}

    def sidecar_fixture(self):
        source = self.source_fixture()
        runtime_sha = "a" * 64
        data = {
            "schema_version": 1,
            "kind": "local-worker-math-golden-summary",
            "scope": "three-case V9 mathematical golden comparison only; no media render, perceptual validation, or CI run",
            "local_validation_origin": "local-windows-x64-cpython-3.15.0-verified-wheel-freeze",
            "python": {"version": provision_worker_runtime.PYTHON_VERSION, "archive_sha256": runtime_sha},
            "wheels": self.fake_wheels(),
            "sources": source,
            "backend_tests": {"passed": True, "minimum_expected_test_count": 127,
                               "test_count": 128, "executed_test_count": 127, "skipped_count": 1},
            "thresholds": {"matrix_max_absolute_error": 1e-9, "weight_max_absolute_error": 1e-10},
            "cases": [
                {"case_id": "case-01", "checker_passed": True,
                 "matrix_max_absolute_error": 1e-10, "weight_max_absolute_error": 1e-11},
                {"case_id": "case-02", "checker_passed": True,
                 "matrix_max_absolute_error": 2e-10, "weight_max_absolute_error": 2e-11},
                {"case_id": "case-03", "checker_passed": True,
                 "matrix_max_absolute_error": 3e-10, "weight_max_absolute_error": 3e-11},
            ],
            "provenance": {"local_only": True, "signed": False, "input_paths_included": False,
                           "inputs_included": False, "absolute_paths_included": False,
                           "raw_media_or_cache_included": False, "ci_reproduction_claim": False},
        }
        runtime_report = {"python": {"published_sha256": runtime_sha, "download": {"sha256": runtime_sha}}}
        return data, runtime_report, source

    def test_source_inventory_normalizes_crlf_and_uses_sorted_lf_terminated_rows(self):
        paths = [*ci.SOURCE_INVENTORY_PATHS, "worker/cha_stabilizer/math/core.py"]
        for relative in paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"# one\r\nvalue = 1\r\n")
        result = ci.source_inventory(self.root)
        self.assertEqual([row["path"] for row in result["files"]], sorted(paths))
        expected_rows = "\n".join(row["path"] + ":" + row["sha256"] for row in result["files"]) + "\n"
        self.assertEqual(result["inventory_sha256"], hashlib.sha256(expected_rows.encode("utf-8")).hexdigest())
        first = result["inventory_sha256"]
        for relative in paths:
            (self.root / relative).write_bytes(b"# one\nvalue = 1\n")
        self.assertEqual(ci.source_inventory(self.root)["inventory_sha256"], first)

    def test_math_sidecar_accepts_dynamic_actual_counts_and_binds_all_identities(self):
        data, runtime, sources = self.sidecar_fixture()
        with mock.patch.object(ci, "source_inventory", return_value=sources), \
                mock.patch.object(ci, "_worker_pins", return_value=self.fake_wheels()):
            summary = ci._validate_math_sidecar(data, self.root, runtime)
        self.assertEqual(summary["case_count"], 3)
        self.assertEqual(summary["local_validation_origin"], "local-windows-x64-cpython-3.15.0-verified-wheel-freeze")
        self.assertFalse(summary["private_goldens_rerun_in_ci"])

    def test_math_sidecar_rejects_inconsistent_count_types_and_unknown_fields(self):
        mutations = (
            lambda sidecar: sidecar["backend_tests"].update(test_count=127, executed_test_count=125),
            lambda sidecar: sidecar["backend_tests"].update(test_count=True),
            lambda sidecar: sidecar["backend_tests"].update(minimum_expected_test_count=126),
            lambda sidecar: sidecar.update(unreviewed="extra"),
            lambda sidecar: sidecar["provenance"].update(input_paths_included=True),
            lambda sidecar: sidecar["cases"][0].update(checker_passed=False),
            lambda sidecar: sidecar["thresholds"].update(matrix_max_absolute_error=1e-8),
        )
        for mutate in mutations:
            data, runtime, sources = self.sidecar_fixture()
            mutate(data)
            with self.subTest(data=data), \
                    mock.patch.object(ci, "source_inventory", return_value=sources), \
                    mock.patch.object(ci, "_worker_pins", return_value=self.fake_wheels()):
                with self.assertRaises(ci.ValidationError):
                    ci._validate_math_sidecar(data, self.root, runtime)

    def test_math_sidecar_rejects_changed_source_wheel_and_python_archive(self):
        for path_name in ("source", "wheel", "python"):
            data, runtime, sources = self.sidecar_fixture()
            expected_sources = copy.deepcopy(sources)
            if path_name == "source":
                data["sources"]["files"][0]["sha256"] = "f" * 64
            elif path_name == "wheel":
                data["wheels"][0]["sha256"] = "f" * 64
            else:
                data["python"]["archive_sha256"] = "f" * 64
            with self.subTest(identity=path_name), \
                    mock.patch.object(ci, "source_inventory", return_value=expected_sources), \
                    mock.patch.object(ci, "_worker_pins", return_value=self.fake_wheels()):
                with self.assertRaises(ci.ValidationError):
                    ci._validate_math_sidecar(data, self.root, runtime)

    def _toolchain_report(self):
        vs = self.root / "vs2026"
        msvc = vs / "VC" / "Tools" / "MSVC" / "14.50.35717"
        cmake = (vs / "Common7" / "IDE" / "CommonExtensions" / "Microsoft"
                 / "CMake" / "CMake" / "bin" / "cmake.exe")
        sdk = self.root / "Program Files (x86)" / "Windows Kits" / "10" / "Include" / "10.0.28000.0"
        for directory in (msvc / "bin" / "Hostx64" / "x64", cmake.parent, sdk):
            directory.mkdir(parents=True, exist_ok=True)
        cmake.write_bytes(b"fixture CMake bytes; never executed")
        (msvc / "bin" / "Hostx64" / "x64" / "cl.exe").write_bytes(b"fixture compiler bytes; never executed")
        sdk_audit = {"source_id": "microsoft-official-windows-sdk-fwlink-2382519",
                     "download_host": "download.microsoft.com", "bytes": 123456,
                     "sha256": "a" * 64, "authenticode_status": "Valid",
                     "signer_subject": "CN=Microsoft Corporation, O=Microsoft Corporation",
                     "installer_file_version": "10.1.28000.2957", "installer_arguments": "/q /norestart",
                     "install_exit_code": 0, "installed_product_version": "10.1.28000.2957",
                     "include_version": "10.0.28000.0"}
        return {"schema_version": 1, "runner_label": "windows-2025-vs2026",
                "visual_studio_version": "18.11.0", "visual_studio_path": str(vs),
                "visual_studio_prerelease": False, "msvc_toolset_version": "14.50.35717",
                "msvc_toolset_path": str(msvc), "cmake_version": "4.4.3", "cmake_path": str(cmake),
                "cmake_version_output": "cmake version 4.4.3\n",
                "windows_sdk_version": "10.0.28000.0", "windows_sdk_product_version": "10.1.28000.2957",
                "sdk_installer": sdk_audit}, cmake

    def test_cmake_versions_accept_stable_plain_and_microsoft_suffix_only(self):
        accepted = {"4.3.1": (4, 3, 1), "4.3.1-msvc1": (4, 3, 1),
                    "4.4.3": (4, 4, 3), "4.4.3-msvc1": (4, 4, 3), "4.4.4-msvc12": (4, 4, 4)}
        for raw, numeric in accepted.items():
            with self.subTest(raw=raw):
                self.assertEqual(ci._parse_cmake_version(raw), numeric)
                output = ("cmake version " + raw + "\r\n\r\nCMake suite maintained and supported by Kitware (kitware.com/cmake).\r\n").encode("ascii")
                self.assertEqual(ci._cmake_version_from_output(output), raw)
        for raw in ("4.4.3-rc1", "4.5.0-alpha1", "4.5.0-beta1", "4.5.0-dev",
                    "4.5.0-msvc1-rc1", "4.4.3-msvc", "4.4.3-local", "4.4.3.1"):
            with self.subTest(rejected=raw), self.assertRaises(ci.ValidationError):
                ci._cmake_version_from_output("cmake version " + raw + "\n")

    def test_microsoft_cmake_suffix_preserves_provenance_without_relaxing_numeric_floor(self):
        report, cmake = self._toolchain_report()
        self.assertEqual(ci.MIN_CMAKE, (4, 3, 1))
        for raw, passes in (("4.3.1-msvc1", True), ("4.3.0-msvc99", False),
                            ("4.4.3", True), ("4.4.3-msvc1", True)):
            candidate = copy.deepcopy(report)
            candidate["cmake_version"] = raw
            candidate["cmake_version_output"] = "cmake version " + raw + "\n"
            completed = subprocess_completed([str(cmake), "--version"], 0,
                                              candidate["cmake_version_output"].encode("ascii"))
            with self.subTest(raw=raw), \
                    mock.patch.dict("os.environ", {"ProgramFiles(x86)": str(self.root / "Program Files (x86)")}), \
                    mock.patch.object(ci.subprocess, "run", return_value=completed):
                if passes:
                    self.assertIs(ci.validate_toolchain_report(candidate), candidate)
                    self.assertEqual(candidate["cmake_version"], raw)
                else:
                    with self.assertRaises(ci.ValidationError):
                        ci.validate_toolchain_report(candidate)

    def test_toolchain_report_versions_and_signed_sdk_evidence_are_strict(self):
        report, cmake = self._toolchain_report()
        completed = subprocess_completed([str(cmake), "--version"], 0, b"cmake version 4.4.3\n")
        with mock.patch.dict("os.environ", {"ProgramFiles(x86)": str(self.root / "Program Files (x86)")}), \
                mock.patch.object(ci.shutil, "which", return_value=str(cmake)), \
                mock.patch.object(ci.subprocess, "run", return_value=completed):
            self.assertIs(ci.validate_toolchain_report(report), report)
        for mutate in (
            lambda row: row.update(msvc_toolset_version="14.44.35207"),
            lambda row: row.update(windows_sdk_product_version="10.1.28000.2526"),
            lambda row: row["sdk_installer"].update(authenticode_status="NotSigned"),
            lambda row: row["sdk_installer"].update(signer_subject="Unknown Publisher"),
            lambda row: row["sdk_installer"].update(installer_arguments="/quiet"),
        ):
            bad = json.loads(json.dumps(report))
            mutate(bad)
            with mock.patch.dict("os.environ", {"ProgramFiles(x86)": str(self.root / "Program Files (x86)")}), \
                    mock.patch.object(ci.shutil, "which", return_value=str(cmake)), \
                    mock.patch.object(ci.subprocess, "run", return_value=completed):
                with self.assertRaises(ci.ValidationError):
                    ci.validate_toolchain_report(bad)

    def test_flutter_cmake_cache_proves_actual_generator_cmake_msvc_and_sdk(self):
        vs = self.root / "vs2026"
        msvc = vs / "VC" / "Tools" / "MSVC" / "14.50.35717"
        compiler = msvc / "bin" / "Hostx64" / "x64" / "cl.exe"
        cmake = (vs / "Common7" / "IDE" / "CommonExtensions" / "Microsoft"
                 / "CMake" / "CMake" / "bin" / "cmake.exe")
        for path in (compiler, cmake):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture executable bytes; never executed")
        build_root = self.root / "ui" / "build" / "windows" / "x64"
        build_root.mkdir(parents=True)
        cache = build_root / "CMakeCache.txt"
        cache.write_text("\n".join((
            "CHASTEADY_CMAKE_COMMAND:INTERNAL=" + str(cmake),
            "CHASTEADY_CMAKE_VERSION:INTERNAL=4.3.1-msvc1",
            "CHASTEADY_CMAKE_GENERATOR:INTERNAL=Visual Studio 18 2026",
            "CHASTEADY_CMAKE_GENERATOR_INSTANCE:INTERNAL=" + str(vs),
            "CHASTEADY_CMAKE_GENERATOR_PLATFORM:INTERNAL=x64",
            "CHASTEADY_CXX_COMPILER:INTERNAL=" + str(compiler),
            "CHASTEADY_CXX_COMPILER_VERSION:INTERNAL=19.50.35717",
            "CHASTEADY_WINDOWS_SDK_VERSION:INTERNAL=10.0.28000.0",
        )), encoding="utf-8")
        report = {"cmake_path": str(cmake), "cmake_version": "4.3.1-msvc1", "visual_studio_path": str(vs),
                  "msvc_toolset_path": str(msvc), "msvc_toolset_version": "14.50.35717",
                  "windows_sdk_version": "10.0.28000.0", "windows_sdk_product_version": "10.1.28000.2957"}
        completed = subprocess_completed([str(cmake), "--version"], 0, b"cmake version 4.3.1-msvc1\n")
        with mock.patch.object(ci.subprocess, "run", return_value=completed):
            result = ci.validate_flutter_windows_toolchain(build_root, report)
        self.assertEqual(result["generator"], "Visual Studio 18 2026")
        self.assertEqual(result["windows_sdk_include_version"], "10.0.28000.0")
        self.assertEqual(result["cmake_version"], "4.3.1-msvc1")
        self.assertEqual(result["cmake_configured_version"], "4.3.1-msvc1")
        report["cmake_version"] = "4.4.3-msvc1"
        vendor_output = b"cmake version 4.4.3-msvc1\r\n"
        completed = subprocess_completed([str(cmake), "--version"], 0, vendor_output)
        for configured in ("4.4.3", "4.4.3-msvc1"):
            content = cache.read_text(encoding="utf-8")
            content = __import__("re").sub(r"(?m)^CHASTEADY_CMAKE_VERSION:INTERNAL=.*$",
                                           "CHASTEADY_CMAKE_VERSION:INTERNAL=" + configured, content)
            cache.write_text(content, encoding="utf-8")
            with self.subTest(configured=configured), mock.patch.object(ci.subprocess, "run", return_value=completed):
                result = ci.validate_flutter_windows_toolchain(build_root, report)
            self.assertEqual(result["cmake_version"], "4.4.3-msvc1")
            self.assertEqual(result["cmake_configured_version"], configured)
            self.assertEqual(result["cmake_version_output"], vendor_output.decode("ascii"))
        cache.write_text(cache.read_text(encoding="utf-8").replace("Visual Studio 18 2026", "Visual Studio 17 2022"),
                         encoding="utf-8")
        with mock.patch.object(ci.subprocess, "run", return_value=completed):
            with self.assertRaises(ci.ValidationError):
                ci.validate_flutter_windows_toolchain(build_root, report)

    def test_run_build_copies_license_texts_before_build_status_reads_the_count(self):
        # Regress the actual run_build statement order without fabricating a
        # successful native build or executing compiler/PyInstaller fixtures.
        module = ast.parse(Path(ci.__file__).read_text(encoding="utf-8"))
        run_build = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                         and node.name == "run_build")
        assignments = [node for node in run_build.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "copied_license_texts"
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        assignment = assignments[0]
        self.assertIsInstance(assignment.value, ast.Call)
        self.assertEqual(assignment.value.func.id, "copy_license_texts")
        loads = [node for node in ast.walk(run_build) if isinstance(node, ast.Name)
                 and node.id == "copied_license_texts" and isinstance(node.ctx, ast.Load)]
        self.assertTrue(loads)
        self.assertTrue(all(node.lineno > assignment.lineno for node in loads))
        stages = {node.value.args[1].value: node.lineno for node in run_build.body
                  if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                  and isinstance(node.value.func, ast.Name) and node.value.func.id == "mark_ci_stage"}
        self.assertLess(stages["bundle_license_texts"], assignment.lineno)
        self.assertLess(assignment.lineno, stages["bundle_metadata"])
        self.assertLess(stages["bundle_metadata"], stages["bundle_legal_notices"])
        self.assertLess(stages["bundle_legal_notices"], stages["public_inventory"])
        inventory_calls = [node for node in ast.walk(run_build) if isinstance(node, ast.Call)
                           and isinstance(node.func, ast.Name) and node.func.id == "assert_public_bundle"]
        self.assertEqual(len(inventory_calls), 1)
        forwarded = next(keyword.value for keyword in inventory_calls[0].keywords
                         if keyword.arg == "runtime_report")
        self.assertIsInstance(forwarded, ast.Name)
        self.assertEqual(forwarded.id, "runtime_report")

    def test_windows_cmake_selects_sdk_before_project_and_records_actual_project_facts(self):
        source = (Path(ci.ROOT) / "ui" / "windows" / "CMakeLists.txt").read_text(encoding="utf-8")
        sdk_assignment = source.index('set(CMAKE_SYSTEM_VERSION "${_chasteady_ci_windows_sdk}"')
        project = source.index("project(cha_stabilizer_ui LANGUAGES CXX)")
        self.assertLess(sdk_assignment, project)
        self.assertIn("CI Windows SDK must be an audited four-part version", source)
        self.assertIn("CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION STREQUAL _chasteady_ci_windows_sdk", source)
        facts = {
            "CHASTEADY_CMAKE_COMMAND": "CMAKE_COMMAND",
            "CHASTEADY_CMAKE_VERSION": "CMAKE_VERSION",
            "CHASTEADY_CMAKE_GENERATOR": "CMAKE_GENERATOR",
            "CHASTEADY_CMAKE_GENERATOR_INSTANCE": "CMAKE_GENERATOR_INSTANCE",
            "CHASTEADY_CMAKE_GENERATOR_PLATFORM": "CMAKE_GENERATOR_PLATFORM",
            "CHASTEADY_CXX_COMPILER": "CMAKE_CXX_COMPILER",
            "CHASTEADY_CXX_COMPILER_VERSION": "CMAKE_CXX_COMPILER_VERSION",
            "CHASTEADY_WINDOWS_SDK_VERSION": "CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION",
        }
        for recorded, actual in facts.items():
            expression = 'set(' + recorded + ' "${' + actual + '}" CACHE INTERNAL '
            with self.subTest(recorded=recorded):
                self.assertGreater(source.index(expression), project)

        pubspec = (Path(ci.ROOT) / "ui/pubspec.yaml").read_text(encoding="utf-8")
        self.assertIn("        - asset: assets/fonts/NotoSansSC-wght.ttf", pubspec)
        self.assertIn('set(INSTALL_BUNDLE_DATA_DIR "${CMAKE_INSTALL_PREFIX}/data")', source)
        self.assertIn('set(FLUTTER_ASSET_DIR_NAME "flutter_assets")', source)
        self.assertIn('DESTINATION "${INSTALL_BUNDLE_DATA_DIR}" COMPONENT Runtime)', source)
        self.assertEqual(ci.BUNDLE_FONT_PATHS, {
            "data/flutter_assets/assets/fonts/NotoSansSC-wght.ttf",
            "web/assets/assets/fonts/NotoSansSC-wght.ttf",
        })

    def test_native_registrar_links_the_plugin_wrapper_implementation(self):
        runner = Path(ci.ROOT) / "ui" / "windows" / "runner"
        window = (runner / "flutter_window.cpp").read_text(encoding="utf-8")
        self.assertIn("PluginRegistrarManager::GetInstance()", window)
        self.assertIn("GetRegistrar<flutter::PluginRegistrarWindows>", window)
        cmake = (runner / "CMakeLists.txt").read_text(encoding="utf-8")
        commands = re.findall(r"target_link_libraries\(\$\{BINARY_NAME\}\s+PRIVATE\s+([^)]*)\)", cmake)
        libraries = {item for command in commands for item in command.split()}
        self.assertTrue({"flutter", "flutter_wrapper_app", "flutter_wrapper_plugin"}.issubset(libraries))

    def test_pyinstaller_manifest_handoff_binds_current_docs_file_without_mutating_env(self):
        manifest = self.root / "docs" / ".ci-worker-runtime-fixture.json"
        manifest.parent.mkdir()
        report = {"schema_version": 1, "status": "fixture-only-not-a-real-runtime"}
        manifest.write_text(json.dumps(report), encoding="utf-8")
        original_env = {"PATH": "trusted-runtime-path"}
        environment = ci.pyinstaller_manifest_environment(self.root, manifest, report, original_env)
        self.assertEqual(environment["CHASTEADY_WORKER_RUNTIME_MANIFEST"], str(manifest.resolve(strict=True)))
        self.assertEqual(environment["CHASTEADY_WORKER_RUNTIME_MANIFEST_SHA256"],
                         hashlib.sha256(manifest.read_bytes()).hexdigest())
        self.assertEqual(original_env, {"PATH": "trusted-runtime-path"})
        self.assertEqual(environment["PATH"], original_env["PATH"])

    def test_pyinstaller_manifest_handoff_rejects_stale_or_outside_docs_manifest(self):
        manifest = self.root / "docs" / ".ci-worker-runtime-fixture.json"
        manifest.parent.mkdir()
        report = {"status": "fixture-only"}
        manifest.write_text(json.dumps({"status": "modified-fixture"}), encoding="utf-8")
        with self.assertRaises(ci.ValidationError):
            ci.pyinstaller_manifest_environment(self.root, manifest, report, {})
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaises(ci.ValidationError):
            ci.pyinstaller_manifest_environment(self.root, outside, report, {})
        with self.assertRaises(ci.ValidationError):
            ci.pyinstaller_manifest_environment(self.root, Path("docs/relative.json"), report, {})

    def test_frozen_worker_inventory_verifier_checks_fixture_bytes_without_execution(self):
        worker = self.root / "Worker"
        worker.mkdir()
        payload = b"fixture only; never executed as an executable"
        (worker / "Worker.exe").write_bytes(payload)
        rows = [{"path": "Worker.exe", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}]
        report = {"freeze": {"status": "built_and_smoke_tested"},
                  "test_facts": {"frozen_worker": {"passed": True, "inventory": {"files": rows}}}}
        evidence = build_windows.verify_worker_inventory(worker, report)
        self.assertTrue(evidence["sha256_inventory_matches"])
        self.assertFalse(evidence["native_application_runtime_verified"])
        (worker / "Worker.exe").write_bytes(b"changed fixture")
        with self.assertRaises(RuntimeError):
            build_windows.verify_worker_inventory(worker, report)

    def test_public_bundle_requires_offline_font_and_license_and_rejects_private_content(self):
        app = self.root / "app-bundle"
        files = {
            "ChaSteady.exe": b"fixture executable; never executed",
            "flutter_windows.dll": b"fixture DLL; never loaded",
            "README.md": b"build-only",
            "BUILD_STATUS.json": b"{}",
            "LICENSE": b"MIT text",
            "THIRD_PARTY_NOTICES.md": b"notices",
            "web/index.html": b"<html></html>",
            "web/flutter_bootstrap.js": b"bootstrap",
            "web/assets/assets/fonts/NotoSansSC-wght.ttf": b"fixture font; never parsed or executed",
            "licenses/fonts/noto-sans-sc/OFL.txt": b"OFL fixture text",
            "Worker/Worker.exe": b"fixture worker; never executed",
            "data/icudtl.dat": b"fixture data",
            "data/flutter_assets/assets/fonts/NotoSansSC-wght.ttf": b"fixture font; never parsed or executed",
        }
        font_digest = hashlib.sha256(files["web/assets/assets/fonts/NotoSansSC-wght.ttf"]).hexdigest()
        license_digest = hashlib.sha256(files["licenses/fonts/noto-sans-sc/OFL.txt"]).hexdigest()
        for relative, payload in files.items():
            target = app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        with mock.patch.object(ci.ci_prepare_assets, "FONT_SHA256", font_digest), \
                mock.patch.object(ci.ci_prepare_assets, "FONT_LICENSE_SHA256", license_digest):
            rows = ci.assert_public_bundle(app, self.root)
            self.assertEqual(len(rows), len(files))
            for relative in ci.BUNDLE_FONT_PATHS:
                with self.subTest(missing_exact_font=relative):
                    target = app / relative
                    payload = target.read_bytes()
                    target.unlink()
                    # A same-basename font elsewhere must not satisfy either
                    # exact Web/native layout, even when its bytes are correct.
                    misplaced = app / "web/assets/fonts/NotoSansSC-wght.ttf"
                    misplaced.parent.mkdir(parents=True, exist_ok=True)
                    misplaced.write_bytes(payload)
                    with self.assertRaises(ci.ValidationError) as failure:
                        ci.assert_public_bundle(app, self.root)
                    self.assertIn("code=CI_BUNDLE_REQUIRED_FILES",
                                  ci.ci_failure_diagnostic(failure.exception, "public_inventory"))
                    misplaced.unlink()
                    target.write_bytes(payload)
            for relative in [*sorted(ci.BUNDLE_FONT_PATHS), "licenses/fonts/noto-sans-sc/OFL.txt"]:
                with self.subTest(altered_identity=relative):
                    target = app / relative
                    original = target.read_bytes()
                    target.write_bytes(b"altered fixture bytes")
                    with self.assertRaises(ci.ValidationError) as failure:
                        ci.assert_public_bundle(app, self.root)
                    self.assertIn("code=CI_BUNDLE_FONT_IDENTITY",
                                  ci.ci_failure_diagnostic(failure.exception, "public_inventory"))
                    target.write_bytes(original)
            (app / "private").mkdir()
            (app / "private" / "profile.txt").write_text("must not ship", encoding="utf-8")
            with self.assertRaises(ci.ValidationError):
                ci.assert_public_bundle(app, self.root)

    def test_all_public_inventory_fixed_guards_have_exact_safe_codes(self):
        module = ast.parse(Path(ci.__file__).read_text(encoding="utf-8"))
        function = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                        and node.name == "assert_public_bundle")
        guards = [node.exc for node in ast.walk(function) if isinstance(node, ast.Raise)
                  and isinstance(node.exc, ast.Call)]
        self.assertGreaterEqual(len(guards), 10)
        for guard in guards:
            self.assertIsInstance(guard.func, ast.Name)
            self.assertIn(guard.func.id, {"ValidationError", "_public_bundle_failure"})
            self.assertIsInstance(guard.args[0], ast.Constant)
            message = guard.args[0].value
            with self.subTest(message=message):
                self.assertIn(message, ci.SAFE_VALIDATION_CODES)
                diagnostic = ci.ci_failure_diagnostic(ci.ValidationError(message), "public_inventory")
                self.assertIn("code=CI_BUNDLE_", diagnostic)
                self.assertNotIn("CI_VALIDATION_FAILED", diagnostic)
                augmented = message + r" D:\PRIVATE\token.txt bearer=never-print"
                diagnostic = ci.ci_failure_diagnostic(ci.ValidationError(augmented), "public_inventory")
                self.assertIn("code=CI_VALIDATION_FAILED", diagnostic)
                self.assertNotIn("never-print", diagnostic)
                self.assertNotIn("D:\\PRIVATE", diagnostic)

    def test_inventory_failure_context_is_only_safe_category_and_full_relative_path_hash(self):
        message = "Staged public bundle contains a prohibited media/cache/log file"
        relative = "Worker/vendor-private-token/secret-cache.npz"
        error = ci._public_bundle_failure(message, relative)
        diagnostic = ci.ci_failure_diagnostic(error, "public_inventory")
        self.assertIn("category=worker relative_path_sha256=" + hashlib.sha256(relative.encode()).hexdigest(),
                      diagnostic)
        self.assertNotIn(relative, diagnostic)
        self.assertNotIn("vendor-private-token", diagnostic)
        self.assertNotIn("secret-cache", diagnostic)
        for context in ((relative, "a" * 64), ("worker", relative), ("worker", "A" * 64), ["worker", "a" * 64]):
            with self.subTest(context_type=type(context).__name__):
                error._ci_bundle_context = context
                diagnostic = ci.ci_failure_diagnostic(error, "public_inventory")
                self.assertNotIn("category=", diagnostic)
                self.assertNotIn("relative_path_sha256=", diagnostic)
                self.assertNotIn(relative, diagnostic)
        error = ci._public_bundle_failure(message, relative)
        self.assertNotIn("category=", ci.ci_failure_diagnostic(error, "bundle_metadata"))
        error = ci._public_bundle_failure("unknown vendor text " + relative, relative)
        diagnostic = ci.ci_failure_diagnostic(error, "public_inventory")
        self.assertIn("CI_VALIDATION_FAILED", diagnostic)
        self.assertNotIn("category=", diagnostic)
        self.assertNotIn(relative, diagnostic)

    @staticmethod
    def runtime_wheel_report_fixture():
        return {"packages": [dict(pin, sha256_published=pin["sha256"], yanked=False,
                                  latest_release_version=pin["version"], latest_release_metadata_checked=True)
                             for pin in provision_worker_runtime.WHEELS]}

    def test_sobol_resource_accepts_only_exact_fixture_bytes_and_audited_runtime_wheel(self):
        # Mock only the data-byte identity for this non-executed unit fixture.
        # Real wheel/Worker bytes are checked separately in the bounded local probe.
        payload = b"Sobol guard fixture; not an NPZ archive; never loaded"
        resource = copy.deepcopy(ci.SCIPY_SOBOL_RESOURCE)
        resource.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        app = self.root / "app"
        path = app / resource["bundle_path"]
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        runtime = self.runtime_wheel_report_fixture()
        with mock.patch.object(ci, "SCIPY_SOBOL_RESOURCE", resource):
            with self.assertRaises(ci.ValidationError) as failure:
                ci.assert_public_bundle(app, self.root, runtime_report=runtime)
        # Passing just this exact resource reaches (not bypasses) native presence.
        self.assertIn("code=CI_BUNDLE_REQUIRED_FILES",
                      ci.ci_failure_diagnostic(failure.exception, "public_inventory"))
        canonical = next(pin for pin in provision_worker_runtime.WHEELS if pin["name"] == "scipy")
        self.assertTrue(all(canonical[key] == value for key, value in resource["wheel"].items()))
        self.assertEqual(resource["bundle_path"], "Worker/" + resource["wheel_entry"])

    def test_sobol_resource_rejects_changed_bytes_or_missing_stale_and_changed_source_pins(self):
        payload = b"Sobol guard fixture; never loaded"
        resource = copy.deepcopy(ci.SCIPY_SOBOL_RESOURCE)
        resource.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        app = self.root / "app"
        path = app / resource["bundle_path"]
        path.parent.mkdir(parents=True)
        runtime = self.runtime_wheel_report_fixture()
        cases = [("missing_manifest", payload, None), ("missing_packages", payload, {}),
                 ("changed_size", payload + b"x", runtime),
                 ("changed_hash_same_size", b"X" + payload[1:], runtime)]
        for field, value in (("version", "0.0.0"), ("filename", "wrong-source.whl"),
                             ("sha256", "0" * 64), ("sha256_published", "0" * 64),
                             ("latest_release_metadata_checked", False)):
            changed = copy.deepcopy(runtime)
            record = next(row for row in changed["packages"] if row["name"] == "scipy")
            record[field] = value
            cases.append(("source_" + field, payload, changed))
        with mock.patch.object(ci, "SCIPY_SOBOL_RESOURCE", resource):
            for label, content, report in cases:
                with self.subTest(case=label):
                    path.write_bytes(content)
                    with self.assertRaises(ci.ValidationError) as failure:
                        ci.assert_public_bundle(app, self.root, runtime_report=report)
                    self.assertIn("code=CI_BUNDLE_VENDOR_RESOURCE_IDENTITY",
                                  ci.ci_failure_diagnostic(failure.exception, "public_inventory"))
            changed_pins = copy.deepcopy(provision_worker_runtime.WHEELS)
            next(row for row in changed_pins if row["name"] == "scipy")["sha256"] = "f" * 64
            with mock.patch.object(provision_worker_runtime, "WHEELS", changed_pins):
                path.write_bytes(payload)
                changed_report = self.runtime_wheel_report_fixture()
                with self.assertRaises(ci.ValidationError) as failure:
                    ci.assert_public_bundle(app, self.root, runtime_report=changed_report)
                self.assertIn("code=CI_BUNDLE_VENDOR_RESOURCE_IDENTITY",
                              ci.ci_failure_diagnostic(failure.exception, "public_inventory"))

    def test_sobol_resource_never_allows_other_npz_npy_or_private_profile_paths(self):
        payload = b"Sobol guard fixture; never loaded"
        resource = copy.deepcopy(ci.SCIPY_SOBOL_RESOURCE)
        resource.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        paths = ["Worker/scipy/stats/other.npz", "Worker/scipy/stats/_sobol_direction_numbers.npy",
                 "Worker/_internal/scipy/stats/_sobol_direction_numbers.npz",
                 "web/_sobol_direction_numbers.npz", "Worker/scipy/stats/_sobol_direction_numbers.NPZ",
                 "Worker/private/_sobol_direction_numbers.npz", "Worker/profile/_sobol_direction_numbers.npz"]
        with mock.patch.object(ci, "SCIPY_SOBOL_RESOURCE", resource):
            for index, relative in enumerate(paths):
                with self.subTest(case=index):
                    app = self.root / ("app-" + str(index))
                    path = app / relative
                    path.parent.mkdir(parents=True)
                    path.write_bytes(payload)
                    with self.assertRaises(ci.ValidationError) as failure:
                        ci.assert_public_bundle(app, self.root, runtime_report=self.runtime_wheel_report_fixture())
                    expected = "CI_BUNDLE_PRIVATE_COMPONENT" if "/private/" in relative or "/profile/" in relative \
                        else "CI_BUNDLE_FORBIDDEN_SUFFIX"
                    diagnostic = ci.ci_failure_diagnostic(failure.exception, "public_inventory")
                    self.assertIn("code=" + expected, diagnostic)
                    self.assertNotIn(relative, diagnostic)

    def test_license_copy_excludes_private_json_and_nonlicense_model_files(self):
        source = self.root / "docs" / "licenses"
        (source / "fonts" / "noto-sans-sc").mkdir(parents=True)
        (source / "python").mkdir()
        (source / "fonts" / "noto-sans-sc" / "OFL.txt").write_text("OFL text", encoding="utf-8")
        (source / "python" / "LICENSE.txt").write_text("license text", encoding="utf-8")
        dop_notice = b"SciPy DOP redistribution notice\n"
        (source / "python" / "LICENSE_DOP").write_bytes(dop_notice)
        (source / "collection-manifest.json").write_text(
            json.dumps({"local_path": r"D:\\PRIVATE\\audit.json"}), encoding="utf-8")
        (source / "haarcascade_license_plate.xml").write_bytes(b"model fixture, not a license")
        (source / "experiment.bin").write_bytes(b"not a license")
        destination = self.root / "app" / "licenses"
        destination.parent.mkdir()
        rows = ci.copy_license_texts(source, destination, self.root)
        names = {row["path"] for row in rows}
        self.assertEqual(names, {"fonts/noto-sans-sc/OFL.txt", "python/LICENSE.txt", "python/LICENSE_DOP"})
        self.assertEqual((destination / "python" / "LICENSE_DOP").read_bytes(), dop_notice)
        self.assertFalse((destination / "collection-manifest.json").exists())
        self.assertFalse((destination / "haarcascade_license_plate.xml").exists())

    def test_license_urls_are_copied_unchanged_and_reach_public_required_file_guard(self):
        source = self.root / "licenses"
        (source / "fonts" / "noto-sans-sc").mkdir(parents=True)
        (source / "fonts" / "noto-sans-sc" / "OFL.txt").write_bytes(b"OFL fixture text")
        # The first URL is the real public sky_engine notice's false-positive
        # context. Scheme suffixes must not be recognized as drive tokens.
        payload = (b"http://www.apache.org/licenses/\n"
                   b"https://example.invalid/license\n"
                   b"ftp://ftp.sgi.com/graphics/tiff/TIFF6.ps.gz\n")
        (source / "NOTICE.txt").write_bytes(payload)
        app = self.root / "app"
        app.mkdir()
        rows = ci.copy_license_texts(source, app / "licenses", self.root)
        self.assertEqual({row["path"] for row in rows}, {"NOTICE.txt", "fonts/noto-sans-sc/OFL.txt"})
        for row in rows:
            copied = (app / "licenses" / row["path"]).read_bytes()
            self.assertEqual(copied, (source / row["path"]).read_bytes())
            self.assertEqual(row["bytes"], len(copied))
            self.assertEqual(row["sha256"], hashlib.sha256(copied).hexdigest())
        ci._write_json_new(app / "BUILD_STATUS.json", {
            "scope": "license-helper-fixture-only", "native_compiled": False,
            "copied_license_text_count": len(rows), "runtime_acceptance_verified": False,
        })
        # Exercise the unmodified final scanner, not a bypass or a fake app.
        # Missing native files are expected after the text/privacy scan finishes.
        with self.assertRaises(ci.ValidationError) as failure:
            ci.assert_public_bundle(app, self.root)
        self.assertIn("code=CI_BUNDLE_REQUIRED_FILES stage=public_inventory",
                      ci.ci_failure_diagnostic(failure.exception, "public_inventory"))
        for label, marker in (("repo", str(self.root.resolve(strict=True))), ("home", str(Path.home()))):
            with self.subTest(marker=label):
                (app / "licenses" / "NOTICE.txt").write_bytes(payload + marker.encode("utf-8"))
                with self.assertRaises(ci.ValidationError) as failure:
                    ci.assert_public_bundle(app, self.root)
                diagnostic = ci.ci_failure_diagnostic(failure.exception, "public_inventory")
                self.assertIn("code=CI_BUNDLE_PATH_PRIVACY stage=public_inventory", diagnostic)
                self.assertNotIn(marker, diagnostic)

    def test_license_text_with_absolute_local_path_is_rejected(self):
        source = self.root / "licenses"
        (source / "fonts" / "noto-sans-sc").mkdir(parents=True)
        (source / "fonts" / "noto-sans-sc" / "OFL.txt").write_text("OFL", encoding="utf-8")
        cases = {
            "drive_backslash": r"Local path D:\PROJECT\PRIVATE",
            "drive_forward_slash": "Local path d:/project/private",
            "drive_at_start": r"R:\private\profile",
            "quoted_drive": r'Local path "Z:\private\profile"',
            "punctuated_drive": "Local path=(Q:/private)",
            "unc_backslash": r"Local path \\private-host\share\profile",
            "unc_forward_slash": r"Local path \\private-host/share/profile",
            "url_does_not_exempt_drive": "https://example.invalid/files/D:/private",
            "url_does_not_exempt_unc": r"https://example.invalid/#\\private-host\share",
            "nul": "License text\x00hidden content",
            # A preceding ASCII token defeats drive detection on Windows, so
            # the separate exact repo/home marker guards must still reject it.
            "repo_marker": "prefix" + str(self.root.resolve(strict=True)),
            "home_marker": "prefix" + str(Path.home()),
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                (source / "OFL.txt").write_text(text, encoding="utf-8")
                destination = self.root / ("out-" + label)
                with self.assertRaises(ci.ValidationError) as failure:
                    ci.copy_license_texts(source, destination, self.root)
                diagnostic = ci.ci_failure_diagnostic(failure.exception, "bundle_license_texts")
                self.assertIn("code=CI_LICENSE_PATH_PRIVACY stage=bundle_license_texts", diagnostic)
                self.assertNotIn("D:\\PROJECT", diagnostic)
                self.assertNotIn(str(self.root), diagnostic)
                self.assertNotIn(str(Path.home()), diagnostic)

    def test_zip_contains_only_explicit_application_stage_and_never_runs_fixture_exes(self):
        app = self.root / "app-stage"
        (app / "Worker").mkdir(parents=True)
        (app / "README.md").write_text("build-only", encoding="utf-8")
        (app / "Worker" / "Worker.exe").write_bytes(b"fixture only; never executed")
        outside = self.root / "outside.log"
        outside.write_text("not included", encoding="utf-8")
        archive = self.root / "package.zip"
        ci.write_zip(app, archive)
        with __import__("zipfile").ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            self.assertEqual(names, {"ChaSteady/README.md", "ChaSteady/Worker/Worker.exe"})
            self.assertNotIn("outside.log", names)
            self.assertEqual(bundle.read("ChaSteady/Worker/Worker.exe"), b"fixture only; never executed")

    def test_native_window_fixture_uses_audited_cmake_and_stays_outside_app_bundle(self):
        source = self.root / "ui"
        build_root = source / "build" / "windows" / "x64"
        executable = build_root / "native_smoke" / "Release" / "chasteady_window_chrome_smoke.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"fixture only; never executed")
        cmake = str(self.root / "audited-cmake.exe")
        report, args = {"cmake_path": cmake}, SimpleNamespace()
        with mock.patch.object(ci, "run_window_fixture_step") as run, \
                mock.patch.object(ci, "validate_flutter_windows_toolchain") as validate, \
                redirect_stdout(io.StringIO()):
            result = ci.run_native_window_fixture(args, source, {}, self.root, report)
        self.assertEqual(run.call_args_list, [
            mock.call("configure", [cmake, "-S", str(source / "windows"), "-B", str(build_root),
                      "-DCHASTEADY_BUILD_WINDOW_CHROME_SMOKE=ON"], source, {}, self.root, timeout=300),
            mock.call("build", [cmake, "--build", str(build_root), "--config", "Release",
                      "--target", "chasteady_window_chrome_smoke"], source, {}, self.root, timeout=600),
            mock.call("run", [str(executable)], source, {}, self.root, timeout=60),
        ])
        validate.assert_called_once_with(build_root, report)
        self.assertFalse(executable.is_relative_to(build_root / "runner" / "Release"))
        self.assertTrue(result["passed"])
        self.assertEqual(result["scope"], "owned_win32_window_chrome_fixture_only")
        for key in ("production_app_runtime_verified", "snap_flyout_verified", "multi_monitor_dpi_verified"):
            self.assertFalse(result[key])
        self.assertEqual(args._ci_stage, "native_fixture_run")

    def test_native_window_fixture_missing_output_is_not_executed(self):
        args = SimpleNamespace()
        with mock.patch.object(ci, "run_window_fixture_step") as run, \
                mock.patch.object(ci, "validate_flutter_windows_toolchain"), \
                redirect_stdout(io.StringIO()), self.assertRaises(ci.ValidationError) as failure:
            ci.run_native_window_fixture(args, self.root, {}, self.root,
                                         {"cmake_path": str(self.root / "audited-cmake.exe")})
        self.assertEqual([call.args[0] for call in run.call_args_list], ["configure", "build"])
        self.assertIn("CI_WINDOW_FIXTURE_OUTPUT", ci.ci_failure_diagnostic(failure.exception, args._ci_stage))

    def test_native_fixture_nonzero_exit_is_fixed_code_with_only_private_logs(self):
        for label in ("configure", "build", "run"):
            with self.subTest(label=label):
                logs = self.root / label
                logs.mkdir()
                registry = mock.Mock()
                registry.snapshot.return_value = []
                process = mock.Mock()
                process.wait.return_value = 1
                with mock.patch.object(ci, "OwnedProcessRegistry", return_value=registry), \
                        mock.patch.object(ci, "spawn_owned_process", return_value=process) as spawn, \
                        self.assertRaises(ci.ValidationError) as failure:
                    ci.run_window_fixture_step(label, ["fixture-never-executed"], self.root, {}, logs, 60)
                process.wait.assert_called_once_with(timeout=60)
                registry.discard.assert_called_once_with(process)
                self.assertEqual(spawn.call_args.args[0], ["fixture-never-executed"])
                self.assertTrue((logs / ("window-fixture-" + label + ".stdout.log")).is_file())
                diagnostic = ci.ci_failure_diagnostic(failure.exception, "native_fixture_" + label)
                self.assertIn("code=CI_WINDOW_FIXTURE_{}_EXIT".format(label.upper()), diagnostic)
                private = str(failure.exception) + r" D:\PRIVATE\session.json bearer=not-public"
                redacted = ci.ci_failure_diagnostic(ci.ValidationError(private), "native_fixture_" + label)
                self.assertIn("code=CI_VALIDATION_FAILED", redacted)
                self.assertNotIn("not-public", redacted)

    def test_ci_runs_analysis_and_tests_before_both_release_builds(self):
        args = SimpleNamespace()
        sdk, source, stage = (self.root / name for name in ("sdk", "ui", "stage"))
        toolchain, observed = {"fixture": "preflight"}, {"fixture": "actual"}
        output = io.StringIO()
        with mock.patch.object(ci, "run_flutter", return_value=b"") as run, \
                mock.patch.object(ci, "validate_flutter_windows_toolchain", return_value=observed) as validate, \
                redirect_stdout(output):
            actual, checks = ci.run_flutter_ui_build(args, sdk, source, {}, stage, toolchain)
        commands = build_windows.flutter_commands(build_only=False)
        self.assertEqual([label for label, _command in commands],
                         ["pub", "l10n", "analyze", "test", "windows", "web"])
        self.assertEqual(commands[2:4], [("analyze", ["analyze", "--no-pub"]),
                                        ("test", ["test", "--no-pub", "--reporter", "expanded"])])
        self.assertEqual(run.call_args_list, [
            mock.call(label, sdk, command, source, {}, stage,
                      timeout=3600 if label in ("windows", "web") else 1200)
            for label, command in commands
        ])
        validate.assert_called_once_with(source / "build" / "windows" / "x64", toolchain)
        self.assertEqual(actual, observed)
        self.assertEqual(checks, {"flutter_analyze_passed": True, "flutter_tests_passed": True})
        self.assertEqual(args._ci_stage, "flutter_web")
        self.assertLess(output.getvalue().index("stage=flutter_analyze"),
                        output.getvalue().index("stage=flutter_windows"))
        self.assertLess(output.getvalue().index("stage=flutter_test"),
                        output.getvalue().index("stage=flutter_windows"))

    def test_ci_ui_check_failure_stops_before_native_build_and_is_safely_reported(self):
        for failed_label in ("analyze", "test"):
            with self.subTest(label=failed_label):
                args = SimpleNamespace()
                def fail_check(label, *_args, **_kwargs):
                    if label == failed_label:
                        raise ci.ValidationError(
                            "Flutter {} exited unsuccessfully; raw runner-local logs are not uploaded".format(label))
                    return b""
                with mock.patch.object(ci, "run_flutter", side_effect=fail_check) as run, \
                        mock.patch.object(ci, "validate_flutter_windows_toolchain") as validate, \
                        redirect_stdout(io.StringIO()), self.assertRaises(ci.ValidationError) as failure:
                    ci.run_flutter_ui_build(args, self.root, self.root, {}, self.root, {})
                labels = [call.args[0] for call in run.call_args_list]
                self.assertEqual(labels[-1], failed_label)
                self.assertNotIn("windows", labels)
                validate.assert_not_called()
                self.assertIn("code=CI_FLUTTER_{}_EXIT stage=flutter_{}".format(
                    failed_label.upper(), failed_label), ci.ci_failure_diagnostic(failure.exception, args._ci_stage))
                private = str(failure.exception) + r" D:\PRIVATE\profile.json token=do-not-print"
                diagnostic = ci.ci_failure_diagnostic(ci.ValidationError(private), args._ci_stage)
                self.assertIn("code=CI_VALIDATION_FAILED", diagnostic)
                self.assertNotIn("do-not-print", diagnostic)

    def test_ci_does_not_accept_omitted_ui_checks_as_a_successful_build(self):
        commands = build_windows.flutter_commands(build_only=True)
        with mock.patch.object(build_windows, "flutter_commands", return_value=commands), \
                mock.patch.object(ci, "run_flutter", return_value=b""), \
                mock.patch.object(ci, "validate_flutter_windows_toolchain", return_value={"fixture": True}), \
                redirect_stdout(io.StringIO()), self.assertRaises(ci.ValidationError) as failure:
            ci.run_flutter_ui_build(SimpleNamespace(), self.root, self.root, {}, self.root, {})
        self.assertIn("CI_UI_CHECKS_MISSING", ci.ci_failure_diagnostic(failure.exception, "flutter_web"))

    def test_build_commands_keep_only_locked_l10n_and_release_builds(self):
        commands = build_windows.flutter_commands(build_only=True)
        self.assertEqual([label for label, _args in commands], ["pub", "l10n", "windows", "web"])
        self.assertEqual(commands[0][1], ["pub", "get", "--enforce-lockfile"])
        self.assertEqual(commands[2][1], ["build", "windows", "--release"])
        self.assertEqual(commands[3][1], ["build", "web", "--release", "--no-web-resources-cdn",
                                         "--pwa-strategy=none"])
        self.assertFalse(any(args[0] in ("analyze", "test", "run", "drive") for _, args in commands))

    def test_flutter_version_warms_with_plain_version_then_requires_strict_machine_identity(self):
        bootstrap = b"Resolving dependencies...\nDownloading packages...\nGot dependencies.\nFlutter version fixture\n"
        identity = {"frameworkVersion": "3.47.7", "channel": "stable", "dartSdkVersion": "3.13.5",
                    "frameworkRevision": "abaf9c523780a608bd46686fd5e53740a07077f8"}
        output = io.StringIO()
        with mock.patch.object(ci, "run_flutter", side_effect=[bootstrap, json.dumps(identity).encode("utf-8")]) as commands, \
                redirect_stdout(output):
            result = ci.flutter_version_check(self.root, self.root, {}, self.root)
        self.assertEqual(commands.call_args_list, [
            mock.call("bootstrap", self.root, ["--version"], self.root, {}, self.root, timeout=300),
            mock.call("version", self.root, ["--version", "--machine"], self.root, {}, self.root, timeout=300),
        ])
        self.assertEqual(result["flutter_version"], "3.47.7")
        self.assertNotIn("Resolving dependencies...", output.getvalue())
        with mock.patch.object(ci, "run_flutter", side_effect=ci.ValidationError(
                "Flutter bootstrap exited unsuccessfully; raw runner-local logs are not uploaded")) as commands, \
                redirect_stdout(io.StringIO()), self.assertRaises(ci.ValidationError) as failure:
            ci.flutter_version_check(self.root, self.root, {}, self.root)
        self.assertEqual(commands.call_count, 1)
        self.assertIn("CI_FLUTTER_BOOTSTRAP_EXIT", ci.ci_failure_diagnostic(failure.exception, "flutter_version"))

    def test_flutter_machine_version_accepts_only_the_expected_json_identity(self):
        info = {"frameworkVersion": "3.47.7", "channel": "stable", "dartSdkVersion": "3.13.5",
                "frameworkRevision": "abaf9c523780a608bd46686fd5e53740a07077f8",
                "flutterRoot": r"D:\fixture-private-sdk\flutter"}
        raw = (json.dumps(info, indent=2) + "\n").encode("utf-8")
        with mock.patch.object(ci, "run_flutter", return_value=raw):
            summary = ci.flutter_version_check(self.root, self.root, {}, self.root)
        self.assertEqual(summary, {"flutter_version": "3.47.7", "dart_version": "3.13.5",
                                   "framework_revision": info["frameworkRevision"]})
        self.assertNotIn(info["flutterRoot"], str(summary))
        info["channel"] = "beta"
        with mock.patch.object(ci, "run_flutter", return_value=json.dumps(info).encode("utf-8")), \
                self.assertRaises(ci.ValidationError) as failure:
            ci.flutter_version_check(self.root, self.root, {}, self.root)
        self.assertIn("CI_FLUTTER_VERSION_IDENTITY", ci.ci_failure_diagnostic(failure.exception, "flutter_version"))

    def test_flutter_machine_version_rejects_exact_notice_multiple_json_and_private_tail(self):
        info = {"frameworkVersion": "3.47.7", "channel": "stable", "dartSdkVersion": "3.13.5",
                "frameworkRevision": "abaf9c523780a608bd46686fd5e53740a07077f8",
                "flutterRoot": r"D:\fixture-private-sdk\flutter"}
        # The SDK 3.47.7 first-run notice reproduced in the private version-only
        # probes remains rejected. The official child-only NoOp switch prevents
        # it instead of loosening JSON parsing or accepting arbitrary trailers.
        notice = """The Flutter CLI developer tool uses Google Analytics to report usage and diagnostic
data along with package dependencies, and crash reporting to send basic crash
reports. This data is used to help improve the Dart platform, Flutter framework,
and related tools.

Telemetry is not sent on the very first run. To disable reporting of telemetry,
run this terminal command:

    flutter --disable-analytics

If you opt out of telemetry, an opt-out event will be sent, and then no further
information will be sent. This data is collected in accordance with the Google
Privacy Policy (https://policies.google.com/privacy).

"""
        private_tail = r"D:\fixture-private-sdk\profile.json bearer=not-for-logs"
        trailers = ("\n" + notice, "\r\n" + notice.replace("\n", "\r\n"),
                    "\n{}", "\n" + json.dumps(info), "\n" + private_tail)
        raw_json = json.dumps(info)
        outputs = [raw_json + trailer for trailer in trailers]
        outputs.extend(["Resolving dependencies...\nDownloading packages...\nGot dependencies.\n" + raw_json,
                        chr(0xFEFF) + raw_json])
        for output in outputs:
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(output_kind=output[:16]), \
                    mock.patch.object(ci, "run_flutter", return_value=output.encode("utf-8")), \
                    redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(ci.ValidationError) as failure:
                ci.flutter_version_check(self.root, self.root, {}, self.root)
            self.assertIn("CI_FLUTTER_VERSION_JSON", ci.ci_failure_diagnostic(failure.exception, "flutter_version"))
            self.assertNotIn(info["flutterRoot"], stdout.getvalue() + stderr.getvalue())
            self.assertNotIn("not-for-logs", stdout.getvalue() + stderr.getvalue())

    def test_flutter_child_environment_isolated_and_git_shim_narrow(self):
        stage = self.root / "stage"
        stage.mkdir()
        git = self.root / "git.exe"
        git.write_bytes(b"fixture runner git bytes; never executed")
        before = dict(__import__("os").environ)
        with mock.patch.object(ci.shutil, "which", return_value=str(git)):
            env = ci.create_flutter_environment({"PATH": "trusted-runner-path", "APPDATA": "real-profile"}, stage)
        self.assertEqual(__import__("os").environ.get("APPDATA"), before.get("APPDATA"))
        self.assertNotEqual(env["APPDATA"], "real-profile")
        self.assertTrue(env["GIT_CONFIG_NOSYSTEM"] == "1")
        self.assertEqual(env["FLUTTER_SUPPRESS_ANALYTICS"], "true")
        self.assertEqual(__import__("os").environ.get("FLUTTER_SUPPRESS_ANALYTICS"),
                         before.get("FLUTTER_SUPPRESS_ANALYTICS"))
        shim = Path(env["PATH"].split(__import__("os").pathsep, 1)[0]) / "$git.cmd"
        text = shim.read_text(encoding="ascii")
        self.assertIn('"%CHA_STEADY_GIT_EXE%" rev-parse HEAD', text)
        self.assertIn('if /I not "%~1"=="rev-parse" goto :deny', text)
        self.assertNotIn("--config", text)
        self.assertNotIn("checkout", text)


def subprocess_completed(args, returncode, stdout):
    return __import__("subprocess").CompletedProcess(args, returncode, stdout, b"")


if __name__ == "__main__":
    unittest.main(verbosity=2)
