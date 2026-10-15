"""Test and freeze the private desktop Worker.exe candidate.

Run from the trusted project root with the CPython executable recorded in
`docs/worker_runtime.json`. This builds a console-mode onedir bundle in a new
private/toolchains UUID directory, then checks its stdio protocol with a fresh
private data root. It never packages source media, profiles, SDKs, or the local
Gyroflow probe report.
"""
import argparse
import base64
import hashlib
import http.client
import ipaddress
import json
import os
import queue
import re
import shutil
import stat
import struct
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


PYTHON_VERSION = "3.15.0"
PYTHON_VERSION_TUPLE = tuple(int(part) for part in PYTHON_VERSION.split("."))
PYTHON_TAG = "python" + "".join(PYTHON_VERSION.split(".")[:2])
PINNED = {
    "numpy": "2.5.4",
    "scipy": "1.18.1",
    "opencv-python-headless": "5.0.0.93",
    "pyinstaller": "6.22.3",
    "pyinstaller-hooks-contrib": "2026.8",
    "altgraph": "0.17.5",
    "packaging": "26.3",
    "pefile": "2024.8.26",
    "pywin32-ctypes": "0.2.3",
    "setuptools": "84.0.0",
    "pip": "26.2.1",
}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".wav", ".mp3", ".m4a"}
MAX_PROTOCOL_LINE = 1024 * 1024


def reparse(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(root, relative, must_exist=True):
    rel = Path(relative)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError("manifest path is not project-relative")
    target = root.joinpath(*rel.parts)
    resolved = target.resolve(strict=must_exist)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("manifest path escaped the project root")
    cursor = root.resolve(strict=True)
    for part in rel.parts:
        cursor = cursor / part
        if reparse(cursor):
            raise ValueError("reparse point found in a verified toolchain path")
    return target


def write_report(path, value):
    if reparse(path) or reparse(path.parent):
        raise ValueError("runtime report path is linked")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    encoded = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with temporary.open("xb") as output:
        output.write(encoded)
    for attempt in range(5):
        try:
            if reparse(path) or reparse(path.parent):
                raise ValueError("runtime report path became linked")
            os.replace(str(temporary), str(path))
            return
        except PermissionError as error:
            # Windows readers/scanners may briefly deny rename/delete sharing.
            # Never alter ACLs, close another process, or discard the old report.
            if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == 4:
                raise
            time.sleep(0.05 * (2 ** attempt))


def clean_env(stage, runtime_root):
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    env_id = uuid.uuid4().hex
    temp = stage / ("freeze-temp-" + env_id)
    temp.mkdir(exist_ok=False)
    home = stage / ("freeze-home-" + env_id)
    pyinstaller_config = stage / ("freeze-pyinstaller-config-" + env_id)
    for folder in ("appdata", "localappdata", "home"):
        (home / folder).mkdir(parents=True, exist_ok=True)
    pyinstaller_config.mkdir(exist_ok=False)
    return {
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "PATH": os.pathsep.join([str(runtime_root), str(Path(system_root) / "System32"), system_root]),
        "TEMP": str(temp), "TMP": str(temp),
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "localappdata"),
        "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": os.devnull,
        "PIP_CACHE_DIR": str(stage / "pip-cache"), "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYINSTALLER_CONFIG_DIR": str(pyinstaller_config), "SETUPTOOLS_USE_DISTUTILS": "local",
    }


def validate_manifest(root, manifest):
    if manifest.get("status") != "provisioned":
        raise ValueError("worker runtime has not completed private provisioning")
    if manifest.get("python", {}).get("version") != PYTHON_VERSION:
        raise ValueError("worker runtime manifest is not CPython " + PYTHON_VERSION)
    if manifest.get("python", {}).get("sigstore_attestation_check", {}).get("artifact_sha256") != manifest["python"].get("published_sha256"):
        raise ValueError("CPython archive digest is not tied to the official Sigstore metadata")
    if manifest.get("python", {}).get("download", {}).get("sha256") != manifest["python"].get("published_sha256"):
        raise ValueError("downloaded CPython archive does not match its published digest")
    sigstore_record = manifest["python"].get("sigstore_attestation_check", {})
    evidence = safe_path(root, sigstore_record.get("evidence_file", ""))
    if sha256_file(evidence) != sigstore_record.get("evidence_sha256"):
        raise ValueError("saved python.org Sigstore digest evidence changed")
    bundle = json.loads(evidence.read_text(encoding="utf-8"))
    entries = bundle.get("verificationMaterial", {}).get("tlogEntries", [])
    if len(entries) != 1 or entries[0].get("kindVersion", {}).get("kind") != "hashedrekord":
        raise ValueError("saved Sigstore evidence does not contain its expected digest record")
    hashed = json.loads(base64.b64decode(entries[0].get("canonicalizedBody", ""), validate=True).decode("utf-8"))
    if hashed.get("spec", {}).get("data", {}).get("hash", {}).get("value", "").lower() != manifest["python"].get("published_sha256"):
        raise ValueError("saved Sigstore evidence digest does not match the Python archive pin")
    toolchain_root = safe_path(root, manifest["toolchain_root"])
    runtime_root = safe_path(root, manifest["python"]["runtime_root"])
    if not runtime_root.is_relative_to(toolchain_root):
        raise ValueError("private CPython extraction is outside its UUID toolchain directory")
    python_exe = safe_path(root, manifest["python"]["interpreter"])
    if python_exe.name.lower() != "python.exe" or not python_exe.is_file():
        raise ValueError("private embeddable python.exe is unavailable")
    pth_key = PYTHON_TAG + "_pth_sha256_after"
    pth = runtime_root / (PYTHON_TAG + "._pth")
    if sha256_file(pth) != manifest["python"].get(pth_key):
        raise ValueError("private Python path configuration changed after audit")
    records = {row.get("name"): row for row in manifest.get("packages", [])}
    for name, version in PINNED.items():
        record = records.get(name)
        if (not record or record.get("version") != version or record.get("yanked") is not False
                or record.get("latest_release_version") != version
                or record.get("latest_release_metadata_checked") is not True):
            raise ValueError("runtime package pin is missing, changed, yanked, or not latest-verified: " + name)
        wheel_path = safe_path(root, str(Path(record["download_path"]).resolve().relative_to(root.resolve())))
        if sha256_file(wheel_path) != record["sha256"] or record.get("sha256_published") != record["sha256"]:
            raise ValueError("verified wheel changed after provisioning: " + name)
        for notice in record.get("license_files", []):
            if not notice.get("project_copy"):
                raise ValueError("package license notice was not copied into the project")
            copy = safe_path(root, notice["project_copy"])
            if sha256_file(copy) != notice["sha256"]:
                raise ValueError("package license notice changed after provisioning: " + name)
    if records["pyinstaller"].get("pyinstaller_exception_notice_detected") is not True:
        raise ValueError("PyInstaller GPL exception notice is not present in the audited distribution")
    for notice in manifest["python"]["license_audit"]["files"]:
        copy = safe_path(root, notice["path"])
        if sha256_file(copy) != notice["sha256"]:
            raise ValueError("CPython license notice changed after provisioning")
    archive_dir = toolchain_root / "downloads"
    archives = list(archive_dir.glob("cpython-*/" + manifest["python"]["archive"]))
    if len(archives) != 1 or reparse(archives[0]) or sha256_file(archives[0]) != manifest["python"]["published_sha256"]:
        raise ValueError("private CPython download archive is missing or changed")
    env = clean_env(toolchain_root, runtime_root)
    command = [str(python_exe), "-I", "-c",
               "import importlib.metadata as m, json, numpy, scipy, cv2, PyInstaller, site, sys; "
               "print(json.dumps({'version':list(sys.version_info[:3]),'isolated':sys.flags.isolated,"
               "'enable_user_site':site.ENABLE_USER_SITE,'numpy':m.version('numpy'),"
               "'scipy':m.version('scipy'),'opencv':m.version('opencv-python-headless'),"
               "'pyinstaller':PyInstaller.__version__,'sys_path':sys.path}))"]
    result = subprocess.run(command, cwd=str(root), env=env, check=True, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=120)
    info = json.loads(result.stdout.strip().splitlines()[-1])
    if info["version"] != list(PYTHON_VERSION_TUPLE) or info["isolated"] != 1 or info["enable_user_site"] not in (False, None):
        raise ValueError("private CPython did not retain its isolated configuration")
    expected_runtime_paths = {runtime_root.resolve(), (runtime_root / (PYTHON_TAG + ".zip")).resolve(),
                              (runtime_root / "Lib" / "site-packages").resolve()}
    actual_paths = {Path(item).resolve(strict=False) for item in info["sys_path"] if item}
    if not actual_paths.issubset(expected_runtime_paths) or (root.resolve() in actual_paths):
        raise ValueError("CPython sys.path contains a project cwd, global site, or external path")
    return toolchain_root, runtime_root, python_exe, env, info


def source_privacy_findings(root):
    pattern = re.compile(
        r"(?i)(?:A Night of Euphony Reverse 1999 Concert|C:[\\/]APPS(?:[\\/]|\b)|"
        r"C:[\\/]Users[\\/]|C:[\\/]Program Files[\\/]WindowsApps(?:[\\/]|\b)|"
        r"C:[\\/]Program Files[\\/]Sony(?:[\\/]|\b))"
    )
    findings = []
    source_root = root / "worker" / "cha_stabilizer"
    for path in sorted(source_root.rglob("*.py")):
        if reparse(path):
            raise ValueError("backend source tree contains a linked Python file")
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            findings.append(path.relative_to(root).as_posix())
    return findings


def run_worker_tests(root, python_exe, stage, runtime_root, env):
    temp_root = stage / "modern-test-temp"
    temp_root.mkdir(exist_ok=False)
    runner = r'''import os, pathlib, sys, tempfile, unittest
root = pathlib.Path(sys.argv[1]).resolve(strict=True)
temp_root = pathlib.Path(sys.argv[2]).resolve(strict=True)
os.environ["TEMP"] = os.environ["TMP"] = str(temp_root)
tempfile.tempdir = str(temp_root)
sys.path.insert(0, str(root / "worker"))
suite = unittest.defaultTestLoader.discover(str(root / "worker" / "tests"), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
    command = [str(python_exe), "-I", "-c", runner, str(root), str(temp_root)]
    result = subprocess.run(command, cwd=str(root), env=env, capture_output=True, timeout=1800)
    stdout = result.stdout.decode("utf-8", "replace")
    stderr = result.stderr.decode("utf-8", "replace")
    diagnostic_files = []
    for name, data in (("modern-tests-stdout.log", result.stdout), ("modern-tests-stderr.log", result.stderr)):
        path = stage / name
        with path.open("xb") as output:
            output.write(data)
        diagnostic_files.append({"path": str(path.relative_to(root)).replace("\\", "/"),
                                 "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    combined = stdout + "\n" + stderr
    match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", combined)
    test_count = int(match.group(1)) if match else None
    summary_match = re.search(r"(?m)^(?:OK|FAILED)(?:\s+\(([^)]*)\))?\s*$", combined)
    summary_details = summary_match.group(1) if summary_match else ""
    skipped_match = re.search(r"\bskipped=(\d+)\b", summary_details or "")
    skipped_count = int(skipped_match.group(1)) if skipped_match else 0
    passed = result.returncode == 0 and test_count is not None and test_count >= 127 and "OK" in combined
    return {"passed": passed, "exit_code": result.returncode,
            "test_count": test_count, "minimum_expected_test_count": 127,
            "skipped_count": skipped_count,
            "executed_test_count": test_count - skipped_count if test_count is not None else None,
            "duration_seconds": float(match.group(2)) if match else None,
            "summary": "OK" if passed else "FAILED",
            "command": "<private CPython {}/python.exe -I unittest discover worker/tests/test_*.py".format(PYTHON_VERSION),
            "diagnostics_captured": bool(stderr), "diagnostic_files_saved_privately": diagnostic_files}


def run_v9_golden(root, python_exe, runtime_root, env):
    script = root / "tools" / "regress_v9.py"
    if not script.is_file() or reparse(script):
        raise FileNotFoundError("the trusted V9 math golden regression script is missing")
    command = [str(python_exe), "-I", str(script)]
    result = subprocess.run(command, cwd=str(root), env=env, check=False, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=1800)
    rows = []
    for line in result.stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "matrix_max_absolute_error" in row:
            rows.append({"window": row.get("window"),
                         "matrix_max_absolute_error": row.get("matrix_max_absolute_error"),
                         "weight_max_absolute_error": row.get("weight_max_absolute_error"),
                         "scope": row.get("scope")})
    passed = result.returncode == 0 and len(rows) == 3 and all(
        isinstance(row.get("matrix_max_absolute_error"), (int, float))
        and row["matrix_max_absolute_error"] <= 1e-9
        and isinstance(row.get("weight_max_absolute_error"), (int, float))
        and row["weight_max_absolute_error"] <= 1e-10
        and row.get("scope") == "mathematical_port_regression_not_perceptual_validation"
        for row in rows
    )
    return {"passed": passed, "exit_code": result.returncode, "rows": rows,
            "rendered": False, "full_source_export": False,
            "scope": "V9 mathematical golden comparison only; no real media render or perceptual winner claim",
            "command": "<private CPython {}/python.exe -I tools/regress_v9.py".format(PYTHON_VERSION),
            "diagnostics_captured": bool(result.stderr)}


def pe_subsystem(executable):
    with executable.open("rb") as stream:
        dos = stream.read(64)
        if len(dos) < 64 or dos[:2] != b"MZ":
            raise ValueError("Worker.exe lacks an MZ header")
        pe_offset = struct.unpack_from("<I", dos, 0x3C)[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError("Worker.exe lacks a PE header")
        coff = stream.read(20)
        if len(coff) != 20:
            raise ValueError("Worker.exe has a truncated COFF header")
        optional_size = struct.unpack_from("<H", coff, 16)[0]
        optional = stream.read(optional_size)
        if len(optional) < 70:
            raise ValueError("Worker.exe has a truncated optional header")
        magic = struct.unpack_from("<H", optional, 0)[0]
        if magic not in (0x10B, 0x20B):
            raise ValueError("Worker.exe has an unsupported PE optional header")
        return struct.unpack_from("<H", optional, 68)[0]


def verify_bundled_python_dll(bundle_root, runtime_root, manifest):
    filename = PYTHON_TAG + ".dll"
    source = runtime_root / filename
    candidates = list(bundle_root.rglob(filename))
    if len(candidates) > 1:
        raise ValueError("Worker bundle contains multiple CPython runtime DLL copies")
    if not candidates:
        return {"file": filename, "bundled": False, "source_authenticode_signature": "not applicable"}
    bundled = candidates[0]
    if reparse(bundled) or not source.is_file() or reparse(source):
        raise ValueError("CPython runtime DLL or bundled copy is not a regular file")
    source_hash = sha256_file(source)
    bundle_hash = sha256_file(bundled)
    if source_hash != bundle_hash:
        raise ValueError("bundled {} differs from the Authenticode-checked runtime file".format(filename))
    check = manifest.get("python", {}).get("pe_authenticode_check", {})
    row = next((item for item in check.get("files", []) if item.get("file") == filename), {})
    return {"file": filename, "bundled": True,
            "bundle_path": bundled.relative_to(bundle_root).as_posix(),
            "sha256_matches_verified_runtime": True, "sha256": bundle_hash,
            "source_authenticode_status": row.get("status"), "signer_subject": row.get("signer_subject"),
            "thumbprint": row.get("thumbprint")}


def drain_stdout(stream, output_queue):
    while True:
        line = stream.readline(MAX_PROTOCOL_LINE + 2)
        if len(line) > MAX_PROTOCOL_LINE:
            output_queue.put("__oversize__")
            return
        output_queue.put(line)
        if not line:
            return


def copy_file_checked(source, destination, expected_sha256):
    if not source.is_file() or reparse(source) or sha256_file(source) != expected_sha256:
        raise ValueError("runtime license notice is missing or changed before smoke staging")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or reparse(destination):
        raise FileExistsError("smoke license target is not a new regular file")
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    if sha256_file(destination) != expected_sha256:
        raise ValueError("smoke license copy failed SHA-256 verification")


def copy_tree_checked(source, destination):
    if not source.is_dir() or reparse(source) or destination.exists() or reparse(destination):
        raise ValueError("smoke staging source must be a real directory and target must be new")
    for path in source.rglob("*"):
        if reparse(path):
            raise ValueError("smoke staging source contains a reparse point")
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES:
            raise ValueError("smoke staging source contains media")
    shutil.copytree(source, destination)


def smoke_worker(resource_root, worker_dir, stage, runtime_root, env):
    executable = worker_dir / "Worker.exe"
    worker_env = dict(env)
    system_root = worker_env.get("SystemRoot", r"C:\Windows")
    worker_env["PATH"] = os.pathsep.join([str(worker_dir), str(Path(system_root) / "System32"), system_root])
    for key in list(worker_env):
        if key.upper().startswith("PYTHON") or key.upper() in ("VIRTUAL_ENV", "CONDA_PREFIX", "FLUTTER_ROOT"):
            worker_env.pop(key, None)
    worker_path = worker_env["PATH"].lower()
    if str(runtime_root.resolve()).lower() in worker_path or "flutter" in worker_path:
        raise ValueError("frozen worker smoke PATH still includes a developer Python/Flutter runtime")
    if any(key in worker_env for key in ("PYTHONHOME", "PYTHONPATH", "FLUTTER_ROOT")):
        raise ValueError("frozen worker smoke environment retained a developer runtime variable")
    help_result = subprocess.run([str(executable), "--help"], cwd=str(resource_root), env=worker_env,
                                 capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    help_text = (help_result.stdout + help_result.stderr).decode("utf-8", "replace")
    if (help_result.returncode != 0 or "--desktop" not in help_text or "--resource-root" not in help_text
            or "--data-root" not in help_text):
        raise RuntimeError("frozen worker desktop-root CLI help did not pass")
    data_root = stage / "smoke-data-root"
    data_root.mkdir(exist_ok=False)
    if resource_root.resolve().is_relative_to(data_root.resolve()) or data_root.resolve().is_relative_to(resource_root.resolve()):
        raise ValueError("worker smoke data root overlaps the resource bundle")
    stderr_path = stage / "worker-smoke-stderr.log"
    lines = queue.Queue()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    stderr_file = stderr_path.open("xb")
    process = None
    try:
        process = subprocess.Popen(
            [str(executable), "--desktop", "--resource-root", str(resource_root), "--data-root", str(data_root)],
            cwd=str(resource_root), env=worker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=stderr_file, creationflags=flags, bufsize=0,
        )
        reader = threading.Thread(target=drain_stdout, args=(process.stdout, lines), daemon=True)
        reader.start()

        def read_line(timeout):
            try:
                line = lines.get(timeout=timeout)
            except queue.Empty as exc:
                raise RuntimeError("frozen worker did not answer its private pipe request") from exc
            if line in (b"", "__oversize__"):
                raise RuntimeError("frozen worker closed or exceeded the bounded stdout protocol")
            value = json.loads(line.decode("utf-8", "strict"))
            if not isinstance(value, dict):
                raise RuntimeError("frozen worker emitted a non-object protocol line")
            return value

        ready = read_line(30)
        origin = ready.get("origin")
        parsed = urlsplit(origin or "")
        if (ready.get("type") != "ready" or ready.get("protocol") != 1
                or ready.get("pid") != process.pid or not ready.get("bearer")
                or not ready.get("native_capability") or parsed.scheme != "http"):
            raise RuntimeError("frozen worker ready handshake failed validation")
        host = parsed.hostname
        if host != "127.0.0.1" or not parsed.port:
            raise RuntimeError("frozen worker origin was not an explicit loopback address")
        if not ipaddress.ip_address(host).is_loopback:
            raise RuntimeError("frozen worker origin was not loopback")
        capability = ready["native_capability"]

        source_index = resource_root / "web" / "index.html"
        if not source_index.is_file() or reparse(source_index):
            raise FileNotFoundError("staged app resource root lacks web/index.html")
        static = http.client.HTTPConnection(host, parsed.port, timeout=15)
        try:
            static.request("GET", "/", headers={
                "Authorization": "Bearer " + ready["bearer"],
                "Origin": origin,
                "Sec-Fetch-Site": "same-origin",
            })
            static_response = static.getresponse()
            static_status = static_response.status
            static_type = static_response.getheader("Content-Type", "")
            static_body = static_response.read(2 * 1024 * 1024 + 1)
        finally:
            static.close()
        if (static_status != 200 or len(static_body) > 2 * 1024 * 1024
                or not static_type.lower().startswith("text/html")
                or hashlib.sha256(static_body).hexdigest() != sha256_file(source_index)):
            raise RuntimeError("authenticated loopback GET did not serve the staged app/web index exactly")

        request_id = "freeze-web-session"
        request = {"protocol": 1, "request_id": request_id, "capability": capability, "action": "web_session"}
        process.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8"))
        process.stdin.flush()
        response = read_line(15)
        if response.get("request_id") != request_id or response.get("ok") is not True:
            raise RuntimeError("frozen worker web_session request failed")
        session_url = response.get("result", {}).get("url", "")
        session = urlsplit(session_url)
        if session.scheme != "http" or session.hostname != host or session.port != parsed.port:
            raise RuntimeError("frozen worker web session did not match its ready origin")

        try:
            process.stdin.close()
        except OSError:
            pass
        eof_exit = process.wait(timeout=20)
        reader.join(timeout=5)
        if eof_exit != 0:
            raise RuntimeError("frozen worker did not exit cleanly after private-pipe EOF")
        stderr_file.flush()
        stderr_file.close()
        eof_diagnostic = stderr_path.read_bytes()
        if ready["bearer"].encode("utf-8") in eof_diagnostic or capability.encode("utf-8") in eof_diagnostic:
            raise RuntimeError("frozen worker wrote a private credential to stderr")

        # A second instance verifies the explicit shutdown request separately
        # from stdin EOF cleanup, using a distinct private data directory.
        shutdown_data_root = stage / "smoke-shutdown-data-root"
        shutdown_data_root.mkdir(exist_ok=False)
        if resource_root.resolve().is_relative_to(shutdown_data_root.resolve()) or shutdown_data_root.resolve().is_relative_to(resource_root.resolve()):
            raise ValueError("worker shutdown data root overlaps the resource bundle")
        shutdown_stderr_path = stage / "worker-shutdown-stderr.log"
        stderr_path = shutdown_stderr_path
        stderr_file = stderr_path.open("xb")
        lines = queue.Queue()
        process = subprocess.Popen(
            [str(executable), "--desktop", "--resource-root", str(resource_root), "--data-root", str(shutdown_data_root)],
            cwd=str(resource_root), env=worker_env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=stderr_file, creationflags=flags, bufsize=0,
        )
        reader = threading.Thread(target=drain_stdout, args=(process.stdout, lines), daemon=True)
        reader.start()
        shutdown_ready = read_line(30)
        shutdown_origin = urlsplit(shutdown_ready.get("origin", ""))
        if (shutdown_ready.get("type") != "ready" or shutdown_ready.get("protocol") != 1
                or shutdown_ready.get("pid") != process.pid or not shutdown_ready.get("native_capability")
                or shutdown_origin.scheme != "http" or shutdown_origin.hostname != "127.0.0.1"
                or not shutdown_origin.port or not shutdown_ready.get("bearer")):
            raise RuntimeError("frozen worker second ready handshake failed validation")
        request_id = "freeze-shutdown"
        request = {"protocol": 1, "request_id": request_id,
                   "capability": shutdown_ready["native_capability"], "action": "shutdown"}
        process.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8"))
        process.stdin.flush()
        response = read_line(15)
        if response.get("request_id") != request_id or response.get("ok") is not True:
            raise RuntimeError("frozen worker shutdown request failed")
        try:
            process.stdin.close()
        except OSError:
            pass
        shutdown_exit = process.wait(timeout=20)
        reader.join(timeout=5)
        if shutdown_exit != 0:
            raise RuntimeError("frozen worker exited with a non-zero status after shutdown")
        stderr_file.flush()
        stderr_file.close()
        shutdown_diagnostic = shutdown_stderr_path.read_bytes()
        if (shutdown_ready["bearer"].encode("utf-8") in shutdown_diagnostic
                or shutdown_ready["native_capability"].encode("utf-8") in shutdown_diagnostic):
            raise RuntimeError("frozen worker wrote a private credential to stderr")
        return {"passed": True, "exit_code": shutdown_exit, "eof_exit_code": eof_exit,
                "console_subsystem": pe_subsystem(executable), "desktop_cli_help": True,
                "created_no_window": True, "ready_protocol": 1, "web_session_request": True,
                "static_get": {"status": static_status, "content_type": static_type,
                               "bytes": len(static_body), "sha256": hashlib.sha256(static_body).hexdigest(),
                               "bearer_header_sent": True, "credential_logged": False},
                "stdin_eof_shutdown": True, "explicit_shutdown_request": True,
                "credentials_recorded": False, "resource_root_argument": "<app bundle root>",
                "worker_executable_relative": "Worker/Worker.exe", "data_roots_separate": True,
                "worker_runtime_on_path": False, "pythonhome_set": False, "pythonpath_set": False,
                "developer_flutter_path_required": False,
                "diagnostic_file_bytes": [len(eof_diagnostic), len(shutdown_diagnostic)],
                "data_roots": [str(data_root.relative_to(stage)).replace("\\", "/"),
                               str(shutdown_data_root.relative_to(stage)).replace("\\", "/")]}
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=10)
            except Exception:
                pass
        if not stderr_file.closed:
            stderr_file.close()


def inventory_bundle(bundle_root):
    rows, total, videos = [], 0, []
    for path in sorted(bundle_root.rglob("*")):
        if reparse(path):
            raise ValueError("reparse point found in frozen worker bundle")
        if not path.is_file():
            continue
        relative = path.relative_to(bundle_root).as_posix()
        if path.suffix.lower() in VIDEO_SUFFIXES:
            videos.append(relative)
        record = {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        rows.append(record)
        total += record["bytes"]
    if videos:
        raise ValueError("frozen worker bundle unexpectedly contains media files")
    native_files = [item["path"] for item in rows if Path(item["path"]).suffix.lower() in (".dll", ".pyd")]
    return {"files": rows, "file_count": len(rows), "total_bytes": total,
            "native_binary_files": native_files,
            "video_or_audio_files": videos, "bundle_sha256": hashlib.sha256(
                "\n".join(item["path"] + ":" + item["sha256"] for item in rows).encode("utf-8")
            ).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path, help="provision report path; defaults to docs/worker_runtime.json")
    parser.add_argument("--web-root", type=Path, required=True,
                        help="verified final offline web build to stage at app/web for the real resource-root smoke")
    parser.add_argument("--no-tests", action="store_true", help="refused; tests are mandatory before freezing")
    args = parser.parse_args()
    if args.no_tests:
        parser.error("modern backend tests and V9 math goldens are mandatory")
    root = args.root.resolve(strict=True)
    web_root = args.web_root.resolve(strict=True)
    if not web_root.is_relative_to(root):
        raise ValueError("verified final web artifact must stay under the D: project root")
    if (not web_root.is_dir() or reparse(web_root) or not (web_root / "index.html").is_file()
            or not (web_root / "flutter_bootstrap.js").is_file()):
        raise ValueError("--web-root must be the verified final offline Flutter web artifact")
    if os.name != "nt" or sys.maxsize < 2 ** 32:
        raise RuntimeError("Worker.exe must be frozen on 64-bit Windows")
    manifest_path = args.manifest.resolve() if args.manifest else root / "docs" / "worker_runtime.json"
    if not manifest_path.is_relative_to((root / "docs").resolve(strict=True)) or reparse(manifest_path):
        raise ValueError("runtime manifest must be a regular file inside project docs")
    report = json.loads(manifest_path.read_text(encoding="utf-8"))
    toolchain_root, runtime_root, python_exe, env, runtime_check = validate_manifest(root, report)
    pe_check = report["python"].get("pe_authenticode_check", {})
    report["python"]["authenticity_scope"] = {
        "download_sha256_matched_pythonorg_sigstore_bundle_digest": True,
        "sigstore_certificate_and_rekor_proof_cryptographically_verified": False,
        "pe_authenticode_signature_check_performed": pe_check.get("performed") is True,
        "pe_authenticode_file_results": pe_check.get("files", []),
    }
    source_findings = source_privacy_findings(root)
    if source_findings:
        report["freeze"] = {"status": "blocked_source_privacy", "source_files_with_machine_specific_paths": source_findings,
                            "bundle_created": False, "completed_utc": datetime.now(timezone.utc).isoformat()}
        write_report(manifest_path, report)
        print(json.dumps(report["freeze"], indent=2), file=sys.stderr)
        return 2

    freeze_id = uuid.uuid4().hex
    stage = root / "private" / "toolchains" / ("worker-freeze-" + freeze_id)
    stage.mkdir(exist_ok=False)
    dist = stage / "dist"
    work = stage / "work"
    dist.mkdir()
    work.mkdir()
    report["test_facts"] = {"modern_worker_tests": "running", "v9_math_golden": "not run", "frozen_worker": "not built"}
    report["freeze"] = {"status": "tests_running", "toolchain_root": str(stage.relative_to(root)).replace("\\", "/"),
                        "runtime_check": runtime_check, "source_privacy_findings": [],
                        "bundle_created": False, "completed_utc": datetime.now(timezone.utc).isoformat()}
    write_report(manifest_path, report)

    try:
        tests = run_worker_tests(root, python_exe, stage, runtime_root, env)
        report["test_facts"]["modern_worker_tests"] = tests
        if not tests["passed"]:
            report["freeze"] = {"status": "blocked_worker_tests", "toolchain_root": str(stage.relative_to(root)).replace("\\", "/"),
                                "bundle_created": False, "completed_utc": datetime.now(timezone.utc).isoformat()}
            write_report(manifest_path, report)
            print(json.dumps({"status": report["freeze"]["status"], "tests": tests["summary"],
                              "test_count": tests["test_count"]}, indent=2), file=sys.stderr)
            return 2

        golden = run_v9_golden(root, python_exe, runtime_root, env)
        report["test_facts"]["v9_math_golden"] = golden
        if not golden["passed"]:
            report["freeze"] = {"status": "blocked_v9_math_golden", "toolchain_root": str(stage.relative_to(root)).replace("\\", "/"),
                                "bundle_created": False, "completed_utc": datetime.now(timezone.utc).isoformat()}
            write_report(manifest_path, report)
            print(json.dumps({"status": report["freeze"]["status"], "golden_rows": golden["rows"]}, indent=2), file=sys.stderr)
            return 2

        report["freeze"]["status"] = "tests_passed"
        report["freeze"]["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write_report(manifest_path, report)
        command = [str(python_exe), "-I", "-m", "PyInstaller", "--noconfirm", "--clean",
                   "--distpath", str(dist), "--workpath", str(work),
                   str(root / "packaging" / "Worker.spec")]
        build_env = dict(env)
        build_env["CHASTEADY_WORKER_RUNTIME_MANIFEST"] = str(manifest_path)
        build_env["CHASTEADY_WORKER_RUNTIME_MANIFEST_SHA256"] = sha256_file(manifest_path)
        build = subprocess.run(command, cwd=str(root), env=build_env, check=False, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=3600)
        if build.returncode != 0:
            diagnostic_files = []
            for label, text in (("pyinstaller-stdout.log", build.stdout), ("pyinstaller-stderr.log", build.stderr)):
                path = stage / label
                data = text.encode("utf-8", "replace")
                with path.open("xb") as output:
                    output.write(data)
                diagnostic_files.append({"path": str(path.relative_to(root)).replace("\\", "/"),
                                         "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            report["freeze"] = {"status": "failed_pyinstaller", "toolchain_root": str(stage.relative_to(root)).replace("\\", "/"),
                                "exit_code": build.returncode, "diagnostic_files_saved_privately": diagnostic_files,
                                "bundle_created": False, "completed_utc": datetime.now(timezone.utc).isoformat()}
            write_report(manifest_path, report)
            print(json.dumps({"status": report["freeze"]["status"], "exit_code": build.returncode,
                              "diagnostic_logs": [item["path"] for item in diagnostic_files]}, indent=2), file=sys.stderr)
            return 2
        worker_bundle = dist / "Worker"
        executable = worker_bundle / "Worker.exe"
        if not executable.is_file() or reparse(executable):
            raise FileNotFoundError("PyInstaller did not create a regular onedir Worker.exe")
        subsystem = pe_subsystem(executable)
        if subsystem != 3:
            raise ValueError("Worker.exe is not a console-subsystem executable; inherited stdio would be unsafe")
        if (worker_bundle / "web").exists() or (worker_bundle / "ui").exists():
            raise ValueError("Worker onedir must not duplicate the app-root offline UI")
        cpython_dll_check = verify_bundled_python_dll(worker_bundle, runtime_root, report)

        # Match the native bundle exactly without fabricating a main EXE: its
        # resource root is app/, with Worker/ and web/ siblings.
        smoke_app_root = stage / "smoke-app"
        smoke_app_root.mkdir(exist_ok=False)
        smoke_worker_dir = smoke_app_root / "Worker"
        copy_tree_checked(worker_bundle, smoke_worker_dir)
        copy_tree_checked(web_root, smoke_app_root / "web")
        web_inventory = inventory_bundle(web_root)
        staged_web_inventory = inventory_bundle(smoke_app_root / "web")
        web_asset_summary = {
            "source_path": str(web_root.relative_to(root)).replace("\\", "/"),
            "source_bundle_sha256": web_inventory["bundle_sha256"],
            "staged_bundle_sha256": staged_web_inventory["bundle_sha256"],
            "files": web_inventory["file_count"], "bytes": web_inventory["total_bytes"],
            "copy_matches_source": web_inventory["bundle_sha256"] == staged_web_inventory["bundle_sha256"],
        }
        if not web_asset_summary["copy_matches_source"]:
            raise ValueError("staged app/web differs from the verified final web artifact")
        if (smoke_app_root / "docs" / "gyroflow_export_probe.json").exists():
            raise ValueError("machine-specific probe report must not enter staged app resources")

        expected_notices = []
        for notice in report["python"]["license_audit"]["files"]:
            expected_notices.append((notice["path"], notice["sha256"]))
        for package in report["packages"]:
            if package.get("role") != "frozen application":
                continue
            for notice in package.get("license_files", []):
                expected_notices.append((notice["project_copy"], notice["sha256"]))
        app_license_root = smoke_app_root / "licenses"
        app_license_root.mkdir(exist_ok=False)
        for relative, digest in expected_notices:
            source = safe_path(root, relative)
            license_relative = source.relative_to(root / "docs" / "licenses")
            staged_notice = app_license_root / license_relative
            copy_file_checked(source, staged_notice, digest)

        pypi_license_sources = []
        for package in report["packages"]:
            if package.get("role") != "frozen application":
                continue
            pypi_license_sources.append({
                "name": package["name"], "version": package["version"],
                "wheel_source": package["source"], "wheel_sha256": package["sha256"],
                "notice_files": [{"project_path": notice["project_copy"], "sha256": notice["sha256"],
                                  "bytes": notice["bytes"]} for notice in package.get("license_files", [])],
            })
        license_coverage = {
            "python_runtime": {
                "version": report["python"]["version"], "archive_source": report["python"]["source"],
                "archive_sha256": report["python"]["published_sha256"],
                "notice_files": [{"project_path": notice["path"], "sha256": notice["sha256"],
                                  "bytes": notice["bytes"]} for notice in report["python"]["license_audit"]["files"]],
            },
            "pypi_frozen_packages": pypi_license_sources,
            "notice_source_root": "docs/licenses/python-runtime and docs/licenses/python-worker-runtime",
            "main_bundle_notice_destination": "app/licenses (main build copies docs/licenses)",
            "smoke_stage_notice_destination": "smoke-app/licenses",
            "copied_notice_file_count": len(expected_notices),
            "bundled_native_file_count": None,
            "unresolved": [
                "This is an inventory of extracted notices, not a legal review or redistribution clearance.",
                "Microsoft Visual C++/Windows runtime terms for any redistributable DLLs were not independently reviewed.",
                "External release, signing, and publication are not authorized by this local freeze task.",
            ],
        }
        smoke = smoke_worker(smoke_app_root, smoke_worker_dir, stage, runtime_root, env)
        inventory = inventory_bundle(worker_bundle)
        license_coverage["bundled_native_file_count"] = len(inventory["native_binary_files"])
        license_coverage["native_file_paths"] = inventory["native_binary_files"]
        files = inventory["files"]
        expected_path = worker_bundle.relative_to(root)
        report["test_facts"]["frozen_worker"] = {
            "passed": True,
            "path": str(expected_path).replace("\\", "/"),
            "executable": str((expected_path / "Worker.exe")).replace("\\", "/"),
            "resource_root": "production app root (ChaSteady.exe parent; sibling directories Worker/ and web/)",
            "smoke_resource_root": str(smoke_app_root.relative_to(root)).replace("\\", "/"),
            "resource_root_layout": {"worker_executable": "app/Worker/Worker.exe", "offline_web": "app/web",
                                     "licenses": "app/licenses (copied by main bundler from docs/licenses)",
                                     "gyroflow_probe_report": "absent; release remains unverified"},
            "launch_contract": "app/Worker/Worker.exe --desktop --resource-root <app root> --data-root <separate per-user data root>",
            "stdio": "console bootloader; CREATE_NO_WINDOW; inherited stdin/stdout pipes; stderr to owned diagnostic file",
            "pe_subsystem": subsystem,
            "inventory": inventory,
            "native_pipe_smoke": smoke,
            "worker_onedir_contains_web": False,
            "cpython_dll_authenticode_lineage": cpython_dll_check,
            "worker_exe_authenticode_signing_performed": False,
            "worker_exe_authenticode_signature_verified": False,
            "worker_exe_authenticode_status": "not checked",
            "sigstore_verification_performed": False,
            "license_notice_files": len(expected_notices),
            "license_coverage": license_coverage,
            "bundle_contains_media": False,
            "bundle_contains_machine_specific_gyroflow_probe": False,
            "bundle_contains_full_source_video_or_profile_state": False,
            "package_build_output": "private local candidate only; no signing or publishing",
        }
        report["freeze"] = {"status": "built_and_smoke_tested", "toolchain_root": str(stage.relative_to(root)).replace("\\", "/"),
                            "bundle_created": True, "pyinstaller_version": "6.22.3",
                            "build_command": ["<private CPython {}/python.exe".format(PYTHON_VERSION), "-I", "-m", "PyInstaller",
                                              "--noconfirm", "--clean", "--distpath", "<private>/dist",
                                              "--workpath", "<private>/work", "packaging/Worker.spec"],
                            "completed_utc": datetime.now(timezone.utc).isoformat()}
        write_report(manifest_path, report)
        print(json.dumps({"status": report["freeze"]["status"], "modern_tests": tests["test_count"],
                          "v9_golden_rows": len(golden["rows"]), "bundle": report["test_facts"]["frozen_worker"]["path"],
                          "files": inventory["file_count"], "bytes": inventory["total_bytes"],
                          "native_pipe_smoke": smoke["passed"]}, indent=2))
        return 0
    except Exception as exc:
        report["freeze"] = {"status": "failed", "toolchain_root": str(stage.relative_to(root)).replace("\\", "/"),
                            "error_type": type(exc).__name__, "error": str(exc),
                            "bundle_created": (stage / "dist" / "Worker").is_dir(),
                            "completed_utc": datetime.now(timezone.utc).isoformat()}
        write_report(manifest_path, report)
        print(json.dumps({"status": report["freeze"]["status"], "error_type": type(exc).__name__,
                          "error": str(exc), "toolchain_root": report["freeze"]["toolchain_root"]}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
