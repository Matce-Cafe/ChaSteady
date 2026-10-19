"""使用自有纯文本夹具验证维护规范，不运行 Git 或应用。"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("project_conventions", Path(__file__).with_name("check_project_conventions.py"))
conventions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conventions)
VALID = "【工作台、任务】改善导航 / 保留工作区草稿\n\n- 修复 Windows 窄窗导航\n- 同步测试与说明\n"
CHANGELOG = "# 更新日志\n\n# 0.2.0（未发布）\n\n## 2026-10-19\n\n### 框架\n\n#### 新增\n\n- 加入维护规范\n"


class ConventionTests(unittest.TestCase):
    def test_chinese_subject_and_entries(self):
        result = conventions.validate_commit_message(VALID)
        self.assertEqual(result["entry_count"], 2)
        self.assertEqual(result["trailer_count"], 0)

    def test_standard_attribution_trailer_is_allowed(self):
        value = VALID + "\nCo-Authored-By: Example <example@example.invalid>\n"
        self.assertEqual(conventions.validate_commit_message(value)["trailer_count"], 1)

    def test_missing_subject_blank_or_bullet_is_rejected(self):
        for value in ("English title\n\n- example\n", "【框架】标题\n- 说明\n",
                      "【框架】标题\n\n说明\n", "【框架】标题\n\n- \n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                conventions.validate_commit_message(value)

    def test_cjk_english_and_numeric_spacing(self):
        for title in ("修复Windows导航", "新增2项测试"):
            with self.subTest(title=title), self.assertRaises(ValueError):
                conventions.validate_commit_message("【框架】" + title + "\n\n- 更新说明\n")

    def test_boundaries_and_controls_are_rejected(self):
        for value in (VALID.rstrip("\n"), VALID + "\n", VALID.replace("\n", "\r\n"),
                      VALID + "\x00", "【框架】标题\n\n- " + "测" * 8192 + "\n"):
            with self.subTest(size=len(value)), self.assertRaises(ValueError):
                conventions.validate_commit_message(value)

    def test_arbitrary_footer_is_rejected(self):
        with self.assertRaises(ValueError):
            conventions.validate_commit_message(VALID + "\nextra instructions\n")

    def document_fixture(self, root, changelog=CHANGELOG):
        (root / "README.md").write_text("# 项目\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("# 维护\n\n## Git 提交规范\n", encoding="utf-8")
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")

    def test_document_hierarchy(self):
        with tempfile.TemporaryDirectory(prefix="conventions-") as value:
            root = Path(value)
            self.document_fixture(root)
            result = conventions.validate_documents(root)
        self.assertEqual(result["changelog_versions"], ["0.2.0"])
        self.assertTrue(result["validated"])

    def test_missing_document_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="conventions-") as value:
            with self.assertRaises(FileNotFoundError):
                conventions.validate_documents(Path(value))

    def test_invalid_date_category_and_module_are_rejected(self):
        for text in (CHANGELOG.replace("2026-10-19", "2026-02-30"),
                     CHANGELOG.replace("#### 新增", "#### 待办"),
                     CHANGELOG.replace("### 框架\n", "")):
            with self.subTest(text=text), tempfile.TemporaryDirectory(prefix="conventions-") as value:
                root = Path(value)
                self.document_fixture(root, text)
                with self.assertRaises(ValueError):
                    conventions.validate_documents(root)

    def test_git_revision_option_is_not_accepted(self):
        with mock.patch.object(conventions.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                conventions.read_commit_message(Path.cwd(), "--unsafe-option")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
