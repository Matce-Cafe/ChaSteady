import os
import tempfile
import unittest
from pathlib import Path

from cha_stabilizer.paths import (
    UnsafePathError,
    create_run_directory,
    ensure_not_alias,
    path_is_within,
    resolve_local_input,
    validate_local_path_syntax,
    validate_run_directory,
    validate_owned_file,
)


class PathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = self.root / "private" / "runs"
        self.runs.mkdir(parents=True)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"source")

    def tearDown(self):
        self.temp.cleanup()

    def test_local_path_lexical_rules_reject_urls_unc_devices_and_relative_paths(self):
        with self.assertRaises(UnsafePathError):
            validate_local_path_syntax("relative.mp4")
        with self.assertRaises(UnsafePathError):
            validate_local_path_syntax("https://example.invalid/video.mp4")
        with self.assertRaises(UnsafePathError):
            validate_local_path_syntax("\\\\server\\share\\video.mp4")
        with self.assertRaises(UnsafePathError):
            validate_local_path_syntax("\\\\?\\C:\\Windows\\video.mp4")
        with self.assertRaises(UnsafePathError):
            validate_local_path_syntax("C:/media/video.mp4:secret")
        self.assertEqual(validate_local_path_syntax(str(self.source)), str(self.source))

    def test_input_file_must_be_regular_and_not_a_symlink(self):
        self.assertEqual(resolve_local_input(str(self.source)), self.source.resolve())
        with self.assertRaises(UnsafePathError):
            resolve_local_input(str(self.root))
        link = self.root / "source-link.mp4"
        try:
            link.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable in this test environment")
        with self.assertRaises(UnsafePathError):
            resolve_local_input(str(link))

    def test_directory_reparse_point_is_rejected_before_input_resolution(self):
        target = self.root / "real-source-dir"
        target.mkdir()
        actual = target / "source.mp4"
        actual.write_bytes(b"source")
        alias = self.root / "source-dir-alias"
        try:
            alias.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory reparse points are unavailable in this test environment")
        with self.assertRaises(UnsafePathError):
            resolve_local_input(str(alias / "source.mp4"))

    def test_run_directory_is_unique_and_owned_output_cannot_escape(self):
        run_dir = create_run_directory(self.runs)
        self.assertTrue(path_is_within(run_dir, self.runs))
        output = run_dir / "render.mp4"
        output.write_bytes(b"rendered")
        self.assertEqual(validate_owned_file(output, run_dir), output.resolve())
        with self.assertRaises(UnsafePathError):
            validate_owned_file(self.source, run_dir)

    def test_job_run_directory_reparse_swap_is_rejected(self):
        run_dir = create_run_directory(self.runs)
        moved = self.root / run_dir.name
        run_dir.rename(moved)
        try:
            run_dir.symlink_to(moved, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory reparse points are unavailable in this test environment")
        with self.assertRaises(UnsafePathError):
            validate_run_directory(run_dir, self.runs, run_dir.name)

    def test_output_aliases_are_rejected(self):
        run_dir = create_run_directory(self.runs)
        linked = run_dir / "hard-link.mp4"
        try:
            os.link(str(self.source), str(linked))
        except (OSError, NotImplementedError):
            self.skipTest("hard links are unavailable in this test environment")
        with self.assertRaises(UnsafePathError):
            validate_owned_file(linked, run_dir, [self.source])
        with self.assertRaises(UnsafePathError):
            ensure_not_alias(self.source, [linked])


if __name__ == "__main__":
    unittest.main()
