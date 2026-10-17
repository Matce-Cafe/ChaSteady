"""Unit tests for the CI Flutter archive guard; no archive is executed/downloaded."""
import hashlib
import io
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_provision_flutter as ci


class FakeResponse:
    def __init__(self, payload, url=None, status=200):
        self.payload = payload
        self.position = 0
        self.status = status
        self.url = url or ci.FLUTTER_URL
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


class FlutterProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ci-flutter-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_archive(self, entries=None):
        if entries is None:
            entries = [
                ("flutter/bin/flutter.bat", b"fixture only; never executed", 0),
                ("flutter/bin/cache/dart-sdk/bin/dart.exe", b"fixture only; never executed", 0),
                ("flutter/README.txt", b"notice", 0),
            ]
        path = self.root / "fixture.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data, mode in entries:
                info = zipfile.ZipInfo(name)
                if mode:
                    info.external_attr = mode << 16
                archive.writestr(info, data)
        payload = path.read_bytes()
        return path, payload

    def pin_fixture(self, archive_path, payload):
        return mock.patch.multiple(
            ci,
            FLUTTER_ARCHIVE_BYTES=len(payload),
            FLUTTER_SHA256=hashlib.sha256(payload).hexdigest(),
        )

    def test_url_is_exact_official_https_release(self):
        ci._approved_url(ci.FLUTTER_URL)
        for url in (
            "http://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.47.7-stable.zip",
            "https://example.com/flutter.zip",
            ci.FLUTTER_URL + "?redirect=1",
            ci.FLUTTER_URL.replace("3.47.7", "3.47.6"),
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ci._approved_url(url)

    def test_member_guard_rejects_traversal_links_and_windows_aliases(self):
        invalid = (
            "../flutter/bin/flutter.bat", "flutter/../outside", "flutter\\bin\\x",
            "/flutter/bin/x", "flutter/CON.txt", "flutter/dir./x", "flutter/name:stream",
        )
        for name in invalid:
            info = zipfile.ZipInfo(name.replace("\\\\", "/"))
            info.filename = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                ci._safe_member(info)
        link = zipfile.ZipInfo("flutter/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            ci._safe_member(link)

    def test_inspect_and_extract_small_archive_without_running_fixture_bytes(self):
        archive_path, payload = self.make_archive()
        with self.pin_fixture(archive_path, payload):
            rows, audit = ci.inspect_archive(archive_path)
            extraction = self.root / "empty-extraction-root"
            extraction.mkdir()
            ci.extract_checked(archive_path, extraction, rows)
        self.assertEqual(audit["entry_count"], 3)
        self.assertEqual((extraction / "flutter/bin/flutter.bat").read_bytes(), b"fixture only; never executed")
        self.assertEqual((extraction / "flutter/bin/cache/dart-sdk/bin/dart.exe").read_bytes(),
                         b"fixture only; never executed")

    def test_archive_hash_must_match_before_member_use(self):
        archive_path, payload = self.make_archive()
        with mock.patch.object(ci, "FLUTTER_ARCHIVE_BYTES", len(payload)), \
                mock.patch.object(ci, "FLUTTER_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "digest"):
                ci.inspect_archive(archive_path)

    def test_archive_rejects_path_traversal_and_case_collisions(self):
        bad_archives = [
            [("flutter/bin/flutter.bat", b"a", 0), ("flutter/bin/cache/dart-sdk/bin/dart.exe", b"b", 0),
             ("flutter/../escape", b"x", 0)],
            [("flutter/bin/flutter.bat", b"a", 0), ("flutter/bin/cache/dart-sdk/bin/dart.exe", b"b", 0),
             ("flutter/Readme.txt", b"a", 0), ("flutter/README.txt", b"b", 0)],
            [("flutter/bin", b"not-a-directory", 0), ("flutter/bin/flutter.bat", b"x", 0),
             ("flutter/bin/cache/dart-sdk/bin/dart.exe", b"y", 0)],
        ]
        for entries in bad_archives:
            with self.subTest(entries=entries):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive_path, payload = self.make_archive(entries)
                with self.pin_fixture(archive_path, payload):
                    with self.assertRaises(ValueError):
                        ci.inspect_archive(archive_path)

    def test_archive_rejects_symlink_entry_before_extraction(self):
        entries = [
            ("flutter/bin/flutter.bat", b"a"),
            ("flutter/bin/cache/dart-sdk/bin/dart.exe", b"b"),
        ]
        path = self.root / "linked.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries:
                archive.writestr(name, data)
            info = zipfile.ZipInfo("flutter/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "target")
        payload = path.read_bytes()
        with self.pin_fixture(path, payload):
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                ci.inspect_archive(path)

    def test_extraction_requires_a_new_empty_root(self):
        archive_path, payload = self.make_archive()
        with self.pin_fixture(archive_path, payload):
            rows, _ = ci.inspect_archive(archive_path)
            target = self.root / "not-empty"
            target.mkdir()
            (target / "sentinel").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                ci.extract_checked(archive_path, target, rows)
            self.assertEqual((target / "sentinel").read_text(encoding="utf-8"), "keep")

    def test_download_uses_strict_pinned_source_and_hash(self):
        payload = b"small test archive bytes"
        response = FakeResponse(payload)
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(ci, "build_opener", return_value=opener), \
                mock.patch.object(ci, "FLUTTER_ARCHIVE_BYTES", len(payload)), \
                mock.patch.object(ci, "FLUTTER_SHA256", hashlib.sha256(payload).hexdigest()):
            destination = self.root / "download.zip"
            info = ci.download_archive(ci.FLUTTER_URL, destination)
        self.assertEqual(destination.read_bytes(), payload)
        self.assertEqual(info["sha256"], hashlib.sha256(payload).hexdigest())
        opener.open.assert_called_once()

    def test_download_rejects_redirect_without_following_it(self):
        opener = mock.Mock()
        opener.open.side_effect = HTTPError(ci.FLUTTER_URL, 302, "redirect", {"Location": "https://example.invalid"}, io.BytesIO())
        with mock.patch.object(ci, "build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "redirect"):
                ci.download_archive(ci.FLUTTER_URL, self.root / "redirect.zip")
        opener.open.assert_called_once()

    def test_download_digest_mismatch_fails(self):
        payload = b"not the pinned archive"
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(payload)
        with mock.patch.object(ci, "build_opener", return_value=opener), \
                mock.patch.object(ci, "FLUTTER_ARCHIVE_BYTES", len(payload)), \
                mock.patch.object(ci, "FLUTTER_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                ci.download_archive(ci.FLUTTER_URL, self.root / "bad-hash.zip")

    def test_analyzer_path_budget_counts_implicit_directories_in_utf16(self):
        rows = [(None, PurePosixPath("flutter/dev/one/two/fixture.txt"), False),
                (None, PurePosixPath("flutter/examples/emoji-\U0001f600"), True),
                (None, PurePosixPath("flutter/packages/pkg/pubspec.yaml"), False),
                (None, PurePosixPath("flutter/bin/cache/not-in-repo-scan/file"), False)]
        result = ci.analyzer_path_budget(Path("D:/short-sdk"), rows)
        lengths = result["subtree_directory_suffix_utf16_max"]
        self.assertEqual(lengths["dev"], len("/dev/one/two"))
        self.assertEqual(lengths["examples"], len("/examples/emoji-\U0001f600".encode("utf-16-le")) // 2)
        self.assertEqual(lengths["packages"], len("/packages/pkg"))
        self.assertLess(result["longest_combined_directory_utf16_units"], result["limit_exclusive"])
        with self.assertRaisesRegex(ValueError, "directory-path budget"):
            ci.analyzer_path_budget(Path("D:/" + "x" * 230), rows)

    def test_provision_compacts_extraction_container_without_skipping_archive_members(self):
        archive_path, payload = self.make_archive()
        scratch = self.root / "scratch"
        def copy_download(_url, destination):
            destination.write_bytes(payload)
            return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
        with self.pin_fixture(archive_path, payload), mock.patch.object(ci, "download_archive", side_effect=copy_download):
            result = ci.provision(scratch)
        extracted = Path(result["extraction_directory"])
        self.assertEqual(extracted.parent, scratch.resolve(strict=True) / "e")
        self.assertRegex(extracted.name, r"^f-[0-9a-f]{32}$")
        self.assertNotEqual(Path(result["download_directory"]), extracted)
        sdk = Path(result["sdk_root"])
        self.assertEqual(sdk, extracted / "flutter")
        self.assertEqual((sdk / "README.txt").read_bytes(), b"notice")
        self.assertEqual((sdk / "bin/flutter.bat").read_bytes(), b"fixture only; never executed")
        budget = result["archive_audit"]["analyzer_path_budget"]
        self.assertEqual(budget["sdk_root_utf16_units"], len(str(sdk).encode("utf-16-le")) // 2)
        self.assertLess(budget["longest_combined_directory_utf16_units"], 240)

    def test_download_and_extraction_allocations_are_separate_unique_empty_dirs(self):
        downloads = self.root / "downloads"
        extractions = self.root / "extractions"
        first = ci.new_empty_uuid_dir(downloads, "flutter-")
        second = ci.new_empty_uuid_dir(downloads, "flutter-")
        extracted = ci.new_empty_uuid_dir(extractions, "flutter-")
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, extracted)
        self.assertFalse(any(first.iterdir()))
        self.assertFalse(any(second.iterdir()))
        self.assertFalse(any(extracted.iterdir()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
