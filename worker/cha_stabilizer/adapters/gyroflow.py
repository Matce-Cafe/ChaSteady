"""Bounded, profile-audited Gyroflow CLI export adapter.

The adapter builds a fresh project/output below the job's owned run directory,
backs up every observed file below the audited Gyroflow profile roots, and never
uses Gyroflow's overwrite switch. Frame-count and source/output PTS mapping are
validated independently of the CLI exit code.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import itertools
import math
import os
import queue
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..errors import AppError, CancelledError, NeedsManualError, NeedsReviewError
from ..runtime_context import RunnerContext
from ..core.bounded_io import capture_small, consume_lines
from ..owned_processes import get_active_registry, spawn_owned_process
from ..paths import (
    UnsafePathError,
    _assert_no_reparse_components,
    resolve_local_input,
    path_is_within,
    same_file_or_alias,
    validate_owned_file,
    validate_run_directory,
)


_MSIX_VERSION = "1.6.3"
_MSIX_SHA256 = "047cee67a60a346dba89d0b8926f02aebe9aa02515afe93a9d7382d86a12a1d8"
_MSIX_PACKAGE_FAMILY = "29160AdrianRoss.Gyroflow_q81n4e8pq4bra"
_NIGHTLY_VERSION = "1.6.3 (gh2811)"
_NIGHTLY_SHA256 = "979baa4f6a4c6e4988c006450d8cf5f80442b1e48a322e7596fbb87b6e5731e7"
_NIGHTLY_COMMIT = "79765f45a079ac6936bd3ea481e0ff101b8c3ed2"
_PROFILE_RELATIVES = (
    Path("AppData") / "Local" / "Gyroflow",
    Path("AppData") / "Local" / "Packages" / _MSIX_PACKAGE_FAMILY / "LocalCache" / "Local" / "Gyroflow",
)
_CACHE_KEYS = ("raw_imu", "quaternions", "image_orientations", "gravity_vectors")
_OUTPUT_PRESETS = {
    "reference_1080p": {"width": 1920, "height": 1080, "bitrate_mbps": 40.0},
    "reference_720p": {"width": 1280, "height": 720, "bitrate_mbps": 8.0},
}
_PROGRESS = re.compile(r"Rendering progress:\s*(\d+)\s*/\s*(\d+)\s*frames\s*\(([\d.]+)%\)", re.I)


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _probe_report_default() -> Path:
    return _root() / "docs" / "gyroflow_export_probe.json"


def _configured_executable(config: Optional[Dict[str, Any]]) -> Optional[Path]:
    config = config if isinstance(config, dict) else {}
    value = config.get("executable")
    if value is None:
        value = config.get("gyroflow")
    toolchain = config.get("toolchain")
    if value is None and isinstance(toolchain, dict):
        value = toolchain.get("gyroflow")
    if isinstance(value, dict):
        value = value.get("path")
    if isinstance(value, (str, Path)) and str(value).strip():
        try:
            return resolve_local_input(str(value), "configured Gyroflow executable")
        except (OSError, ValueError, UnsafePathError):
            return None
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binary_identity(
    path: Path,
    digest: Optional[str] = None,
    development_identity: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Match exact audited binary pins only at paths supplied by dev config."""
    normalized = os.path.normcase(str(Path(path).resolve(strict=True))).casefold()
    development_identity = development_identity if isinstance(development_identity, dict) else {}
    msix_value = development_identity.get("msix_executable")
    if isinstance(msix_value, (str, Path)):
        msix_path = Path(msix_value)
        if normalized == os.path.normcase(str(msix_path.resolve(strict=False))).casefold() and (
            digest is None or digest.casefold() == _MSIX_SHA256
        ):
            return {
                "build_id": "stable_msix_1.6.3",
                "path": str(msix_path),
                "version": _MSIX_VERSION,
                "sha256": _MSIX_SHA256,
                "package_family": _MSIX_PACKAGE_FAMILY,
                "commit": None,
                "direct_cli_launch_supported": False,
            }
    nightly_value = development_identity.get("nightly_executable")
    if isinstance(nightly_value, (str, Path)):
        nightly_path = Path(nightly_value)
        if normalized == os.path.normcase(str(nightly_path.resolve(strict=False))).casefold() and (
            digest is None or digest.casefold() == _NIGHTLY_SHA256
        ):
            return {
                "build_id": "official_nightly_gh2811",
                "path": str(nightly_path),
                "version": _NIGHTLY_VERSION,
                "sha256": _NIGHTLY_SHA256,
                "package_family": None,
                "commit": _NIGHTLY_COMMIT,
                "direct_cli_launch_supported": True,
            }
    return None


def _pe_version(path: Path) -> Optional[str]:
    # 只读 PE 版本资源，不启动 GUI，也不信任文件名或 HTTP 提交的 verified 标记。
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes
        library = ctypes.WinDLL("version", use_last_error=True)
        library.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        library.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        library.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        library.GetFileVersionInfoW.restype = wintypes.BOOL
        library.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                           ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        library.VerQueryValueW.restype = wintypes.BOOL
        ignored = wintypes.DWORD()
        size = library.GetFileVersionInfoSizeW(str(path), ctypes.byref(ignored))
        if not 0 < size <= 1024 * 1024:
            return None
        data = ctypes.create_string_buffer(size)
        if not library.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not library.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
            return None
        fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
        if fields[0] != 0xFEEF04BD:
            return None
        high, low = fields[2], fields[3]
        return "{}.{}.{}.{}".format(high >> 16, high & 0xFFFF, low >> 16, low & 0xFFFF)
    except (OSError, ValueError, AttributeError):
        return None


def _production_binary_identity(path: Path, digest: str) -> Optional[Dict[str, Any]]:
    # catalog 只含已审公开版本、摘要和源码身份，不含开发者本机安装路径。
    audited = {
        _MSIX_SHA256: ("stable_msix_1.6.3", _MSIX_VERSION, False, _MSIX_PACKAGE_FAMILY, None),
        _NIGHTLY_SHA256: ("official_nightly_gh2811", _NIGHTLY_VERSION, True, None, _NIGHTLY_COMMIT),
    }.get(digest.casefold())
    actual_version = _pe_version(path)
    if audited is None or actual_version is None or actual_version.split(".")[:3] != ["1", "6", "3"]:
        return None
    return {
        "build_id": audited[0], "path": str(path), "version": audited[1], "sha256": digest,
        "direct_cli_launch_supported": audited[2], "package_family": audited[3], "commit": audited[4],
        "actual_file_version": actual_version, "identity_source": "compiled_audited_sha256_and_pe_version",
        "source_url": "https://github.com/gyroflow/gyroflow",
    }


def _identity_for_toolchain(path: Path, digest: str, toolchain: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    context = toolchain.get("_runner_context")
    if isinstance(context, RunnerContext) and context.production:
        return _production_binary_identity(path, digest)
    if "development_identity" in toolchain:
        return _binary_identity(path, digest, toolchain.get("development_identity"))
    return _binary_identity(path, digest)


def _load_probe_report(path: Path) -> Dict[str, Any]:
    try:
        _assert_no_reparse_components(path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def capabilities(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect Gyroflow and match it against the local audited probe report.

    Accepted config keys are ``executable`` (str or Path) and ``probe_report``
    (str or Path). ``toolchain.gyroflow`` is also accepted for parity with
    existing adapters. A report outside this project's docs path is not trusted.
    """
    executable = _configured_executable(config)
    detected = executable is not None
    config = config if isinstance(config, dict) else {}
    context = config.get("_runner_context")
    if isinstance(context, RunnerContext) and context.production:
        digest = _sha256_file(executable) if executable is not None else None
        identity = _production_binary_identity(executable, digest) if executable is not None else None
        executable_supported = bool(identity and identity["direct_cli_launch_supported"])
        return {
            "detected": detected, "path": str(executable) if executable is not None else None,
            "mode": "cli", "build_id": identity.get("build_id") if identity else None,
            "version": identity.get("version") if identity else None, "sha256": digest,
            "actual_file_version": identity.get("actual_file_version") if identity else None,
            "identity_verified": identity is not None,
            "identity_source": identity.get("identity_source") if identity else None,
            "execution_supported": executable_supported,
            "prior_verified": False, "export_verified": False, "trim_mapping_verified": False,
            "content_correspondence_verified": False,
            "cli_status": "audited_binary" if executable_supported else "blocked" if identity else "unverified",
            "validation_status": "requires_new_export_validation", "profile_safety_required": True,
            "probe_report": None,
        }
    report_value = config.get("probe_report")
    report_path = Path(report_value) if isinstance(report_value, (str, Path)) else _probe_report_default()
    expected_report = _probe_report_default()
    try:
        report_path = report_path.resolve(strict=True)
        report_is_canonical = os.path.normcase(str(report_path)).casefold() == os.path.normcase(
            str(expected_report.resolve(strict=False))
        ).casefold()
    except (OSError, RuntimeError):
        report_is_canonical = False
    record = _load_probe_report(report_path) if report_is_canonical else {}
    stable_installation = record.get("installation") if isinstance(record.get("installation"), dict) else {}
    stable_audit = record.get("audit") if isinstance(record.get("audit"), dict) else {}
    stable_export = record.get("export_probe") if isinstance(record.get("export_probe"), dict) else {}
    nightly_record = record.get("nightly_build") if isinstance(record.get("nightly_build"), dict) else {}
    nightly_installation = nightly_record.get("installation") if isinstance(nightly_record.get("installation"), dict) else {}
    nightly_audit = nightly_record.get("audit") if isinstance(nightly_record.get("audit"), dict) else {}
    nightly_export = nightly_record.get("export_probe") if isinstance(nightly_record.get("export_probe"), dict) else {}

    executable_hash = None
    if detected:
        try:
            executable_hash = _sha256_file(executable)
        except OSError:
            detected = False
            executable = None
    configured_path = str(executable.resolve(strict=True)) if detected and executable else None
    if detected and executable and executable_hash:
        if "development_identity" in config:
            identity = _binary_identity(executable, executable_hash, config.get("development_identity"))
        else:
            identity = _binary_identity(executable, executable_hash)
    else:
        identity = None
    candidates = [
        ("stable_msix_1.6.3", stable_installation, stable_audit, stable_export),
        ("official_nightly_gh2811", nightly_installation, nightly_audit, nightly_export),
    ]
    selected = next((
        item for item in candidates
        if identity is not None
        and item[0] == identity["build_id"]
        and isinstance(item[1].get("path"), str)
        and os.path.normcase(configured_path).casefold() == os.path.normcase(item[1]["path"]).casefold()
        and item[1].get("version") == identity["version"]
        and item[1].get("sha256") == identity["sha256"]
    ), None)
    installation, audit, export_probe = selected[1:] if selected else ({}, {}, {})
    same_binary = selected is not None
    invocation_verified = bool(
        same_binary
        and audit.get("cli_invocation_verified") is True
        and audit.get("cli_exit_code") == 0
        and audit.get("profile_backup_verified") is True
        and audit.get("profile_post_matches_pre") is True
        and audit.get("tool_directory_post_matches_pre", True) is True
        and audit.get("concurrent_process_check") == "clear"
    )
    prior_verified = bool(invocation_verified)
    trim_mapping_verified = bool(prior_verified and export_probe.get("trim_mapping_verified") is True)
    export_verified = bool(
        prior_verified
        and export_probe.get("media_export_verified") is True
        and export_probe.get("validation_status") == "verified_media"
    )
    cli_blocked = bool(same_binary and audit.get("cli_launch_status") == "blocked_before_process_creation")
    validation_status = (
        export_probe.get("validation_status") if prior_verified
        else "cli_blocked" if cli_blocked
        else "not_audited"
    )
    cli_status = "not_detected" if not detected else "verified" if prior_verified else "blocked" if cli_blocked else "unverified"
    status = (
        "not_detected" if not detected
        else "installed_cli_blocked" if cli_blocked
        else "installed_cli_verified" if prior_verified
        else "installed_unverified"
    )
    return {
        "detected": detected,
        "path": configured_path,
        "mode": "cli",
        "build_id": identity.get("build_id") if identity else None,
        "version": installation.get("version") if same_binary else (identity.get("version") if identity else None),
        "sha256": executable_hash,
        "commit": identity.get("commit") if identity else None,
        "prior_verified": prior_verified,
        "export_verified": export_verified,
        "trim_mapping_verified": trim_mapping_verified,
        "cli_status": cli_status,
        "status": status,
        "probe_report": str(expected_report),
        "validation_status": validation_status,
        "profile_safety_required": True,
    }


def _known_profile_directory() -> Path:
    """Read FOLDERID_Profile directly, matching the audited Gyroflow source."""
    if os.name != "nt":
        raise OSError("Gyroflow profile resolution requires the Windows Profile known folder")
    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    folder_id = _GUID()
    ctypes.memmove(ctypes.byref(folder_id), uuid.UUID("5e6c858f-0e22-4760-9afe-ea3317b67173").bytes_le, 16)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    raw = ctypes.c_wchar_p()
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    result = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(raw))
    if result != 0 or not raw.value:
        raise OSError("Windows did not return the Profile known folder")
    try:
        return Path(raw.value)
    finally:
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole32.CoTaskMemFree(ctypes.cast(raw, ctypes.c_void_p))


def _profile_roots() -> List[Tuple[str, Path]]:
    try:
        profile = _known_profile_directory()
    except OSError as exc:
        raise NeedsReviewError("The Gyroflow profile directory could not be resolved from Windows FOLDERID_Profile; no APPDATA fallback is allowed.") from exc
    return [("profile_{}".format(index), profile / relative) for index, relative in enumerate(_PROFILE_RELATIVES)]


def _process_owner_context(*, deadline: Optional[float] = None, cancel: Any = None) -> Dict[str, Any]:
    # 只读 documented TokenUser/WTS 元数据；不提权，不把 NULL SID 或进程名当系统证明。
    if os.name != "nt":
        raise OSError("process_owner_metadata_unavailable")
    from ctypes import wintypes

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class _TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", _SID_AND_ATTRIBUTES)]

    class _WTS_PROCESS_INFO_EXW(ctypes.Structure):
        _fields_ = [("SessionId", wintypes.DWORD), ("ProcessId", wintypes.DWORD),
                    ("pProcessName", wintypes.LPWSTR), ("pUserSid", ctypes.c_void_p),
                    ("NumberOfThreads", wintypes.DWORD), ("HandleCount", wintypes.DWORD),
                    ("PagefileUsage", wintypes.DWORD), ("PeakPagefileUsage", wintypes.DWORD),
                    ("WorkingSetSize", wintypes.DWORD), ("PeakWorkingSetSize", wintypes.DWORD),
                    ("UserTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong)]

    def check():
        if _cancelled(cancel):
            raise CancelledError("Process owner/session inspection was cancelled.")
        if deadline is not None and time.monotonic() > deadline:
            raise OSError("process_owner_metadata_timeout")

    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        kernel.GetCurrentProcess.argtypes = []
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel.ProcessIdToSessionId.restype = wintypes.BOOL
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        advapi.GetTokenInformation.restype = wintypes.BOOL
        advapi.IsValidSid.argtypes = [ctypes.c_void_p]
        advapi.IsValidSid.restype = wintypes.BOOL
        advapi.GetLengthSid.argtypes = [ctypes.c_void_p]
        advapi.GetLengthSid.restype = wintypes.DWORD
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
        wts.WTSEnumerateProcessesExW.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                               ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
        wts.WTSEnumerateProcessesExW.restype = wintypes.BOOL
        wts.WTSFreeMemoryExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.ULONG]
        wts.WTSFreeMemoryExW.restype = wintypes.BOOL

        def sid_text(pointer):
            if not pointer or not advapi.IsValidSid(pointer) or not 8 <= advapi.GetLengthSid(pointer) <= 68:
                return None
            text = wintypes.LPWSTR()
            if not advapi.ConvertSidToStringSidW(pointer, ctypes.byref(text)):
                return None
            try:
                value = text.value
                return value if isinstance(value, str) and len(value) <= 184 else None
            finally:
                kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))

        check()
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise OSError("current_process_token_unreadable")
        try:
            needed = wintypes.DWORD()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if not ctypes.sizeof(_TOKEN_USER) <= needed.value <= 65536:
                raise OSError("current_process_token_size_unverified")
            data = ctypes.create_string_buffer(needed.value)
            if not advapi.GetTokenInformation(token, 1, data, needed.value, ctypes.byref(needed)):
                raise OSError("current_process_token_unreadable")
            current_sid = sid_text(ctypes.cast(data, ctypes.POINTER(_TOKEN_USER)).contents.User.Sid)
        finally:
            kernel.CloseHandle(token)
        session = wintypes.DWORD()
        if not current_sid or not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
            raise OSError("current_process_owner_session_unverified")
        check()
        level, count, pointer = wintypes.DWORD(1), wintypes.DWORD(), ctypes.c_void_p()
        if not wts.WTSEnumerateProcessesExW(None, ctypes.byref(level), 0xFFFFFFFE, ctypes.byref(pointer), ctypes.byref(count)):
            raise OSError("wts_owner_session_enumeration_unavailable")
        owners = {}
        try:
            if level.value != 1 or count.value > 4096 or not pointer.value:
                raise OSError("wts_owner_session_inventory_unverified")
            rows = ctypes.cast(pointer, ctypes.POINTER(_WTS_PROCESS_INFO_EXW))
            for index in range(count.value):
                check()
                row = rows[index]
                pid = int(row.ProcessId)
                if pid in owners:
                    raise OSError("wts_duplicate_process_identity")
                owners[pid] = {"sid": sid_text(row.pUserSid), "session_id": int(row.SessionId),
                               "name": row.pProcessName or ""}
        finally:
            if pointer.value and not wts.WTSFreeMemoryExW(1, pointer, count.value):
                raise OSError("wts_owner_metadata_release_failed")
        own = owners.get(os.getpid(), {})
        if own.get("sid") != current_sid or own.get("session_id") != int(session.value):
            raise OSError("current_owner_wts_crosscheck_failed")
        check()
        return {"current_user_sid": current_sid, "current_session_id": int(session.value), "owners": owners}
    except AttributeError as exc:
        raise OSError("process_owner_metadata_api_unavailable") from exc


def _isolated_system_identity(row: Dict[str, Any], context: Dict[str, Any]) -> bool:
    current = context.get("current_user_sid")
    current_session = context.get("current_session_id")
    builtins = ("S-1-5-18", "S-1-5-19", "S-1-5-20")
    if (not isinstance(current, str) or not current.startswith("S-") or current in builtins
            or isinstance(current_session, bool) or not isinstance(current_session, int) or not 0 <= current_session < 0xFFFFFFFE):
        return False
    name = str(row.get("name", ""))
    if not name or "gyroflow" in name.casefold() or row.get("query_error") != 5:
        return False
    owner = context.get("owners", {}).get(row.get("pid"), {})
    sid, session = owner.get("sid"), owner.get("session_id")
    if (sid not in builtins or sid == current or isinstance(session, bool) or not isinstance(session, int)
            or not 0 <= session < 0xFFFFFFFE or str(owner.get("name", "")).casefold() != name.casefold()):
        return False
    # 内置服务账户限 session 0；SYSTEM 可承载各会话的受保护 OS 进程。
    # 这是 primary-token 用户状态域隔离，不是根据 csrss.exe 等名字放行。
    return sid == "S-1-5-18" or session == 0


def _windows_process_images(*, deadline: Optional[float] = None, cancel: Any = None) -> List[Dict[str, Any]]:
    # 只用查询权限读取实际映像，不挂接、暂停、终止或接管任何现有进程。
    if os.name != "nt":
        raise OSError("Windows process-image auditing is unavailable")
    from ctypes import wintypes

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    snapshot_value = snapshot.value if hasattr(snapshot, "value") else snapshot
    if not snapshot_value or snapshot_value == ctypes.c_void_p(-1).value:
        raise OSError("Windows process list could not be inspected")
    result = []
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if _cancelled(cancel):
                raise CancelledError("The process-image metadata query was cancelled.")
            if deadline is not None and time.monotonic() > deadline:
                raise OSError("process_image_metadata_timeout")
            if len(result) >= 4096:
                raise OSError("process_image_pid_budget_exceeded")
            pid = int(entry.th32ProcessID)
            if pid not in (0, os.getpid()):
                row = {"pid": pid, "name": str(entry.szExeFile), "image_path": None, "query_error": None}
                ctypes.set_last_error(0)
                process = kernel32.OpenProcess(0x1000, False, pid)
                if process:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        length = wintypes.DWORD(len(buffer))
                        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)) and buffer.value:
                            row["image_path"] = buffer.value
                        else:
                            row["query_error"] = int(ctypes.get_last_error())
                    finally:
                        kernel32.CloseHandle(process)
                else:
                    row["query_error"] = int(ctypes.get_last_error())
                result.append(row)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:
            raise OSError("Windows process enumeration ended without a complete snapshot")
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def _pe_resource(path: Path, *, max_bytes: int = 1024 * 1024) -> Optional[bytes]:
    from ctypes import wintypes
    library = ctypes.WinDLL("version", use_last_error=True)
    library.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    library.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    library.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    library.GetFileVersionInfoW.restype = wintypes.BOOL
    unused = wintypes.DWORD()
    size = library.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
    if not size:
        if ctypes.get_last_error() in (1812, 1813, 1814, 1815):
            return None
        raise ctypes.WinError(ctypes.get_last_error(), "process_image_version_metadata_unreadable")
    if size > min(1024 * 1024, max_bytes):
        raise OSError("Process-image version metadata exceeds its remaining byte budget")
    data = ctypes.create_string_buffer(size)
    if not library.GetFileVersionInfoW(str(path), 0, size, data):
        raise ctypes.WinError(ctypes.get_last_error(), "process_image_version_metadata_unreadable")
    return data.raw


def _gyroflow_process_ids(executable: Optional[Path] = None, expected_sha256: Optional[str] = None,
                          *, cancel: Any = None, diagnostics: Optional[Dict[str, Any]] = None) -> List[int]:
    # 这是一轮有界的映像审计，不是按名字宣称绝对清场；任一必要身份未知即失败关闭。
    if executable is None:
        raise OSError("A selected audited engine image is required for concurrency checking")
    selected = resolve_local_input(str(executable), "selected audited engine")
    selected_stat = selected.stat()
    expected_sha256 = expected_sha256 or _sha256_file(selected)
    deadline = time.monotonic() + 5.0
    bytes_read = 0
    inspected_files = 0
    classifications = {}
    found = []
    owner_context = None
    stats = diagnostics if diagnostics is not None else {}
    stats.update({"process_entries": 0, "isolated_system_identities": 0, "unknown_identities": 0,
                  "images_inspected": 0, "engines_detected": 0, "owner_context_verified": False})

    def isolated_system(row):
        nonlocal owner_context
        if owner_context is None:
            owner_context = _process_owner_context(deadline=deadline, cancel=cancel)
            stats["owner_context_verified"] = True
            stats["owner_inventory_entries"] = len(owner_context.get("owners", {}))
        if _isolated_system_identity(row, owner_context):
            stats["isolated_system_identities"] += 1
            return True
        return False

    def access_denied(error):
        for _ in range(4):
            if getattr(error, "winerror", None) == 5:
                return True
            error = getattr(error, "__cause__", None)
            if error is None:
                break
        return False

    for row in _windows_process_images(deadline=deadline, cancel=cancel):
        stats["process_entries"] += 1
        if _cancelled(cancel):
            raise CancelledError("The process-image audit was cancelled.")
        if time.monotonic() > deadline:
            raise OSError("Process-image audit exceeded its time budget")
        image = row.get("image_path")
        if not image:
            stats["unknown_identities"] += 1
            if isolated_system(row):
                stats["unknown_identities"] -= 1
                continue
            raise OSError("process_image_unknown_in_user_state_domain: pid={}".format(row.get("pid")))
        if os.path.normcase(os.path.normpath(str(image))) == os.path.normcase(os.path.normpath(str(selected))):
            found.append(int(row["pid"]))
            stats["engines_detected"] = len(found)
            continue
        try:
            path = resolve_local_input(str(image), "running process image")
            info = path.stat()
        except (OSError, ValueError) as exc:
            stats["unknown_identities"] += 1
            if access_denied(exc) and isolated_system(dict(row, query_error=5)):
                stats["unknown_identities"] -= 1
                continue
            raise OSError("process_image_unreadable_in_user_state_domain: pid={}".format(row.get("pid"))) from exc
        if (str(path).casefold() == str(selected).casefold()
                or (info.st_dev, info.st_ino) == (selected_stat.st_dev, selected_stat.st_ino)
                or "gyroflow" in str(row.get("name", "")).casefold()):
            found.append(int(row["pid"]))
            stats["engines_detected"] = len(found)
            continue
        file_key = (str(path).casefold(), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if file_key in classifications:
            if classifications[file_key]:
                found.append(int(row["pid"]))
            stats["engines_detected"] = len(found)
            continue
        inspected_files += 1
        stats["images_inspected"] = inspected_files
        if inspected_files > 512:
            raise OSError("process_image_file_budget_exceeded")
        if info.st_size == selected_stat.st_size:
            if bytes_read + info.st_size > 128 * 1024 ** 2:
                raise OSError("Process-image audit has insufficient remaining hash-byte budget")
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    while True:
                        if _cancelled(cancel):
                            raise CancelledError("The process-image audit was cancelled.")
                        if time.monotonic() > deadline:
                            raise OSError("Process-image identity hashing exceeded its time budget")
                        chunk = stream.read(65536)
                        if not chunk:
                            break
                        bytes_read += len(chunk)
                        if bytes_read > 128 * 1024 ** 2:
                            raise OSError("Process-image audit exceeded its byte budget")
                        digest.update(chunk)
            except OSError as exc:
                stats["unknown_identities"] += 1
                if access_denied(exc) and isolated_system(dict(row, query_error=5)):
                    stats["unknown_identities"] -= 1
                    continue
                raise OSError("process_image_hash_unreadable_in_user_state_domain: pid={}".format(row.get("pid"))) from exc
            if digest.hexdigest() in (expected_sha256, _MSIX_SHA256, _NIGHTLY_SHA256):
                classifications[file_key] = True
                found.append(int(row["pid"]))
                stats["engines_detected"] = len(found)
                continue
        try:
            resource = _pe_resource(path, max_bytes=128 * 1024 ** 2 - bytes_read)
        except OSError as exc:
            stats["unknown_identities"] += 1
            if access_denied(exc) and isolated_system(dict(row, query_error=5)):
                stats["unknown_identities"] -= 1
                continue
            raise
        if resource is not None:
            bytes_read += len(resource)
            if bytes_read > 128 * 1024 ** 2:
                raise OSError("Process-image audit exceeded its byte budget")
            if "gyroflow" in resource.decode("utf-16-le", errors="ignore").casefold():
                classifications[file_key] = True
                found.append(int(row["pid"]))
                stats["engines_detected"] = len(found)
                continue
        current = path.stat()
        if (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino) != (
            current.st_size, current.st_mtime_ns, current.st_dev, current.st_ino
        ):
            raise OSError("process_image_changed_during_audit: pid={}".format(row.get("pid")))
        classifications[file_key] = False
    if time.monotonic() > deadline:
        raise OSError("process_image_audit_timeout")
    return found


def _cancelled(cancel: Any) -> bool:
    return bool(cancel is not None and getattr(cancel, "is_set", lambda: False)())


def _emit(on_event: Optional[Callable[[str, Optional[float], str], None]], stage: str, progress: Optional[float], message: str) -> None:
    if callable(on_event):
        on_event(stage, progress, message)


def _validate_request(
    request: Dict[str, Any], *, development_identity: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    if not isinstance(request, dict):
        raise NeedsReviewError("Gyroflow request must be an object.")
    allowed = {"original", "project_template", "start", "end", "full_source", "output_preset"}
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise NeedsReviewError("Gyroflow request contains unsupported options.", {"unsupported_fields": unknown})
    original_value = request.get("original")
    if not isinstance(original_value, (str, Path)) or not str(original_value).strip():
        raise NeedsReviewError("Choose an original local media file for Gyroflow export.")
    try:
        original = resolve_local_input(str(original_value), "original")
    except (OSError, ValueError, UnsafePathError) as exc:
        raise NeedsReviewError("Gyroflow requires an existing local source file.", {"reason": str(exc)}) from exc
    template_value = request.get("project_template")
    if template_value is None:
        development_identity = development_identity if isinstance(development_identity, dict) else {}
        template_value = development_identity.get("default_template")
        if template_value is None:
            raise NeedsManualError("Gyroflow export requires an explicitly selected local project template.")
        try:
            template = resolve_local_input(str(template_value), "development Gyroflow project template")
        except (OSError, ValueError, UnsafePathError) as exc:
            raise NeedsManualError("The development Gyroflow project template is unavailable; select a local template.") from exc
    else:
        if not isinstance(template_value, (str, Path)) or not str(template_value).strip():
            raise NeedsReviewError("Gyroflow project template must be a local file path.")
        try:
            template = resolve_local_input(str(template_value), "project_template")
        except (OSError, ValueError, UnsafePathError) as exc:
            raise NeedsReviewError("Gyroflow project template must be an existing local file.", {"reason": str(exc)}) from exc
    if template.stat().st_size > 2 * 1024 * 1024:
        raise NeedsReviewError("Gyroflow project template exceeds the bounded two-MiB schema budget.")
    if same_file_or_alias(original, template):
        raise NeedsReviewError("The source media and Gyroflow project template must be different files.")

    full_source = request.get("full_source", False)
    if not isinstance(full_source, bool):
        raise NeedsReviewError("full_source must be a boolean.")
    output_preset = request.get("output_preset", "reference_1080p")
    if not isinstance(output_preset, str) or output_preset not in _OUTPUT_PRESETS:
        raise NeedsReviewError("output_preset must be reference_1080p or reference_720p.")
    start = request.get("start")
    end = request.get("end")
    if full_source:
        if start is not None or end is not None:
            raise NeedsReviewError("A full-source export cannot also specify a trim range.")
        normalized_start = normalized_end = None
    else:
        if start is None or end is None:
            raise NeedsReviewError("A bounded Gyroflow export requires both start and end; full-source export must be explicit.")
        if isinstance(start, bool) or isinstance(end, bool):
            raise NeedsReviewError("Gyroflow trim bounds must be finite seconds.")
        try:
            normalized_start = float(start)
            normalized_end = float(end)
        except (TypeError, ValueError, OverflowError) as exc:
            raise NeedsReviewError("Gyroflow trim bounds must be finite seconds.") from exc
        if not math.isfinite(normalized_start) or not math.isfinite(normalized_end) or normalized_start < 0 or normalized_end <= normalized_start:
            raise NeedsReviewError("Gyroflow trim range is invalid.", {"start": start, "end": end})
    return {
        "original": original,
        "project_template": template,
        "start": normalized_start,
        "end": normalized_end,
        "full_source": full_source,
        "output_preset": output_preset,
    }


def _validated_run_dir(value: Path, context: Optional[RunnerContext] = None) -> Path:
    run_dir = Path(value)
    try:
        if isinstance(context, RunnerContext):
            return context.validate(run_dir)
        return validate_run_directory(run_dir, _root() / "private" / "runs", run_dir.name)
    except (OSError, ValueError, UnsafePathError) as exc:
        raise NeedsReviewError("Gyroflow requires the current job's owned private/runs UUID workspace.") from exc


def _json_write_new(path: Path, value: Any) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(str(path), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _snapshot_template(source: Path, destination: Path, cancel: Any) -> Dict[str, Any]:
    source = resolve_local_input(str(source), "Gyroflow template source")
    if same_file_or_alias(source, destination):
        raise NeedsReviewError("Template snapshot must not alias its source.")
    digest = hashlib.sha256()
    total = 0
    with source.open("rb") as stream, destination.open("xb") as target:
        before = os.fstat(stream.fileno())
        if before.st_size > 2 * 1024 ** 2:
            raise NeedsReviewError("Template snapshot exceeds the two-MiB budget.")
        while True:
            if _cancelled(cancel):
                raise CancelledError("Template snapshot was cancelled.")
            chunk = stream.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > 2 * 1024 ** 2:
                raise NeedsReviewError("Template source grew beyond its snapshot budget.")
            digest.update(chunk)
            target.write(chunk)
        after = os.fstat(stream.fileno())
        target.flush()
        os.fsync(target.fileno())
    current = resolve_local_input(str(source), "Gyroflow template source").stat()
    fields = ("st_size", "st_mtime_ns", "st_dev", "st_ino")
    if before.st_ctime_ns != after.st_ctime_ns or any(
        getattr(before, key) != getattr(item, key) for item in (after, current) for key in fields
    ):
        raise NeedsReviewError("Template source changed during its owned snapshot.")
    return {"sha256": digest.hexdigest(), "bytes": total, "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns, "device": before.st_dev, "file_id": before.st_ino,
            "source_path": str(source), "snapshot_path": str(destination)}


def _template_source_matches(source: Path, identity: Dict[str, Any], cancel: Any) -> bool:
    try:
        path = resolve_local_input(str(source), "Gyroflow template source")
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_dev, before.st_ino) != (
                identity["bytes"], identity["mtime_ns"], identity["ctime_ns"], identity["device"], identity["file_id"]
            ):
                return False
            digest = hashlib.sha256()
            total = 0
            while True:
                if _cancelled(cancel):
                    raise CancelledError("Template identity validation was cancelled.")
                chunk = stream.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > 2 * 1024 ** 2:
                    return False
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        current = resolve_local_input(str(source), "Gyroflow template source").stat()
        return (total == identity["bytes"] and digest.hexdigest() == identity["sha256"]
                and before.st_mtime_ns == after.st_mtime_ns and before.st_ctime_ns == after.st_ctime_ns
                and (before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino)
                == (current.st_size, current.st_mtime_ns, current.st_dev, current.st_ino))
    except (OSError, ValueError):
        return False


def _build_project(template: Path, source: Path, output_dir: Path, project_path: Path, start: Optional[float], end: Optional[float], full_source: bool, output_preset: str, *, fresh_source: bool = False, template_content: Optional[bytes] = None) -> Path:
    try:
        raw = template_content.decode("utf-8") if template_content is not None else template.read_text(encoding="utf-8")
        project = json.loads(raw)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise NeedsReviewError("Gyroflow project template is not valid UTF-8 JSON.") from exc
    if not isinstance(project, dict) or not isinstance(project.get("gyro_source"), dict) or not isinstance(project.get("output"), dict):
        raise NeedsReviewError("Gyroflow project template is missing required project, gyro-source, or output data.")

    source_url = source.as_uri()
    if fresh_source:
        # 新单原片任务必须重读 Sony 源元数据，不沿用模板上一段视频的尺寸、帧数或姿态。
        project.pop("video_info", None)
    project["title"] = "ChaSteady bounded Gyroflow export"
    project["videofile"] = source_url
    project.pop("calibration_data", None)
    for key in _CACHE_KEYS:
        project.pop(key, None)
    gyro_source = project["gyro_source"]
    gyro_source["filepath"] = source_url
    gyro_source.pop("file_metadata", None)
    for key in _CACHE_KEYS:
        gyro_source.pop(key, None)
    project["offsets"] = {}
    project["keyframes"] = {}
    project["trim_ranges_ms"] = [] if full_source else [[start * 1000.0, end * 1000.0]]

    output_name = "gyroflow_export_{}.mp4".format(uuid.uuid4().hex)
    output = project["output"]
    preset = _OUTPUT_PRESETS[output_preset]
    output.update({
        "codec": "H.264/AVC",
        "output_folder": str(output_dir),
        "output_filename": output_name,
        "output_width": preset["width"],
        "output_height": preset["height"],
        "input_filename": source.name,
        "input_url": source_url,
        "bitrate": preset["bitrate_mbps"],
        "use_gpu": True,
        "audio": True,
        "audio_codec": "AAC",
        "pixel_format": "yuv420p",
        "pad_with_black": False,
        "export_trims_separately": False,
        "preserve_other_tracks": False,
        "interpolation": "Lanczos4",
    })
    output_path = output_dir / output_name
    if output_path.exists() or output_path.is_symlink():
        raise NeedsReviewError("Refusing to overwrite an existing Gyroflow output.")
    _json_write_new(project_path, project)
    return output_path


def _walk_profile_root(root: Path) -> Tuple[bool, Dict[str, Dict[str, Any]], List[str]]:
    try:
        _assert_no_reparse_components(root, allow_missing_leaf=True)
    except (OSError, ValueError, UnsafePathError) as exc:
        raise NeedsReviewError("An audited Gyroflow profile root could not be traversed safely.") from exc
    if not root.exists():
        return False, {}, []
    _assert_no_reparse_components(root)
    if not root.is_dir():
        raise NeedsReviewError("An audited Gyroflow profile root is not a regular directory.", {"profile_root": str(root)})
    files: Dict[str, Dict[str, Any]] = {}
    directories: List[str] = [""]
    for current, dirnames, filenames in os.walk(str(root), followlinks=False):
        current_path = Path(current)
        safe_dirs = []
        for name in sorted(dirnames):
            child = current_path / name
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise NeedsReviewError("A Gyroflow profile contains a link/reparse point; no files were backed up.", {"profile_root": str(root)})
            if not stat.S_ISDIR(info.st_mode):
                raise NeedsReviewError("A Gyroflow profile contains a non-directory child.", {"profile_root": str(root)})
            safe_dirs.append(name)
            directories.append(str(child.relative_to(root)).replace("\\", "/"))
        dirnames[:] = safe_dirs
        for name in sorted(filenames):
            child = current_path / name
            info = child.lstat()
            if not stat.S_ISREG(info.st_mode) or _is_reparse(info) or getattr(info, "st_nlink", 1) != 1:
                raise NeedsReviewError("A Gyroflow profile contains a non-regular or hard-linked file; no launch is allowed.", {"profile_root": str(root)})
            relative = str(child.relative_to(root)).replace("\\", "/")
            files[relative] = {"path": child, "size": int(info.st_size), "sha256": _sha256_file(child)}
    return True, files, sorted(set(directories))


def _profile_snapshot(roots: Sequence[Tuple[str, Path]], backup_dir: Optional[Path] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"roots": [], "files": {}, "directories": {}}
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=False)
    for label, root in roots:
        exists, files, directories = _walk_profile_root(root)
        root_info = {"label": label, "path": str(root), "exists": exists}
        result["roots"].append(root_info)
        result["directories"][label] = directories
        for relative, item in sorted(files.items()):
            key = label + "/" + relative
            backup_path = None
            if backup_dir is not None:
                backup_path = backup_dir / label / Path(relative)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_BINARY"):
                    flags |= os.O_BINARY
                fd = os.open(str(backup_path), flags, 0o600)
                with os.fdopen(fd, "wb") as target, item["path"].open("rb") as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                if _sha256_file(backup_path) != item["sha256"] or backup_path.stat().st_size != item["size"]:
                    raise NeedsReviewError("A Gyroflow profile backup did not match its source bytes.", {"profile_file": str(item["path"])})
            result["files"][key] = {
                "path": str(item["path"]),
                "size": item["size"],
                "sha256": item["sha256"],
                "backup": str(backup_path) if backup_path is not None else None,
            }
    result["backup_verified"] = backup_dir is not None
    return result


def _profile_changes(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    before_files = before.get("files", {})
    after_files = after.get("files", {})
    added = sorted(set(after_files) - set(before_files))
    deleted = sorted(set(before_files) - set(after_files))
    changed = sorted(key for key in set(before_files) & set(after_files) if before_files[key]["sha256"] != after_files[key]["sha256"])
    before_roots = {item["label"]: item["exists"] for item in before.get("roots", [])}
    after_roots = {item["label"]: item["exists"] for item in after.get("roots", [])}
    root_changes = sorted(label for label in set(before_roots) | set(after_roots) if before_roots.get(label, False) != after_roots.get(label, False))
    return {"added": added, "deleted": deleted, "changed": changed, "root_existence_changed": root_changes}


def _restore_known_logs(
    roots: Sequence[Tuple[str, Path]],
    before: Dict[str, Any],
    after: Dict[str, Any],
    *,
    no_concurrency: bool,
    own_write_confirmed: bool,
    launch_time_ns: int,
) -> Dict[str, Any]:
    restored: List[str] = []
    skipped: List[str] = []
    before_files = before.get("files", {})
    after_files = after.get("files", {})
    changed_logs = []
    for label, _root in roots:
        key = label + "/gyroflow.log"
        prior = before_files.get(key)
        current = after_files.get(key)
        if (prior is None) != (current is None) or (
            prior is not None and current is not None and prior.get("sha256") != current.get("sha256")
        ):
            changed_logs.append(key)
    if not no_concurrency:
        return {"restored": restored, "skipped": ["concurrency was not clear"] if changed_logs else skipped}
    if not own_write_confirmed:
        return {"restored": restored, "skipped": ["log content changed without a completed owned CLI launch"] if changed_logs else skipped}
    for label, root in roots:
        relative = "gyroflow.log"
        key = label + "/" + relative
        prior = before_files.get(key)
        current = after_files.get(key)
        if prior is not None and current is not None and prior["sha256"] == current["sha256"]:
            continue
        if prior is None and current is None:
            continue
        current_path = root / relative
        if prior is not None:
            backup_path = Path(prior.get("backup") or "")
            try:
                if not current_path.is_file() or _sha256_file(current_path) != current["sha256"]:
                    raise OSError("the post-launch log changed after its snapshot")
                if current_path.stat().st_mtime_ns + 2_000_000_000 < launch_time_ns:
                    raise OSError("the log modification time does not confirm a launch-time write")
                if _sha256_file(backup_path) != prior["sha256"]:
                    raise OSError("the byte backup no longer matches the pre-launch log")
                temporary = current_path.with_name(".gyroflow.log.restore.{}.tmp".format(uuid.uuid4().hex))
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_BINARY"):
                    flags |= os.O_BINARY
                fd = os.open(str(temporary), flags, 0o600)
                try:
                    with os.fdopen(fd, "wb") as target, backup_path.open("rb") as source:
                        shutil.copyfileobj(source, target, 1024 * 1024)
                        target.flush()
                        os.fsync(target.fileno())
                    if _sha256_file(temporary) != prior["sha256"]:
                        raise OSError("restored log bytes failed their pre-launch SHA-256 check")
                    if _sha256_file(current_path) != current["sha256"]:
                        raise OSError("the profile log changed immediately before restore")
                    os.replace(str(temporary), str(current_path))
                    if _sha256_file(current_path) != prior["sha256"]:
                        raise OSError("restored profile log failed SHA-256 verification")
                    restored.append(str(current_path))
                finally:
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
            except (OSError, KeyError, TypeError):
                skipped.append(str(current_path))
        else:
            try:
                if not current_path.is_file() or _sha256_file(current_path) != current["sha256"]:
                    raise OSError("the new log changed after its post-launch snapshot")
                if current_path.stat().st_mtime_ns + 2_000_000_000 < launch_time_ns:
                    raise OSError("the new log timestamp does not confirm a launch-time write")
                current_path.unlink()
                restored.append(str(current_path) + " (removed; absent before launch)")
            except (OSError, KeyError, TypeError):
                skipped.append(str(current_path))
    # Remove only empty directories created below roots that were absent before
    # launch or created by this run; never remove a directory containing data.
    before_dirs = before.get("directories", {})
    for label, root in roots:
        if not root.exists():
            continue
        original = set(before_dirs.get(label, []))
        new_dirs = []
        for current, dirs, _files in os.walk(str(root), topdown=True, followlinks=False):
            for name in dirs:
                directory = Path(current) / name
                relative = str(directory.relative_to(root)).replace("\\", "/")
                if relative not in original:
                    new_dirs.append(directory)
        for directory in sorted(new_dirs, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        root_was_present = next((item["exists"] for item in before.get("roots", []) if item["label"] == label), False)
        if not root_was_present:
            try:
                root.rmdir()
            except OSError:
                pass
    return {"restored": restored, "skipped": skipped}


def _tool_directory_candidates(root: Path, *, checkpoint: Optional[Callable] = None) -> Tuple[List[str], List[Path]]:
    _assert_no_reparse_components(root)
    roots_by_name: Dict[str, Path] = {}
    for current, dirnames, filenames in os.walk(str(root), followlinks=False):
        if checkpoint:
            checkpoint(len(dirnames) + len(filenames))
        current_path = Path(current)
        safe_dirs = []
        for name in sorted(dirnames):
            child = current_path / name
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise NeedsReviewError("Gyroflow tool directory contains an unsafe directory; no CLI launch is allowed.")
            safe_dirs.append(name)
            if name.casefold() == "camera_presets" or "cache" in name.casefold():
                roots_by_name[child.relative_to(root).as_posix()] = child
        dirnames[:] = safe_dirs
    # 外层 candidate 已涵盖子树；避免重叠缓存目录重复复制同一个文件。
    names = []
    for name in sorted(roots_by_name):
        if not any(path_is_within(roots_by_name[name], roots_by_name[parent]) for parent in names):
            names.append(name)
    return names, [roots_by_name[name] for name in names]


def _tool_directory_snapshot(executable: Path, backup_dir: Optional[Path] = None, *, cancel: Any = None,
                             max_bytes: int = 512 * 1024 ** 2, max_entries: int = 10000,
                             timeout: float = 60.0) -> Dict[str, Any]:
    root = Path(executable).parent
    started = time.monotonic()
    entries = io_bytes = 0

    def check(add_entries=0, add_bytes=0):
        nonlocal entries, io_bytes
        if _cancelled(cancel):
            raise CancelledError("Tool-directory snapshot was cancelled.")
        entries += add_entries
        io_bytes += add_bytes
        if entries > max_entries or io_bytes > max_bytes or time.monotonic() - started > timeout:
            raise NeedsReviewError("Tool-directory snapshot exceeded its entry, total-I/O or time budget; no CLI launch is allowed.")

    check()
    if backup_dir is not None:
        backup_dir = Path(backup_dir)
        # 在扫描、建目标和复制前核双向隔离，不能把 own runs 当作待备份 cache 的子树。
        if path_is_within(backup_dir, root) or path_is_within(root, backup_dir):
            raise NeedsReviewError("Tool-directory source and backup destination overlap; nothing was copied or launched.")
        _assert_no_reparse_components(backup_dir, allow_missing_leaf=True)
    candidate_names, candidates = _tool_directory_candidates(root, checkpoint=check)
    if backup_dir is not None:
        for candidate in candidates:
            if path_is_within(candidate, backup_dir) or path_is_within(backup_dir, candidate):
                raise NeedsReviewError("A cache candidate overlaps the owned backup destination.")
        backup_dir.mkdir(parents=False, exist_ok=False)
    files: Dict[str, Dict[str, Any]] = {}
    nested_directories: Dict[str, List[str]] = {}
    for candidate_name, candidate in zip(candidate_names, candidates):
        nested_directories[candidate_name] = [""]
        for current, dirnames, filenames in os.walk(str(candidate), followlinks=False):
            check(len(dirnames) + len(filenames))
            current_path = Path(current)
            safe_dirs = []
            for name in sorted(dirnames):
                child = current_path / name
                info = child.lstat()
                if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                    raise NeedsReviewError("A Gyroflow cache/profile candidate contains an unsafe directory.")
                safe_dirs.append(name)
                nested_directories[candidate_name].append(child.relative_to(candidate).as_posix())
            dirnames[:] = safe_dirs
            for name in sorted(filenames):
                check()
                child = current_path / name
                info = child.lstat()
                if not stat.S_ISREG(info.st_mode) or _is_reparse(info) or getattr(info, "st_nlink", 1) != 1:
                    raise NeedsReviewError("A Gyroflow cache/profile candidate contains an unsafe file.")
                # 同时预算源读取、目标写入与回读校验，而不是只限制单文件大小。
                required = info.st_size * (3 if backup_dir is not None else 1)
                if io_bytes + required > max_bytes:
                    raise NeedsReviewError("A tool-directory candidate exceeds the remaining total-I/O budget.")
                relative = child.relative_to(root).as_posix()
                backup_path = backup_dir / Path(relative) if backup_dir is not None else None
                digest = hashlib.sha256()
                with contextlib.ExitStack() as stack:
                    source = stack.enter_context(child.open("rb"))
                    target = None
                    if backup_path is not None:
                        backup_path.parent.mkdir(parents=True, exist_ok=True)
                        target = stack.enter_context(backup_path.open("xb"))
                    while True:
                        check()
                        chunk = source.read(65536)
                        if not chunk:
                            break
                        check(add_bytes=len(chunk) * (2 if target is not None else 1))
                        digest.update(chunk)
                        if target is not None:
                            target.write(chunk)
                    if target is not None:
                        target.flush()
                        os.fsync(target.fileno())
                current_info = child.stat()
                if (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino) != (
                    current_info.st_size, current_info.st_mtime_ns, current_info.st_dev, current_info.st_ino
                ):
                    raise NeedsReviewError("A tool-directory candidate changed during its bounded snapshot.")
                if backup_path is not None:
                    copied = hashlib.sha256()
                    with backup_path.open("rb") as stream:
                        while True:
                            check()
                            chunk = stream.read(65536)
                            if not chunk:
                                break
                            check(add_bytes=len(chunk))
                            copied.update(chunk)
                    if copied.hexdigest() != digest.hexdigest() or backup_path.stat().st_size != info.st_size:
                        raise NeedsReviewError("A tool-directory backup failed its SHA-256/size check.")
                files[relative] = {"path": str(child), "size": int(info.st_size), "sha256": digest.hexdigest(),
                                   "backup": str(backup_path) if backup_path is not None else None}
    return {"root": str(root), "candidate_directories": candidate_names,
            "directories": {key: sorted(set(value)) for key, value in nested_directories.items()},
            "files": dict(sorted(files.items())), "backup_verified": backup_dir is not None,
            "snapshot_budget": {"io_bytes": io_bytes, "max_io_bytes": max_bytes, "entries": entries,
                                "max_entries": max_entries, "timeout_seconds": timeout}}


def _tool_directory_changes(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    before_files = before.get("files", {})
    after_files = after.get("files", {})
    added = sorted(set(after_files) - set(before_files))
    deleted = sorted(set(before_files) - set(after_files))
    changed = sorted(key for key in set(before_files) & set(after_files) if before_files[key].get("sha256") != after_files[key].get("sha256"))
    before_dirs = before.get("directories", {})
    after_dirs = after.get("directories", {})
    directory_changes = sorted(key for key in set(before_dirs) | set(after_dirs) if before_dirs.get(key) != after_dirs.get(key))
    candidate_changes = sorted(set(before.get("candidate_directories", [])) ^ set(after.get("candidate_directories", [])))
    return {"added": added, "deleted": deleted, "changed": changed, "directory_changes": directory_changes, "candidate_directory_changes": candidate_changes}


def _parse_time_base(stream: Dict[str, Any]) -> Optional[Fraction]:
    value = stream.get("time_base")
    try:
        fraction = Fraction(str(value))
        return fraction if fraction > 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def _frame_pts(frames: Iterable[Dict[str, Any]], time_base: Optional[Fraction]) -> List[Fraction]:
    result: List[Fraction] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        tick = frame.get("best_effort_timestamp")
        if tick not in (None, "N/A") and time_base is not None:
            try:
                result.append(int(tick) * time_base)
                continue
            except (TypeError, ValueError, OverflowError):
                pass
        timestamp = frame.get("best_effort_timestamp_time")
        if timestamp in (None, "N/A"):
            raise ValueError("ffprobe returned a video frame without a usable presentation timestamp")
        result.append(Fraction(str(timestamp)))
    return result


def _probe_media(path: Path, ffprobe: Path, cancel: Any, interval: Optional[Tuple[float, float]] = None,
                 *, ledger_dir: Optional[Path] = None) -> Dict[str, Any]:
    if ledger_dir is None:
        raise NeedsReviewError("PTS validation requires an owned ledger directory.")
    entries = "format=duration:stream=index,codec_name,codec_type,width,height,pix_fmt,avg_frame_rate,r_frame_rate,time_base,start_time,duration,nb_frames"
    prefix = [str(ffprobe), "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "V:0"]
    try:
        raw = capture_small(prefix + ["-show_streams", "-show_format", "-show_entries", entries, "-of", "json", str(path)], cancel)
        data = json.loads(raw)
        stream = next(item for item in data.get("streams", []) if item.get("codec_type") == "video")
        time_base = _parse_time_base(stream)
        if time_base is None:
            raise ValueError("missing rational time base")
        duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("missing bounded duration")
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        raise NeedsReviewError("ffprobe returned incomplete bounded stream metadata.") from exc
    args = list(prefix)
    if interval is not None:
        start, end = interval
        seek = max(0.0, start)
        duration = max(0.1, end - seek)
        args.extend(["-read_intervals", "{:.9f}%+{:.9f}".format(seek, duration)])
    args += ["-show_frames", "-show_entries", "frame=best_effort_timestamp:frame_side_data=", "-of", "compact=p=0:nk=0", str(path)]
    ledger_path = Path(ledger_dir) / ("pts-" + uuid.uuid4().hex + ".ticks")
    count = 0
    digest = hashlib.sha256()
    with ledger_path.open("xb") as ledger:
        def record(line):
            nonlocal count
            if not line:
                return
            fields = dict(item.split(b"=", 1) for item in line.split(b"|") if b"=" in item)
            tick = fields.get(b"best_effort_timestamp", b"")
            if not re.fullmatch(rb"-?\d{1,24}", tick):
                raise NeedsReviewError("A decoded video frame has no usable PTS; no mapping was accepted.")
            count += 1
            if count > 2_000_000:
                raise NeedsReviewError("PTS validation exceeded its declared two-million-frame budget.")
            row = tick + b"\n"
            ledger.write(row)
            digest.update(row)
        summary = consume_lines(args, record, cancel, timeout=min(14400.0, max(120.0, duration * 8.0)),
                                max_stdout_bytes=256 * 1024 ** 2)
        ledger.flush()
        os.fsync(ledger.fileno())
    if summary["returncode"] or summary["stderr"] or count == 0:
        raise NeedsReviewError("The complete video PTS ledger could not be validated.", {"frames_recorded": count})
    return {"stream": stream, "format": data.get("format", {}), "ledger_path": ledger_path,
            "ledger_sha256": digest.hexdigest(), "ledger_frames": count, "ledger_complete": True}


def _iter_probe_pts(probe: Dict[str, Any]):
    if "pts" in probe:
        yield from probe["pts"]
        return
    if probe.get("ledger_complete") is not True:
        raise NeedsReviewError("An incomplete PTS ledger cannot be used as mapping evidence.")
    path = Path(probe["ledger_path"])
    _assert_no_reparse_components(path)
    time_base = _parse_time_base(probe["stream"])
    count = 0
    digest = hashlib.sha256()
    with path.open("rb") as ledger:
        while True:
            row = ledger.readline(28)
            if not row:
                break
            if len(row) > 26 or not re.fullmatch(rb"-?\d{1,24}\n", row):
                raise NeedsReviewError("The retained PTS ledger is malformed.")
            count += 1
            if count > 2_000_000:
                raise NeedsReviewError("The retained PTS ledger exceeds its frame budget.")
            digest.update(row)
            yield int(row) * time_base
    if count != probe.get("ledger_frames") or digest.hexdigest() != probe.get("ledger_sha256"):
        raise NeedsReviewError("The retained PTS ledger identity changed before acceptance.")


def _decode_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _decode_output(path: Path, ffmpeg: Path, cancel: Any, duration: float = 1800.0) -> Dict[str, Any]:
    args = [
        str(ffmpeg), "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-threads", "3",
        "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:V", "-map", "0:a?",
        "-vsync", "0", "-f", "null", "-",
    ]
    try:
        completed = consume_lines(args, lambda line: None, cancel,
                                  timeout=min(14400.0, max(120.0, duration * 8.0)), max_stdout_bytes=65536)
    except NeedsReviewError as exc:
        return {"passed": False, "error": exc.message}
    passed = completed["returncode"] == 0 and not completed["stderr"]
    return {"passed": passed, "error": _decode_text(completed["stderr"])[-4000:] if not passed else None,
            "scope": "all_non_attached_video_and_all_audio_streams"}


def _decimal(value: Fraction) -> float:
    return float(value.numerator) / float(value.denominator)


def _mapping_evidence(source_probe: Dict[str, Any], output_probe: Dict[str, Any], start: Optional[float], end: Optional[float], full_source: bool, *, cancel: Any = None) -> Dict[str, Any]:
    source_pts = _iter_probe_pts(source_probe)
    if full_source:
        selected = source_pts
    else:
        start_fraction = Fraction(str(start))
        end_fraction = Fraction(str(end))
        selected = (value for value in source_pts if start_fraction <= value < end_fraction)
    output_pts = _iter_probe_pts(output_probe)
    source_stream = source_probe.get("stream", {})
    output_stream = output_probe.get("stream", {})
    source_tb = _parse_time_base(source_stream) or Fraction(1, 1000000)
    output_tb = _parse_time_base(output_stream) or Fraction(1, 1000000)
    expected = actual = 0
    tolerance = source_tb + output_tb
    max_error = None
    source_first = output_first = source_last = output_last = None
    source_monotonic = output_monotonic = True
    sentinel = object()
    started = time.monotonic()
    frame_budget = source_probe.get("ledger_frames", 0) + output_probe.get("ledger_frames", 0)
    mapping_timeout = min(14400.0, max(120.0, frame_budget * 0.001))
    for src, out in itertools.zip_longest(selected, output_pts, fillvalue=sentinel):
        if _cancelled(cancel):
            raise CancelledError("PTS ledger comparison was cancelled.")
        if time.monotonic() - started > mapping_timeout:
            raise NeedsReviewError("PTS ledger comparison exceeded its bounded CPU budget.")
        if src is not sentinel:
            expected += 1
            if source_first is None:
                source_first = src
            if source_last is not None and src <= source_last:
                source_monotonic = False
            source_last = src
        if out is not sentinel:
            actual += 1
            if output_first is None:
                output_first = out
            if output_last is not None and out <= output_last:
                output_monotonic = False
            output_last = out
        if src is not sentinel and out is not sentinel:
            error = abs((out - output_first) - (src - source_first))
            max_error = max(max_error or Fraction(0), error)
    if expected != actual:
        max_error = None
    exact = bool(
        expected > 0
        and expected == actual
        and source_monotonic
        and output_monotonic
        and max_error is not None
        and max_error <= tolerance
    )
    return {
        "trim_mapping_verified": exact,
        "content_correspondence_verified": False,
        "mapping_basis": "presentation timestamp order/count only; no decoded image-content correspondence analysis",
        "expected_frames": expected,
        "actual_frames": actual,
        "source_pts_first_seconds": _decimal(source_first) if source_first is not None else None,
        "source_pts_last_seconds": _decimal(source_last) if source_last is not None else None,
        "output_pts_first_seconds": _decimal(output_first) if output_first is not None else None,
        "output_pts_last_seconds": _decimal(output_last) if output_last is not None else None,
        "pts_mapping_max_abs_error_seconds": _decimal(max_error) if max_error is not None else None,
        "pts_mapping_tolerance_seconds": _decimal(tolerance),
        "source_pts_monotonic": source_monotonic,
        "output_pts_monotonic": output_monotonic,
        "source_time_base": source_stream.get("time_base"),
        "output_time_base": output_stream.get("time_base"),
    }


def _launch_cli(
    executable: Path,
    project_path: Path,
    cwd: Path,
    log_path: Path,
    cancel: Any,
    on_event: Optional[Callable[[str, Optional[float], str], None]],
) -> Dict[str, Any]:
    if any(item.suffix.casefold() == ".dmp" for item in cwd.iterdir()):
        raise NeedsReviewError("Gyroflow CLI working directory contains a crash dump; no launch was allowed.")
    registry = get_active_registry()
    if registry is None:
        raise AppError("Gyroflow CLI must run inside an owned process registry.")
    executable_hash = _sha256_file(executable)
    args = [str(executable), str(project_path), "--stdout-progress"]
    log_handle = log_path.open("xb")
    try:
        process = spawn_owned_process(
            args,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
    except Exception:
        log_handle.close()
        raise
    lines: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=128)
    reader_error: List[str] = []
    reader_stop = threading.Event()

    def _send_line(line) -> None:
        while not reader_stop.is_set():
            try:
                lines.put(line, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read_output() -> None:
        try:
            if process.stdout is not None:
                while not reader_stop.is_set():
                    line = process.stdout.readline(16385)
                    if not line:
                        break
                    if len(line) > 16384:
                        reader_error.append("Gyroflow CLI emitted an oversized line.")
                        break
                    _send_line(line)
        except Exception:
            # 读取失败仍只由当前 registry 管理子进程，不泄露原始异常路径。
            reader_error.append("Gyroflow CLI output could not be read.")
        finally:
            _send_line(None)

    reader = threading.Thread(target=_read_output, name="gyroflow-stdout-reader", daemon=True)
    reader.start()
    tail: List[str] = []
    foreign_process_seen = False
    process_audit_error = None
    done_reading = False
    last_process_check = 0.0
    status_reason = None
    started = time.monotonic()
    log_bytes = 0
    with log_handle as log:
        try:
            while process.poll() is None or not done_reading:
                if reader_error or time.monotonic() - started > 14400.0:
                    status_reason = "bounded_reader_error_or_timeout"
                    registry.terminate_all()
                    break
                if _cancelled(cancel):
                    registry.terminate_all()
                    status_reason = "cancelled"
                    break
                now = time.monotonic()
                if process.poll() is None and now - last_process_check >= 0.25:
                    last_process_check = now
                    try:
                        others = [pid for pid in _gyroflow_process_ids(executable, executable_hash, cancel=cancel) if pid != process.pid]
                    except OSError as exc:
                        process_audit_error = str(exc)[:300]
                        others = [-1]
                    if others:
                        foreign_process_seen = True
                        status_reason = "process_image_audit_unverifiable" if process_audit_error else "concurrent_engine_image_detected"
                        registry.terminate_all()
                        break
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    done_reading = True
                    continue
                log_bytes += len(line)
                if log_bytes > 128 * 1024 ** 2:
                    status_reason = "cli_log_byte_budget_exceeded"
                    registry.terminate_all()
                    break
                log.write(line)
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if text:
                    tail.append(text)
                    if len(tail) > 40:
                        del tail[:len(tail) - 40]
                    match = _PROGRESS.search(text)
                    if match:
                        current, total = int(match.group(1)), int(match.group(2))
                        progress = min(0.99, max(0.0, current / total)) if total > 0 else None
                        _emit(on_event, "gyroflow_export", progress, text[:1000])
            if process.poll() is None:
                registry.terminate_all()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                registry.terminate_all()
                process.wait(timeout=5)
            log.flush()
            os.fsync(log.fileno())
        finally:
            reader_stop.set()
            if process.poll() is None:
                registry.terminate_all()
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            reader.join(timeout=1.0)
            registry.discard(process)
    if status_reason == "cancelled":
        raise CancelledError("Gyroflow export was cancelled; only its owned process was stopped.")
    return {
        "exit_code": process.returncode,
        "tail": tail,
        "foreign_process_seen": foreign_process_seen,
        "process_audit_error": process_audit_error,
        "status_reason": status_reason,
        "reader_error": reader_error[0] if reader_error else None,
    }


def _write_manifest(path: Path, record: Dict[str, Any]) -> None:
    try:
        _json_write_new(path, record)
    except OSError as exc:
        raise AppError("Gyroflow export evidence could not be written to its owned workspace.") from exc


def _output_descriptor(path: Path, metadata: Dict[str, Any], warnings: List[str], verified: bool) -> List[Dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        return []
    return [{
        "path": path,
        "label": "Gyroflow stabilized export" if verified else "Gyroflow export requiring review",
        "kind": "video" if verified else "diagnostic_video",
        "mime": "video/mp4",
        "metadata": metadata,
        "warnings": list(warnings),
        "validation_scope": "source_output_pts_sequence_and_exact_frame_count_plus_full_decode" if verified else "source_output_pts_sequence_and_exact_frame_count_not_verified",
    }]


def _review_diagnostic_descriptors(
    paths: Sequence[Tuple[Path, str, str, str]],
    run_dir: Path,
    inputs: Sequence[Path],
    metadata: Dict[str, Any],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    for path, label, kind, mime in paths:
        try:
            if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
                continue
            resolved = validate_owned_file(path, run_dir, inputs)
        except (OSError, ValueError, UnsafePathError):
            continue
        outputs.append({
            "path": resolved,
            "label": label,
            "kind": kind,
            "mime": mime,
            "metadata": dict(metadata),
            "warnings": list(warnings),
            "validation_scope": "diagnostic_only_not_verified_media",
        })
    return outputs


def run_export(
    request: Dict[str, Any],
    workdir: Path,
    toolchain: Dict[str, Any],
    cancel: Any,
    on_event: Optional[Callable[[str, Optional[float], str], None]],
) -> Dict[str, Any]:
    """Run a fresh owned Gyroflow project and check PTS/count plus full decode.

    PTS cadence/count evidence does not establish per-frame decoded-image
    correspondence; a CFR output must never be treated as such proof.
    """
    if _cancelled(cancel):
        raise CancelledError("Gyroflow export was cancelled before preparation.")
    toolchain = toolchain if isinstance(toolchain, dict) else {}
    context = toolchain.get("_runner_context")
    development_identity = toolchain.get("development_identity")
    if isinstance(context, RunnerContext) and context.production:
        development_identity = None
    validated = _validate_request(request, development_identity=development_identity)
    run_dir = _validated_run_dir(Path(workdir), context)
    executable_value = toolchain.get("gyroflow")
    ffprobe_value = toolchain.get("ffprobe")
    ffmpeg_value = toolchain.get("ffmpeg")
    if not all(isinstance(value, (str, Path)) for value in (executable_value, ffprobe_value, ffmpeg_value)):
        raise AppError("Gyroflow export requires configured Gyroflow, ffprobe, and ffmpeg executables.")
    try:
        executable = resolve_local_input(str(executable_value), "configured Gyroflow executable")
        ffprobe = resolve_local_input(str(ffprobe_value), "configured ffprobe executable")
        ffmpeg = resolve_local_input(str(ffmpeg_value), "configured ffmpeg executable")
    except (OSError, ValueError, UnsafePathError) as exc:
        raise AppError("Gyroflow, ffprobe, and ffmpeg must be existing local executables.") from exc
    executable_hash = _sha256_file(executable)
    identity = _identity_for_toolchain(executable, executable_hash, toolchain)
    if identity is None:
        raise NeedsReviewError(
            "Configured Gyroflow binary does not match either explicitly audited build; no export was started.",
            {"configured_path": str(executable), "sha256": executable_hash},
        )
    if not identity["direct_cli_launch_supported"]:
        raise NeedsReviewError(
            "The installed MSIX executable is known to block direct owned CLI process creation, and no supported App Execution Alias exists; no retry was made.",
            {"build_id": identity["build_id"], "path": identity["path"], "version": identity["version"], "sha256": identity["sha256"], "cli_status": "blocked"},
        )
    if _cancelled(cancel):
        raise CancelledError("Gyroflow export was cancelled before preparation.")

    attempt_dir = run_dir / ("gyroflow-" + uuid.uuid4().hex)
    try:
        attempt_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise NeedsReviewError("A fresh Gyroflow workspace could not be created without overwriting.") from exc
    output_dir = attempt_dir / "export"
    output_dir.mkdir(mode=0o700, exist_ok=False)
    cli_cwd = attempt_dir / "cli-cwd"
    cli_cwd.mkdir(mode=0o700, exist_ok=False)
    project_path = attempt_dir / "owned_export.gyroflow"
    template_snapshot = attempt_dir / "template-used.gyroflow"
    template_identity = _snapshot_template(validated["project_template"], template_snapshot, cancel)
    with template_snapshot.open("rb") as stream:
        template_content = stream.read(2 * 1024 ** 2 + 1)
    if len(template_content) != template_identity["bytes"] or hashlib.sha256(template_content).hexdigest() != template_identity["sha256"]:
        raise NeedsReviewError("The owned template snapshot changed before project construction.")
    output_path = _build_project(
        template_snapshot, validated["original"], output_dir, project_path,
        validated["start"], validated["end"], validated["full_source"], validated["output_preset"],
        fresh_source=toolchain.get("_fresh_source_project") is True, template_content=template_content,
    )
    project_size = project_path.stat().st_size
    if project_size > 16 * 1024 ** 2:
        raise NeedsReviewError("The generated project exceeds its bounded input budget.")
    project_sha256 = _sha256_file(project_path)
    log_path = attempt_dir / "gyroflow-cli.log"
    manifest_path = attempt_dir / "gyroflow_export_manifest.json"
    profile_roots = _profile_roots()

    try:
        existing_processes = _gyroflow_process_ids(executable, executable_hash, cancel=cancel)
    except OSError as exc:
        raise NeedsReviewError("The selected engine process-image audit could not be completed; no CLI launch was allowed.",
                               {"concurrent_process_check": "unverifiable", "reason": str(exc)[:300]}) from exc
    if existing_processes:
        raise NeedsReviewError(
            "Another Gyroflow process is active; this adapter will not take over or launch concurrently.",
            {"concurrent_process_check": "blocked", "active_process_count": len(existing_processes)},
        )
    profile_backup_dir = attempt_dir / "profile-backup"
    before = _profile_snapshot(profile_roots, profile_backup_dir)
    if not before.get("backup_verified"):
        raise NeedsReviewError("Gyroflow profile files were not backed up and verified; no CLI launch was allowed.")
    tool_backup_dir = attempt_dir / "tool-directory-backup"
    tool_before = _tool_directory_snapshot(executable, tool_backup_dir, cancel=cancel)
    if not tool_before.get("backup_verified"):
        raise NeedsReviewError("Gyroflow tool-directory camera presets/cache candidates were not backed up; no CLI launch was allowed.")
    if any(item.suffix.casefold() == ".dmp" for item in cli_cwd.iterdir()):
        raise NeedsReviewError("Gyroflow CLI working directory contains a crash dump; no launch was allowed.")
    # Repeat the process guard after the byte-backed snapshot, immediately before launch.
    try:
        existing_processes = _gyroflow_process_ids(executable, executable_hash, cancel=cancel)
    except OSError as exc:
        raise NeedsReviewError("The selected engine process-image audit failed after profile backup; no CLI launch was allowed.",
                               {"concurrent_process_check": "unverifiable", "reason": str(exc)[:300]}) from exc
    if existing_processes:
        raise NeedsReviewError(
            "Another Gyroflow process appeared during profile backup; this adapter will not launch.",
            {"concurrent_process_check": "blocked", "active_process_count": len(existing_processes)},
        )

    if _sha256_file(executable) != executable_hash:
        raise NeedsReviewError("Gyroflow executable identity changed after preflight; no CLI launch was allowed.")
    if isinstance(context, RunnerContext) and context.production and _production_binary_identity(executable, executable_hash) != identity:
        raise NeedsReviewError("Gyroflow executable version identity changed after preflight.")
    if not _template_source_matches(validated["project_template"], template_identity, cancel):
        raise NeedsReviewError("Template source changed before CLI launch; only the original owned snapshot was retained.",
                               {"template_used_sha256": template_identity["sha256"]})
    if project_path.stat().st_size != project_size or _sha256_file(project_path) != project_sha256:
        raise NeedsReviewError("The generated project identity changed before CLI launch.")
    launch_time_ns = time.time_ns()
    _emit(on_event, "gyroflow_preflight", 0.0, "Profile backups verified; starting the bounded local Gyroflow CLI export.")
    launch: Dict[str, Any] = {"exit_code": None, "tail": [], "foreign_process_seen": False, "status_reason": None}
    launch_error: Optional[BaseException] = None
    try:
        launch = _launch_cli(executable, project_path, cli_cwd, log_path, cancel, on_event)
    except BaseException as exc:
        launch_error = exc

    # 任一并发映像或未知身份都禁止日志恢复；仅记录有界时点审计，不宣称绝对排他。
    concurrency_errors = [launch["process_audit_error"]] if launch.get("process_audit_error") else []
    try:
        post_processes = _gyroflow_process_ids(executable, executable_hash, cancel=cancel)
    except OSError as exc:
        concurrency_errors.append(str(exc)[:300])
        post_processes = [-1]
    concurrent_clear = not launch.get("foreign_process_seen", False) and not post_processes
    after_launch: Dict[str, Any]
    try:
        after_launch = _profile_snapshot(profile_roots)
    except (OSError, ValueError, UnsafePathError, NeedsReviewError) as exc:
        after_launch = {"roots": [], "files": {}, "directories": {}, "snapshot_error": str(exc)}
    try:
        tool_after_launch = _tool_directory_snapshot(executable, cancel=cancel)
    except (OSError, ValueError, UnsafePathError, NeedsReviewError) as exc:
        tool_after_launch = {"root": str(executable.parent), "candidate_directories": [], "directories": {}, "files": {}, "snapshot_error": str(exc)}
    tool_dir_diff = _tool_directory_changes(tool_before, tool_after_launch)
    tool_dir_matches = not any(tool_dir_diff.values()) and "snapshot_error" not in tool_after_launch
    try:
        restore_processes = _gyroflow_process_ids(executable, executable_hash, cancel=cancel)
    except OSError as exc:
        concurrency_errors.append(str(exc)[:300])
        restore_processes = [-1]
    concurrent_clear = concurrent_clear and not restore_processes
    log_restoration = _restore_known_logs(
        profile_roots, before, after_launch,
        no_concurrency=concurrent_clear,
        own_write_confirmed=launch.get("exit_code") is not None,
        launch_time_ns=launch_time_ns,
    )
    try:
        after_restore_processes = _gyroflow_process_ids(executable, executable_hash, cancel=cancel)
    except OSError as exc:
        concurrency_errors.append(str(exc)[:300])
        after_restore_processes = [-1]
    concurrent_clear = concurrent_clear and not after_restore_processes
    try:
        final_profile = _profile_snapshot(profile_roots)
    except (OSError, ValueError, UnsafePathError, NeedsReviewError) as exc:
        final_profile = {"roots": [], "files": {}, "directories": {}, "snapshot_error": str(exc)}
    profile_diff = _profile_changes(before, final_profile)
    profile_matches = not any(profile_diff.values()) and "snapshot_error" not in final_profile

    if isinstance(launch_error, CancelledError):
        raise launch_error
    output_metadata: Dict[str, Any] = {}
    output_warnings: List[str] = []
    output_exists = output_path.is_file() and not output_path.is_symlink() and output_path.stat().st_size > 0
    if output_exists:
        try:
            validate_owned_file(output_path, run_dir, [validated["original"], validated["project_template"]])
        except (OSError, ValueError, UnsafePathError) as exc:
            raise NeedsReviewError("Gyroflow output failed owned-workspace validation and will not be exposed.", {"reason": str(exc)}) from exc

    probe_evidence: Dict[str, Any] = {}
    decode_evidence: Dict[str, Any] = {"passed": False, "error": "Output was not created."}
    source_probe: Optional[Dict[str, Any]] = None
    output_probe: Optional[Dict[str, Any]] = None
    probe_error: Optional[str] = None
    if output_exists and launch.get("exit_code") == 0:
        try:
            interval = None
            if not validated["full_source"]:
                interval = (max(0.0, validated["start"] - 2.0), validated["end"] + 2.0)
            source_probe = _probe_media(validated["original"], ffprobe, cancel, interval, ledger_dir=attempt_dir)
            output_probe = _probe_media(output_path, ffprobe, cancel, ledger_dir=attempt_dir)
            probe_evidence = _mapping_evidence(
                source_probe, output_probe, validated["start"], validated["end"], validated["full_source"], cancel=cancel,
            )
            output_metadata = {
                "codec_name": output_probe["stream"].get("codec_name"),
                "width": output_probe["stream"].get("width"),
                "height": output_probe["stream"].get("height"),
                "pixel_format": output_probe["stream"].get("pix_fmt"),
                "fps": output_probe["stream"].get("avg_frame_rate"),
                "duration_seconds": (output_probe.get("format") or {}).get("duration"),
                "frame_mapping": probe_evidence,
            }
            decode_duration = float((output_probe.get("format") or {}).get("duration") or 1800.0)
            decode_evidence = _decode_output(output_path, ffmpeg, cancel, decode_duration)
        except (NeedsReviewError, CancelledError) as exc:
            if isinstance(exc, CancelledError):
                raise
            probe_error = exc.message
            if isinstance(exc.details, dict):
                output_metadata["probe_details"] = exc.details
        except Exception as exc:
            probe_error = "Media timestamp validation failed: {}".format(type(exc).__name__)
    elif launch.get("exit_code") not in (0, None):
        probe_error = "Gyroflow CLI exited with code {}.".format(launch.get("exit_code"))
    elif launch_error is not None:
        probe_error = "Gyroflow CLI launch failed: {}".format(type(launch_error).__name__)

    cli_invocation_verified = bool(
        launch_error is None
        and launch.get("exit_code") == 0
        and launch.get("status_reason") is None
        and not launch.get("reader_error")
        and concurrent_clear
        and Path(log_path).is_file()
    )
    template_source_unchanged = _template_source_matches(validated["project_template"], template_identity, cancel)
    with template_snapshot.open("rb") as stream:
        snapshot_after = stream.read(2 * 1024 ** 2 + 1)
    with project_path.open("rb") as stream:
        project_after = stream.read(16 * 1024 ** 2 + 1)
    template_snapshot_unchanged = (len(snapshot_after) == template_identity["bytes"]
                                   and hashlib.sha256(snapshot_after).hexdigest() == template_identity["sha256"])
    project_input_unchanged = len(project_after) == project_size and hashlib.sha256(project_after).hexdigest() == project_sha256
    verified = bool(
        cli_invocation_verified
        and template_source_unchanged and template_snapshot_unchanged and project_input_unchanged
        and profile_matches
        and tool_dir_matches
        and probe_evidence.get("trim_mapping_verified") is True
        and decode_evidence.get("passed") is True
        and not probe_error
    )
    if launch.get("exit_code") is not None:
        cli_launch_status = "started_and_exited"
    elif isinstance(launch_error, PermissionError):
        cli_launch_status = "blocked_before_process_creation"
    elif launch_error is not None:
        cli_launch_status = "launch_failed"
    else:
        cli_launch_status = "not_started"
    validation_status = "verified_media" if verified else "needs_review"
    warnings: List[str] = [
        "Verification checks source/output PTS sequence, exact frame count, and full decode only; it does not establish decoded image-content correspondence (CFR alone is not proof) or certify stabilization quality, corners, FOV, or perceptual quality.",
        "Gyroflow CLI may send lens-profile checksum usage metadata; audited CLI paths showed no footage upload. Crash-dump upload is guarded by a fresh empty CLI working directory.",
    ]
    if validated["full_source"]:
        warnings.append("Full-source rendering was explicitly requested; this adapter does not authorize it by default.")
    if validated["output_preset"] == "reference_720p":
        warnings.append("reference_720p is an 8-bit H.264 reference output, not a 4K/10-bit master or original-FOV certificate.")
    if not template_source_unchanged or not template_snapshot_unchanged or not project_input_unchanged:
        warnings.append("Template source or owned project identity changed; the manifest retains the actual pre-export template/project identities, not a replacement hash.")
    if not cli_invocation_verified:
        warnings.append("Gyroflow CLI invocation did not complete under the bounded process-image concurrency audit.")
    if not profile_matches:
        warnings.append("Gyroflow profile contents did not match their byte-backed pre-launch snapshot; no settings file was automatically restored.")
    if not tool_dir_matches:
        warnings.append("Gyroflow tool-directory camera_presets/cache candidates changed; no tool-directory file was automatically restored.")
    if not probe_evidence.get("trim_mapping_verified"):
        warnings.append("Exact source-to-output PTS/frame mapping did not pass.")
    if not decode_evidence.get("passed"):
        warnings.append("Full output decode did not pass.")
    if probe_error:
        warnings.append(probe_error)
    if concurrent_clear is False:
        warnings.append("A concurrent Gyroflow process was observed or process enumeration failed; profile logs were not restored.")

    output_metadata.update({
        "validation_status": validation_status,
        "source_start_seconds": validated["start"],
        "source_end_seconds": validated["end"],
        "full_source": validated["full_source"],
        "output_preset": validated["output_preset"],
        "gyroflow_version": identity["version"],
        "gyroflow_sha256": executable_hash,
        "gyroflow_build_id": identity["build_id"],
        "gyroflow_commit": identity["commit"],
    })
    media_outputs = _output_descriptor(output_path, output_metadata, warnings, verified) if output_exists else []
    audit = {
        "cli_invocation_verified": cli_invocation_verified,
        "cli_launch_status": cli_launch_status,
        "cli_process_started": launch.get("exit_code") is not None,
        "cli_launch_error_type": type(launch_error).__name__ if launch_error is not None else None,
        "cli_exit_code": launch.get("exit_code"),
        "cli_log": str(log_path),
        "cli_log_tail": launch.get("tail", []),
        "cli_reader_error": launch.get("reader_error"),
        "profile_backup_verified": before.get("backup_verified") is True,
        "profile_post_matches_pre": profile_matches,
        "profile_changes_after_restore": profile_diff,
        "profile_log_restoration": log_restoration,
        "profile_before": before,
        "profile_after_launch": after_launch,
        "profile_final": final_profile,
        "tool_directory_backup_verified": tool_before.get("backup_verified") is True,
        "tool_directory_post_matches_pre": tool_dir_matches,
        "tool_directory_changes": tool_dir_diff,
        "tool_directory_before": tool_before,
        "tool_directory_after": tool_after_launch,
        "concurrent_process_check": "unverifiable" if concurrency_errors else "clear" if concurrent_clear else "conflict_detected",
        "concurrency_audit_scope": "bounded_point_in_time_selected_image_identity_and_Gyroflow_branded_images_not_absolute_exclusion",
        "concurrency_unknown_policy": "fail_closed_no_launch_or_profile_log_restoration",
        "concurrency_audit_errors": concurrency_errors,
        "concurrency_audit_budgets": {"pids": 4096, "files": 512, "bytes": 128 * 1024 ** 2, "seconds": 5.0},
        "crash_dump_cwd_preflight_clear": True,
        "crash_dump_found_after_launch": any(item.suffix.casefold() == ".dmp" for item in cli_cwd.iterdir()),
    }
    record = {
        "schema_version": 1,
        "installation": {
            "build_id": identity["build_id"],
            "path": str(executable.resolve(strict=True)),
            "version": identity["version"],
            "sha256": executable_hash,
            "package_family": identity["package_family"],
            "commit": identity["commit"],
            "actual_file_version": identity.get("actual_file_version"),
            "identity_source": identity.get("identity_source", "development_path_and_hash"),
        },
        "request": {
            "source_path": str(validated["original"]),
            "project_template": str(validated["project_template"]),
            "template_used_sha256": template_identity["sha256"],
            "template_snapshot": str(template_snapshot),
            "template_source_identity_before": template_identity,
            "project_input_sha256_before": project_sha256,
            "template_source_unchanged": template_source_unchanged,
            "template_snapshot_unchanged": template_snapshot_unchanged,
            "project_input_unchanged": project_input_unchanged,
            "start": validated["start"],
            "end": validated["end"],
            "full_source": validated["full_source"],
            "output_preset": validated["output_preset"],
        },
        "audit": audit,
        "export_probe": {
            "output_path": str(output_path) if output_exists else None,
            "media_export_verified": bool(output_exists and launch.get("exit_code") == 0 and decode_evidence.get("passed") is True),
            "trim_mapping_verified": probe_evidence.get("trim_mapping_verified") is True,
            "frame_mapping": probe_evidence,
            "full_decode_verified": decode_evidence.get("passed") is True,
            "decode": decode_evidence,
            "validation_status": validation_status,
            "probe_error": probe_error,
            "expected_frames": probe_evidence.get("expected_frames"),
            "actual_frames": probe_evidence.get("actual_frames"),
        },
        "network_audit": {
            "footage_upload_path_found_in_reviewed_cli": False,
            "lens_profile_usage_checksum_request_possible": True,
            "crash_dump_upload_guard": "Fresh empty process working directory is checked before launch; no pre-existing .dmp is allowed.",
        },
    }
    _write_manifest(manifest_path, record)
    outputs = list(media_outputs)
    if not verified:
        outputs.extend(_review_diagnostic_descriptors(
            [
                (project_path, "Gyroflow project used for diagnostic review", "diagnostic_project", "application/json"),
                (log_path, "Gyroflow CLI diagnostic log", "diagnostic_log", "text/plain"),
                (manifest_path, "Gyroflow export audit manifest", "diagnostic_manifest", "application/json"),
            ],
            run_dir,
            [validated["original"], validated["project_template"]],
            {"build_id": identity["build_id"], "version": identity["version"], "sha256": executable_hash},
            warnings,
        ))

    if launch_error is not None and not isinstance(launch_error, CancelledError):
        probe_error = probe_error or "Gyroflow CLI launch failed: {}".format(type(launch_error).__name__)
    validation = {
        "status": "verified_media" if verified else "needs_review",
        "verified_media": verified,
        "scope": "source_output_pts_sequence_exact_frame_count_and_full_decode_no_content_correspondence" if verified else "gyroflow_export_requires_review",
        "trim_mapping_verified": probe_evidence.get("trim_mapping_verified") is True,
        "profile_post_matches_pre": profile_matches,
        "tool_directory_post_matches_pre": tool_dir_matches,
        "full_decode_verified": decode_evidence.get("passed") is True,
        "template_source_unchanged": template_source_unchanged,
        "template_snapshot_unchanged": template_snapshot_unchanged,
        "project_input_unchanged": project_input_unchanged,
        "template_used_sha256": template_identity["sha256"],
        "project_input_sha256_before": project_sha256,
        "manifest": str(manifest_path),
    }
    if not verified:
        detail = {
            "outputs": outputs,
            "manifest": str(manifest_path),
            "validation": validation,
            "frame_mapping": probe_evidence,
            "profile_post_matches_pre": profile_matches,
            "concurrent_process_check": audit["concurrent_process_check"],
            "warnings": warnings,
            "cli_exit_code": launch.get("exit_code"),
        }
        message = "Gyroflow output was retained for review because exact PTS/frame mapping, profile safety, decode, or CLI checks did not pass."
        raise NeedsReviewError(message, detail)
    _emit(on_event, "gyroflow_export_verified", 1.0, "Gyroflow export passed the PTS sequence/count check and full decode within the reported scope; no image-content correspondence is claimed.")
    return {
        "outputs": outputs,
        "manifest": manifest_path,
        "warnings": warnings,
        "validation": validation,
    }


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
