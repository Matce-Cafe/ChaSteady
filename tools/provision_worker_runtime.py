"""Provision a private CPython 3.15.0 worker/freezer environment.

Run from the trusted project root with the existing isolated interpreter:
  private/venv/Scripts/python.exe -I tools/provision_worker_runtime.py --root .

The existing 3.9 venv/global Python are never modified. Downloads and ZIP
extractions each receive separate, new UUID directories; archives are audited
as data before extraction or use. Only python.org and the pinned PyPI hosts are
allowed, and all HTTP redirects are rejected.
"""
import argparse
import base64
import csv
import email.parser
import hashlib
import io
import json
import gzip
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


PYTHON_VERSION = "3.15.0"
PYTHON_TAG = "python" + "".join(PYTHON_VERSION.split(".")[:2])
PYTHON_VERSION_TUPLE = tuple(int(part) for part in PYTHON_VERSION.split("."))
PYTHON_URL = "https://www.python.org/ftp/python/3.15.0/python-3.15.0-embed-amd64.zip"
PYTHON_RELEASE_URL = "https://www.python.org/downloads/release/python-3150/"
PYTHON_SIGSTORE_URL = PYTHON_URL + ".sigstore"
PYTHON_FILENAME = "python-3.15.0-embed-amd64.zip"
PYTHON_SHA256 = "a6999bcbcbe56f937159ef79c2630260eca99f65f7860bc5cd20430324079a44"
PYTHON_MAX_ARCHIVE = 128 * 1024 * 1024
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_MEMBER = 1024 * 1024 * 1024
MAX_ENTRIES = 200000
MAX_RATIO = 2000

# Exact non-yanked Windows-compatible wheels. This tool rechecks each version
# against PyPI's current stable release JSON, its version-specific JSON record,
# the published SHA-256, the downloaded bytes, wheel RECORD, and archive bounds.
WHEELS = [
    {"name": "numpy", "version": "2.5.4", "filename": "numpy-2.5.4-cp315-cp315-win_amd64.whl", "sha256": "332f3378fe077dd850e677ec01bdcc4f22368fb5d50ef10b2c79230b1bf5a592", "tag": "cp315-cp315-win_amd64", "freeze": True},
    {"name": "scipy", "version": "1.18.1", "filename": "scipy-1.18.1-cp315-cp315-win_amd64.whl", "sha256": "92c14f5bdbfb6216315ce33e78080474082de8b3830122ba97809bfbe65f75c0", "tag": "cp315-cp315-win_amd64", "freeze": True},
    {"name": "opencv-python-headless", "version": "5.0.0.93", "module_version": "5.0.0", "filename": "opencv_python_headless-5.0.0.93-cp37-abi3-win_amd64.whl", "sha256": "829717b6a95554f273e49e357cee3b3a2a26b6f4842fbc1bed2b45bdd8f87e0e", "tag": "cp37-abi3-win_amd64", "freeze": True},
    {"name": "pyinstaller", "version": "6.22.3", "filename": "pyinstaller-6.22.3-py3-none-win_amd64.whl", "sha256": "500bd58c7bf7e584a8435adccbd763a0b918d5c12b08d74ff50fd79b2915458b", "tag": "py3-none-win_amd64", "freeze": True},
    {"name": "pyinstaller-hooks-contrib", "version": "2026.8", "filename": "pyinstaller_hooks_contrib-2026.8-py3-none-any.whl", "sha256": "6d21d65323ea4467753afc21f52d7d0e69416ae8101dd88269bf273ad48db084", "tag": "py3-none-any", "freeze": True},
    {"name": "altgraph", "version": "0.17.5", "filename": "altgraph-0.17.5-py2.py3-none-any.whl", "sha256": "f3a22400bce1b0c701683820ac4f3b159cd301acab067c51c653e06961600597", "tag": "py2.py3-none-any", "freeze": True},
    {"name": "packaging", "version": "26.3", "filename": "packaging-26.3-py3-none-any.whl", "sha256": "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c", "tag": "py3-none-any", "freeze": True},
    {"name": "pefile", "version": "2024.8.26", "filename": "pefile-2024.8.26-py3-none-any.whl", "sha256": "76f8b485dcd3b1bb8166f1128d395fa3d87af26360c2358fb75b80019b957c6f", "tag": "py3-none-any", "freeze": True},
    {"name": "pywin32-ctypes", "version": "0.2.3", "filename": "pywin32_ctypes-0.2.3-py3-none-any.whl", "sha256": "8a1513379d709975552d202d942d9837758905c8d01eb82b8bcc30918929e7b8", "tag": "py3-none-any", "freeze": True},
    {"name": "setuptools", "version": "84.0.0", "filename": "setuptools-84.0.0-py3-none-any.whl", "sha256": "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670", "tag": "py3-none-any", "freeze": True},
    {"name": "pip", "version": "26.2.1", "filename": "pip-26.2.1-py3-none-any.whl", "sha256": "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e", "tag": "py3-none-any", "freeze": False},
]

PYTHON_HOSTS = {"www.python.org"}
PYPI_HOSTS = {"pypi.org", "files.pythonhosted.org"}
LICENSE_PREFIXES = ("license", "licence", "copying", "notice", "copyright")
SETUPTOOLS_PTH_EXPECTED = (
    "import os; var = 'SETUPTOOLS_USE_DISTUTILS'; enabled = os.environ.get(var, 'local') == 'local'; "
    "enabled and __import__('_distutils_hack').add_shim();"
)


class SourceRedirectBlocked(RuntimeError):
    def __init__(self, url, status, location):
        self.url = url
        self.status = status
        self.location = location
        host = urlparse(location).hostname if location else None
        super().__init__("source returned HTTP {} redirect to {}; redirect was not followed".format(status, host or "an invalid URL"))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def allowed_url(url, hosts):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise ValueError("URL is outside the approved HTTPS source allowlist")
    return parsed


def get_bytes(url, hosts, limit=16 * 1024 * 1024):
    allowed_url(url, hosts)
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    request = Request(url, headers={"User-Agent": "ChaSteady-private-runtime-audit/1.0", "Accept-Encoding": "identity"})
    try:
        response = opener.open(request, timeout=60)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise SourceRedirectBlocked(url, exc.code, exc.headers.get("Location", "")) from exc
        raise RuntimeError("approved source returned HTTP {}".format(exc.code)) from exc
    except URLError as exc:
        raise RuntimeError("approved source connection failed: {}".format(type(exc.reason).__name__)) from exc
    with response:
        final_url = response.geturl()
        if final_url != url:
            raise RuntimeError("source changed URL despite redirect rejection")
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise RuntimeError("response exceeds the configured size limit")
        chunks, total = [], 0
        while True:
            block = response.read(min(1024 * 1024, limit + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > limit:
                raise RuntimeError("response exceeds the configured size limit")
        content = b"".join(chunks)
        encoding = response.headers.get("Content-Encoding", "").lower().strip()
        if encoding == "gzip":
            expanded, expanded_size = [], 0
            with gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb") as stream:
                while True:
                    block = stream.read(min(1024 * 1024, limit + 1 - expanded_size))
                    if not block:
                        break
                    expanded.append(block)
                    expanded_size += len(block)
                    if expanded_size > limit:
                        raise RuntimeError("decompressed metadata response exceeds size limit")
            content = b"".join(expanded)
        elif encoding not in ("", "identity"):
            raise RuntimeError("unsupported compressed metadata response")
        return content, {"status": response.status, "content_length": total, "content_type": response.headers.get("Content-Type"),
                         "content_encoding": encoding or "identity"}


def verify_python_sigstore_bundle(path, project_root):
    transfer = download(PYTHON_SIGSTORE_URL, PYTHON_HOSTS, path, limit=16 * 1024 * 1024)
    raw = path.read_bytes()
    bundle = json.loads(raw.decode("utf-8"))
    if bundle.get("mediaType") != "application/vnd.dev.sigstore.bundle.v0.3+json":
        raise ValueError("python.org returned an unexpected Sigstore bundle format")
    entries = bundle.get("verificationMaterial", {}).get("tlogEntries", [])
    if len(entries) != 1 or entries[0].get("kindVersion", {}).get("kind") != "hashedrekord":
        raise ValueError("python.org Sigstore bundle lacks a single Rekor hashedrekord entry")
    canonical = base64.b64decode(entries[0].get("canonicalizedBody", ""), validate=True)
    attestation = json.loads(canonical.decode("utf-8"))
    digest = attestation.get("spec", {}).get("data", {}).get("hash", {})
    if digest.get("algorithm") != "sha256" or digest.get("value", "").lower() != PYTHON_SHA256:
        raise ValueError("python.org Sigstore bundle digest does not match the pinned CPython archive")
    return {"url": PYTHON_SIGSTORE_URL, "http_status": transfer["http_status"], "bytes": transfer["bytes"],
            "evidence_file": str(path.relative_to(project_root)).replace("\\", "/"),
            "evidence_sha256": transfer["sha256"], "artifact_sha256": digest["value"].lower(),
            "rekor_hashedrekord_present": True,
            "cryptographic_signature_and_inclusion_proof_independently_verified": False}


def download(url, hosts, path, limit):
    allowed_url(url, hosts)
    if path.exists() or path.is_symlink():
        raise FileExistsError("download target already exists")
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    request = Request(url, headers={"User-Agent": "ChaSteady-private-runtime-audit/1.0", "Accept-Encoding": "identity"})
    try:
        response = opener.open(request, timeout=120)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise SourceRedirectBlocked(url, exc.code, exc.headers.get("Location", "")) from exc
        raise RuntimeError("approved source returned HTTP {}".format(exc.code)) from exc
    except URLError as exc:
        raise RuntimeError("approved source connection failed: {}".format(type(exc.reason).__name__)) from exc
    digest = hashlib.sha256()
    total = 0
    with response, path.open("xb") as out:
        if response.geturl() != url:
            raise RuntimeError("source changed URL despite redirect rejection")
        encoding = response.headers.get("Content-Encoding", "").lower().strip()
        if encoding not in ("", "identity"):
            raise RuntimeError("binary archive response used unexpected HTTP content encoding")
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise RuntimeError("download exceeds the configured size limit")
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise RuntimeError("download exceeds the configured size limit")
            digest.update(block)
            out.write(block)
    return {"url": url, "bytes": total, "sha256": digest.hexdigest(), "http_status": response.status,
            "content_type": response.headers.get("Content-Type")}


def reparse(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def canonical_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def safe_member(raw):
    if not raw or "\\" in raw or "\x00" in raw or raw.startswith("/"):
        raise ValueError("unsafe ZIP path")
    directory = raw.endswith("/")
    pieces = raw[:-1].split("/") if directory else raw.split("/")
    if not pieces or any(part in ("", ".", "..") or ":" in part for part in pieces):
        raise ValueError("unsafe ZIP path")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {"COM{}".format(i) for i in range(1, 10)} | {"LPT{}".format(i) for i in range(1, 10)}
    for part in pieces:
        if part.endswith((" ", ".")) or part.split(".")[0].upper() in reserved:
            raise ValueError("unsafe Windows ZIP path component")
    return PurePosixPath(*pieces), directory


def checked_members(archive_path, max_archive=MAX_ARCHIVE, max_expanded=MAX_EXPANDED):
    if not archive_path.is_file() or reparse(archive_path) or archive_path.stat().st_size > max_archive:
        raise ValueError("archive is missing, reparse-backed, or too large")
    seen, total, rows = set(), 0, []
    with zipfile.ZipFile(str(archive_path), "r") as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError("ZIP entry-count bound exceeded")
        for info in infos:
            member, directory = safe_member(info.filename)
            key = member.as_posix().casefold()
            if key in seen:
                raise ValueError("duplicate or case-colliding ZIP path")
            seen.add(key)
            mode = (info.external_attr >> 16) & 0xFFFF
            dos_attributes = info.external_attr & 0xFFFF
            kind = stat.S_IFMT(mode)
            if dos_attributes & 0x0400:
                raise ValueError("ZIP contains a Windows reparse-point attribute")
            if kind == stat.S_IFLNK or (kind not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError("ZIP contains a link or non-regular object")
            if (info.flag_bits & 0x1) != 0:
                raise ValueError("encrypted ZIP entries are not accepted")
            if info.file_size > MAX_MEMBER:
                raise ValueError("ZIP member exceeds the size bound")
            total += info.file_size
            if total > max_expanded:
                raise ValueError("ZIP expansion bound exceeded")
            if info.file_size and info.compress_size == 0:
                raise ValueError("invalid compressed-size metadata")
            if info.compress_size and info.file_size > max(info.compress_size, 1) * MAX_RATIO:
                raise ValueError("ZIP expansion ratio bound exceeded")
            if directory != info.is_dir():
                raise ValueError("inconsistent ZIP directory metadata")
            rows.append((info, member, directory))
        bad = archive.testzip()
        if bad is not None:
            raise ValueError("ZIP CRC check failed")
    return rows, total


def extract_checked(archive_path, destination, max_archive=MAX_ARCHIVE, max_expanded=MAX_EXPANDED):
    destination.mkdir(parents=True, exist_ok=False)
    if any(destination.iterdir()):
        raise RuntimeError("extraction directory must start empty")
    rows, expanded = checked_members(archive_path, max_archive=max_archive, max_expanded=max_expanded)
    root = destination.resolve(strict=True)
    with zipfile.ZipFile(str(archive_path), "r") as archive:
        for info, member, directory in rows:
            target = destination.joinpath(*member.parts)
            if not target.resolve(strict=False).is_relative_to(root):
                raise ValueError("ZIP member escaped extraction root")
            parent = target if directory else target.parent
            parent.mkdir(parents=True, exist_ok=True)
            cursor = root
            for part in parent.relative_to(destination).parts:
                cursor = cursor / part
                if reparse(cursor):
                    raise ValueError("reparse point appeared during extraction")
            if directory:
                continue
            with archive.open(info, "r") as source, target.open("xb") as output:
                copied = 0
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    copied += len(block)
                    if copied > info.file_size:
                        raise ValueError("ZIP member expanded past its declared length")
                    output.write(block)
                if copied != info.file_size:
                    raise ValueError("ZIP member length mismatch")
    return {"members": len(rows), "expanded_bytes": expanded, "crc_checked": True}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_record(extract_root, dist_info):
    record = dist_info / "RECORD"
    if not record.is_file() or reparse(record):
        raise ValueError("wheel lacks a regular RECORD")
    listed = {}
    with record.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) != 3:
                raise ValueError("malformed wheel RECORD row")
            relative = PurePosixPath(unquote(row[0]))
            if relative.is_absolute() or not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
                raise ValueError("unsafe RECORD path")
            key = relative.as_posix().casefold()
            if key in listed:
                raise ValueError("duplicate wheel RECORD path")
            listed[key] = (row[1], row[2])
    for path in extract_root.rglob("*"):
        if reparse(path):
            raise ValueError("reparse point found in extracted wheel")
        if not path.is_file():
            continue
        relative = path.relative_to(extract_root).as_posix()
        key = relative.casefold()
        if relative.endswith("/RECORD.jws") or relative.endswith("/RECORD.p7s"):
            continue
        if key not in listed:
            raise ValueError("wheel file is absent from RECORD")
        expected_hash, expected_size = listed[key]
        if key == record.relative_to(extract_root).as_posix().casefold():
            if expected_hash or expected_size:
                raise ValueError("wheel RECORD must not hash itself")
            continue
        if not expected_hash.startswith("sha256="):
            raise ValueError("wheel RECORD must use SHA-256")
        expected = expected_hash.split("=", 1)[1]
        actual = base64.urlsafe_b64encode(bytes.fromhex(sha256_file(path))).decode("ascii").rstrip("=")
        if actual != expected or (expected_size and int(expected_size) != path.stat().st_size):
            raise ValueError("wheel RECORD file hash/size mismatch")
    return True


def license_like(path):
    name = path.name.lower()
    return name.startswith(LICENSE_PREFIXES) or "third-party" in name or "3rd-party" in name


def audit_wheel(pin, wheel_path, audit_dir, pypi_metadata):
    source_digest = pypi_metadata["digests"]["sha256"].lower()
    if source_digest != pin["sha256"] or pypi_metadata.get("yanked", False):
        raise ValueError("PyPI release digest mismatch or yanked wheel for {}".format(pin["name"]))
    if wheel_path.name != pin["filename"] or sha256_file(wheel_path) != pin["sha256"]:
        raise ValueError("downloaded wheel filename/SHA-256 mismatch for {}".format(pin["name"]))
    archive_report = extract_checked(wheel_path, audit_dir, max_archive=MAX_ARCHIVE)
    dist_infos = list(audit_dir.glob("*.dist-info"))
    if len(dist_infos) != 1:
        raise ValueError("wheel must contain exactly one root dist-info directory")
    dist_info = dist_infos[0]
    metadata_path = dist_info / "METADATA"
    wheel_metadata = email.parser.Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
    if canonical_name(wheel_metadata.get("Name", "")) != canonical_name(pin["name"]):
        raise ValueError("wheel METADATA project name mismatch")
    if wheel_metadata.get("Version") != pin["version"]:
        raise ValueError("wheel METADATA version mismatch")
    wheel_text = (dist_info / "WHEEL").read_text(encoding="utf-8")
    tags = [line[5:].strip() for line in wheel_text.splitlines() if line.startswith("Tag: ")]
    parts = pin["filename"][:-4].split("-")[-3:]
    expected_tags = {"-".join((python_tag, abi_tag, platform_tag))
                     for python_tag in parts[0].split(".")
                     for abi_tag in parts[1].split(".")
                     for platform_tag in parts[2].split(".")}
    if not expected_tags.intersection(tags):
        raise ValueError("wheel WHEEL tag does not match pinned filename for {}".format(pin["name"]))
    verify_record(audit_dir, dist_info)
    startup_hooks = []
    for path in audit_dir.rglob("*"):
        lower = path.name.lower()
        if lower in ("sitecustomize.py", "usercustomize.py"):
            raise ValueError("wheel contains sitecustomize startup code")
        if lower.endswith(".pth"):
            relative = path.relative_to(audit_dir).as_posix()
            text = path.read_text(encoding="utf-8").strip()
            if (pin["name"] != "setuptools" or relative != "distutils-precedence.pth"
                    or text != SETUPTOOLS_PTH_EXPECTED):
                raise ValueError("wheel contains an unapproved .pth startup file")
            startup_hooks.append({"path": relative, "sha256": sha256_file(path),
                                  "purpose": "setuptools local distutils shim; no sys.path edits"})
    licenses = []
    for path in sorted(audit_dir.rglob("*")):
        if path.is_file() and license_like(path):
            relative = path.relative_to(audit_dir).as_posix()
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("license/notice file exceeds review limit")
            licenses.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    if not licenses:
        raise ValueError("wheel has no recognizable text license/notice files: {}".format(pin["name"]))
    pyinstaller_exception = None
    if pin["name"] == "pyinstaller":
        license_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in audit_dir.rglob("*") if path.is_file() and license_like(path)
        ).lower()
        pyinstaller_exception = "exception" in license_text and "gpl" in license_text
    return {
        "name": pin["name"], "version": pin["version"], "module_version": pin.get("module_version"),
        "filename": pin["filename"],
        "source": pypi_metadata["url"], "metadata_source": "https://pypi.org/pypi/{}/{}/json".format(pin["name"], pin["version"]),
        "sha256": pin["sha256"], "sha256_published": source_digest, "yanked": False,
        "latest_release_version": pypi_metadata.get("latest_release_version"),
        "latest_release_metadata_checked": pypi_metadata.get("latest_release_verified") is True,
        "requires_python": pypi_metadata.get("requires_python"), "requires_dist": wheel_metadata.get_all("Requires-Dist", []),
        "license": wheel_metadata.get("License-Expression") or wheel_metadata.get("License"),
        "license_files": licenses, "approved_startup_hooks": startup_hooks,
        "pyinstaller_exception_notice_detected": pyinstaller_exception,
        "wheel_tags": tags, "archive": archive_report,
        "audit_directory": str(audit_dir), "download_path": str(wheel_path),
        "role": "frozen application" if pin["freeze"] else "private build bootstrap only",
    }


def get_pypi_json(url, context):
    last_error = None
    for attempt in range(3):
        raw, _ = get_bytes(url, PYPI_HOSTS)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt == 2:
                raise ValueError("official PyPI JSON remained incomplete for {} ({} bytes, character {})".format(
                    context, len(raw), getattr(exc, "pos", "unknown"))) from exc
    raise ValueError("official PyPI JSON could not be parsed for {}: {}".format(context, type(last_error).__name__))


def pypi_release(pin):
    latest_url = "https://pypi.org/pypi/{}/json".format(pin["name"])
    latest = get_pypi_json(latest_url, pin["name"] + " latest-release metadata")
    latest_version = latest.get("info", {}).get("version")
    if latest_version != pin["version"]:
        raise ValueError("pinned {} {} is not PyPI's current latest stable release ({})".format(
            pin["name"], pin["version"], latest_version or "unknown"))

    url = "https://pypi.org/pypi/{}/{}/json".format(pin["name"], pin["version"])
    release = get_pypi_json(url, pin["name"] + " " + pin["version"] + " release metadata")
    if release.get("info", {}).get("version") != pin["version"]:
        raise ValueError("PyPI release version mismatch for {}".format(pin["name"]))
    candidates = [item for item in release.get("urls", []) if item.get("filename") == pin["filename"]]
    if len(candidates) != 1:
        raise ValueError("PyPI does not publish exactly one pinned wheel for {}".format(pin["name"]))
    item = candidates[0]
    if item.get("yanked") is not False:
        raise ValueError("refusing yanked or unclassified PyPI wheel for {}".format(pin["name"]))
    if item.get("digests", {}).get("sha256", "").lower() != pin["sha256"]:
        raise ValueError("published PyPI SHA-256 changed for {}".format(pin["name"]))
    allowed_url(item.get("url", ""), PYPI_HOSTS)
    if urlparse(item["url"]).hostname != "files.pythonhosted.org":
        raise ValueError("wheel download must be served by files.pythonhosted.org")
    item["requires_python"] = release.get("info", {}).get("requires_python")
    item["latest_release_version"] = latest_version
    item["latest_release_verified"] = True
    return item


def copy_file_new(source, destination):
    if not source.is_file() or reparse(source):
        raise ValueError("license source is not a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_file(destination) != sha256_file(source):
            raise FileExistsError("existing license copy differs; refusing overwrite")
        return
    with source.open("rb") as inp, destination.open("xb") as out:
        shutil.copyfileobj(inp, out, 1024 * 1024)


def collect_runtime_licenses(runtime_root, extraction_root, project_root):
    stdlib_zip = runtime_root / (PYTHON_TAG + ".zip")
    if not stdlib_zip.is_file() or reparse(stdlib_zip):
        raise ValueError("CPython embeddable archive lacks " + PYTHON_TAG + ".zip")
    stdlib_extract = extraction_root / ("python-stdlib-" + uuid.uuid4().hex)
    stdlib_audit = extract_checked(stdlib_zip, stdlib_extract)
    candidates = []
    for path in runtime_root.iterdir():
        if path.is_file() and license_like(path):
            candidates.append((path, PurePosixPath("archive") / path.name))
    for path in stdlib_extract.rglob("*"):
        if path.is_file() and license_like(path):
            candidates.append((path, PurePosixPath("stdlib") / path.relative_to(stdlib_extract).as_posix()))
    copied = []
    psf_found = False
    destination_root = project_root / "docs" / "licenses" / "python-runtime" / ("Python-" + PYTHON_VERSION)
    for source, relative in candidates:
        try:
            text = source.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        if "python software foundation" in text.lower():
            psf_found = True
        destination = destination_root.joinpath(*relative.parts)
        copy_file_new(source, destination)
        copied.append({"path": str(destination.relative_to(project_root)).replace("\\", "/"),
                       "sha256": sha256_file(source), "bytes": source.stat().st_size})
    if not psf_found:
        raise ValueError("CPython archive did not provide a readable PSF license notice")
    return {"stdlib_archive_audit": stdlib_audit, "files": copied, "psf_license_detected": psf_found}


def install_bootstrap_wheel(audit_dir, site_packages, runtime_root):
    site_packages.mkdir(parents=True, exist_ok=True)
    for source in sorted(audit_dir.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(audit_dir)
        parts = relative.parts
        data_index = next((i for i, part in enumerate(parts) if part.endswith(".data")), None)
        if data_index is None:
            target = site_packages.joinpath(*parts)
        else:
            if data_index != 0 or len(parts) < 3:
                raise ValueError("unexpected wheel .data layout")
            kind = parts[1]
            remainder = parts[2:]
            roots = {"purelib": site_packages, "platlib": site_packages, "scripts": runtime_root / "Scripts",
                     "data": runtime_root, "headers": runtime_root / "include"}
            if kind not in roots:
                raise ValueError("unsupported wheel .data directory")
            target = roots[kind].joinpath(*remainder)
        if not target.resolve(strict=False).is_relative_to(runtime_root.resolve(strict=True)):
            raise ValueError("wheel install target escapes private runtime")
        target.parent.mkdir(parents=True, exist_ok=True)
        if reparse(target.parent) or target.exists():
            raise ValueError("wheel bootstrap target is unsafe or already exists")
        with source.open("rb") as inp, target.open("xb") as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)


def clean_child_env(stage, runtime_root):
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    temp = stage / "temp"
    temp.mkdir(exist_ok=False)
    home = stage / "home"
    for name in ("appdata", "localappdata", "home"):
        (home / name).mkdir(parents=True, exist_ok=True)
    env = {
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "PATH": os.pathsep.join([str(runtime_root), str(Path(system_root) / "System32"), system_root]),
        "TEMP": str(temp), "TMP": str(temp),
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "appdata"), "LOCALAPPDATA": str(home / "localappdata"),
        "PIP_CONFIG_FILE": os.devnull, "PIP_CACHE_DIR": str(stage / "pip-cache"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1",
    }
    return env


def run_python(python_exe, args, cwd, env, timeout=600):
    command = [str(python_exe), "-I"] + list(args)
    return subprocess.run(command, cwd=str(cwd), env=env, check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def check_pe_authenticode(system_root, runtime_root):
    powershell = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file() or reparse(powershell):
        return {"performed": False, "status": "PowerShell unavailable", "trust_store_modified": False,
                "revocation_policy_modified": False}
    files = [runtime_root / "python.exe", runtime_root / (PYTHON_TAG + ".dll")]
    literals = ["'" + str(path).replace("'", "''") + "'" for path in files]
    script = (
        "$paths=@(" + ",".join(literals) + "); $rows=@(); "
        "foreach($p in $paths){$s=Get-AuthenticodeSignature -LiteralPath $p; "
        "$subject=$null; $thumb=$null; if($s.SignerCertificate){$subject=$s.SignerCertificate.Subject; $thumb=$s.SignerCertificate.Thumbprint}; "
        "$rows += [pscustomobject]@{file=[IO.Path]::GetFileName($p);status=$s.Status.ToString();signer_subject=$subject;thumbprint=$thumb}}; "
        "ConvertTo-Json -InputObject $rows -Compress"
    )
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                           cwd=str(Path(__file__).resolve().parents[1]), capture_output=True, timeout=60)
    try:
        rows = json.loads(result.stdout.decode("utf-8", "strict")) if result.returncode == 0 else []
    except (UnicodeDecodeError, ValueError):
        rows = []
    if isinstance(rows, dict):
        rows = [rows]
    return {"performed": bool(rows), "files": rows if isinstance(rows, list) else [],
            "exit_code": result.returncode, "trust_store_modified": False,
            "revocation_policy_modified": False,
            "revocation_network_behavior": "not instrumented; native PowerShell trust defaults used"}


def write_report(path, report, replace_existing):
    encoded = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if path.exists() or reparse(path):
        if not replace_existing:
            raise FileExistsError("refusing to overwrite an existing runtime report")
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        with temporary.open("xb") as output:
            output.write(encoded)
        os.replace(str(temporary), str(path))
    else:
        with path.open("xb") as output:
            output.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path, help="report path; defaults to docs/worker_runtime.json")
    parser.add_argument("--replace-report", action="store_true", help="replace an existing report while preserving it as previous_attempt")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if os.name != "nt" or sys.maxsize < 2 ** 32:
        raise RuntimeError("runtime provisioning requires a 64-bit Windows host")
    if sys.version_info < (3, 9):
        raise RuntimeError("trusted provisioning script interpreter must be Python 3.9 or newer")
    toolchains = root / "private" / "toolchains"
    if not toolchains.is_dir() or reparse(toolchains):
        raise RuntimeError("project private/toolchains directory must already exist and be non-reparse")
    run_id = uuid.uuid4().hex
    stage = toolchains / ("worker-runtime-" + run_id)
    stage.mkdir(exist_ok=False)
    downloads = stage / "downloads"
    extractions = stage / "audited-extractions"
    downloads.mkdir()
    extractions.mkdir()
    report_path = args.report.resolve() if args.report else root / "docs" / "worker_runtime.json"
    docs_root = (root / "docs").resolve(strict=True)
    if not report_path.is_relative_to(docs_root):
        raise ValueError("runtime report must stay within the project docs directory")
    if not report_path.parent.is_dir() or reparse(report_path.parent) or reparse(report_path):
        raise ValueError("runtime report parent must be an existing non-reparse directory")
    previous_report = None
    if report_path.exists():
        if not args.replace_report:
            raise FileExistsError("refusing to overwrite an existing runtime report without --replace-report")
        old_report = json.loads(report_path.read_text(encoding="utf-8"))
        previous_report = {key: old_report.get(key) for key in ("status", "toolchain_root", "error", "completed_utc")}
    report = {
        "schema_version": 1,
        "status": "provisioning",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": {"version": PYTHON_VERSION, "archive": PYTHON_FILENAME, "source": PYTHON_URL,
                   "release_metadata": PYTHON_RELEASE_URL, "sigstore_metadata": PYTHON_SIGSTORE_URL,
                   "published_sha256": PYTHON_SHA256,
                   "distribution": "Windows x86-64 embeddable ZIP", "used_venv": False, "used_ensurepip": False,
                   "authenticity_scope": {"published_digest_source": PYTHON_SIGSTORE_URL,
                                          "download_sha256_checked": False,
                                          "sigstore_certificate_and_rekor_proof_cryptographically_verified": False,
                                          "pe_authenticode_signature_checked": False}},
        "toolchain_root": str(stage.relative_to(root)).replace("\\", "/"),
        "source_policy": {"allowed_hosts": sorted(PYTHON_HOSTS | PYPI_HOSTS), "redirects_followed": False,
                          "download_authentication": "official HTTPS source plus published SHA-256 digest; no independent Sigstore verification",
                          "global_python_modified": False, "existing_3_9_venv_modified": False,
                          "registry_path_association_or_PATH_changes": False},
        "packages": [], "checks": {}, "test_facts": {"modern_worker_tests": "not run", "v9_math_golden": "not run", "frozen_worker": "not built"},
        "notes": ["PyInstaller uses a console bootloader; the supervisor must start Worker.exe with CREATE_NO_WINDOW and inherited anonymous pipes."],
    }
    if previous_report is not None:
        report["previous_attempt"] = previous_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Download and authenticate the official embeddable runtime before any
        # files from it are expanded or executed.
        sigstore_dir = downloads / ("python-sigstore-" + uuid.uuid4().hex)
        sigstore_dir.mkdir(exist_ok=False)
        report["python"]["sigstore_attestation_check"] = verify_python_sigstore_bundle(
            sigstore_dir / (PYTHON_FILENAME + ".sigstore"), root,
        )
        py_download_dir = downloads / ("cpython-" + uuid.uuid4().hex)
        py_download_dir.mkdir(exist_ok=False)
        py_archive = py_download_dir / PYTHON_FILENAME
        py_download = download(PYTHON_URL, PYTHON_HOSTS, py_archive, PYTHON_MAX_ARCHIVE)
        if py_download["sha256"] != PYTHON_SHA256:
            raise ValueError("CPython embeddable archive does not match the python.org release SHA-256")
        report["python"]["authenticity_scope"]["download_sha256_checked"] = True
        runtime_extract_dir = extractions / ("cpython-" + uuid.uuid4().hex)
        py_extract = extract_checked(py_archive, runtime_extract_dir, max_archive=PYTHON_MAX_ARCHIVE)
        report["python"].update({"download": {"bytes": py_download["bytes"], "sha256": py_download["sha256"], "http_status": py_download["http_status"]},
                                 "archive_audit": py_extract, "runtime_root": str(runtime_extract_dir.relative_to(root)).replace("\\", "/")})
        if not (runtime_extract_dir / "python.exe").is_file() or not (runtime_extract_dir / (PYTHON_TAG + ".dll")).is_file():
            raise ValueError("official archive lacks the expected complete x64 python.exe/{} runtime".format(PYTHON_TAG + ".dll"))
        report["python"]["pe_authenticode_check"] = check_pe_authenticode(
            os.environ.get("SystemRoot", r"C:\Windows"), runtime_extract_dir,
        )
        report["python"]["authenticity_scope"]["pe_authenticode_signature_checked"] = report["python"]["pe_authenticode_check"]["performed"]
        report["python"]["license_audit"] = collect_runtime_licenses(runtime_extract_dir, extractions, root)
        pth = runtime_extract_dir / (PYTHON_TAG + "._pth")
        if not pth.is_file() or reparse(pth):
            raise ValueError("official archive lacks a regular {}._pth".format(PYTHON_TAG))
        pth_before = pth.read_bytes()
        pth_lines = pth_before.decode("utf-8").splitlines()
        stdlib_zip_name = PYTHON_TAG + ".zip"
        if stdlib_zip_name not in pth_lines or "." not in pth_lines:
            raise ValueError("unexpected embedded-runtime path configuration")
        if any(line.strip().lower() in ("..", "../", "lib/site-packages/../../") for line in pth_lines):
            raise ValueError("unsafe path in original {}._pth".format(PYTHON_TAG))
        if any("appdata" in line.lower() or "site-packages" in line.lower() or "user" in line.lower() for line in pth_lines):
            raise ValueError("unexpected user/global site path in original {}._pth".format(PYTHON_TAG))
        active_pth_lines = [line.strip() for line in pth_lines if line.strip() and not line.strip().startswith("#")]
        if active_pth_lines != [stdlib_zip_name, "."]:
            raise ValueError("unexpected active search path in the official {}._pth".format(PYTHON_TAG))
        normalized = [stdlib_zip_name, ".", "Lib/site-packages", "import site"]
        pth_after = ("\n".join(normalized) + "\n").encode("utf-8")
        pth.write_bytes(pth_after)
        site_packages = runtime_extract_dir / "Lib" / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=False)
        report["python"].update({PYTHON_TAG + "_pth_sha256_before": hashlib.sha256(pth_before).hexdigest(),
                                 PYTHON_TAG + "_pth_sha256_after": hashlib.sha256(pth_after).hexdigest(),
                                 PYTHON_TAG + "_pth_lines": normalized,
                                 "private_site_packages": "Lib/site-packages"})

        # Fetch, hash-check, CRC/path-audit and unpack all pinned wheels into
        # distinct read-only audit directories before package code is run.
        verified = []
        for pin in WHEELS:
            item = pypi_release(pin)
            download_dir = downloads / ("wheel-" + canonical_name(pin["name"]) + "-" + uuid.uuid4().hex)
            download_dir.mkdir(exist_ok=False)
            wheel_path = download(item["url"], PYPI_HOSTS, download_dir / pin["filename"], MAX_ARCHIVE)
            if wheel_path["sha256"] != pin["sha256"]:
                raise ValueError("downloaded PyPI wheel digest mismatch for {}".format(pin["name"]))
            audit_dir = extractions / ("wheel-" + canonical_name(pin["name"]) + "-" + uuid.uuid4().hex)
            if audit_dir.exists() or reparse(audit_dir):
                raise FileExistsError("wheel audit extraction directory unexpectedly exists")
            record = audit_wheel(pin, download_dir / pin["filename"], audit_dir, item)
            record["download"] = {"bytes": wheel_path["bytes"], "sha256": wheel_path["sha256"], "http_status": wheel_path["http_status"]}
            verified.append((pin, audit_dir, download_dir / pin["filename"], record))
            report["packages"].append(record)

        # Copy only verified notice/license text into a new, versioned project
        # notice directory; do not copy the existing machine-specific probe.
        license_root = root / "docs" / "licenses" / "python-worker-runtime"
        for pin, audit_dir, wheel_path, record in verified:
            package_root = license_root / (canonical_name(pin["name"]) + "-" + pin["version"])
            for notice in record["license_files"]:
                source = audit_dir.joinpath(*PurePosixPath(notice["path"]).parts)
                destination = package_root.joinpath(*PurePosixPath(notice["path"]).parts)
                copy_file_new(source, destination)
                notice["project_copy"] = str(destination.relative_to(root)).replace("\\", "/")

        # The embeddable archive has no ensurepip/venv by design. Bootstrap
        # pip by installing its hash-verified universal wheel as data, then use
        # pip only offline with the already-hashed local wheel paths.
        pip_pin, pip_audit, pip_wheel, pip_record = next(row for row in verified if row[0]["name"] == "pip")
        install_bootstrap_wheel(pip_audit, site_packages, runtime_extract_dir)
        env = clean_child_env(stage, runtime_extract_dir)
        python_exe = runtime_extract_dir / "python.exe"
        import_check = run_python(python_exe, ["-c", "import json, platform, site, sys, sysconfig; print(json.dumps({'version':sys.version,'version_info':list(sys.version_info[:3]),'executable':sys.executable,'isolated':sys.flags.isolated,'enable_user_site':site.ENABLE_USER_SITE,'sys_path':sys.path,'maxsize':sys.maxsize,'platform':sysconfig.get_platform(),'machine':platform.machine()}))"], root, env)
        runtime_info = json.loads(import_check.stdout.strip().splitlines()[-1])
        if (runtime_info["version_info"] != list(PYTHON_VERSION_TUPLE) or runtime_info["isolated"] != 1
                or runtime_info["enable_user_site"] not in (False, None)
                or runtime_info["maxsize"] != 2 ** 63 - 1 or runtime_info["platform"] != "win-amd64"):
            raise ValueError("private embedded runtime did not pass version/x64/isolation checks")
        runtime_paths = [Path(p).resolve(strict=False) for p in runtime_info["sys_path"] if p]
        allowed_runtime_paths = {runtime_extract_dir.resolve(), site_packages.resolve(), (runtime_extract_dir / (PYTHON_TAG + ".zip")).resolve()}
        if any(path not in allowed_runtime_paths for path in runtime_paths):
            raise ValueError("runtime sys.path contains a cwd, user-site, or non-private path")
        if root in runtime_paths or Path.cwd().resolve() in runtime_paths:
            raise ValueError("trusted app cwd was added to isolated runtime sys.path")
        if site_packages.resolve() not in runtime_paths:
            raise ValueError("{}._pth did not enable the private site-packages directory".format(PYTHON_TAG))
        pip_check = run_python(python_exe, ["-m", "pip", "--version"], root, env)
        if "pip 26.2.1" not in pip_check.stdout:
            raise ValueError("hash-verified pip bootstrap failed")
        install_wheels = [str(path) for pin, audit_dir, path, record in verified if pin["name"] != "pip"]
        pip_install = run_python(python_exe, ["-m", "pip", "install", "--disable-pip-version-check", "--no-index", "--no-deps", "--no-cache-dir", "--only-binary=:all:", "--upgrade"] + install_wheels,
                                 root, env, timeout=1200)
        package_names = [pin["name"] for pin in WHEELS]
        package_check_code = (
            "import importlib.metadata as m, json, numpy, scipy, cv2, PyInstaller, sys; "
            "names=" + repr(package_names) + "; "
            "print(json.dumps({'versions':{name:m.version(name) for name in names},"
            "'cv2':cv2.__version__,'pyinstaller':PyInstaller.__version__,'sys_executable':sys.executable}))"
        )
        package_check = run_python(python_exe, ["-c", package_check_code], root, env)
        imports = json.loads(package_check.stdout.strip().splitlines()[-1])
        expected_versions = {pin["name"]: pin["version"] for pin in WHEELS}
        if imports.get("versions") != expected_versions:
            raise ValueError("installed runtime package versions differ from the fully verified wheel set")
        expected_cv2_module_version = next(pin["module_version"] for pin in WHEELS
                                           if pin["name"] == "opencv-python-headless")
        if (imports.get("cv2") != expected_cv2_module_version
                or imports.get("pyinstaller") != expected_versions["pyinstaller"]):
            raise ValueError("installed cv2/PyInstaller module version mismatch")
        pyinstaller_check = run_python(python_exe, ["-m", "PyInstaller", "--version"], root, env)
        if pyinstaller_check.stdout.strip() != "6.22.3":
            raise ValueError("PyInstaller command/module smoke check failed")
        report["python"].update({"interpreter": str(python_exe.relative_to(root)).replace("\\", "/"),
                                 "venv_available": False, "ensurepip_available": False,
                                 "pip_bootstrap": "verified local wheel manually laid out into private Lib/site-packages",
                                 "isolated_runtime_check": runtime_info, "package_imports": imports})
        report["checks"] = {"source_sha256": True, "zip_crc_and_bounds": True, "wheel_RECORDs": True,
                            "pypi_metadata_pins_and_yanked": True, "private_site_packages_only": True,
                            "pip_offline_install": True, "scientific_imports": True, "pyinstaller_smoke": True,
                            "global_python_modified": False, "existing_3_9_venv_modified": False,
                            "registry_path_or_associations_modified": False}
        report["status"] = "provisioned"
        report["pip_install_output"] = pip_install.stdout[-4000:]
        report["license_directory"] = str(license_root.relative_to(root)).replace("\\", "/")
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write_report(report_path, report, args.replace_report)
        print(json.dumps({"status": report["status"], "runtime": report["python"]["interpreter"],
                          "toolchain_root": report["toolchain_root"], "packages": imports,
                          "manifest": str(report_path)}, indent=2))
        return 0
    except Exception as exc:
        report["status"] = "blocked" if isinstance(exc, SourceRedirectBlocked) else "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        if isinstance(exc, SourceRedirectBlocked):
            report["error"].update({"source_url": exc.url, "http_status": exc.status,
                                    "redirect_host_not_followed": urlparse(exc.location).hostname if exc.location else None})
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        write_report(report_path, report, args.replace_report)
        print(json.dumps({"status": report["status"], "error": report["error"],
                          "toolchain_root": report["toolchain_root"], "manifest": str(report_path)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
