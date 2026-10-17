"""Build native Flutter and stage a fresh relocatable Windows application bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.stdout.reconfigure(encoding="utf-8")
from cha_stabilizer.owned_processes import OwnedProcessRegistry, registry_scope, spawn_owned_process
from cha_stabilizer.paths import _assert_no_reparse_components


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 ** 2), b""):
            result.update(data)
    return result.hexdigest()


def copy_directory(source, destination, omit_debug=False):
    _assert_no_reparse_components(source)
    if not source.is_dir() or destination.exists():
        raise RuntimeError("Source must exist and destination must be new")
    for item in source.rglob("*"):
        _assert_no_reparse_components(item)
        if item.is_file() and item.suffix.lower() in {
            ".mp4", ".mov", ".mxf", ".m4v", ".mkv", ".avi", ".webm",
            ".wav", ".aac", ".mp3", ".dmp",
        }:
            raise RuntimeError("Media or crash dump must not enter an application bundle")
    debug_suffixes = {".pdb", ".ilk", ".exp", ".lib"}
    def ignore_debug(directory, names):
        return [name for name in names if Path(name).suffix.lower() in debug_suffixes]
    shutil.copytree(source, destination, ignore=ignore_debug if omit_debug else None)


def copy_windows_source(source, destination):
    # Do not import an earlier build's ephemeral SDK links, caches or CMake paths.
    _assert_no_reparse_components(source)
    destination.mkdir()
    copy_directory(source / "runner", destination / "runner")
    _assert_no_reparse_components(source / "CMakeLists.txt")
    shutil.copyfile(source / "CMakeLists.txt", destination / "CMakeLists.txt")
    managed = destination / "flutter"
    managed.mkdir()
    for name in ("CMakeLists.txt", "generated_plugin_registrant.h",
                 "generated_plugin_registrant.cc", "generated_plugins.cmake"):
        original = source / "flutter" / name
        _assert_no_reparse_components(original)
        shutil.copyfile(original, managed / name)


def bundle_metadata(bundle, worker_present):
    files = [{"path": file.relative_to(bundle).as_posix(), "bytes": file.stat().st_size,
              "sha256": digest(file)}
             for file in sorted(bundle.rglob("*")) if file.is_file()]
    return {"native_compiled": True, "worker_packaged": worker_present,
            "web_assets_packaged": True, "web_menu_shared_backend_runtime_verified": False,
            "runtime_acceptance_verified": False, "signed": False,
            "public_distribution_cleared": False,
            "validation_scope": "build_and_inventory_only_not_runtime_or_licence_clearance",
            "files": files}


def verify_worker_inventory(directory, report):
    _assert_no_reparse_components(directory)
    frozen = report.get("test_facts", {}).get("frozen_worker", {})
    if report.get("freeze", {}).get("status") != "built_and_smoke_tested" or frozen.get("passed") is not True:
        raise RuntimeError("Worker build/protocol evidence is incomplete")
    expected = {}
    for row in frozen.get("inventory", {}).get("files", []):
        raw = row.get("path")
        if not isinstance(raw, str) or "\\" in raw:
            raise RuntimeError("Worker inventory path is invalid")
        relative = PurePosixPath(raw)
        if (relative.is_absolute() or relative.as_posix() != raw or not relative.parts
                or any(part in (".", "..") or ":" in part for part in relative.parts)):
            raise RuntimeError("Worker inventory path escapes its bundle")
        key = raw.casefold()
        if key in expected or type(row.get("bytes")) is not int or row["bytes"] < 0:
            raise RuntimeError("Worker inventory entry is duplicate or invalid")
        if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise RuntimeError("Worker inventory lacks a valid SHA-256")
        expected[key] = row
    if "worker.exe" not in expected:
        raise RuntimeError("Worker inventory is missing Worker.exe")
    actual = {}
    for file in directory.rglob("*"):
        _assert_no_reparse_components(file)
        if file.is_file():
            key = file.relative_to(directory).as_posix().casefold()
            if key in actual:
                raise RuntimeError("Worker directory contains case-colliding file names")
            actual[key] = file
    if set(actual) != set(expected):
        raise RuntimeError("Worker directory differs from the verified file inventory")
    for key, file in actual.items():
        if file.stat().st_size != expected[key]["bytes"] or digest(file) != expected[key]["sha256"]:
            raise RuntimeError("Worker file bytes changed after verification")
    return {"file_count": len(expected), "sha256_inventory_matches": True,
            "build_protocol_smoke_verified": True,
            "native_application_runtime_verified": False}


def flutter_commands(build_only=False):
    commands = [
        ("pub", ["pub", "get", "--enforce-lockfile"]),
        ("l10n", ["gen-l10n"]),
    ]
    if not build_only:
        commands.extend([("analyze", ["analyze", "--no-pub"]),
                         ("test", ["test", "--no-pub", "--reporter", "expanded"])])
    commands.extend([
        ("windows", ["build", "windows", "--release"]),
        ("web", ["build", "web", "--release", "--no-web-resources-cdn", "--pwa-strategy=none"]),
    ])
    return commands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-dir", type=Path, help="Verified PyInstaller onedir containing Worker.exe")
    parser.add_argument("--worker-manifest", type=Path, default=ROOT / "docs/worker_runtime.json",
                        help="Build/protocol evidence and exact Worker file hashes")
    parser.add_argument("--vc-runtime-dir", type=Path, help="Licensed app-local Microsoft C++ CRT directory")
    parser.add_argument("--build-only", action="store_true",
                        help="Build and stage only; skip analyze/tests and leave runtime acceptance unverified")
    args = parser.parse_args()
    worker = None
    worker_report = None
    worker_evidence = None
    if args.worker_dir is not None:
        _assert_no_reparse_components(args.worker_dir)
        _assert_no_reparse_components(args.worker_manifest)
        worker = args.worker_dir.resolve(strict=True)
        worker_report = json.loads(args.worker_manifest.read_text(encoding="utf-8"))
        worker_evidence = verify_worker_inventory(worker, worker_report)
    metadata = json.loads((ROOT / "docs/flutter_toolchain.json").read_text(encoding="utf-8"))
    sdk = Path(metadata["sdk"]["sdk_root"])
    shim = Path(metadata["trusted_git_shim"]["path"])
    git = Path(metadata["trusted_git_shim"]["installed_git_executable"])
    checks = [(sdk / "bin/internal/shared.bat", metadata["launcher_source_audit"]["zip_and_extracted_source_sha256_crlf"]),
              (shim, metadata["trusted_git_shim"]["sha256"]), (git, metadata["trusted_git_shim"]["installed_git_sha256"])]
    for file, expected in checks:
        if digest(file) != expected:
            raise RuntimeError("Existing SDK audit changed: " + str(file))
    run = ROOT / "private/toolchains/cache" / ("windows-build-" + uuid.uuid4().hex)
    run.mkdir()
    source = run / "ui"
    source.mkdir()
    for name in ("lib", "test", "web", "assets"):
        copy_directory(ROOT / "ui" / name, source / name)
    copy_windows_source(ROOT / "ui/windows", source / "windows")
    for name in ("pubspec.yaml", "pubspec.lock", "analysis_options.yaml", "l10n.yaml"):
        origin = ROOT / "ui" / name
        if origin.is_file():
            shutil.copyfile(origin, source / name)
    if not (source / "pubspec.lock").is_file():
        raise RuntimeError("A final locked UI dependency graph is required")
    environment = os.environ.copy()
    for key, value in metadata["cli_validation"]["cli_environment_for_ui_agent"].items():
        if key not in ("PATH_prefix", "PATH_modification_scope"):
            environment[key] = str(value)
    environment["PATH"] = str(shim.parent) + os.pathsep + environment.get("PATH", "")
    registry = OwnedProcessRegistry(threading.Event())
    commands = flutter_commands(args.build_only)
    try:
        with registry_scope(registry):
            for label, arguments in commands:
                print("Flutter " + label, flush=True)
                with (run / (label + ".stdout.log")).open("xb") as stdout, (run / (label + ".stderr.log")).open("xb") as stderr:
                    process = spawn_owned_process([str(sdk / "bin/flutter.bat"), "--suppress-analytics", "--no-version-check"] + arguments,
                                                   cwd=str(source), env=environment, stdout=stdout, stderr=stderr,
                                                   stdin=subprocess.DEVNULL)
                    code = process.wait(timeout=1200)
                    registry.discard(process)
                if code:
                    raise RuntimeError("Flutter " + label + " failed; retained logs: " + str(run))
    finally:
        if registry.snapshot():
            registry.terminate_all()
    compiled = source / "build/windows/x64/runner/Release"
    if not (compiled / "ChaSteady.exe").is_file() or not (compiled / "flutter_windows.dll").is_file():
        raise RuntimeError("No genuine native Windows release output")
    release = ROOT / "private/releases" / ("windows-x64-" + uuid.uuid4().hex)
    release.mkdir(parents=True)
    bundle = release / "app"
    copy_directory(compiled, bundle, omit_debug=True)
    copy_directory(source / "build/web", bundle / "web")
    worker_present = worker is not None
    if worker_present:
        copy_directory(worker, bundle / "Worker", omit_debug=True)
        worker_evidence = verify_worker_inventory(bundle / "Worker", worker_report)
    if args.vc_runtime_dir is not None:
        _assert_no_reparse_components(args.vc_runtime_dir)
        crt = args.vc_runtime_dir.resolve(strict=True)
        _assert_no_reparse_components(crt)
        libraries = list(crt.glob("*.dll"))
        if not libraries:
            raise RuntimeError("No app-local C++ runtime libraries")
        for library in libraries:
            _assert_no_reparse_components(library)
            destination = bundle / library.name
            if destination.exists():
                if digest(destination) != digest(library):
                    raise RuntimeError("Conflicting application-local runtime library")
                continue
            shutil.copyfile(library, destination)
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, bundle / name)
    shutil.copyfile(ROOT / "docs/WINDOWS_PORTABLE_GUIDE.md", bundle / "README.md")
    copy_directory(ROOT / "docs/licenses", bundle / "licenses")
    with (bundle / "BUILD_STATUS.json").open("x", encoding="utf-8") as stream:
        json.dump({"native_compiled": True, "worker_packaged": worker_present,
                   "build_only": args.build_only, "prebuild_tests_run": not args.build_only,
                   "runtime_acceptance_verified": False, "signed": False,
                   "public_distribution_cleared": False,
                   "license_path_in_this_bundle": "licenses/",
                   "notice_source_paths": "docs/ paths in THIRD_PARTY_NOTICES refer to source-checkout provenance, not bundled diagnostic logs"},
                  stream, ensure_ascii=False, indent=2)
    manifest = bundle_metadata(bundle, worker_present)
    manifest["build_only"] = args.build_only
    manifest["prebuild_tests_run"] = not args.build_only
    manifest["worker_inventory_verification"] = worker_evidence
    manifest["logs"] = str(run)
    with (release / "bundle-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    print("Native build and logs: " + str(run), flush=True)
    print("Staged app: " + str(bundle), flush=True)
    if not worker_present:
        print("Incomplete runtime package: no Worker.exe; do not call this a usable delivery.", flush=True)


if __name__ == "__main__":
    main()
