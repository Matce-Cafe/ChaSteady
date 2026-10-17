"""Fetch the pinned Noto Sans SC font as data for an ephemeral CI build.

Only the fixed Google Fonts Git blob is accepted. HTTPS certificate validation
is enabled, redirects are refused, and the font is verified by byte count,
Git blob SHA-1, SHA-256, and a bounded TrueType table-directory check. The font
is never executed or written into the repository checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import struct
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


FONT_REPOSITORY = "google/fonts"
FONT_COMMIT = "a85815a42757630ce188fdad368c2dfc444d4773"
FONT_REPOSITORY_PATH = "ofl/notosanssc/NotoSansSC[wght].ttf"
FONT_BLOB_SHA1 = "fb0637bafbcd804fe32152370a1225990745b4bc"
FONT_BYTES = 17_772_300
FONT_SHA256 = "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da"
FONT_LICENSE_BLOB_SHA1 = "1c9f43281b8f216c5461fe9ac729afbade7724e4"
FONT_LICENSE_SHA256 = "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9"
FONT_LICENSE_URL = "https://github.com/google/fonts/blob/" + FONT_COMMIT + "/ofl/notosanssc/OFL.txt"
FONT_URL = "https://api.github.com/repos/google/fonts/git/blobs/" + FONT_BLOB_SHA1
MAX_TABLES = 100
CHUNK_BYTES = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_reparse(path: Path) -> bool:
    import stat
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def new_empty_uuid_dir(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    if is_reparse(parent) or not parent.is_dir():
        raise RuntimeError("Font scratch root must be a regular directory")
    for _ in range(5):
        directory = parent / (prefix + uuid.uuid4().hex)
        try:
            directory.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        if is_reparse(directory) or any(directory.iterdir()):
            raise RuntimeError("New font UUID directory was not empty")
        return directory
    raise RuntimeError("Could not allocate a unique font UUID directory")


def _assert_approved_url(url: str) -> None:
    parsed = urlsplit(url)
    if (url != FONT_URL or parsed.scheme != "https" or parsed.hostname != "api.github.com"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("Font source is not the pinned official GitHub API blob URL")


def parse_provenance(path: Path) -> dict:
    if not path.is_file() or is_reparse(path) or path.stat().st_size > 64 * 1024:
        raise ValueError("Font provenance file is missing, linked, or too large")
    text = path.read_text(encoding="utf-8")
    values = {}
    labels = {
        "Pinned Google Fonts commit": "commit",
        "Pinned path": "path",
        "Pinned Git blob SHA-1": "blob_sha1",
        "Downloaded bytes": "bytes",
        "Downloaded SHA-256": "sha256",
        "License source": "license_source",
        "License Git blob SHA-1": "license_blob_sha1",
        "License SHA-256": "license_sha256",
    }
    for line in text.splitlines():
        for label, key in labels.items():
            prefix = label + ":"
            if line.startswith(prefix):
                if key in values:
                    raise ValueError("Font provenance contains a duplicate identity field")
                values[key] = line[len(prefix):].strip()
    if "bytes" in values:
        values["bytes"] = values["bytes"].replace(",", "")
    expected = {"commit": FONT_COMMIT, "path": FONT_REPOSITORY_PATH,
                "blob_sha1": FONT_BLOB_SHA1, "bytes": str(FONT_BYTES), "sha256": FONT_SHA256,
                "license_source": FONT_LICENSE_URL, "license_blob_sha1": FONT_LICENSE_BLOB_SHA1,
                "license_sha256": FONT_LICENSE_SHA256}
    if values != expected:
        raise ValueError("Font provenance identity differs from the CI-pinned official blob")
    return values


def git_blob_sha1(payload: bytes) -> str:
    prefix = ("blob {}\0".format(len(payload))).encode("ascii")
    digest = hashlib.sha1()
    digest.update(prefix)
    digest.update(payload)
    return digest.hexdigest()


def git_blob_sha1_file(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(("blob {}\0".format(size)).encode("ascii"))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_font_license(path: Path) -> dict:
    if not path.is_file() or is_reparse(path) or path.stat().st_size > 1024 * 1024:
        raise ValueError("Noto Sans SC OFL license is missing, linked, or too large")
    actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    actual_blob_sha1 = git_blob_sha1_file(path)
    if actual_sha256 != FONT_LICENSE_SHA256 or actual_blob_sha1 != FONT_LICENSE_BLOB_SHA1:
        raise ValueError("Noto Sans SC OFL text differs from its pinned Google Fonts license")
    return {"file": "OFL.txt", "bytes": path.stat().st_size,
            "sha256": actual_sha256, "git_blob_sha1": actual_blob_sha1}


def inspect_ttf(path: Path) -> dict:
    size = path.stat().st_size
    if size != FONT_BYTES or is_reparse(path):
        raise ValueError("Downloaded font is not a regular file of the pinned byte length")
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError("Font has a truncated SFNT header")
        scaler_type, table_count, _search_range, _entry_selector, _range_shift = struct.unpack(">IHHHH", header)
        if scaler_type != 0x00010000 or table_count <= 0 or table_count > MAX_TABLES:
            raise ValueError("Pinned asset is not a bounded TrueType SFNT font")
        directory_end = 12 + table_count * 16
        if directory_end > size:
            raise ValueError("Font table directory is truncated")
        directory = stream.read(table_count * 16)
        tables = {}
        ranges = []
        for index in range(table_count):
            record = directory[index * 16:(index + 1) * 16]
            tag_raw, _checksum, offset, length = struct.unpack(">4sIII", record)
            try:
                tag = tag_raw.decode("ascii")
            except UnicodeError as error:
                raise ValueError("Font has a non-ASCII table tag") from error
            if not re.fullmatch(r"[\x20-\x7e]{4}", tag) or tag in tables:
                raise ValueError("Font has an invalid or duplicate table tag")
            if offset < directory_end or offset + length > size or (length and offset % 4):
                raise ValueError("Font table offset or length escapes the pinned file")
            tables[tag] = (offset, length)
            if length:
                ranges.append((offset, offset + length, tag))
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1]:
                raise ValueError("Font table payloads overlap")
        required = {"cmap", "fvar", "glyf", "head", "hhea", "maxp", "name"}
        if not required.issubset(tables):
            raise ValueError("Font is missing required TrueType variable-font tables")
        for tag, minimum_length in (("cmap", 4), ("fvar", 16), ("glyf", 1),
                                    ("head", 54), ("hhea", 36), ("maxp", 6), ("name", 6)):
            if tables[tag][1] < minimum_length:
                raise ValueError("Font table is shorter than its minimum structural header")
        head_offset, _ = tables["head"]
        stream.seek(head_offset + 12)
        magic_number = struct.unpack(">I", stream.read(4))[0]
        stream.seek(head_offset + 18)
        units_per_em = struct.unpack(">H", stream.read(2))[0]
        if magic_number != 0x5F0F3CF5 or not 16 <= units_per_em <= 16384:
            raise ValueError("Font head table failed its TrueType magic/units check")
        maxp_offset, _ = tables["maxp"]
        stream.seek(maxp_offset + 4)
        glyph_count = struct.unpack(">H", stream.read(2))[0]
        fvar_offset, _ = tables["fvar"]
        stream.seek(fvar_offset + 8)
        axis_count = struct.unpack(">H", stream.read(2))[0]
        if glyph_count <= 0 or axis_count <= 0:
            raise ValueError("Font does not contain glyphs and a variable-font axis")
    return {"sfnt": "TrueType 1.0", "table_count": table_count,
            "variable_font": True, "glyph_count": glyph_count, "axis_count": axis_count}


def download_font(destination: Path) -> dict:
    _assert_approved_url(FONT_URL)
    if destination.exists() or is_reparse(destination):
        raise FileExistsError("Pinned font download target must be a new regular file")
    headers = {
        "User-Agent": "ChaSteady-Windows-CI/1.0",
        "Accept": "application/vnd.github.raw+json",
        "Accept-Encoding": "identity",
    }
    # Only the explicit step-scoped CI credential is used, never a local PAT.
    token = os.environ.get("CHASTEADY_CI_FONT_GITHUB_TOKEN", "")
    if token:
        if not re.fullmatch(r"[A-Za-z0-9_]{20,512}", token):
            raise ValueError("CI font credential has an invalid header format")
        headers["Authorization"] = "Bearer " + token
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    request = Request(FONT_URL, headers=headers)
    sha256 = hashlib.sha256()
    total = 0
    try:
        response = opener.open(request, timeout=180)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise RuntimeError("Pinned GitHub font blob returned a redirect; it was not followed") from exc
        raise RuntimeError("Pinned GitHub font blob returned HTTP {}".format(exc.code)) from exc
    except URLError as exc:
        raise RuntimeError("Pinned GitHub font connection failed: {}".format(type(exc.reason).__name__)) from exc
    with response, destination.open("xb") as output:
        if response.geturl() != FONT_URL or response.status != 200:
            raise RuntimeError("GitHub font response URL or status differs from the pinned blob request")
        encoding = response.headers.get("Content-Encoding", "").strip().lower()
        if encoding not in ("", "identity"):
            raise RuntimeError("Pinned GitHub font response used unexpected content encoding")
        header_length = response.headers.get("Content-Length")
        if header_length is not None and (not header_length.isdecimal() or int(header_length) != FONT_BYTES):
            raise RuntimeError("Pinned font response length differs from its recorded identity")
        while True:
            block = response.read(CHUNK_BYTES)
            if not block:
                break
            total += len(block)
            if total > FONT_BYTES:
                raise RuntimeError("Pinned font response exceeded its recorded byte count")
            sha256.update(block)
            output.write(block)
    actual_sha256 = sha256.hexdigest()
    # Git object IDs cover a canonical blob header as well as the file bytes.
    payload_sha1 = hashlib.sha1()
    payload_sha1.update(("blob {}\0".format(total)).encode("ascii"))
    with destination.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
            payload_sha1.update(block)
    git_sha1 = payload_sha1.hexdigest()
    if total != FONT_BYTES or actual_sha256 != FONT_SHA256 or git_sha1 != FONT_BLOB_SHA1:
        raise RuntimeError("Downloaded Google Fonts blob failed byte-count or cryptographic identity checks")
    return {"url": FONT_URL, "status": 200, "bytes": total,
            "sha256": actual_sha256, "git_blob_sha1": git_sha1}


def prepare(scratch_root: Path, provenance_file: Path) -> dict:
    expected = parse_provenance(provenance_file)
    license_report = verify_font_license(provenance_file.parent / "OFL.txt")
    scratch_root.mkdir(parents=True, exist_ok=True)
    if is_reparse(scratch_root) or not scratch_root.is_dir():
        raise ValueError("Font scratch root must be a regular directory")
    font_dir = new_empty_uuid_dir(scratch_root, "google-fonts-")
    font_path = font_dir / "NotoSansSC-wght.ttf"
    download = download_font(font_path)
    structure = inspect_ttf(font_path)
    return {"schema_version": 1, "repository": FONT_REPOSITORY, "commit": expected["commit"],
            "repository_path": expected["path"], "git_blob_sha1": download["git_blob_sha1"],
            "sha256": download["sha256"], "bytes": download["bytes"],
            "font_path": str(font_path.resolve(strict=True)), "font_directory": str(font_dir.resolve(strict=True)),
            "structure": structure, "license": license_report, "executed_as_code": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-root", type=Path, required=True,
                        help="runner temporary parent; the pinned font gets a new empty UUID directory")
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True,
                        help="new result JSON path outside the downloaded font directory")
    args = parser.parse_args(argv)
    result = prepare(args.scratch_root.resolve(), args.provenance.resolve(strict=True))
    output = args.result_json.resolve()
    if output.exists() or is_reparse(output) or is_reparse(output.parent):
        raise FileExistsError("Font preparation result must be a new regular file")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("Pinned Google Fonts data passed Git blob, SHA-256 and TrueType checks.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("CI font preparation failed: {}: {}".format(type(error).__name__, error), file=sys.stderr)
        raise
