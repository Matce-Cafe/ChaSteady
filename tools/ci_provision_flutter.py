"""Download and safely extract the pinned official Flutter Windows SDK for CI.

The script is repository-owned code and never executes anything from the archive.
Each archive download and extraction uses a separate new UUID directory. TLS is
validated normally, redirects are refused, and the complete archive SHA-256 is
checked before ZIP metadata is inspected or any member is extracted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import stat
import sys
import uuid
import zipfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


FLUTTER_VERSION = "3.47.7"
FLUTTER_ARCHIVE = "flutter_windows_3.47.7-stable.zip"
FLUTTER_URL = "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/" + FLUTTER_ARCHIVE
FLUTTER_SHA256 = "c2c875da25a1a1448d18ee4e8f398b2f6fce888b4775d8f9130538e16d826cb4"
FLUTTER_ARCHIVE_BYTES = 1_934_624_561
FLUTTER_HOST = "storage.googleapis.com"
MAX_ARCHIVE_BYTES = 3 * 1024 ** 3
MAX_ENTRY_COUNT = 250_000
MAX_EXPANDED_BYTES = 12 * 1024 ** 3
MAX_ENTRY_BYTES = 2 * 1024 ** 3
MAX_COMPRESSION_RATIO = 1000
CHUNK_BYTES = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def new_empty_uuid_dir(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    if is_reparse(parent) or not parent.is_dir():
        raise RuntimeError("CI scratch parent must be a regular directory")
    for _ in range(5):
        target = parent / (prefix + uuid.uuid4().hex)
        try:
            target.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        if is_reparse(target) or any(target.iterdir()):
            raise RuntimeError("New UUID directory was not an empty regular directory")
        return target
    raise RuntimeError("Could not allocate a unique UUID directory")


def _approved_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != FLUTTER_HOST or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Flutter download URL is outside the pinned official HTTPS origin")
    if url != FLUTTER_URL:
        raise ValueError("Flutter download URL differs from the pinned release URL")


def download_archive(url: str, destination: Path) -> dict:
    _approved_url(url)
    if destination.exists() or is_reparse(destination):
        raise FileExistsError("Flutter archive target must be a new regular file")
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    request = Request(url, headers={"User-Agent": "ChaSteady-Windows-CI/1.0", "Accept-Encoding": "identity"})
    digest = hashlib.sha256()
    total = 0
    try:
        response = opener.open(request, timeout=180)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise RuntimeError("Official Flutter source returned a redirect; it was not followed") from exc
        raise RuntimeError("Official Flutter archive request returned HTTP {}".format(exc.code)) from exc
    except URLError as exc:
        raise RuntimeError("Official Flutter archive connection failed: {}".format(type(exc.reason).__name__)) from exc
    with response, destination.open("xb") as output:
        if response.geturl() != url or response.status != 200:
            raise RuntimeError("Flutter response URL or status differs from the pinned request")
        encoding = response.headers.get("Content-Encoding", "").lower().strip()
        if encoding not in ("", "identity"):
            raise RuntimeError("Flutter archive used an unexpected HTTP content encoding")
        header_length = response.headers.get("Content-Length")
        if header_length is None or not header_length.isdecimal():
            raise RuntimeError("Flutter archive response lacks a valid Content-Length")
        if int(header_length) != FLUTTER_ARCHIVE_BYTES:
            raise RuntimeError("Flutter archive Content-Length differs from the official pinned size")
        if int(header_length) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Flutter archive exceeds the configured download bound")
        while True:
            block = response.read(CHUNK_BYTES)
            if not block:
                break
            total += len(block)
            if total > MAX_ARCHIVE_BYTES or total > FLUTTER_ARCHIVE_BYTES:
                raise RuntimeError("Flutter archive exceeded its pinned byte bound")
            digest.update(block)
            output.write(block)
    actual = digest.hexdigest()
    if total != FLUTTER_ARCHIVE_BYTES:
        raise RuntimeError("Flutter archive byte count differs from the official pinned size")
    if actual != FLUTTER_SHA256:
        raise RuntimeError("Flutter archive SHA-256 differs from the official pinned digest")
    return {"url": url, "http_status": 200, "bytes": total, "sha256": actual}


def _safe_member(info: zipfile.ZipInfo) -> tuple[PurePosixPath, bool]:
    raw = info.filename
    if not raw or "\\" in raw or "\x00" in raw or raw.startswith("/"):
        raise ValueError("Flutter ZIP contains an unsafe member name")
    directory_by_name = raw.endswith("/")
    if raw.endswith("//"):
        raise ValueError("Flutter ZIP contains a repeated trailing separator")
    value = raw[:-1] if directory_by_name else raw
    parts = value.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("Flutter ZIP contains a traversal or empty path component")
    if parts[0] != "flutter":
        raise ValueError("Flutter ZIP contains an unexpected archive root")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {"COM{}".format(n) for n in range(1, 10)} | {"LPT{}".format(n) for n in range(1, 10)}
    for part in parts:
        if (part.endswith((" ", ".")) or re.search(r'[<>:"|?*\x00-\x1f]', part)
                or part.split(".", 1)[0].upper() in reserved):
            raise ValueError("Flutter ZIP contains an unsafe Windows path component")
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise ValueError("Flutter ZIP symbolic links are not allowed")
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError("Flutter ZIP special files are not allowed")
    directory_by_mode = file_type == stat.S_IFDIR
    if directory_by_name and file_type == stat.S_IFREG:
        raise ValueError("Flutter ZIP directory marker conflicts with regular-file mode")
    if directory_by_mode and not directory_by_name:
        raise ValueError("Flutter ZIP directory mode lacks a directory name")
    directory = directory_by_name or directory_by_mode
    if directory and info.file_size != 0:
        raise ValueError("Flutter ZIP directory entry contains data")
    if info.flag_bits & 0x1:
        raise ValueError("Encrypted Flutter ZIP members are not allowed")
    return PurePosixPath(*parts), directory


def inspect_archive(archive_path: Path) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath, bool]], dict]:
    if not archive_path.is_file() or is_reparse(archive_path) or archive_path.stat().st_size != FLUTTER_ARCHIVE_BYTES:
        raise ValueError("Flutter archive is missing, linked, or has an unexpected size")
    digest = hashlib.sha256()
    with archive_path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(block)
    if digest.hexdigest() != FLUTTER_SHA256:
        raise ValueError("Flutter archive digest changed before ZIP inspection")

    rows: list[tuple[zipfile.ZipInfo, PurePosixPath, bool]] = []
    exact_paths: set[str] = set()
    case_paths: set[str] = set()
    file_paths: set[str] = set()
    directory_paths: set[str] = set()
    expanded = 0
    with zipfile.ZipFile(str(archive_path), "r") as archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ENTRY_COUNT:
            raise ValueError("Flutter ZIP entry count is outside the configured bound")
        for info in infos:
            relative, is_directory = _safe_member(info)
            name = relative.as_posix()
            folded = name.casefold()
            if name in exact_paths or folded in case_paths:
                raise ValueError("Flutter ZIP contains duplicate or case-colliding paths")
            exact_paths.add(name)
            case_paths.add(folded)
            if info.file_size < 0 or info.file_size > MAX_ENTRY_BYTES or info.compress_size < 0:
                raise ValueError("Flutter ZIP member size is outside the configured bound")
            if info.file_size > 0 and info.compress_size == 0:
                raise ValueError("Flutter ZIP member has a zero-byte compressed payload")
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise ValueError("Flutter ZIP compression ratio exceeds the configured bound")
            expanded += info.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise ValueError("Flutter ZIP total expanded size exceeds the configured bound")

            parts = relative.parts
            for index in range(1, len(parts)):
                parent = PurePosixPath(*parts[:index]).as_posix().casefold()
                if parent in file_paths:
                    raise ValueError("Flutter ZIP places a child beneath a regular file")
                directory_paths.add(parent)
            if is_directory:
                if folded in file_paths:
                    raise ValueError("Flutter ZIP path is both a file and directory")
                directory_paths.add(folded)
            else:
                if folded in directory_paths:
                    raise ValueError("Flutter ZIP path is both a file and directory")
                file_paths.add(folded)
            rows.append((info, relative, is_directory))

        if not any(path.as_posix() == "flutter/bin/flutter.bat" and not is_dir for _, path, is_dir in rows):
            raise ValueError("Flutter ZIP lacks the expected Windows launcher")
        if not any(path.as_posix() == "flutter/bin/cache/dart-sdk/bin/dart.exe" and not is_dir
                   for _, path, is_dir in rows):
            raise ValueError("Flutter ZIP lacks the expected bundled Dart executable")
    return rows, {"entry_count": len(rows), "expanded_bytes": expanded,
                  "bounds": {"maximum_archive_bytes": MAX_ARCHIVE_BYTES,
                             "maximum_entry_count": MAX_ENTRY_COUNT,
                             "maximum_total_expanded_bytes": MAX_EXPANDED_BYTES,
                             "maximum_single_entry_bytes": MAX_ENTRY_BYTES,
                             "maximum_compression_ratio": MAX_COMPRESSION_RATIO}}


def extract_checked(archive_path: Path, extraction_root: Path,
                    rows: list[tuple[zipfile.ZipInfo, PurePosixPath, bool]]) -> None:
    if (not extraction_root.is_dir() or is_reparse(extraction_root)
            or any(extraction_root.iterdir())):
        raise FileExistsError("Flutter extraction root must be a new empty regular directory")
    prefix = extraction_root.resolve(strict=True)
    with zipfile.ZipFile(str(archive_path), "r") as archive:
        for info, relative, is_directory in rows:
            target = extraction_root.joinpath(*relative.parts)
            parent = target.parent
            cursor = extraction_root
            for component in relative.parts[:-1]:
                cursor = cursor / component
                if cursor.exists():
                    if is_reparse(cursor) or not cursor.is_dir():
                        raise ValueError("Flutter extraction parent is linked or not a directory")
                else:
                    cursor.mkdir()
                if not cursor.resolve(strict=True).is_relative_to(prefix):
                    raise ValueError("Flutter ZIP member escaped its UUID extraction root")
            if is_directory:
                if target.exists():
                    if is_reparse(target) or not target.is_dir():
                        raise ValueError("Flutter ZIP directory target collides with another file")
                else:
                    target.mkdir()
                continue
            if target.exists() or is_reparse(target):
                raise FileExistsError("Flutter ZIP member target was already created")
            written = 0
            with archive.open(info, "r") as source, target.open("xb") as destination:
                while True:
                    block = source.read(CHUNK_BYTES)
                    if not block:
                        break
                    written += len(block)
                    if written > info.file_size:
                        raise ValueError("Flutter ZIP member expanded beyond its declared size")
                    destination.write(block)
            if written != info.file_size or target.stat().st_size != info.file_size:
                raise ValueError("Flutter ZIP member extracted length differs from the audited size")
            if is_reparse(target):
                raise ValueError("Flutter extraction produced an unexpected reparse point")

    sdk_root = extraction_root / "flutter"
    if (not (sdk_root / "bin" / "flutter.bat").is_file()
            or not (sdk_root / "bin" / "cache" / "dart-sdk" / "bin" / "dart.exe").is_file()):
        raise RuntimeError("Authenticated archive did not produce a complete Flutter/Dart SDK")


def analyzer_path_budget(extraction_root: Path, rows: list) -> dict:
    maxima = {"dev": 0, "examples": 0, "packages": 0}
    for _info, relative, is_directory in rows:
        directory = relative if is_directory else relative.parent
        parts = directory.parts
        if len(parts) >= 2 and parts[0] == "flutter" and parts[1] in maxima:
            suffix = "/" + "/".join(parts[1:])
            maxima[parts[1]] = max(maxima[parts[1]], len(suffix.encode("utf-16-le")) // 2)
    sdk_units = len(str(extraction_root.absolute() / "flutter").encode("utf-16-le")) // 2
    if any(sdk_units + suffix >= 240 for suffix in maxima.values()):
        raise ValueError("Flutter SDK layout exceeds the bounded analyzer directory-path budget")
    return {"sdk_root_utf16_units": sdk_units, "subtree_directory_suffix_utf16_max": maxima,
            "longest_combined_directory_utf16_units": sdk_units + max(maxima.values()),
            "limit_exclusive": 240}


def provision(scratch_root: Path) -> dict:
    if scratch_root.exists() and (is_reparse(scratch_root) or not scratch_root.is_dir()):
        raise ValueError("CI scratch root must be a regular directory")
    scratch_root.mkdir(parents=True, exist_ok=True)
    if is_reparse(scratch_root):
        raise ValueError("CI scratch root must not be a reparse point")
    downloads = scratch_root / "downloads"
    extractions = scratch_root / "e"
    downloads.mkdir(exist_ok=True)
    extractions.mkdir(exist_ok=True)
    download_dir = new_empty_uuid_dir(downloads, "flutter-" + FLUTTER_VERSION + "-")
    archive_path = download_dir / FLUTTER_ARCHIVE
    archive_info = download_archive(FLUTTER_URL, archive_path)
    rows, audit = inspect_archive(archive_path)
    extraction_dir = new_empty_uuid_dir(extractions, "f-")
    audit["analyzer_path_budget"] = analyzer_path_budget(extraction_dir, rows)
    extract_checked(archive_path, extraction_dir, rows)
    return {"schema_version": 1, "version": FLUTTER_VERSION, "channel": "stable",
            "archive": FLUTTER_ARCHIVE, "archive_url": FLUTTER_URL,
            "archive_sha256": archive_info["sha256"], "archive_bytes": archive_info["bytes"],
            "sdk_root": str((extraction_dir / "flutter").resolve(strict=True)),
            "download_directory": str(download_dir.resolve(strict=True)),
            "extraction_directory": str(extraction_dir.resolve(strict=True)),
            "archive_audit": audit}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-root", type=Path, required=True,
                        help="runner temporary root; downloads/extractions get separate new UUID subdirectories")
    parser.add_argument("--result-json", type=Path, required=True,
                        help="new result JSON path outside the SDK archive/extraction directories")
    args = parser.parse_args(argv)
    result = provision(args.scratch_root.resolve())
    output = args.result_json.resolve()
    if output.exists() or is_reparse(output) or is_reparse(output.parent):
        raise FileExistsError("Flutter provision result must be written to a new regular file")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"version": result["version"], "archive_sha256": result["archive_sha256"],
                      "sdk_root": result["sdk_root"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("Flutter CI provisioning failed: {}: {}".format(type(error).__name__, error), file=sys.stderr)
        raise
