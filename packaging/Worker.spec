# PyInstaller one-directory Worker bundle. Build only with tools/freeze_worker.py.
from pathlib import Path
import hashlib
import json
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_submodules


SPEC_PATH = Path(SPECPATH).resolve()
if SPEC_PATH.is_file():
    SPEC_PATH = SPEC_PATH.parent
PROJECT_ROOT = SPEC_PATH.parent
WORKER_SOURCE = PROJECT_ROOT / "worker"
ENTRYPOINT = PROJECT_ROOT / "tools" / "worker_desktop_entry.py"
manifest_argument = os.environ.get("CHASTEADY_WORKER_RUNTIME_MANIFEST")
manifest_sha256 = os.environ.get("CHASTEADY_WORKER_RUNTIME_MANIFEST_SHA256")
if not manifest_argument or not manifest_sha256:
    raise RuntimeError("freeze_worker.py must pass the verified runtime manifest path and SHA-256")
MANIFEST_PATH = Path(manifest_argument)
if (not MANIFEST_PATH.is_absolute() or MANIFEST_PATH.is_symlink()
        or not MANIFEST_PATH.resolve(strict=True).is_relative_to((PROJECT_ROOT / "docs").resolve(strict=True))):
    raise RuntimeError("worker runtime manifest must be a regular file inside project docs")

for path in (WORKER_SOURCE, ENTRYPOINT.parent, MANIFEST_PATH):
    if not path.exists() or path.is_symlink():
        raise RuntimeError("required trusted worker build input is missing or linked: " + path.name)

manifest_bytes = MANIFEST_PATH.read_bytes()
if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
    raise RuntimeError("worker runtime manifest changed after freezer validation")
manifest = json.loads(manifest_bytes.decode("utf-8"))
if manifest.get("status") not in ("provisioned", "freeze_in_progress", "tests_passed"):
    raise RuntimeError("worker runtime manifest does not describe a provisioned candidate")
if manifest.get("python", {}).get("version") != "3.15.0":
    raise RuntimeError("worker runtime manifest is not pinned to CPython 3.15.0")
package_rows = {row.get("name"): row for row in manifest.get("packages", [])}
required_packages = {
    "numpy": "2.5.4",
    "scipy": "1.18.1",
    "opencv-python-headless": "5.0.0.93",
    "pyinstaller": "6.22.3",
    "pyinstaller-hooks-contrib": "2026.8",
}
for name, version in required_packages.items():
    row = package_rows.get(name, {})
    if (row.get("version") != version or row.get("latest_release_version") != version
            or row.get("latest_release_metadata_checked") is not True):
        raise RuntimeError("worker runtime manifest lacks the latest-verified pin for " + name)
if package_rows["pyinstaller"].get("pyinstaller_exception_notice_detected") is not True:
    raise RuntimeError("PyInstaller redistribution exception notice was not found in the audited wheel")

# collect_submodules discovers the backend's importlib-loaded modules. Its
# source directory is explicitly added; no cwd or user site is used.
sys.path.insert(0, str(WORKER_SOURCE))
backend_hidden = collect_submodules("cha_stabilizer")


def runtime_module(name):
    return not set(name.split(".")).intersection({"tests", "test", "benchmarks", "examples"})


nonruntime_data = ["**/tests/**", "**/test/**", "**/benchmarks/**", "**/examples/**"]
scipy_data, scipy_binaries, scipy_hidden = collect_all(
    "scipy", filter_submodules=runtime_module, exclude_datas=nonruntime_data)
cv2_data, cv2_binaries, cv2_hidden = collect_all(
    "cv2", filter_submodules=runtime_module, exclude_datas=nonruntime_data)


def unique_pairs(items):
    result, seen = [], set()
    for source, destination in items:
        key = (os.path.normcase(os.path.abspath(source)), destination.replace("\\", "/").casefold())
        if key not in seen:
            seen.add(key)
            result.append((source, destination))
    return result


def safe_notice_source(relative_path, expected_sha256):
    source = PROJECT_ROOT / Path(*Path(relative_path).parts)
    resolved = source.resolve(strict=True)
    if not resolved.is_relative_to((PROJECT_ROOT / "docs" / "licenses").resolve(strict=True)):
        raise RuntimeError("license notice escaped the project notice root")
    if not source.is_file() or source.is_symlink():
        raise RuntimeError("a verified runtime license notice is missing or linked")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError("a runtime license notice changed after PyPI hash verification")
    destination = "licenses/" + resolved.relative_to((PROJECT_ROOT / "docs" / "licenses").resolve(strict=True)).as_posix()
    return str(source), destination


datas = []
datas.extend(scipy_data)
datas.extend(cv2_data)

# Validate the package/runtime notices here, but keep them in the app-root
# license tree rather than duplicating them inside Worker. The native bundler
# places UI at app/web and project licenses at app/licenses.
for notice in manifest.get("python", {}).get("license_audit", {}).get("files", []):
    safe_notice_source(notice["path"], notice["sha256"])
for package in manifest.get("packages", []):
    if package.get("role") != "frozen application":
        continue
    for notice in package.get("license_files", []):
        if not notice.get("project_copy"):
            raise RuntimeError("a verified package license notice has no project copy")
        safe_notice_source(notice["project_copy"], notice["sha256"])

datas = unique_pairs(datas)
binaries = []
binaries.extend(scipy_binaries)
binaries.extend(cv2_binaries)
binaries.extend(collect_dynamic_libs("numpy"))
binaries = unique_pairs(binaries)
hiddenimports = sorted(set(backend_hidden + scipy_hidden + cv2_hidden))

analysis = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(WORKER_SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory=".",
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Worker",
)
