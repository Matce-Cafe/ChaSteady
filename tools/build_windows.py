"""Build native Flutter and stage a fresh relocatable Windows application bundle."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
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


class ProductVersionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductVersion:
    major: int
    minor: int
    patch: int
    build: int

    def __post_init__(self):
        if any(type(part) is not int or not 0 <= part <= 65535 for part in self.windows_version):
            raise ProductVersionError("Product version must contain four uint16 components")

    @property
    def windows_version(self):
        return self.major, self.minor, self.patch, self.build

    @property
    def version(self):
        return ".".join(map(str, self.windows_version[:3]))

    @property
    def build_number(self):
        return str(self.build)

    @property
    def pubspec_version(self):
        return self.version + "+" + self.build_number

    @property
    def package_stem(self):
        return "ChaSteady-" + self.pubspec_version + "-Windows-x64"

    def metadata(self):
        return {"product_version": self.version, "build_number": self.build_number,
                "pubspec_version": self.pubspec_version, "version_source": "ui/pubspec.yaml",
                "package_stem": self.package_stem}


def parse_product_version(value):
    # 四段均受 PE 的 WORD 上限约束；不接受预发布、前导零或可注入参数的字符。
    component = r"(0|[1-9][0-9]{0,4})"
    if type(value) is not str or not re.fullmatch(
            component + r"\." + component + r"\." + component + r"\+" + component, value):
        raise ProductVersionError("Product version must be canonical major.minor.patch+build")
    return ProductVersion(*(int(part) for part in re.split(r"[.+]", value)))


def read_product_version(pubspec):
    # 只接受有界 pubspec 的规范顶层映射子集，避免引入 YAML 执行器或歧义键。
    pubspec = Path(pubspec)
    try:
        _assert_no_reparse_components(pubspec)
        if not pubspec.is_file() or not 0 < pubspec.stat().st_size <= 65536:
            raise ProductVersionError("Product pubspec must be a bounded regular UTF-8 file")
        with pubspec.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ProductVersionError("Product pubspec must be a bounded regular UTF-8 file")
        text = raw.decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError, ValueError) as error:
        raise ProductVersionError("Product pubspec must be a bounded regular UTF-8 file") from error
    if any(ord(character) < 32 and character != "\n" for character in text):
        raise ProductVersionError("Product pubspec must use unique canonical top-level keys and one plain version")
    seen, version, current_key = set(), None, None
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith(" "):
            # YAML 的缩进续行会改变实际版本标量，不能只截取第一行接受。
            if current_key == "version":
                raise ProductVersionError("Product pubspec must use unique canonical top-level keys and one plain version")
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?: +(.*))?", line.rstrip(" "))
        if match is None or match[1] in seen:
            raise ProductVersionError("Product pubspec must use unique canonical top-level keys and one plain version")
        current_key = match[1]
        seen.add(current_key)
        if current_key == "version":
            value = (match[2] or "").split(" #", 1)[0].rstrip(" ")
            version = parse_product_version(value)
    if version is None:
        raise ProductVersionError("Product pubspec must use unique canonical top-level keys and one plain version")
    return version


def parse_fixed_file_info(raw):
    # VS_FIXEDFILEINFO 固定为 13 个小端 DWORD，不依赖本机 ctypes 结构对齐。
    if type(raw) is not bytes or len(raw) != 52:
        raise ProductVersionError("Windows fixed version resource is invalid")
    fields = struct.unpack("<13I", raw)
    if fields[0] != 0xFEEF04BD or fields[1] != 0x00010000:
        raise ProductVersionError("Windows fixed version resource is invalid")
    def components(high, low):
        return high >> 16, high & 65535, low >> 16, low & 65535
    return {"file_version": components(fields[2], fields[3]),
            "product_version": components(fields[4], fields[5])}


def _read_windows_fixed_file_info(executable):
    if os.name != "nt":
        raise ProductVersionError("Windows product version resource requires the Windows system API")
    import ctypes
    from ctypes import wintypes

    # 只从 System32 加载系统版本 API；读取资源，不加载或启动待验应用。
    api = ctypes.WinDLL("version.dll", use_last_error=True, winmode=0x00000800)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    api.VerQueryValueW.restype = wintypes.BOOL
    ignored = wintypes.DWORD()
    size = api.GetFileVersionInfoSizeW(str(executable), ctypes.byref(ignored))
    if not 52 <= size <= 16 * 1024 * 1024:
        raise ProductVersionError("Windows product version resource could not be read safely")
    buffer = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(executable), 0, size, buffer):
        raise ProductVersionError("Windows product version resource could not be read safely")
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        raise ProductVersionError("Windows product version resource could not be read safely")
    start = ctypes.addressof(buffer)
    if length.value != 52 or pointer.value is None or not start <= pointer.value <= start + size - 52:
        raise ProductVersionError("Windows product version resource could not be read safely")
    return ctypes.string_at(pointer, 52)


def verify_windows_product_version(directory, product_version):
    # 调用方只交付受控输出目录，固定读取其中的 ChaSteady.exe。
    directory = Path(directory)
    try:
        _assert_no_reparse_components(directory)
        executable = directory / "ChaSteady.exe"
        _assert_no_reparse_components(executable)
        if not directory.is_absolute() or not executable.is_file():
            raise ProductVersionError("Windows product version input must be a controlled regular application output")
        executable = executable.resolve(strict=True)
        if executable.parent != directory.resolve(strict=True):
            raise ProductVersionError("Windows product version input must be a controlled regular application output")
        fixed = parse_fixed_file_info(_read_windows_fixed_file_info(executable))
    except (OSError, ValueError) as error:
        raise ProductVersionError("Windows product version resource could not be read safely") from error
    if any(value != product_version.windows_version for value in fixed.values()):
        raise ProductVersionError("Windows file or product version differs from the product pubspec")
    # 字符串资源可能不含 build；以两个固定四段数值为准，不做原始字符串相等判断。
    return {"fixed_file_version": ".".join(map(str, fixed["file_version"])),
            "fixed_product_version": ".".join(map(str, fixed["product_version"])),
            "matches_pubspec": True, "scope": "static_windows_version_resource_only",
            "executable_executed": False, "runtime_acceptance_verified": False}


def flutter_commands(build_only=False, product_version=None):
    defines, build_version = [], []
    if product_version is not None:
        if type(product_version) is not ProductVersion:
            raise ProductVersionError("Flutter product version must be a validated ProductVersion")
        defines = ["--dart-define=CHASTEADY_PRODUCT_VERSION=" + product_version.version,
                   "--dart-define=CHASTEADY_BUILD_NUMBER=" + product_version.build_number]
        build_version = ["--build-name=" + product_version.version,
                         "--build-number=" + product_version.build_number]
    commands = [
        ("pub", ["pub", "get", "--enforce-lockfile"]),
        ("l10n", ["gen-l10n"]),
    ]
    if not build_only:
        commands.extend([("analyze", ["analyze", "--no-pub"]),
                         ("test", ["test", "--no-pub", "--reporter", "expanded"] + defines)])
    commands.extend([
        ("windows", ["build", "windows", "--release"] + build_version + defines),
        ("web", ["build", "web", "--release", "--no-web-resources-cdn", "--pwa-strategy=none"]
         + build_version + defines),
    ])
    return commands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-summary", action="store_true",
                        help="Print bounded source product-version JSON only; do not run a build")
    parser.add_argument("--worker-dir", type=Path, help="Verified PyInstaller onedir containing Worker.exe")
    parser.add_argument("--worker-manifest", type=Path, default=ROOT / "docs/worker_runtime.json",
                        help="Build/protocol evidence and exact Worker file hashes")
    parser.add_argument("--vc-runtime-dir", type=Path, help="Licensed app-local Microsoft C++ CRT directory")
    parser.add_argument("--build-only", action="store_true",
                        help="Build and stage only; skip analyze/tests and leave runtime acceptance unverified")
    args = parser.parse_args()
    if args.version_summary:
        try:
            summary = read_product_version(ROOT / "ui/pubspec.yaml").metadata()
        except ProductVersionError:
            parser.error("Product pubspec is missing or invalid")
        print(json.dumps(summary, ensure_ascii=True))
        return
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
    product_version = read_product_version(source / "pubspec.yaml")
    commands = flutter_commands(args.build_only, product_version=product_version)
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
    release = ROOT / "private/releases" / (product_version.package_stem + "-" + uuid.uuid4().hex)
    release.mkdir(parents=True)
    bundle = release / "app"
    copy_directory(compiled, bundle, omit_debug=True)
    pe_version = verify_windows_product_version(bundle, product_version)
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
        json.dump({**product_version.metadata(), "windows_pe_version": pe_version,
                   "native_compiled": True, "worker_packaged": worker_present,
                   "build_only": args.build_only, "prebuild_tests_run": not args.build_only,
                   "runtime_acceptance_verified": False, "signed": False,
                   "public_distribution_cleared": False,
                   "license_path_in_this_bundle": "licenses/",
                   "notice_source_paths": "docs/ paths in THIRD_PARTY_NOTICES refer to source-checkout provenance, not bundled diagnostic logs"},
                  stream, ensure_ascii=False, indent=2)
    manifest = bundle_metadata(bundle, worker_present)
    manifest.update(product_version.metadata())
    manifest["windows_pe_version"] = pe_version
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
