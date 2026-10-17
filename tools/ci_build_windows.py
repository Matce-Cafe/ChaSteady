"""Build and inventory a public-safe Windows bundle in a manual CI run.

This CI-only path intentionally does not call ``freeze_worker.main``: that
canonical local command requires the private V9 golden inputs to be rerun. CI
instead reruns the complete backend unittest suite, validates the unsigned
local math-validation sidecar against the current source/runtime identities,
then reuses the existing runtime validation, source privacy, frozen protocol
smoke and inventory helpers around a normal PyInstaller build. It never reads
or packages private golden inputs, source media, logs, or a local prebuilt
Worker.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import threading
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / "worker"))

import build_windows  # noqa: E402
import ci_prepare_assets  # noqa: E402
import ci_provision_flutter  # noqa: E402
import freeze_worker  # noqa: E402
import provision_worker_runtime  # noqa: E402
from cha_stabilizer.owned_processes import (  # noqa: E402
    OwnedProcessRegistry,
    registry_scope,
    spawn_owned_process,
)


SIDECAR_NAME = re.compile(r"^worker_math_golden_summary_20261015_[0-9a-fA-F-]{32,36}\.json$")
SOURCE_CANONICALIZATION = "utf-8-lf-v1"
SOURCE_INVENTORY_PATHS = (
    "tools/freeze_worker.py",
    "tools/regress_v9.py",
    "tools/worker_desktop_entry.py",
)
SOURCE_GLOB = "worker/cha_stabilizer/**/*.py"
EXPECTED_CASE_IDS = ("case-01", "case-02", "case-03")
EXPECTED_THRESHOLDS = {"matrix_max_absolute_error": 1e-9,
                       "weight_max_absolute_error": 1e-10}
EXPECTED_RUNNER_LABEL = "windows-2025-vs2026"
MIN_VISUAL_STUDIO = (18, 11, 0)
MIN_MSVC = (14, 50)
# Stable VS 18.11 official bundle baseline, not standalone upstream latest.
MIN_CMAKE = (4, 3, 1)
MIN_WINDOWS_SDK = (10, 0, 28000, 0)
MIN_WINDOWS_SDK_PRODUCT = (10, 1, 28000, 2957)
MIN_WINDOWS_SDK_INSTALLER_SERVICING = (10, 0, 28000, 2957)
FORBIDDEN_BUNDLE_SUFFIXES = {
    ".mp4", ".mov", ".mxf", ".m4v", ".mkv", ".avi", ".wmv", ".flv",
    ".webm", ".mpg", ".mpeg", ".wav", ".mp3", ".m4a", ".aac", ".dmp",
    ".npz", ".npy", ".prof", ".pstats", ".log", ".pickle", ".pkl",
}
FORBIDDEN_BUNDLE_COMPONENTS = {"private", ".git", ".dart_tool", ".cache", "profiles", "profile"}
BUNDLE_FONT_PATHS = frozenset({
    "data/flutter_assets/assets/fonts/NotoSansSC-wght.ttf",
    "web/assets/assets/fonts/NotoSansSC-wght.ttf",
})
# Reviewed dependency data, not an alternative runtime lock. Its exact source
# identity must still match the canonical provisioner and the validated runtime
# manifest. Any SciPy wheel update requires a fresh audit of this single entry.
SCIPY_SOBOL_RESOURCE = {
    "bundle_path": "Worker/scipy/stats/_sobol_direction_numbers.npz",
    "wheel_entry": "scipy/stats/_sobol_direction_numbers.npz",
    "wheel": {
        "name": "scipy", "version": "1.18.1",
        "filename": "scipy-1.18.1-cp315-cp315-win_amd64.whl",
        "sha256": "92c14f5bdbfb6216315ce33e78080474082de8b3830122ba97809bfbe65f75c0",
    },
    "bytes": 589334,
    "sha256": "4859931147d42ce465b8605cb277f957d98b839d03194fdf06579357906d193b",
}
GIT_SHIM_TEXT = (
    "@echo off\r\n"
    "setlocal EnableExtensions DisableDelayedExpansion\r\n"
    'if /I not "%~1"=="rev-parse" goto :deny\r\n'
    'if /I not "%~2"=="HEAD" goto :deny\r\n'
    'if not "%~3"=="" goto :deny\r\n'
    'if not defined CHA_STEADY_GIT_EXE goto :deny\r\n'
    '"%CHA_STEADY_GIT_EXE%" rev-parse HEAD\r\n'
    'exit /b %ERRORLEVEL%\r\n'
    ':deny\r\n'
    'exit /b 87\r\n'
)


class ValidationError(RuntimeError):
    pass


CI_STAGES = frozenset({
    "checkout", "toolchain_report", "flutter_report", "font_report", "worker_report",
    "stage_ui", "flutter_environment", "flutter_version", "flutter_pub", "flutter_l10n",
    "flutter_analyze", "flutter_test", "flutter_windows", "native_toolchain", "flutter_web",
    "native_outputs", "native_fixture_configure", "native_fixture_build", "native_fixture_run",
    "worker_runtime",
    "local_math_identity", "stage_app", "worker_build_and_smoke", "worker_inventory",
    "bundle_license_texts", "bundle_metadata", "bundle_legal_notices", "public_inventory",
    "artifact_zip", "artifact_manifest", "flutter_preflight_result",
})
# Exact messages authored in this file only. Never print arbitrary exception
# strings, a prefix-matched vendor log line, argv, paths, or protocol output.
SAFE_VALIDATION_CODES = {
    "Build root differs from the repository containing this trusted CI helper": "CI_CHECKOUT_ROOT",
    "A complete Git checkout is required for the trusted runner build": "CI_CHECKOUT_MISSING",
    "A required regular JSON file is missing or outside its size bound": "CI_INPUT_JSON_FILE",
    "A required JSON file is not valid UTF-8 JSON": "CI_INPUT_JSON_FORMAT",
    "JSON contains a duplicate object key": "CI_INPUT_JSON_DUPLICATE",
    "JSON contains a non-finite numeric value": "CI_INPUT_JSON_NONFINITE",
    "Runner toolchain report has missing or unknown fields": "CI_TOOLCHAIN_SCHEMA",
    "Runner label or preflight schema is not approved": "CI_RUNNER_IDENTITY",
    "Windows SDK installer version is not a stable numeric version": "CI_SDK_INSTALLER_VERSION_FORMAT",
    "Windows SDK official installer evidence does not meet the audited target contract": "CI_SDK_INSTALLER_IDENTITY",
    "CMake executable raw version differs from the runner preflight report": "CI_CMAKE_EXECUTABLE_IDENTITY",
    "Flutter provisioning report has missing or unknown fields": "CI_FLUTTER_REPORT_SCHEMA",
    "Flutter provisioning report differs from the pinned official stable archive": "CI_FLUTTER_ARCHIVE_IDENTITY",
    "Flutter SDK paths escaped their isolated download/extraction roots": "CI_FLUTTER_REPORT_PATHS",
    "Flutter preflight stage overlaps SDK or source files": "CI_FLUTTER_PREFLIGHT_STAGE",
    "CI output directory must be new and non-reparse": "CI_STAGE_OUTPUT_NOT_NEW",
    "Pinned font acquisition report has missing or unknown fields": "CI_FONT_REPORT_SCHEMA",
    "Pinned font content changed after acquisition": "CI_FONT_CONTENT_IDENTITY",
    "Noto Sans SC provenance or OFL license failed its pinned identity": "CI_FONT_LICENSE_IDENTITY",
    "The binary Noto font must not be committed in the public source checkout": "CI_FONT_IN_SOURCE",
    "Locked Flutter UI dependency graph is required": "CI_UI_LOCKFILE_MISSING",
    "Required Flutter UI analysis or tests did not execute": "CI_UI_CHECKS_MISSING",
    "Windows fixture output is missing or is not a regular file": "CI_WINDOW_FIXTURE_OUTPUT",
    "A runner-provided Git executable is required for the audited Flutter shim": "CI_FLUTTER_GIT_MISSING",
    "Pinned Flutter SDK did not return its machine-readable version": "CI_FLUTTER_VERSION_JSON",
    "Executed Flutter/Dart versions differ from the pinned stable SDK": "CI_FLUTTER_VERSION_IDENTITY",
    "Math sidecar worker/math source hashes differ from the current checkout": "CI_MATH_SOURCE_IDENTITY",
    "License source must be regular and destination must be new": "CI_LICENSE_TREE_INPUT",
    "License tree contains a reparse point": "CI_LICENSE_REPARSE",
    "A license text exceeds the configured public-copy size bound": "CI_LICENSE_SIZE",
    "A selected license notice is not UTF-8 text": "CI_LICENSE_UTF8",
    "A selected license notice contains a machine-specific path": "CI_LICENSE_PATH_PRIVACY",
    "License copy target is not a new regular file": "CI_LICENSE_COPY_TARGET",
    "Selected license texts omit the exact Noto Sans SC OFL notice": "CI_LICENSE_NOTO_NOTICE",
    "Application metadata source or target is not a new regular file": "CI_METADATA_FILE",
    "Staged app bundle is not a regular directory": "CI_BUNDLE_ROOT",
    "Staged public bundle contains a reparse point": "CI_BUNDLE_REPARSE",
    "Staged public bundle contains a private/profile/cache path": "CI_BUNDLE_PRIVATE_COMPONENT",
    "Staged public bundle contains a prohibited media/cache/log file": "CI_BUNDLE_FORBIDDEN_SUFFIX",
    "Audited vendor runtime resource failed its exact source or content identity": "CI_BUNDLE_VENDOR_RESOURCE_IDENTITY",
    "A staged file contains a local build-root or profile path": "CI_BUNDLE_PATH_PRIVACY",
    "Staged app bundle is missing a required native, Worker, web, README or license file": "CI_BUNDLE_REQUIRED_FILES",
    "Staged app bundle lacks Flutter data assets": "CI_BUNDLE_FLUTTER_DATA",
    "Staged app bundle lacks copied third-party license notices": "CI_BUNDLE_LICENSES",
    "Public app bundle font or corresponding OFL license differs from its pinned identity": "CI_BUNDLE_FONT_IDENTITY",
    "Staged app bundle has duplicate relative file names": "CI_BUNDLE_DUPLICATE_PATH",
}
for _flutter_stage in ("bootstrap", "version", "pub", "l10n", "analyze", "test", "windows", "web"):
    SAFE_VALIDATION_CODES[
        "Flutter {} exited unsuccessfully; raw runner-local logs are not uploaded".format(_flutter_stage)
    ] = "CI_FLUTTER_{}_EXIT".format(_flutter_stage.upper())
for _fixture_stage in ("configure", "build", "run"):
    SAFE_VALIDATION_CODES[
        "Windows fixture {} exited unsuccessfully; raw runner-local logs are not uploaded".format(_fixture_stage)
    ] = "CI_WINDOW_FIXTURE_{}_EXIT".format(_fixture_stage.upper())


def mark_ci_stage(args, stage: str) -> None:
    if stage not in CI_STAGES:
        raise ValueError("Unknown internal CI stage")
    args._ci_stage = stage
    print("ChaSteady CI stage=" + stage + " started", flush=True)


def ci_failure_diagnostic(error: Exception, stage) -> str:
    safe_stage = stage if type(stage) is str and stage in CI_STAGES else "unknown"
    message = error.args[0] if type(error) is ValidationError and len(error.args) == 1 else None
    code = SAFE_VALIDATION_CODES.get(message) if type(message) is str else None
    if code is not None:
        detail = message
    elif isinstance(error, ValidationError):
        code, detail = "CI_VALIDATION_FAILED", "A validation guard rejected this stage."
    else:
        code, detail = "CI_INTERNAL_FAILED", "An internal operation failed in this stage."
    context_text = ""
    context = getattr(error, "_ci_bundle_context", None) if type(error) is ValidationError else None
    if (safe_stage == "public_inventory" and code.startswith("CI_BUNDLE_")
            and type(context) is tuple and len(context) == 2
            and type(context[0]) is str and context[0] in {
                "worker", "web", "flutter_data", "licenses", "metadata", "native", "other"}
            and type(context[1]) is str and re.fullmatch(r"[0-9a-f]{64}", context[1])):
        context_text = " category=" + context[0] + " relative_path_sha256=" + context[1]
    return ("ChaSteady CI build failed code=" + code + " stage=" + safe_stage + context_text + ": " + detail
            + " Raw runner-local diagnostics were not uploaded.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def is_reparse(path: Path) -> bool:
    return ci_provision_flutter.is_reparse(path)


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON contains a duplicate object key")
        result[key] = value
    return result


def read_json(path: Path, max_bytes: int = 1024 * 1024) -> dict:
    if not path.is_file() or is_reparse(path) or path.stat().st_size > max_bytes:
        raise ValidationError("A required regular JSON file is missing or outside its size bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys,
                           parse_constant=lambda _value: (_ for _ in ()).throw(
                               ValidationError("JSON contains a non-finite numeric value")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError("A required JSON file is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValidationError("A required JSON document must be an object")
    return value


def exact_keys(value: dict, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValidationError(label + " has missing or unknown fields")


def _validate_hex_digest(value, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValidationError(label + " must be a lowercase SHA-256")
    return value


def _source_paths(root: Path) -> list[Path]:
    paths = [path for path in root.glob(SOURCE_GLOB) if path.is_file()]
    paths.extend(root / relative for relative in SOURCE_INVENTORY_PATHS)
    unique = {}
    for path in paths:
        if not path.is_file() or is_reparse(path):
            raise ValidationError("A required worker/math source file is missing or linked")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve(strict=True)):
            raise ValidationError("A worker/math source path escaped the project root")
        relative = path.relative_to(root).as_posix()
        unique[relative] = path
    return [unique[name] for name in sorted(unique)]


def canonical_source_sha256(path: Path) -> str:
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeError as error:
        raise ValidationError("Worker/math source is not canonical UTF-8 text") from error
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def source_inventory(root: Path) -> dict:
    rows = [{"path": path.relative_to(root).as_posix(), "sha256": canonical_source_sha256(path)}
            for path in _source_paths(root)]
    encoded = ("\n".join(row["path"] + ":" + row["sha256"] for row in rows) + "\n").encode("utf-8")
    return {"canonicalization": SOURCE_CANONICALIZATION,
            "inventory_sha256": hashlib.sha256(encoded).hexdigest(), "files": rows}


def _parse_version(value, label: str, parts: int | None = None) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){1,3}", value):
        raise ValidationError(label + " is not a stable numeric version")
    numbers = tuple(int(part) for part in value.split("."))
    if parts is not None and len(numbers) < parts:
        numbers += (0,) * (parts - len(numbers))
    return numbers


def _parse_cmake_version(value, label: str = "CMake version") -> tuple[int, ...]:
    if not isinstance(value, str):
        raise ValidationError(label + " must be a stable version string")
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:-msvc[0-9]+)?", value)
    if not match:
        raise ValidationError(label + " is not a stable plain or Microsoft -msvcN version")
    return _parse_version(match.group(1), label, 3)


def _cmake_version_from_output(output: bytes | str) -> str:
    try:
        text = output.decode("utf-8") if isinstance(output, bytes) else output
    except UnicodeError as error:
        raise ValidationError("CMake version output is not UTF-8") from error
    if not isinstance(text, str):
        raise ValidationError("CMake version output must be text")
    matches = re.findall(r"(?m)^cmake version ([^\r\n]+)\r?$", text)
    if len(matches) != 1:
        raise ValidationError("CMake output must contain exactly one version line")
    raw_version = matches[0].strip()
    _parse_cmake_version(raw_version)
    return raw_version


def _at_least(found: tuple[int, ...], required: tuple[int, ...]) -> bool:
    length = max(len(found), len(required))
    return found + (0,) * (length - len(found)) >= required + (0,) * (length - len(required))


def validate_toolchain_report(report: dict) -> dict:
    expected = {"schema_version", "runner_label", "visual_studio_version", "visual_studio_path",
                "visual_studio_prerelease", "msvc_toolset_version", "msvc_toolset_path",
                "cmake_version", "cmake_version_output", "cmake_path", "windows_sdk_version",
                "windows_sdk_product_version", "sdk_installer"}
    exact_keys(report, expected, "Runner toolchain report")
    if report["schema_version"] != 1 or report["runner_label"] != EXPECTED_RUNNER_LABEL:
        raise ValidationError("Runner label or preflight schema is not approved")
    if report["visual_studio_prerelease"] is not False:
        raise ValidationError("Preview Visual Studio instances are not accepted")
    versions = {
        "visual_studio_version": (MIN_VISUAL_STUDIO, 3),
        "msvc_toolset_version": (MIN_MSVC, 2),
        "cmake_version": (MIN_CMAKE, 3),
        "windows_sdk_version": (MIN_WINDOWS_SDK, 4),
        "windows_sdk_product_version": (MIN_WINDOWS_SDK_PRODUCT, 4),
    }
    for field, (minimum, parts) in versions.items():
        found = (_parse_cmake_version(report[field], field) if field == "cmake_version"
                 else _parse_version(report[field], field, parts))
        if not _at_least(found, minimum):
            raise ValidationError(field + " is older than the required stable toolchain floor")
    if _cmake_version_from_output(report["cmake_version_output"]) != report["cmake_version"]:
        raise ValidationError("Preserved CMake output differs from its reported raw version")
    sdk_installer = report["sdk_installer"]
    exact_keys(sdk_installer, {"source_id", "download_host", "bytes", "sha256", "authenticode_status",
                               "signer_subject", "installer_file_version", "installer_arguments",
                               "install_exit_code", "installed_product_version", "include_version"},
               "Windows SDK installer audit")
    if (sdk_installer["source_id"] != "microsoft-official-windows-sdk-fwlink-2382519"
            or sdk_installer["download_host"] != "download.microsoft.com"
            or type(sdk_installer["bytes"]) is not int or not 0 < sdk_installer["bytes"] <= 1024 ** 3
            or sdk_installer["authenticode_status"] != "Valid"
            or not isinstance(sdk_installer["signer_subject"], str)
            or "Microsoft Corporation" not in sdk_installer["signer_subject"]
            or sdk_installer["installer_arguments"] != "/q /norestart"
            or sdk_installer["install_exit_code"] != 0
            or sdk_installer["installed_product_version"] != report["windows_sdk_product_version"]
            or sdk_installer["include_version"] != report["windows_sdk_version"]
            or report["windows_sdk_version"] != "10.0.28000.0"):
        raise ValidationError("Windows SDK official installer evidence does not meet the audited target contract")
    _validate_hex_digest(sdk_installer["sha256"], "Windows SDK installer SHA-256")
    if not _at_least(_parse_version(sdk_installer["installer_file_version"], "SDK installer version", 4),
                     MIN_WINDOWS_SDK_INSTALLER_SERVICING):
        raise ValidationError("Signed Windows SDK installer version is older than servicing revision 2957")
    vs_path = Path(report["visual_studio_path"])
    msvc_path = Path(report["msvc_toolset_path"])
    if (not vs_path.is_absolute() or is_reparse(vs_path) or not vs_path.is_dir()
            or not msvc_path.is_absolute() or is_reparse(msvc_path) or not msvc_path.is_dir()):
        raise ValidationError("Runner toolchain path is not a regular installed directory")
    expected_msvc_parent = (vs_path / "VC" / "Tools" / "MSVC").resolve(strict=True)
    if (not msvc_path.resolve(strict=True).is_relative_to(expected_msvc_parent)
            or msvc_path.name != report["msvc_toolset_version"]):
        raise ValidationError("Selected MSVC toolset is not part of the selected Visual Studio instance")
    expected_cmake = (vs_path / "Common7" / "IDE" / "CommonExtensions" / "Microsoft"
                      / "CMake" / "CMake" / "bin" / "cmake.exe")
    reported_cmake = Path(report["cmake_path"])
    if (not reported_cmake.is_absolute() or is_reparse(reported_cmake) or not reported_cmake.is_file()
            or os.path.normcase(os.path.abspath(expected_cmake))
            != os.path.normcase(os.path.abspath(reported_cmake))):
        raise ValidationError("Preflight CMake is not the executable bundled with Flutter's selected Visual Studio instance")
    cmake_result = subprocess.run([str(reported_cmake), "--version"], check=False, capture_output=True, timeout=30)
    if (cmake_result.returncode != 0
            or _cmake_version_from_output(cmake_result.stdout) != report["cmake_version"]):
        raise ValidationError("CMake executable raw version differs from the runner preflight report")
    kits_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "Include"
    sdk_path = kits_root / report["windows_sdk_version"]
    if not sdk_path.is_dir() or is_reparse(sdk_path):
        raise ValidationError("Reported Windows SDK version is not installed in the official Windows Kits tree")
    return report


def _worker_pins(runtime_report: dict) -> list[dict]:
    expected_pins = provision_worker_runtime.WHEELS
    records = runtime_report.get("packages")
    if not isinstance(records, list):
        raise ValidationError("Worker runtime manifest has no package list")
    by_name = {row.get("name"): row for row in records if isinstance(row, dict)}
    if len(by_name) != len(records) or set(by_name) != {row["name"] for row in expected_pins}:
        raise ValidationError("Worker runtime manifest does not contain the complete pinned wheel set")
    result = []
    for pin in expected_pins:
        record = by_name[pin["name"]]
        if (record.get("version") != pin["version"] or record.get("filename") != pin["filename"]
                or record.get("sha256") != pin["sha256"] or record.get("sha256_published") != pin["sha256"]
                or record.get("yanked") is not False
                or record.get("latest_release_version") != pin["version"]
                or record.get("latest_release_metadata_checked") is not True):
            raise ValidationError("Worker runtime wheel is not the current exact non-yanked official pin")
        result.append({"name": pin["name"], "version": pin["version"], "filename": pin["filename"],
                       "sha256": pin["sha256"], "latest_release_verified": True})
    return sorted(result, key=lambda row: row["name"])


def _valid_relative_source(path: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        return False
    relative = PurePosixPath(path)
    return (not relative.is_absolute() and relative.as_posix() == path and bool(relative.parts)
            and all(part not in ("", ".", "..") and ":" not in part for part in relative.parts))


def _validate_math_sidecar(data: dict, root: Path, runtime_report: dict) -> dict:
    exact_keys(data, {"schema_version", "kind", "scope", "local_validation_origin", "python", "wheels",
                      "sources", "backend_tests", "thresholds", "cases", "provenance"},
               "Math-validation sidecar")
    if data["schema_version"] != 1 or data["kind"] != "local-worker-math-golden-summary":
        raise ValidationError("Math sidecar kind or schema version is not supported")
    if (data["scope"] != "three-case V9 mathematical golden comparison only; no media render, perceptual validation, or CI run"
            or data["local_validation_origin"] != "local-windows-x64-cpython-3.15.0-verified-wheel-freeze"):
        raise ValidationError("Math sidecar is not explicitly identified as the expected local Windows x64 canonical validation")

    python = data["python"]
    exact_keys(python, {"version", "archive_sha256"}, "Math sidecar Python identity")
    python_record = runtime_report.get("python", {})
    archive_sha = _validate_hex_digest(python["archive_sha256"], "Math sidecar Python archive digest")
    if (python["version"] != provision_worker_runtime.PYTHON_VERSION
            or archive_sha != python_record.get("published_sha256")
            or archive_sha != python_record.get("download", {}).get("sha256")):
        raise ValidationError("Math sidecar Python archive identity differs from the freshly verified runtime")

    sidecar_wheels = data["wheels"]
    if not isinstance(sidecar_wheels, list):
        raise ValidationError("Math sidecar wheel identities must be a list")
    normalized_wheels = []
    for row in sidecar_wheels:
        exact_keys(row, {"name", "version", "filename", "sha256", "latest_release_verified"},
                   "Math sidecar wheel identity")
        if row["latest_release_verified"] is not True:
            raise ValidationError("Math sidecar wheel is not marked latest-release verified")
        normalized_wheels.append({"name": row["name"], "version": row["version"],
                                  "filename": row["filename"],
                                  "sha256": _validate_hex_digest(row["sha256"], "Math sidecar wheel digest"),
                                  "latest_release_verified": True})
    normalized_wheels.sort(key=lambda row: row["name"])
    if normalized_wheels != _worker_pins(runtime_report):
        raise ValidationError("Math sidecar wheel identities differ from the verified runtime pins")

    sources = data["sources"]
    exact_keys(sources, {"canonicalization", "inventory_sha256", "files"}, "Math sidecar source identity")
    if sources["canonicalization"] != SOURCE_CANONICALIZATION or not isinstance(sources["files"], list):
        raise ValidationError("Math sidecar source canonicalization is not supported")
    rows = []
    for row in sources["files"]:
        exact_keys(row, {"path", "sha256"}, "Math sidecar source row")
        if not _valid_relative_source(row["path"]):
            raise ValidationError("Math sidecar source path is not a safe project-relative path")
        rows.append({"path": row["path"], "sha256": _validate_hex_digest(row["sha256"], "Source digest")})
    expected_sources = source_inventory(root)
    if rows != expected_sources["files"] or sources["inventory_sha256"] != expected_sources["inventory_sha256"]:
        raise ValidationError("Math sidecar worker/math source hashes differ from the current checkout")

    backend = data["backend_tests"]
    exact_keys(backend, {"passed", "minimum_expected_test_count", "test_count",
                         "executed_test_count", "skipped_count"},
               "Math sidecar backend-test identity")
    counts = [backend[name] for name in
              ("minimum_expected_test_count", "test_count", "executed_test_count", "skipped_count")]
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValidationError("Math sidecar backend-test counts must be nonnegative integers")
    if (backend["passed"] is not True or backend["minimum_expected_test_count"] < 127
            or backend["test_count"] < backend["minimum_expected_test_count"]
            or backend["executed_test_count"] + backend["skipped_count"] != backend["test_count"]):
        raise ValidationError("Math sidecar does not record a complete internally consistent canonical backend test run")

    thresholds = data["thresholds"]
    exact_keys(thresholds, set(EXPECTED_THRESHOLDS), "Math sidecar thresholds")
    for name, expected in EXPECTED_THRESHOLDS.items():
        value = thresholds[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != expected:
            raise ValidationError("Math sidecar checker thresholds differ from the canonical V9 values")

    cases = data["cases"]
    if not isinstance(cases, list) or len(cases) != len(EXPECTED_CASE_IDS):
        raise ValidationError("Math sidecar must contain exactly three anonymous golden cases")
    observed_ids = []
    for case in cases:
        exact_keys(case, {"case_id", "checker_passed", "matrix_max_absolute_error", "weight_max_absolute_error"},
                   "Math sidecar golden case")
        observed_ids.append(case["case_id"])
        if case["checker_passed"] is not True:
            raise ValidationError("A local golden case did not pass its original canonical checker")
        for name, threshold in EXPECTED_THRESHOLDS.items():
            value = case[name]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    or value < 0 or value > threshold):
                raise ValidationError("A measured local golden error exceeds its original canonical checker")
    if observed_ids != list(EXPECTED_CASE_IDS):
        raise ValidationError("Math sidecar anonymous golden case IDs or ordering are invalid")

    provenance = data["provenance"]
    exact_keys(provenance, {"local_only", "signed", "input_paths_included", "inputs_included",
                            "absolute_paths_included", "raw_media_or_cache_included", "ci_reproduction_claim"},
               "Math sidecar privacy and authenticity scope")
    if (provenance["local_only"] is not True or provenance["signed"] is not False
            or provenance["input_paths_included"] is not False or provenance["inputs_included"] is not False
            or provenance["absolute_paths_included"] is not False
            or provenance["raw_media_or_cache_included"] is not False
            or provenance["ci_reproduction_claim"] is not False):
        raise ValidationError("Math sidecar must be unsigned/local-only with no paths, data or CI-reproduction claim")
    return {"local_validation_origin": data["local_validation_origin"], "scope": data["scope"],
            "sidecar_sha256": None, "case_count": 3, "original_checker_passed": True,
            "worker_source_inventory_sha256": expected_sources["inventory_sha256"],
            "python_archive_sha256": archive_sha,
            "wheels": normalized_wheels,
            "private_goldens_rerun_in_ci": False,
            "authenticity_scope": "unsigned local evidence bound by content hashes; not cryptographic attestation"}


def validate_math_sidecar(path: Path, root: Path, runtime_report: dict) -> dict:
    if not SIDECAR_NAME.fullmatch(path.name):
        raise ValidationError("Math sidecar filename does not match the approved dated UUID name")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to((root / "docs").resolve(strict=True)):
        raise ValidationError("Math sidecar must be a public-safe JSON summary inside docs/")
    data = read_json(resolved, max_bytes=1024 * 1024)
    summary = _validate_math_sidecar(data, root, runtime_report)
    summary["sidecar_sha256"] = sha256_file(resolved)
    return summary


def validate_flutter_result(path: Path, scratch_root: Path) -> dict:
    result = read_json(path, max_bytes=64 * 1024)
    expected_keys = {"schema_version", "version", "channel", "archive", "archive_url", "archive_sha256",
                     "archive_bytes", "sdk_root", "download_directory", "extraction_directory", "archive_audit"}
    exact_keys(result, expected_keys, "Flutter provisioning report")
    if (result["schema_version"] != 1 or result["version"] != "3.47.7" or result["channel"] != "stable"
            or result["archive"] != ci_provision_flutter.FLUTTER_ARCHIVE
            or result["archive_url"] != ci_provision_flutter.FLUTTER_URL
            or result["archive_sha256"] != ci_provision_flutter.FLUTTER_SHA256
            or result["archive_bytes"] != ci_provision_flutter.FLUTTER_ARCHIVE_BYTES):
        raise ValidationError("Flutter provisioning report differs from the pinned official stable archive")
    scratch = scratch_root.resolve(strict=True)
    sdk_root = Path(result["sdk_root"]).resolve(strict=True)
    extraction = Path(result["extraction_directory"]).resolve(strict=True)
    downloads = Path(result["download_directory"]).resolve(strict=True)
    if (not extraction.is_relative_to((scratch / "extractions").resolve(strict=True))
            or not downloads.is_relative_to((scratch / "downloads").resolve(strict=True))
            or sdk_root != extraction / "flutter"):
        raise ValidationError("Flutter SDK paths escaped their isolated download/extraction roots")
    for path_to_check in (sdk_root / "bin" / "flutter.bat", sdk_root / "bin" / "cache" / "dart-sdk" / "bin" / "dart.exe"):
        if not path_to_check.is_file() or is_reparse(path_to_check):
            raise ValidationError("Pinned Flutter/Dart SDK is incomplete or linked")
    audit = result["archive_audit"]
    if not isinstance(audit, dict) or type(audit.get("entry_count")) is not int or audit["entry_count"] <= 0:
        raise ValidationError("Flutter ZIP audit summary is missing")
    return result


def validate_font_result(path: Path, scratch_root: Path, root: Path) -> dict:
    result = read_json(path, max_bytes=64 * 1024)
    expected_keys = {"schema_version", "repository", "commit", "repository_path", "git_blob_sha1", "sha256",
                     "bytes", "font_path", "font_directory", "structure", "license", "executed_as_code"}
    exact_keys(result, expected_keys, "Pinned font acquisition report")
    if (result["schema_version"] != 1 or result["repository"] != ci_prepare_assets.FONT_REPOSITORY
            or result["commit"] != ci_prepare_assets.FONT_COMMIT
            or result["repository_path"] != ci_prepare_assets.FONT_REPOSITORY_PATH
            or result["git_blob_sha1"] != ci_prepare_assets.FONT_BLOB_SHA1
            or result["sha256"] != ci_prepare_assets.FONT_SHA256
            or result["bytes"] != ci_prepare_assets.FONT_BYTES
            or result["executed_as_code"] is not False):
        raise ValidationError("Font acquisition report differs from the pinned Google Fonts blob")
    scratch = scratch_root.resolve(strict=True)
    directory = Path(result["font_directory"]).resolve(strict=True)
    font_path = Path(result["font_path"]).resolve(strict=True)
    if (directory.parent != scratch or not re.fullmatch(r"google-fonts-[0-9a-f]{32}", directory.name)
            or font_path != directory / "NotoSansSC-wght.ttf" or is_reparse(directory) or is_reparse(font_path)
            or not font_path.is_file()):
        raise ValidationError("Font file is outside its new UUID directory under the isolated CI scratch root")
    if (font_path.stat().st_size != ci_prepare_assets.FONT_BYTES
            or sha256_file(font_path) != ci_prepare_assets.FONT_SHA256
            or ci_prepare_assets.git_blob_sha1_file(font_path) != ci_prepare_assets.FONT_BLOB_SHA1):
        raise ValidationError("Pinned font content changed after acquisition")
    try:
        structure = ci_prepare_assets.inspect_ttf(font_path)
    except Exception as error:
        raise ValidationError("Downloaded font failed the bounded TrueType structure audit") from error
    exact_keys(result["structure"], {"sfnt", "table_count", "variable_font", "glyph_count", "axis_count"},
               "Pinned font structural summary")
    if structure != result["structure"]:
        raise ValidationError("Pinned font structural summary differs from the downloaded bytes")
    provenance = root / "ui" / "assets" / "fonts" / "PROVENANCE.txt"
    license_file = root / "ui" / "assets" / "fonts" / "OFL.txt"
    try:
        ci_prepare_assets.parse_provenance(provenance)
        license_record = ci_prepare_assets.verify_font_license(license_file)
    except Exception as error:
        raise ValidationError("Noto Sans SC provenance or OFL license failed its pinned identity") from error
    exact_keys(result["license"], {"file", "bytes", "sha256", "git_blob_sha1"}, "Font license summary")
    if result["license"] != license_record:
        raise ValidationError("Font acquisition report does not bind the exact OFL license")
    if (root / "ui" / "assets" / "fonts" / "NotoSansSC-wght.ttf").exists():
        raise ValidationError("The binary Noto font must not be committed in the public source checkout")
    return {"repository": result["repository"], "commit": result["commit"],
            "repository_path": result["repository_path"], "git_blob_sha1": result["git_blob_sha1"],
            "sha256": result["sha256"], "bytes": result["bytes"],
            "license_sha256": license_record["sha256"], "variable_font": True,
            "font_path_for_ephemeral_build_only": font_path}


def make_new_directory(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_reparse(path.parent) or path.exists() or is_reparse(path):
        raise ValidationError("CI output directory must be new and non-reparse")
    path.mkdir(exist_ok=False)
    return path


def create_flutter_environment(base_env: dict, stage: Path) -> dict:
    state = stage / "flutter-isolated-state"
    state.mkdir(exist_ok=False)
    folders = {name: state / name for name in
               ("appdata", "localappdata", "home", "userprofile", "temp", "pub-cache", "git-bin")}
    for folder in folders.values():
        folder.mkdir(exist_ok=False)
    git_exe = shutil.which("git.exe") or shutil.which("git")
    if not git_exe:
        raise ValidationError("A runner-provided Git executable is required for the audited Flutter shim")
    git_path = Path(git_exe).resolve(strict=True)
    if is_reparse(git_path) or not git_path.is_file():
        raise ValidationError("Runner-provided Git is not a regular executable")
    shim = folders["git-bin"] / "$git.cmd"
    with shim.open("x", encoding="ascii", newline="") as stream:
        stream.write(GIT_SHIM_TEXT)
    if hashlib.sha256(shim.read_bytes()).hexdigest() != hashlib.sha256(GIT_SHIM_TEXT.encode("ascii")).hexdigest():
        raise ValidationError("Narrow Flutter Git shim changed after creation")
    gitconfig = state / "empty.gitconfig"
    gitconfig.open("xb").close()
    environment = dict(base_env)
    environment.update({
        "APPDATA": str(folders["appdata"]),
        "LOCALAPPDATA": str(folders["localappdata"]),
        "HOME": str(folders["home"]),
        "USERPROFILE": str(folders["userprofile"]),
        "TEMP": str(folders["temp"]),
        "TMP": str(folders["temp"]),
        "PUB_CACHE": str(folders["pub-cache"]),
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "CHA_STEADY_GIT_EXE": str(git_path),
        "PUB_HOSTED_URL": "https://pub.dev",
        "FLUTTER_STORAGE_BASE_URL": "https://storage.googleapis.com",
        # Official SDK switch: choose NoOpAnalytics, including no first-run notice.
        # Unlike --suppress-analytics, this avoids telemetry-profile initialization.
        "FLUTTER_SUPPRESS_ANALYTICS": "true",
        "PATH": str(folders["git-bin"]) + os.pathsep + base_env.get("PATH", ""),
    })
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "FLUTTER_ROOT"):
        environment.pop(name, None)
    return environment


def run_flutter(label: str, sdk_root: Path, args: list[str], cwd: Path, env: dict,
                logs_root: Path, timeout: int = 1200) -> bytes:
    stdout_path = logs_root / (label + ".stdout.log")
    stderr_path = logs_root / (label + ".stderr.log")
    if stdout_path.exists() or stderr_path.exists():
        raise ValidationError("Flutter diagnostic target is not new")
    registry = OwnedProcessRegistry(threading.Event())
    command = [str(sdk_root / "bin" / "flutter.bat"), "--suppress-analytics", "--no-version-check"] + args
    try:
        with registry_scope(registry):
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                process = spawn_owned_process(command, cwd=str(cwd), env=env, stdout=stdout, stderr=stderr,
                                              stdin=subprocess.DEVNULL)
                code = process.wait(timeout=timeout)
                registry.discard(process)
    finally:
        if registry.snapshot():
            registry.terminate_all()
    if code != 0:
        flutter_json_shape_diagnostic(stdout_path.read_bytes(), stderr_path, RuntimeError())
        raise ValidationError("Flutter {} exited unsuccessfully; raw runner-local logs are not uploaded".format(label))
    return stdout_path.read_bytes()


def flutter_json_shape_diagnostic(raw: bytes, stderr_path: Path, error: Exception) -> None:
    """Print only bounded numeric/boolean shape, never child output or paths."""
    stderr_bytes, stderr_sample = None, b""
    try:
        if stderr_path.is_file() and not is_reparse(stderr_path):
            stderr_bytes = stderr_path.stat().st_size
            with stderr_path.open("rb") as stream:
                stderr_sample = stream.read(64 * 1024)
    except OSError:
        pass
    try:
        raw.decode("utf-8")
        utf8_valid = True
    except UnicodeError:
        utf8_valid = False
    position = getattr(error, "pos", None)
    shape = {"stdout_bytes": len(raw), "stderr_bytes": stderr_bytes,
             "stdout_utf8_bom": raw.startswith(b"\xef\xbb\xbf"), "stdout_utf8_valid": utf8_valid,
             "json_error_pos": position if type(position) is int and position >= 0 else None}
    # Exact launcher markers from the pinned official Windows SDK source.
    markers = {"tool_build": b"Building flutter tool...", "pub_upgrade": b"Running pub upgrade...",
               "dart_version_check": b"Checking Dart SDK version..."}
    for name, marker in markers.items():
        shape["stdout_" + name] = marker in raw
        shape["stderr_" + name] = marker in stderr_sample
    print("ChaSteady Flutter JSON diagnostic " + json.dumps(shape, sort_keys=True), flush=True)


def flutter_version_check(sdk_root: Path, cwd: Path, env: dict, stage: Path) -> dict:
    # A cold official Windows SDK may bootstrap its tool through dart pub upgrade,
    # whose inherited stdout precedes even machine JSON. Capture one supported
    # plain version/bootstrap separately; never strip text from the strict query.
    print("ChaSteady Flutter version step=bootstrap started", flush=True)
    run_flutter("bootstrap", sdk_root, ["--version"], cwd, env, stage, timeout=300)
    print("ChaSteady Flutter version step=strict_machine started", flush=True)
    raw = run_flutter("version", sdk_root, ["--version", "--machine"], cwd, env, stage, timeout=300)
    try:
        info = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        flutter_json_shape_diagnostic(raw, stage / "version.stderr.log", error)
        raise ValidationError("Pinned Flutter SDK did not return its machine-readable version") from error
    if (info.get("frameworkVersion") != "3.47.7" or info.get("channel") != "stable"
            or info.get("dartSdkVersion") != "3.13.5"):
        raise ValidationError("Executed Flutter/Dart versions differ from the pinned stable SDK")
    return {"flutter_version": info["frameworkVersion"], "dart_version": info["dartSdkVersion"],
            "framework_revision": info.get("frameworkRevision")}


def validate_flutter_windows_toolchain(windows_build_root: Path, toolchain_report: dict) -> dict:
    cache_path = windows_build_root / "CMakeCache.txt"
    if (not cache_path.is_file() or is_reparse(cache_path) or cache_path.stat().st_size > 8 * 1024 * 1024
            or not cache_path.resolve(strict=True).is_relative_to(windows_build_root.resolve(strict=True))):
        raise ValidationError("Flutter Windows build lacks a bounded CMakeCache in its actual build directory")
    try:
        lines = cache_path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeError as error:
        raise ValidationError("Flutter CMakeCache is not valid UTF-8 text") from error
    values = {}
    for line in lines:
        if not line or line.startswith(("//", "#")) or "=" not in line or ":" not in line.split("=", 1)[0]:
            continue
        typed_key, value = line.split("=", 1)
        key = typed_key.split(":", 1)[0]
        if key in values:
            raise ValidationError("Flutter CMakeCache contains a duplicate toolchain key")
        values[key] = value.strip()
    required = {"CHASTEADY_CMAKE_COMMAND", "CHASTEADY_CMAKE_VERSION", "CHASTEADY_CMAKE_GENERATOR",
                "CHASTEADY_CMAKE_GENERATOR_INSTANCE", "CHASTEADY_CMAKE_GENERATOR_PLATFORM",
                "CHASTEADY_CXX_COMPILER", "CHASTEADY_CXX_COMPILER_VERSION", "CHASTEADY_WINDOWS_SDK_VERSION"}
    if not required.issubset(values):
        raise ValidationError("Flutter CMakeCache omits explicit post-project toolchain evidence")
    if (values["CHASTEADY_CMAKE_GENERATOR"] != "Visual Studio 18 2026"
            or values["CHASTEADY_CMAKE_GENERATOR_PLATFORM"] != "x64"):
        raise ValidationError("Flutter selected a generator/platform other than stable VS 2026 x64")
    if (_parse_cmake_version(values["CHASTEADY_CMAKE_VERSION"], "Configured CMake version")
            != _parse_cmake_version(toolchain_report["cmake_version"], "Audited CMake version")):
        raise ValidationError("Post-project CMake version differs from the audited VS-bundled executable")
    cmake_command = Path(values["CHASTEADY_CMAKE_COMMAND"])
    expected_cmake = Path(toolchain_report["cmake_path"])
    if (not cmake_command.is_absolute() or not cmake_command.is_file() or is_reparse(cmake_command)
            or os.path.normcase(os.path.abspath(cmake_command))
            != os.path.normcase(os.path.abspath(expected_cmake))):
        raise ValidationError("Flutter's CMake generator used a different executable from the audited runner CMake")
    cmake_result = subprocess.run([str(cmake_command), "--version"], check=False,
                                  capture_output=True, timeout=30)
    if (cmake_result.returncode != 0
            or _cmake_version_from_output(cmake_result.stdout) != toolchain_report["cmake_version"]):
        raise ValidationError("Actual Flutter Windows configuration did not use the audited CMake raw version")

    instance = Path(values["CHASTEADY_CMAKE_GENERATOR_INSTANCE"])
    if (not instance.is_absolute() or not instance.is_dir() or is_reparse(instance)
            or os.path.normcase(os.path.abspath(instance))
            != os.path.normcase(os.path.abspath(toolchain_report["visual_studio_path"]))):
        raise ValidationError("Flutter CMake configuration selected a different Visual Studio installation")
    compiler = Path(values["CHASTEADY_CXX_COMPILER"])
    msvc_root = Path(toolchain_report["msvc_toolset_path"]).resolve(strict=True)
    if (not compiler.is_absolute() or not compiler.is_file() or is_reparse(compiler)
            or not compiler.resolve(strict=True).is_relative_to(msvc_root)):
        raise ValidationError("Flutter CMake configuration selected a compiler outside the audited MSVC toolset")
    actual_compiler_version = values["CHASTEADY_CXX_COMPILER_VERSION"]
    if not _at_least(_parse_version(actual_compiler_version, "Actual C++ compiler version", 3), (19, 50)):
        raise ValidationError("Configured C++ compiler is older than the audited MSVC 14.50 floor")
    actual_sdk = values["CHASTEADY_WINDOWS_SDK_VERSION"]
    if (actual_sdk != toolchain_report["windows_sdk_version"]
            or not _at_least(_parse_version(actual_sdk, "Actual Windows SDK target", 4), MIN_WINDOWS_SDK)):
        raise ValidationError("Flutter CMake configuration selected a different or older Windows SDK")
    return {"generator": values["CHASTEADY_CMAKE_GENERATOR"],
            "platform": values["CHASTEADY_CMAKE_GENERATOR_PLATFORM"],
            "cmake_version": toolchain_report["cmake_version"],
            "cmake_configured_version": values["CHASTEADY_CMAKE_VERSION"],
            "cmake_version_output": cmake_result.stdout.decode("utf-8"),
            "msvc_toolset_version": toolchain_report["msvc_toolset_version"],
            "cxx_compiler_version": actual_compiler_version,
            "windows_sdk_include_version": actual_sdk,
            "windows_sdk_product_version": toolchain_report["windows_sdk_product_version"]}


def validate_worker_runtime(root: Path, runtime_manifest_path: Path, sidecar_path: Path,
                            stage: Path) -> tuple[dict, dict, Path, Path, dict, dict]:
    if not runtime_manifest_path.resolve(strict=True).is_relative_to((root / "docs").resolve(strict=True)):
        raise ValidationError("Fresh Worker runtime report must be under docs/")
    runtime_report = read_json(runtime_manifest_path, max_bytes=16 * 1024 * 1024)
    try:
        runtime_toolchain_root, runtime_root, python_exe, runtime_env, _runtime_info = \
            freeze_worker.validate_manifest(root, runtime_report)
    except Exception as error:
        raise ValidationError("Fresh Worker runtime manifest failed its original canonical validation") from error
    sidecar_summary = validate_math_sidecar(sidecar_path, root, runtime_report)
    return runtime_report, runtime_toolchain_root, runtime_root, python_exe, runtime_env, sidecar_summary


def pyinstaller_manifest_environment(root: Path, manifest_path: Path, runtime_report: dict,
                                     runtime_env: dict) -> dict:
    if not manifest_path.is_absolute():
        raise ValidationError("PyInstaller runtime manifest handoff must use an absolute path")
    try:
        relative = manifest_path.relative_to(root).as_posix()
        checked = freeze_worker.safe_path(root, relative)
    except (ValueError, OSError) as error:
        raise ValidationError("PyInstaller runtime manifest handoff escaped the regular project tree") from error
    if (not checked.resolve(strict=True).is_relative_to((root / "docs").resolve(strict=True))
            or read_json(checked, max_bytes=16 * 1024 * 1024) != runtime_report):
        raise ValidationError("PyInstaller runtime manifest is outside docs or changed after validation")
    environment = dict(runtime_env)
    environment["CHASTEADY_WORKER_RUNTIME_MANIFEST"] = str(checked.resolve(strict=True))
    environment["CHASTEADY_WORKER_RUNTIME_MANIFEST_SHA256"] = sha256_file(checked)
    return environment


def build_worker(root: Path, runtime_report: dict, runtime_root: Path, python_exe: Path,
                 runtime_env: dict, resource_root: Path, stage: Path, *,
                 runtime_manifest_path: Path) -> tuple[Path, dict, dict, dict]:
    findings = freeze_worker.source_privacy_findings(root)
    if findings:
        raise ValidationError("Canonical Worker source privacy check found machine-specific paths")
    test_facts = freeze_worker.run_worker_tests(root, python_exe, stage, runtime_root, runtime_env)
    minimum_expected = test_facts.get("minimum_expected_test_count")
    test_count = test_facts.get("test_count")
    executed_count = test_facts.get("executed_test_count")
    skipped_count = test_facts.get("skipped_count")
    counts = (minimum_expected, test_count, executed_count, skipped_count)
    if (test_facts.get("passed") is not True or any(type(value) is not int or value < 0 for value in counts)
            or minimum_expected < 127 or test_count < minimum_expected
            or executed_count + skipped_count != test_count):
        raise ValidationError("Worker suite failed the canonical minimum-count and actual-count consistency gate")

    dist = stage / "dist"
    work = stage / "work"
    dist.mkdir(exist_ok=False)
    work.mkdir(exist_ok=False)
    command = [str(python_exe), "-I", "-m", "PyInstaller", "--noconfirm", "--clean",
               "--distpath", str(dist), "--workpath", str(work), str(root / "packaging" / "Worker.spec")]
    stdout_path = stage / "pyinstaller-stdout.log"
    stderr_path = stage / "pyinstaller-stderr.log"
    build_env = pyinstaller_manifest_environment(root, runtime_manifest_path, runtime_report, runtime_env)
    result = subprocess.run(command, cwd=str(root), env=build_env, check=False, capture_output=True,
                            timeout=3600)
    with stdout_path.open("xb") as stream:
        stream.write(result.stdout)
    with stderr_path.open("xb") as stream:
        stream.write(result.stderr)
    if result.returncode != 0:
        raise ValidationError("Canonical PyInstaller command failed; raw runner-local logs are not uploaded")

    worker_bundle = dist / "Worker"
    executable = worker_bundle / "Worker.exe"
    if not executable.is_file() or is_reparse(executable) or freeze_worker.pe_subsystem(executable) != 3:
        raise ValidationError("PyInstaller did not create a regular console-subsystem Worker.exe")
    if (worker_bundle / "web").exists() or (worker_bundle / "ui").exists():
        raise ValidationError("Frozen Worker unexpectedly duplicates the Flutter UI")
    python_dll = freeze_worker.verify_bundled_python_dll(worker_bundle, runtime_root, runtime_report)
    smoke = freeze_worker.smoke_worker(resource_root, worker_bundle, stage, runtime_root, runtime_env)
    if smoke.get("passed") is not True:
        raise ValidationError("Existing frozen Worker stdio/HTTP protocol smoke failed")
    inventory = freeze_worker.inventory_bundle(worker_bundle)
    if (inventory.get("file_count", 0) <= 0 or inventory.get("video_or_audio_files")
            or not any(row["path"].casefold() == "worker.exe" for row in inventory["files"])):
        raise ValidationError("Frozen Worker inventory is incomplete or contains media")
    return worker_bundle, {"passed": True,
                           "minimum_expected_test_count": test_facts["minimum_expected_test_count"],
                           "test_count": test_facts["test_count"],
                           "executed_test_count": test_facts["executed_test_count"],
                           "skipped_count": test_facts["skipped_count"]}, {
        "passed": True, "console_subsystem": 3, "protocol": "stdio + authenticated loopback HTTP",
        "web_session": True, "shutdown": True, "credentials_recorded": False,
        "file_count": inventory["file_count"], "total_bytes": inventory["total_bytes"],
        "inventory_sha256": inventory["bundle_sha256"], "python_dll": python_dll,
        "native_application_runtime_verified": False,
    }, inventory


def _copy_file(source: Path, destination: Path) -> None:
    if not source.is_file() or is_reparse(source) or destination.exists() or is_reparse(destination):
        raise ValidationError("Application metadata source or target is not a new regular file")
    shutil.copyfile(source, destination)


LICENSE_TEXT_SUFFIXES = {".txt", ".md", ".license", ".licence", ".notice", ".copying"}
LICENSE_TEXT_BASENAMES = {"license", "licence", "copying", "notice", "copyright", "ofl", "license_dop"}


def copy_license_texts(source: Path, destination: Path, repo_root: Path) -> list[dict]:
    if not source.is_dir() or is_reparse(source) or destination.exists() or is_reparse(destination):
        raise ValidationError("License source must be regular and destination must be new")
    destination.mkdir(exist_ok=False)
    repo_marker = str(repo_root.resolve(strict=True)).encode("utf-8", "ignore").lower()
    home_marker = str(Path.home()).encode("utf-8", "ignore").lower()
    # A drive letter must start a token: the final p:/ in http:// (or s:/
    # in https://) is not a Windows path. Do not exempt URLs or license files;
    # real drive/UNC paths and the independent root/home checks still apply.
    windows_path = re.compile(r"(?i)(?:(?<![A-Z0-9_])[A-Z]:[\\/]|\\\\[A-Z0-9_.-]+[\\/])")
    rows = []
    for item in sorted(source.rglob("*")):
        if is_reparse(item):
            raise ValidationError("License tree contains a reparse point")
        if not item.is_file():
            continue
        if item.name.casefold() == "collection-manifest.json":
            continue
        is_license_text = (item.suffix.casefold() in LICENSE_TEXT_SUFFIXES
                           or item.name.split(".", 1)[0].casefold() in LICENSE_TEXT_BASENAMES)
        if not is_license_text:
            continue
        if item.stat().st_size > 8 * 1024 * 1024:
            raise ValidationError("A license text exceeds the configured public-copy size bound")
        payload = item.read_bytes()
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeError as error:
            raise ValidationError("A selected license notice is not UTF-8 text") from error
        folded = payload.lower()
        if (b"\x00" in payload or windows_path.search(text)
                or (repo_marker and repo_marker in folded) or (home_marker and home_marker in folded)):
            raise ValidationError("A selected license notice contains a machine-specific path")
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or is_reparse(target):
            raise ValidationError("License copy target is not a new regular file")
        with target.open("xb") as output:
            output.write(payload)
        rows.append({"path": relative.as_posix(), "bytes": len(payload),
                     "sha256": hashlib.sha256(payload).hexdigest()})
    if not rows or not any(row["path"] == "fonts/noto-sans-sc/OFL.txt" for row in rows):
        raise ValidationError("Selected license texts omit the exact Noto Sans SC OFL notice")
    return rows


def _write_json_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _public_bundle_failure(message: str, relative: str) -> ValidationError:
    # Only an allowlisted class and a hash of the complete relative path may
    # reach public diagnostics. Never attach a raw path or vendor exception.
    category = {
        "worker": "worker", "web": "web", "data": "flutter_data", "licenses": "licenses",
        "chasteady.exe": "native", "flutter_windows.dll": "native",
        "readme.md": "metadata", "build_status.json": "metadata", "license": "metadata",
        "third_party_notices.md": "metadata",
    }.get(relative.split("/", 1)[0].casefold(), "other")
    error = ValidationError(message)
    error._ci_bundle_context = (category, hashlib.sha256(relative.encode("utf-8")).hexdigest())
    return error


def _is_audited_scipy_sobol(path: Path, relative: str, runtime_report: dict | None) -> bool:
    resource = SCIPY_SOBOL_RESOURCE
    if (relative != resource["bundle_path"]
            or relative != "Worker/" + resource["wheel_entry"]
            or path.stat().st_size != resource["bytes"]
            or sha256_file(path) != resource["sha256"] or not isinstance(runtime_report, dict)):
        return False
    identity = resource["wheel"]
    canonical = [pin for pin in provision_worker_runtime.WHEELS if pin["name"] == identity["name"]]
    if len(canonical) != 1 or any(canonical[0].get(key) != value for key, value in identity.items()):
        return False
    try:
        wheels = _worker_pins(runtime_report)
    except ValidationError:
        return False
    return any(all(wheel.get(key) == value for key, value in identity.items()) for wheel in wheels)


def assert_public_bundle(app_root: Path, repo_root: Path, *, runtime_report: dict | None = None) -> list[dict]:
    if not app_root.is_dir() or is_reparse(app_root):
        raise ValidationError("Staged app bundle is not a regular directory")
    root_texts = {str(repo_root.resolve(strict=True)).encode("utf-8", "ignore"),
                  str(Path.home()).encode("utf-8", "ignore")}
    rows = []
    for path in sorted(app_root.rglob("*")):
        relative = path.relative_to(app_root).as_posix()
        if is_reparse(path):
            raise _public_bundle_failure("Staged public bundle contains a reparse point", relative)
        if not path.is_file():
            continue
        pure = PurePosixPath(relative)
        if any(part.casefold() in FORBIDDEN_BUNDLE_COMPONENTS for part in pure.parts):
            raise _public_bundle_failure("Staged public bundle contains a private/profile/cache path", relative)
        if path.suffix.casefold() in FORBIDDEN_BUNDLE_SUFFIXES:
            if relative != SCIPY_SOBOL_RESOURCE["bundle_path"]:
                raise _public_bundle_failure("Staged public bundle contains a prohibited media/cache/log file", relative)
            if not _is_audited_scipy_sobol(path, relative, runtime_report):
                raise _public_bundle_failure(
                    "Audited vendor runtime resource failed its exact source or content identity", relative)
        if path.suffix.casefold() in (".exe", ".dll", ".pyd", ".dat", ".json", ".js", ".html", ".css", ".txt"):
            # Only runner/repository root and current user-home markers are tested;
            # arbitrary private input data is never opened by the packaging step.
            with path.open("rb") as stream:
                carry = b""
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    sample = carry + block
                    if any(marker and marker.lower() in sample.lower() for marker in root_texts):
                        raise _public_bundle_failure("A staged file contains a local build-root or profile path", relative)
                    carry = sample[-512:]
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    relative_names = {row["path"] for row in rows}
    required = {"ChaSteady.exe", "flutter_windows.dll", "README.md", "BUILD_STATUS.json",
                "LICENSE", "THIRD_PARTY_NOTICES.md", "web/index.html", "web/flutter_bootstrap.js",
                "licenses/fonts/noto-sans-sc/OFL.txt", "Worker/Worker.exe", *BUNDLE_FONT_PATHS}
    if not required.issubset(relative_names):
        raise ValidationError("Staged app bundle is missing a required native, Worker, web, README or license file")
    if not any(name.startswith("data/") for name in relative_names):
        raise ValidationError("Staged app bundle lacks Flutter data assets")
    if not any(name.startswith("licenses/") for name in relative_names):
        raise ValidationError("Staged app bundle lacks copied third-party license notices")
    font_rows = [row for row in rows if row["path"].endswith("/NotoSansSC-wght.ttf")]
    bad_font = next((row for row in font_rows if row["sha256"] != ci_prepare_assets.FONT_SHA256), None)
    ofl_path = "licenses/fonts/noto-sans-sc/OFL.txt"
    if (not font_rows or bad_font is not None
            or next((row["sha256"] for row in rows if row["path"] == ofl_path), None)
            != ci_prepare_assets.FONT_LICENSE_SHA256):
        raise _public_bundle_failure(
            "Public app bundle font or corresponding OFL license differs from its pinned identity",
            bad_font["path"] if bad_font is not None else ofl_path)
    if len(rows) != len(relative_names):
        raise ValidationError("Staged app bundle has duplicate relative file names")
    return rows


def write_zip(app_root: Path, archive_path: Path) -> None:
    if archive_path.exists() or is_reparse(archive_path):
        raise ValidationError("Public ZIP target must be a new file")
    with zipfile.ZipFile(str(archive_path), "x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for path in sorted(item for item in app_root.rglob("*") if item.is_file()):
            if is_reparse(path):
                raise ValidationError("Staged app changed while being archived")
            relative = path.relative_to(app_root).as_posix()
            archive.write(str(path), "ChaSteady/" + relative)


def run_flutter_preflight(args) -> dict:
    """Execute only the pinned Flutter identity gate, before VS/SDK installation."""
    mark_ci_stage(args, "checkout")
    root = args.root.resolve(strict=True)
    if root != ROOT.resolve(strict=True):
        raise ValidationError("Build root differs from the repository containing this trusted CI helper")
    mark_ci_stage(args, "flutter_report")
    result = validate_flutter_result(args.flutter_result, args.flutter_scratch)
    sdk_root = Path(result["sdk_root"])
    stage_path = args.preflight_stage.resolve()
    excluded = [sdk_root, Path(result["extraction_directory"]), Path(result["download_directory"]),
                root / "tools", root / "worker", root / "ui"]
    if any(stage_path.is_relative_to(path.resolve()) or path.resolve().is_relative_to(stage_path)
           for path in excluded):
        raise ValidationError("Flutter preflight stage overlaps SDK or source files")
    stage = make_new_directory(stage_path)
    mark_ci_stage(args, "flutter_environment")
    environment = create_flutter_environment(os.environ, stage)
    mark_ci_stage(args, "flutter_version")
    identity = flutter_version_check(sdk_root, root, environment, stage)
    mark_ci_stage(args, "flutter_preflight_result")
    receipt = {"schema_version": 1, "scope": "pinned_flutter_executable_identity_only",
               "archive_sha256": result["archive_sha256"], "identity": identity,
               "strict_machine_json_verified": True, "native_build_executed": False,
               "worker_tests_or_math_executed": False, "runtime_acceptance_verified": False}
    _write_json_new(stage / "flutter-preflight.json", receipt)
    print("Pinned Flutter executable identity preflight passed; no native or Worker build was run.", flush=True)
    return receipt


def run_window_fixture_step(label: str, command: list[str], source: Path,
                            environment: dict, stage: Path, timeout: int) -> None:
    if label not in {"configure", "build", "run"}:
        raise ValueError("Unknown internal window fixture stage")
    registry = OwnedProcessRegistry(threading.Event())
    stdout_path = stage / ("window-fixture-" + label + ".stdout.log")
    stderr_path = stage / ("window-fixture-" + label + ".stderr.log")
    try:
        with registry_scope(registry):
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                process = spawn_owned_process(command, cwd=str(source), env=environment,
                                              stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL)
                code = process.wait(timeout=timeout)
                registry.discard(process)
    finally:
        if registry.snapshot():
            registry.terminate_all()
    if code != 0:
        raise ValidationError(
            "Windows fixture {} exited unsuccessfully; raw runner-local logs are not uploaded".format(label))


def run_native_window_fixture(args, source: Path, environment: dict,
                              stage: Path, toolchain_report: dict) -> dict:
    build_root = source / "build" / "windows" / "x64"
    cmake = str(Path(toolchain_report["cmake_path"]))
    mark_ci_stage(args, "native_fixture_configure")
    run_window_fixture_step("configure", [cmake, "-S", str(source / "windows"), "-B", str(build_root),
                            "-DCHASTEADY_BUILD_WINDOW_CHROME_SMOKE=ON"],
                            source, environment, stage, timeout=300)
    # Reconfiguration must retain the same audited VS2026/MSVC/SDK combination.
    validate_flutter_windows_toolchain(build_root, toolchain_report)
    mark_ci_stage(args, "native_fixture_build")
    run_window_fixture_step("build", [cmake, "--build", str(build_root), "--config", "Release",
                            "--target", "chasteady_window_chrome_smoke"],
                            source, environment, stage, timeout=600)
    executable = build_root / "native_smoke" / "Release" / "chasteady_window_chrome_smoke.exe"
    if (not executable.is_file() or is_reparse(executable)
            or not executable.resolve(strict=True).is_relative_to(build_root.resolve(strict=True))):
        raise ValidationError("Windows fixture output is missing or is not a regular file")
    mark_ci_stage(args, "native_fixture_run")
    run_window_fixture_step("run", [str(executable)], source, environment, stage, timeout=60)
    return {"passed": True, "scope": "owned_win32_window_chrome_fixture_only",
            "production_app_runtime_verified": False, "snap_flyout_verified": False,
            "multi_monitor_dpi_verified": False}


def run_flutter_ui_build(args, sdk_root: Path, source: Path, environment: dict,
                         stage: Path, toolchain_report: dict) -> tuple[dict, dict]:
    checks = {"flutter_analyze_passed": False, "flutter_tests_passed": False}
    actual_windows_toolchain = None
    for label, command in build_windows.flutter_commands(build_only=False):
        mark_ci_stage(args, "flutter_" + label)
        run_flutter(label, sdk_root, command, source, environment, stage,
                    timeout=3600 if label in ("windows", "web") else 1200)
        if label == "analyze":
            checks["flutter_analyze_passed"] = True
        elif label == "test":
            checks["flutter_tests_passed"] = True
        elif label == "windows":
            mark_ci_stage(args, "native_toolchain")
            actual_windows_toolchain = validate_flutter_windows_toolchain(
                source / "build" / "windows" / "x64", toolchain_report)
    if not all(checks.values()):
        raise ValidationError("Required Flutter UI analysis or tests did not execute")
    if actual_windows_toolchain is None:
        raise ValidationError("Flutter did not execute the required Windows release build")
    return actual_windows_toolchain, checks


def run_build(args) -> dict:
    mark_ci_stage(args, "checkout")
    root = args.root.resolve(strict=True)
    if root != ROOT.resolve(strict=True):
        raise ValidationError("Build root differs from the repository containing this trusted CI helper")
    if not (root / ".git").exists():
        raise ValidationError("A complete Git checkout is required for the trusted runner build")
    mark_ci_stage(args, "toolchain_report")
    toolchain_report = validate_toolchain_report(read_json(args.toolchain_report, max_bytes=64 * 1024))
    mark_ci_stage(args, "flutter_report")
    flutter_result = validate_flutter_result(args.flutter_result, args.flutter_scratch)
    mark_ci_stage(args, "font_report")
    font_summary = validate_font_result(args.font_result.resolve(strict=True), args.font_scratch, root)
    font_path = font_summary.pop("font_path_for_ephemeral_build_only")
    mark_ci_stage(args, "worker_report")
    runtime_report_path = args.worker_manifest.resolve(strict=True)
    runtime_report = read_json(runtime_report_path, max_bytes=16 * 1024 * 1024)
    mark_ci_stage(args, "stage_ui")
    # Keep all build state under the ignored ephemeral private tree. Only the
    # explicit app ZIP, digest and sanitized manifest are exported by the workflow.
    private_root = root / "private"
    if private_root.exists() and (is_reparse(private_root) or not private_root.is_dir()):
        raise ValidationError("Ephemeral private directory is not a regular directory")
    private_root.mkdir(exist_ok=True)
    toolchains = private_root / "toolchains"
    if toolchains.exists() and (is_reparse(toolchains) or not toolchains.is_dir()):
        raise ValidationError("Ephemeral toolchain directory is not a regular directory")
    toolchains.mkdir(exist_ok=True)
    stage = make_new_directory(toolchains / ("ci-build-" + uuid.uuid4().hex))
    app_stage = stage / "app-stage"
    flutter_source = stage / "ui"
    flutter_source.mkdir(exist_ok=False)
    for name in ("lib", "test", "web", "assets"):
        build_windows.copy_directory(root / "ui" / name, flutter_source / name)
    font_destination = flutter_source / "assets" / "fonts" / "NotoSansSC-wght.ttf"
    _copy_file(font_path, font_destination)
    if (sha256_file(font_destination) != ci_prepare_assets.FONT_SHA256
            or ci_prepare_assets.git_blob_sha1_file(font_destination) != ci_prepare_assets.FONT_BLOB_SHA1):
        raise ValidationError("Downloaded font changed while entering the isolated Flutter source copy")
    build_windows.copy_windows_source(root / "ui" / "windows", flutter_source / "windows")
    for name in ("pubspec.yaml", "pubspec.lock", "analysis_options.yaml", "l10n.yaml"):
        source = root / "ui" / name
        if source.is_file():
            _copy_file(source, flutter_source / name)
    if not (flutter_source / "pubspec.lock").is_file():
        raise ValidationError("Locked Flutter UI dependency graph is required")

    mark_ci_stage(args, "flutter_environment")
    flutter_env = create_flutter_environment(os.environ, stage)
    flutter_env["CHASTEADY_WINDOWS_SDK_VERSION"] = toolchain_report["windows_sdk_version"]
    sdk_root = Path(flutter_result["sdk_root"])
    mark_ci_stage(args, "flutter_version")
    version_info = flutter_version_check(sdk_root, flutter_source, flutter_env, stage)
    actual_windows_toolchain, ui_checks = run_flutter_ui_build(
        args, sdk_root, flutter_source, flutter_env, stage, toolchain_report)
    native_window_fixture = run_native_window_fixture(
        args, flutter_source, flutter_env, stage, toolchain_report)

    mark_ci_stage(args, "native_outputs")
    web_root = flutter_source / "build" / "web"
    if not (web_root / "index.html").is_file() or not (web_root / "flutter_bootstrap.js").is_file():
        raise ValidationError("Real Flutter web build did not produce its offline entry points")
    compiled = flutter_source / "build" / "windows" / "x64" / "runner" / "Release"
    if (not (compiled / "ChaSteady.exe").is_file() or is_reparse(compiled / "ChaSteady.exe")
            or not (compiled / "flutter_windows.dll").is_file() or is_reparse(compiled / "flutter_windows.dll")
            or not (compiled / "data").is_dir()):
        raise ValidationError("Real Flutter Windows Release output lacks the native executable, engine DLL or data")

    mark_ci_stage(args, "worker_runtime")
    runtime_toolchain_root, runtime_root, python_exe, runtime_env, _ = \
        freeze_worker.validate_manifest(root, runtime_report)
    mark_ci_stage(args, "local_math_identity")
    sidecar_summary = validate_math_sidecar(args.math_sidecar.resolve(strict=True), root, runtime_report)
    mark_ci_stage(args, "stage_app")
    build_windows.copy_directory(compiled, app_stage, omit_debug=True)
    build_windows.copy_directory(web_root, app_stage / "web")
    mark_ci_stage(args, "worker_build_and_smoke")
    worker_bundle, backend_summary, worker_summary, worker_inventory = build_worker(
        root, runtime_report, runtime_root, python_exe, runtime_env, app_stage, stage,
        runtime_manifest_path=runtime_report_path,
    )
    mark_ci_stage(args, "worker_inventory")
    worker_target = app_stage / "Worker"
    build_windows.copy_directory(worker_bundle, worker_target, omit_debug=True)
    worker_inventory_evidence = build_windows.verify_worker_inventory(worker_target, {
        "freeze": {"status": "built_and_smoke_tested"},
        "test_facts": {"frozen_worker": {"passed": True,
                                           "inventory": {"files": worker_inventory["files"]}}},
    })

    mark_ci_stage(args, "bundle_license_texts")
    copied_license_texts = copy_license_texts(root / "docs" / "licenses", app_stage / "licenses", root)
    mark_ci_stage(args, "bundle_metadata")
    build_status = {
        "schema_version": 1,
        "native_compiled": True,
        "worker_packaged": True,
        "web_assets_packaged": True,
        "build_only": True,
        "prebuild_ui_analyze_or_tests_run": all(ui_checks.values()),
        "ui_checks": ui_checks,
        "native_window_fixture": native_window_fixture,
        "backend_tests": backend_summary,
        "local_validation_origin": sidecar_summary["local_validation_origin"],
        "private_goldens_rerun_in_ci": False,
        "math_golden_case_count": sidecar_summary["case_count"],
        "math_golden_original_checker_passed": sidecar_summary["original_checker_passed"],
        "worker_protocol_smoke_passed": True,
        "worker_inventory_verification": worker_inventory_evidence,
        "flutter_windows_toolchain": actual_windows_toolchain,
        "offline_font": font_summary,
        "copied_license_text_count": len(copied_license_texts),
        "runtime_acceptance_verified": False,
        "web_menu_shared_backend_runtime_verified": False,
        "signed": False,
        "public_distribution_cleared": False,
        "legal_certification": False,
        "license_scope": "MIT covers original ChaSteady code only; bundled third-party license notices are retained.",
    }
    _write_json_new(app_stage / "BUILD_STATUS.json", build_status)
    mark_ci_stage(args, "bundle_legal_notices")
    _copy_file(root / "LICENSE", app_stage / "LICENSE")
    _copy_file(root / "THIRD_PARTY_NOTICES.md", app_stage / "THIRD_PARTY_NOTICES.md")
    _copy_file(root / "docs" / "WINDOWS_PORTABLE_GUIDE.md", app_stage / "README.md")

    mark_ci_stage(args, "public_inventory")
    files = assert_public_bundle(app_stage, root, runtime_report=runtime_report)
    # This helper intentionally creates its output directory only after all builds,
    # tests, sidecar identities and source-to-output checks have passed.
    mark_ci_stage(args, "artifact_zip")
    artifact_dir = make_new_directory(args.artifact_dir.resolve())
    zip_path = artifact_dir / "ChaSteady-Windows-x64.zip"
    write_zip(app_stage, zip_path)
    zip_hash = sha256_file(zip_path)
    with (artifact_dir / "ChaSteady-Windows-x64.zip.sha256").open("x", encoding="ascii", newline="\n") as stream:
        stream.write(zip_hash + "  ChaSteady-Windows-x64.zip\n")

    mark_ci_stage(args, "artifact_manifest")
    runtime_python = runtime_report["python"]
    manifest = {
        "schema_version": 1,
        "product": "ChaSteady",
        "build_scope": "manual_windows_x64_build_only",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "toolchain": {
            "runner_label": toolchain_report["runner_label"],
            "visual_studio_version": toolchain_report["visual_studio_version"],
            "msvc_toolset_version": toolchain_report["msvc_toolset_version"],
            "cmake_version": toolchain_report["cmake_version"],
            "cmake_version_output": toolchain_report["cmake_version_output"],
            "windows_sdk_version": toolchain_report["windows_sdk_version"],
            "windows_sdk_product_version": toolchain_report["windows_sdk_product_version"],
            "windows_sdk_installer": {
                "source_id": toolchain_report["sdk_installer"]["source_id"],
                "bytes": toolchain_report["sdk_installer"]["bytes"],
                "sha256": toolchain_report["sdk_installer"]["sha256"],
                "authenticode_status": toolchain_report["sdk_installer"]["authenticode_status"],
                "installer_file_version": toolchain_report["sdk_installer"]["installer_file_version"],
            },
            "flutter_windows": actual_windows_toolchain,
            "flutter": {"version": version_info["flutter_version"], "dart_version": version_info["dart_version"],
                        "archive_sha256": flutter_result["archive_sha256"]},
            "python": {"version": runtime_python["version"],
                       "archive_sha256": runtime_python["published_sha256"]},
            "worker_wheels": sidecar_summary["wheels"],
            "offline_font": font_summary,
        },
        "validation": {
            "backend_tests": backend_summary,
            "worker_protocol_smoke": worker_summary,
            "worker_inventory_verification": worker_inventory_evidence,
            "local_validation_origin": sidecar_summary["local_validation_origin"],
            "local_math_scope": sidecar_summary["scope"],
            "math_sidecar_sha256": sidecar_summary["sidecar_sha256"],
            "worker_source_inventory_sha256": sidecar_summary["worker_source_inventory_sha256"],
            "copied_license_text_count": len(copied_license_texts),
            "private_goldens_rerun_in_ci": False,
            "ui_analyze_or_tests_run": all(ui_checks.values()),
            "ui_checks": ui_checks,
            "native_window_fixture": native_window_fixture,
            "native_application_runtime_verified": False,
            "public_distribution_cleared": False,
            "signed": False,
            "legal_certification": False,
        },
        "license_scope": "MIT covers original ChaSteady code only; bundled third-party notices are preserved.",
        "files": files,
        "artifact_zip": {"filename": zip_path.name, "bytes": zip_path.stat().st_size, "sha256": zip_hash},
    }
    _write_json_new(artifact_dir / "ChaSteady-Windows-x64.manifest.json", manifest)
    print("ChaSteady Windows build, source-bound Worker validation, and public-safe inventory passed.")
    return {"artifact_dir": artifact_dir, "manifest": manifest}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--preflight-flutter-only", action="store_true",
                        help="Verify only the pinned Flutter executable identity; never build native/Worker outputs")
    parser.add_argument("--preflight-stage", type=Path, help="New isolated stage for version-only preflight logs/receipt")
    parser.add_argument("--toolchain-report", type=Path)
    parser.add_argument("--flutter-result", type=Path, required=True)
    parser.add_argument("--flutter-scratch", type=Path, required=True)
    parser.add_argument("--font-result", type=Path)
    parser.add_argument("--font-scratch", type=Path)
    parser.add_argument("--worker-manifest", type=Path)
    parser.add_argument("--math-sidecar", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args(argv)
    full_fields = ("toolchain_report", "font_result", "font_scratch", "worker_manifest", "math_sidecar", "artifact_dir")
    if args.preflight_flutter_only:
        if args.preflight_stage is None:
            parser.error("--preflight-flutter-only requires --preflight-stage")
        if any(getattr(args, field) is not None for field in full_fields):
            parser.error("--preflight-flutter-only cannot accept full-build inputs or an artifact directory")
    else:
        if args.preflight_stage is not None:
            parser.error("--preflight-stage requires --preflight-flutter-only")
        missing = ["--" + field.replace("_", "-") for field in full_fields if getattr(args, field) is None]
        if missing:
            parser.error("Full build requires " + ", ".join(missing))
    try:
        if args.preflight_flutter_only:
            run_flutter_preflight(args)
        else:
            run_build(args)
    except Exception as error:
        # Print only fixed stages/codes and exact allowlisted author messages.
        # Unknown exception strings and all raw child/process logs stay private.
        print(ci_failure_diagnostic(error, getattr(args, "_ci_stage", None)), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
