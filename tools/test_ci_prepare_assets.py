"""Tests for pinned CI font acquisition; generated SFNT bytes are parser fixtures only."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_prepare_assets as ci


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.position = 0
        self.status = 200
        self.url = ci.FONT_URL
        self.headers = {"Content-Length": str(len(payload)), "Content-Encoding": "identity"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        if size < 0:
            size = len(self.payload) - self.position
        result = self.payload[self.position:self.position + size]
        self.position += len(result)
        return result


def make_ttf_fixture():
    head = bytearray(54)
    struct.pack_into(">I", head, 12, 0x5F0F3CF5)
    struct.pack_into(">H", head, 18, 1000)
    tables = {
        "cmap": b"\x00\x00\x00\x01",
        "fvar": struct.pack(">HHHHHHHH", 1, 0, 16, 2, 1, 20, 0, 0),
        "glyf": b"g",
        "head": bytes(head),
        "hhea": bytes(36),
        "maxp": b"\x00\x01\x00\x00\x00\x01",
        "name": bytes(6),
    }
    ordered = sorted(tables.items())
    start = 12 + 16 * len(ordered)
    records = []
    body = bytearray()
    for tag, payload in ordered:
        while (start + len(body)) % 4:
            body.append(0)
        offset = start + len(body)
        records.append(struct.pack(">4sIII", tag.encode("ascii"), 0, offset, len(payload)))
        body.extend(payload)
    header = struct.pack(">IHHHH", 0x00010000, len(ordered), 0, 0, 0)
    return header + b"".join(records) + bytes(body)


class CiFontAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ci-font-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_repository_provenance_matches_the_exact_official_blob(self):
        provenance = Path(__file__).resolve().parents[1] / "ui/assets/fonts/PROVENANCE.txt"
        result = ci.parse_provenance(provenance)
        self.assertEqual(result["commit"], ci.FONT_COMMIT)
        self.assertEqual(result["path"], ci.FONT_REPOSITORY_PATH)
        self.assertEqual(result["blob_sha1"], ci.FONT_BLOB_SHA1)
        self.assertEqual(result["bytes"], str(ci.FONT_BYTES))
        self.assertEqual(result["sha256"], ci.FONT_SHA256)
        self.assertEqual(result["license_blob_sha1"], ci.FONT_LICENSE_BLOB_SHA1)
        self.assertEqual(result["license_sha256"], ci.FONT_LICENSE_SHA256)
        license_record = ci.verify_font_license(provenance.parent / "OFL.txt")
        self.assertEqual(license_record["sha256"], ci.FONT_LICENSE_SHA256)
        public_copy = Path(__file__).resolve().parents[1] / "docs/licenses/fonts/noto-sans-sc/OFL.txt"
        self.assertEqual(ci.verify_font_license(public_copy)["git_blob_sha1"], ci.FONT_LICENSE_BLOB_SHA1)

    def test_only_the_pinned_github_blob_https_url_is_accepted(self):
        ci._assert_approved_url(ci.FONT_URL)
        for url in (ci.FONT_URL.replace("https://", "http://"),
                    ci.FONT_URL.replace("api.github.com", "github.com"),
                    ci.FONT_URL + "?ref=other", "https://example.invalid/font.ttf"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ci._assert_approved_url(url)

    def test_git_blob_sha1_uses_git_blob_header(self):
        payload = b"fixture bytes only"
        expected = hashlib.sha1(b"blob 18\0" + payload).hexdigest()
        self.assertEqual(ci.git_blob_sha1(payload), expected)

    def test_ttf_parser_checks_bounded_variable_font_structure(self):
        fixture = make_ttf_fixture()
        path = self.root / "fixture.ttf"
        path.write_bytes(fixture)
        with mock.patch.object(ci, "FONT_BYTES", len(fixture)):
            summary = ci.inspect_ttf(path)
        self.assertEqual(summary["sfnt"], "TrueType 1.0")
        self.assertTrue(summary["variable_font"])
        self.assertEqual(summary["glyph_count"], 1)
        self.assertEqual(summary["axis_count"], 1)

    def test_ttf_parser_rejects_bad_header_or_truncated_directory(self):
        for payload in (b"wOF2" + b"\x00" * 40, b"\x00\x01\x00\x00" + b"\x00" * 8):
            path = self.root / (str(len(payload)) + ".ttf")
            path.write_bytes(payload)
            with mock.patch.object(ci, "FONT_BYTES", len(payload)):
                with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                    ci.inspect_ttf(path)

    def test_download_verifies_git_blob_and_sha256_without_following_redirects(self):
        payload = make_ttf_fixture()
        actual_blob = ci.git_blob_sha1(payload)
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(payload)
        with mock.patch.object(ci, "build_opener", return_value=opener), \
                mock.patch.object(ci, "FONT_BYTES", len(payload)), \
                mock.patch.object(ci, "FONT_BLOB_SHA1", actual_blob), \
                mock.patch.object(ci, "FONT_SHA256", actual_sha256):
            destination = self.root / "NotoSansSC-wght.ttf"
            summary = ci.download_font(destination)
        self.assertEqual(summary["git_blob_sha1"], actual_blob)
        self.assertEqual(summary["sha256"], actual_sha256)
        self.assertEqual(destination.read_bytes(), payload)
        opener.open.assert_called_once()

    def test_download_rejects_changed_blob_digest(self):
        payload = make_ttf_fixture()
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(payload)
        with mock.patch.object(ci, "build_opener", return_value=opener), \
                mock.patch.object(ci, "FONT_BYTES", len(payload)), \
                mock.patch.object(ci, "FONT_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "identity"):
                ci.download_font(self.root / "wrong-font.ttf")

    def test_explicit_step_credential_is_bound_to_pinned_request_and_not_receipt(self):
        payload = make_ttf_fixture()
        token = "ghs_" + "a" * 36
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(payload)
        with mock.patch.dict(ci.os.environ, {"CHASTEADY_CI_FONT_GITHUB_TOKEN": token}), \
                mock.patch.object(ci, "build_opener", return_value=opener) as build, \
                mock.patch.object(ci, "FONT_BYTES", len(payload)), \
                mock.patch.object(ci, "FONT_BLOB_SHA1", ci.git_blob_sha1(payload)), \
                mock.patch.object(ci, "FONT_SHA256", hashlib.sha256(payload).hexdigest()):
            result = ci.download_font(self.root / "authenticated-font.ttf")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, ci.FONT_URL)
        self.assertEqual(request.get_header("Authorization"), "Bearer " + token)
        self.assertNotIn(token, str(result))
        self.assertTrue(any(isinstance(handler, ci.NoRedirect) for handler in build.call_args.args))
        self.assertIsNone(ci.NoRedirect().redirect_request(request, None, 302, "redirect", {}, "https://example.invalid/"))
        opener.open.assert_called_once()

    def test_invalid_credential_is_rejected_without_echo_or_network(self):
        for value in ("ghs_" + "a" * 36 + "\r\nX-Injected: private", "x" * 513, "short", "private secret value"):
            with mock.patch.dict(ci.os.environ, {"CHASTEADY_CI_FONT_GITHUB_TOKEN": value}), \
                    mock.patch.object(ci, "build_opener") as build, self.assertRaises(ValueError) as failure:
                ci.download_font(self.root / "never-created.ttf")
            self.assertNotIn(value, str(failure.exception))
            build.assert_not_called()
        with mock.patch.dict(ci.os.environ, {"GH_TOKEN": "ghp_" + "b" * 36, "GITHUB_TOKEN": "ghs_" + "c" * 36}, clear=True), \
                mock.patch.object(ci, "build_opener") as build:
            build.return_value.open.side_effect = ci.HTTPError(ci.FONT_URL, 302, "redirect", {}, None)
            with self.assertRaisesRegex(RuntimeError, "redirect"):
                ci.download_font(self.root / "redirect-font.ttf")
            self.assertIsNone(build.return_value.open.call_args.args[0].get_header("Authorization"))
            build.return_value.open.assert_called_once()

    def test_workflow_font_credential_is_step_scoped_with_read_only_permissions(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
        font = workflow[workflow.index("      - name: Fetch and verify the pinned Noto font"):].split("\n      - name:", 1)[0]
        self.assertIn("        env:\n          CHASTEADY_CI_FONT_GITHUB_TOKEN: ${{ github.token }}", font)
        self.assertEqual(workflow.count("CHASTEADY_CI_FONT_GITHUB_TOKEN"), 1)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("--token", font)

    def test_font_download_directory_is_new_unique_and_empty(self):
        first = ci.new_empty_uuid_dir(self.root / "font-cache", "font-")
        second = ci.new_empty_uuid_dir(self.root / "font-cache", "font-")
        self.assertNotEqual(first, second)
        self.assertFalse(any(first.iterdir()))
        self.assertFalse(any(second.iterdir()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
