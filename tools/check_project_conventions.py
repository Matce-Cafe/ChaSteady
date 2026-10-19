"""校验中文提交格式与项目维护文档，不修改 Git 或工作区。"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOC_NAMES = ("README.md", "CLAUDE.md", "CHANGELOG.md")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
TRAILER_PATTERN = re.compile(r"(?:Co-authored-by|Signed-off-by): .+ <[^<>\s]+@[^<>\s]+>", re.I)


def validate_commit_message(message):
    if (type(message) is not str or not message.endswith("\n")
            or message.endswith("\n\n") or "\r" in message or "\x00" in message
            or len(message.encode("utf-8")) > 8192):
        raise ValueError("提交信息必须是有界 UTF-8 文本并以一个换行结束")
    lines = message.splitlines()
    if (len(lines) < 3 or lines[1] != ""
            or not re.fullmatch(r"【[^】\r\n]{1,40}】[^\r\n]+", lines[0])
            or not re.search(r"[一-鿿]", lines[0])):
        raise ValueError("提交格式应为中文模块标题、空行和变更条目")
    entries, trailers = [], []
    in_trailers = False
    for line in lines[2:]:
        if not line:
            if not entries or in_trailers:
                raise ValueError("变更说明存在多余空行")
            in_trailers = True
        elif in_trailers:
            if not TRAILER_PATTERN.fullmatch(line):
                raise ValueError("提交尾注格式不正确")
            trailers.append(line)
        elif line.startswith("- ") and line[2:].strip():
            entries.append(line)
        else:
            raise ValueError("每个变更说明必须以 - 开头")
    if not entries or in_trailers and not trailers:
        raise ValueError("提交缺少变更条目或尾注")
    if re.search(r"[一-鿿][A-Za-z0-9]|[A-Za-z0-9][一-鿿]", "\n".join(lines[:2] + entries)):
        raise ValueError("中文与英文或数字之间必须留空格")
    return {"subject": lines[0], "entry_count": len(entries), "trailer_count": len(trailers)}


def read_regular(path, maximum):
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("维护文档路径不能含链接或重解析点")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
        raise ValueError("维护文档不是有界普通文件")
    return path.read_text(encoding="utf-8")


def validate_documents(root):
    texts = {name: read_regular(root / name, 1024 * 1024) for name in DOC_NAMES}
    if any(not text.strip() for text in texts.values()):
        raise ValueError("维护文档不能为空")
    changelog = texts["CHANGELOG.md"]
    versions = re.findall(r"^# (\d+\.\d+\.\d+)(?:[（ (].*)?$", changelog, re.M)
    dates = re.findall(r"^## (\d{4}-\d{2}-\d{2})$", changelog, re.M)
    if not versions or not dates:
        raise ValueError("更新日志必须包含版本与日期层级")
    for value in dates:
        datetime.date.fromisoformat(value)
    if not re.search(r"^### \S.+$", changelog, re.M):
        raise ValueError("更新日志缺少模块层级")
    categories = re.findall(r"^#### (.+)$", changelog, re.M)
    if not categories or any(value not in {"新增", "修复", "变更", "移除"} for value in categories):
        raise ValueError("更新日志分类不符合约定")
    if "Git 提交规范" not in texts["CLAUDE.md"]:
        raise ValueError("CLAUDE.md 缺少 Git 提交规范")
    return {"documents": list(DOC_NAMES), "changelog_versions": versions,
            "changelog_dates": dates, "validated": True}


def read_commit_message(repo, requested_sha=None):
    environment = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_PAGER="")
    command = ["git", "-c", "core.fsmonitor=false", "-C", str(repo)]
    def invoke(*arguments):
        return subprocess.run(command + list(arguments), capture_output=True,
                              check=True, env=environment, timeout=30).stdout
    sha = requested_sha or invoke("rev-parse", "--verify", "HEAD").decode("ascii").strip()
    if not SHA_PATTERN.fullmatch(sha):
        raise ValueError("提交号必须为完整 SHA-1")
    size_text = invoke("cat-file", "-s", sha).decode("ascii").strip()
    if not size_text.isdecimal() or not 1 <= int(size_text) <= 65536:
        raise ValueError("提交对象超过校验上限")
    raw = invoke("cat-file", "commit", sha)
    if len(raw) != int(size_text):
        raise ValueError("提交对象长度改变")
    header, separator, message = raw.partition(b"\n\n")
    if not separator or not header.startswith(b"tree "):
        raise ValueError("提交对象格式不正确")
    return sha, message.decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check-head", action="store_true")
    modes.add_argument("--commit-sha")
    modes.add_argument("--message-file", type=Path)
    parser.add_argument("--check-docs", action="store_true")
    args = parser.parse_args()
    if not (args.check_head or args.commit_sha or args.message_file or args.check_docs):
        parser.error("至少选择一项提交或文档校验")
    root = args.root.absolute()
    result = {"scope": "source_maintenance_conventions_only", "passed": True,
              "git_modified": False, "runtime_verified": False}
    if args.message_file:
        result["commit_message"] = validate_commit_message(read_regular(args.message_file.absolute(), 8192))
    elif args.check_head or args.commit_sha:
        sha, message = read_commit_message(root, args.commit_sha)
        result["commit_sha"] = sha
        result["commit_message"] = validate_commit_message(message)
    if args.check_docs:
        result["maintenance_documents"] = validate_documents(root)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
