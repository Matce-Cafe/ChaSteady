"""Local-path validation and private-run ownership helpers."""
import os
import re
import stat
import sys
import uuid
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Optional


_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM{}".format(i) for i in range(1, 10)]
    + ["LPT{}".format(i) for i in range(1, 10)]
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class UnsafePathError(ValueError):
    """A path is not an approved local filesystem path."""


def validate_local_path_syntax(value: str, name: str = "path") -> str:
    """Reject non-local and ambiguous path spellings before touching disk."""
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise UnsafePathError("{} must be a non-empty local absolute path".format(name))
    # Windows network shares, device namespaces and URL-like schemes are never
    # valid media paths. The drive-letter exception allows e.g. N:/media/file.
    win = value.replace("/", "\\")
    if value.startswith(("//", "\\\\")) or win.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
        raise UnsafePathError("{} must not be a UNC or device path".format(name))
    if _URL_SCHEME.match(value) and not _WINDOWS_DRIVE.match(value):
        raise UnsafePathError("{} must not be a URL".format(name))
    if ":" in value[2:] if _WINDOWS_DRIVE.match(value) else ":" in value:
        # Reject NTFS alternate data streams and other colon-based aliases.
        raise UnsafePathError("{} contains an unsupported path component".format(name))
    if sys.platform == "win32":
        path = Path(value)
        if not path.is_absolute() or not _WINDOWS_DRIVE.match(value):
            raise UnsafePathError("{} must be an absolute local-drive path".format(name))
        parts = PureWindowsPath(value).parts[1:]
        for component in parts:
            if component in ("", ".", "..") or component.endswith((".", " ")):
                raise UnsafePathError("{} contains an ambiguous path component".format(name))
            if component.split(".", 1)[0].upper() in _RESERVED_NAMES:
                raise UnsafePathError("{} contains a reserved device name".format(name))
    else:
        # This service is a Windows application, but permit native absolute
        # paths for isolated unit tests and portable local deployments.
        if not Path(value).is_absolute() and not PureWindowsPath(value).is_absolute():
            raise UnsafePathError("{} must be an absolute local path".format(name))
        for component in Path(value).parts:
            if component in (".", ".."):
                raise UnsafePathError("{} contains an ambiguous path component".format(name))
    return value


def _is_reparse(info: os.stat_result) -> bool:
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & _REPARSE_POINT)


def _assert_no_reparse_components(path: Path, *, allow_missing_leaf: bool = False) -> None:
    """Reject symlink/junction traversal in an absolute path."""
    absolute = Path(os.path.abspath(str(path)))
    parts = list(absolute.parents)[::-1] + [absolute]
    for index, component in enumerate(parts):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            raise UnsafePathError("path does not exist")
        except OSError as exc:
            raise UnsafePathError("path could not be inspected") from exc
        if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
            raise UnsafePathError("path must not traverse a symbolic link or junction")


def resolve_local_input(value: str, name: str = "path") -> Path:
    """Resolve an existing regular local file without following aliases."""
    validate_local_path_syntax(value, name)
    path = Path(value)
    if not path.is_absolute():
        raise UnsafePathError("{} must be absolute".format(name))
    _assert_no_reparse_components(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise UnsafePathError("{} does not exist or cannot be read".format(name)) from exc
    if not stat.S_ISREG(info.st_mode):
        raise UnsafePathError("{} must refer to a regular file".format(name))
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnsafePathError("{} could not be resolved safely".format(name)) from exc
    return resolved


def ensure_desktop_data_root(value: Path) -> Path:
    """Create a new desktop data root with a protected Windows DACL."""
    raw = str(value)
    validate_local_path_syntax(raw, "data root")
    path = Path(os.path.abspath(raw))
    parent = path.parent
    try:
        _assert_no_reparse_components(parent)
    except UnsafePathError as exc:
        raise UnsafePathError("data root parent must be an existing ordinary directory") from exc
    if not parent.is_dir():
        raise UnsafePathError("data root parent must be an existing directory")
    try:
        info = path.lstat()
    except FileNotFoundError:
        if os.name == "nt":
            _create_windows_private_directory(path)
        else:
            path.mkdir(mode=0o700, parents=False, exist_ok=False)
        info = path.lstat()
    except OSError as exc:
        raise UnsafePathError("data root could not be inspected") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or _is_reparse(info):
        raise UnsafePathError("data root must be an ordinary directory")
    _assert_no_reparse_components(path)
    if os.name != "nt" and info.st_uid != os.getuid():
        raise UnsafePathError("data root must be owned by the current user")
    return path.resolve(strict=True)


def ensure_private_layout(app_root: Path) -> tuple:
    """Create/check app-owned private and run roots; never follow reparse points."""
    root = Path(app_root).resolve(strict=True)
    private = root / "private"
    runs = private / "runs"
    for directory in (private, runs):
        if directory.exists():
            _assert_no_reparse_components(directory)
            if not directory.is_dir():
                raise UnsafePathError("private storage path is not a directory")
        else:
            directory.mkdir()
            _assert_no_reparse_components(directory)
    return private, runs


class _WindowsPrivateSecurity:
    """Build an owner/SYSTEM/Admin-only protected DACL for a new app object."""

    def __init__(self, *, inheritable: bool, access_mask: int = 0x001F01FF):
        import ctypes
        from ctypes import wintypes

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [
                ("nLength", wintypes.DWORD),
                ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL),
            ]

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32, kernel32 = self.advapi32, self.kernel32
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        advapi32.InitializeAcl.restype = wintypes.BOOL
        advapi32.AddAccessAllowedAceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        advapi32.AddAccessAllowedAceEx.restype = wintypes.BOOL
        advapi32.InitializeSecurityDescriptor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        advapi32.InitializeSecurityDescriptor.restype = wintypes.BOOL
        advapi32.SetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.c_void_p, wintypes.BOOL]
        advapi32.SetSecurityDescriptorDacl.restype = wintypes.BOOL
        advapi32.SetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, wintypes.USHORT, wintypes.USHORT]
        advapi32.SetSecurityDescriptorControl.restype = wintypes.BOOL
        advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
        advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self.security_attributes_type = SecurityAttributes
        self.token = wintypes.HANDLE()
        self.allocated_sids = []
        self.closed = False
        self._check(advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(self.token)), "OpenProcessToken")
        try:
            required = wintypes.DWORD()
            advapi32.GetTokenInformation(self.token, 1, None, 0, ctypes.byref(required))
            self.token_user = ctypes.create_string_buffer(required.value)
            self._check(advapi32.GetTokenInformation(self.token, 1, self.token_user, required.value, ctypes.byref(required)), "GetTokenInformation")
            user_sid = ctypes.cast(self.token_user, ctypes.POINTER(ctypes.c_void_p))[0]
            system_sid = ctypes.c_void_p()
            admins_sid = ctypes.c_void_p()
            self._check(advapi32.ConvertStringSidToSidW("S-1-5-18", ctypes.byref(system_sid)), "Convert SYSTEM SID")
            self.allocated_sids.append(system_sid)
            self._check(advapi32.ConvertStringSidToSidW("S-1-5-32-544", ctypes.byref(admins_sid)), "Convert Administrators SID")
            self.allocated_sids.append(admins_sid)

            self.acl_buffer = ctypes.create_string_buffer(1024)
            self._check(advapi32.InitializeAcl(self.acl_buffer, len(self.acl_buffer), 2), "InitializeAcl")
            ace_flags = (0x01 | 0x02) if inheritable else 0
            for sid in (user_sid, system_sid, admins_sid):
                self._check(advapi32.AddAccessAllowedAceEx(self.acl_buffer, 2, ace_flags, access_mask, sid), "AddAccessAllowedAceEx")

            self.descriptor = ctypes.create_string_buffer(1024)
            self._check(advapi32.InitializeSecurityDescriptor(self.descriptor, 1), "InitializeSecurityDescriptor")
            self._check(advapi32.SetSecurityDescriptorDacl(self.descriptor, True, self.acl_buffer, False), "SetSecurityDescriptorDacl")
            self._check(advapi32.SetSecurityDescriptorControl(self.descriptor, 0x1000, 0x1000), "Protect private DACL")
            self.attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), ctypes.cast(self.descriptor, ctypes.c_void_p), False)
        except Exception:
            self.close()
            raise

    def _check(self, ok: Any, operation: str) -> None:
        if not ok:
            raise self.ctypes.WinError(self.ctypes.get_last_error(), operation)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for sid in self.allocated_sids:
            self.kernel32.LocalFree(sid)
        if self.token:
            self.kernel32.CloseHandle(self.token)


def _create_windows_private_directory(path: Path) -> None:
    """Atomically create a protected run directory before it can inherit access."""
    import ctypes

    security = _WindowsPrivateSecurity(inheritable=True)
    try:
        kernel32 = security.kernel32
        kernel32.CreateDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(security.security_attributes_type)]
        kernel32.CreateDirectoryW.restype = security.wintypes.BOOL
        security._check(kernel32.CreateDirectoryW(str(path), ctypes.byref(security.attributes)), "CreateDirectoryW private workspace")
    finally:
        security.close()


def _create_windows_private_file(path: Path) -> int:
    """Atomically create a protected private file and return a writable fd."""
    import ctypes
    import msvcrt

    security = _WindowsPrivateSecurity(inheritable=False)
    handle = None
    try:
        kernel32 = security.kernel32
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, security.wintypes.DWORD, security.wintypes.DWORD,
            ctypes.POINTER(security.security_attributes_type), security.wintypes.DWORD,
            security.wintypes.DWORD, security.wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = security.wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [security.wintypes.HANDLE]
        kernel32.CloseHandle.restype = security.wintypes.BOOL
        handle = kernel32.CreateFileW(
            str(path), 0x40000000, 0, ctypes.byref(security.attributes), 1, 0x80, None
        )
        invalid = ctypes.c_void_p(-1).value
        if not handle or (handle.value if hasattr(handle, "value") else int(handle)) == invalid:
            raise ctypes.WinError(ctypes.get_last_error(), "CreateFileW private preferences")
        raw_handle = handle.value if hasattr(handle, "value") else int(handle)
        fd = msvcrt.open_osfhandle(raw_handle, os.O_WRONLY | getattr(os, "O_BINARY", 0))
        handle = None  # ownership transferred to the CRT file descriptor
        return fd
    finally:
        if handle:
            security.kernel32.CloseHandle(handle)
        security.close()


def _copy_windows_dacl(source: Path, target: Path) -> None:
    """Copy the existing target DACL to a new atomic-replacement file."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    _assert_no_reparse_components(source)
    _assert_no_reparse_components(target)
    source_info, target_info = source.lstat(), target.lstat()
    if (
        not stat.S_ISREG(source_info.st_mode)
        or not stat.S_ISREG(target_info.st_mode)
        or getattr(source_info, "st_nlink", 1) != 1
        or getattr(target_info, "st_nlink", 1) != 1
    ):
        raise UnsafePathError("preference ACL source and replacement must be single-link regular files")

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(source), 1, 0x00000001 | 0x00000002 | 0x00000004,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), None, ctypes.byref(descriptor)
    )
    if status != 0:
        raise ctypes.WinError(status, "GetNamedSecurityInfoW preferences")
    try:
        control = wintypes.USHORT()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error(), "GetSecurityDescriptorControl preferences")
        dacl_flag = 0x80000000 if control.value & 0x1000 else 0x20000000
        set_status = advapi32.SetNamedSecurityInfoW(
            str(target), 1, 0x00000001 | 0x00000002 | 0x00000004 | dacl_flag,
            owner, group, dacl, None,
        )
        if set_status != 0:
            raise ctypes.WinError(set_status, "SetNamedSecurityInfoW replacement preferences")
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)


def create_run_directory(runs_root: Path, job_id: Optional[str] = None) -> Path:
    """Create an exclusive UUID workspace below private/runs."""
    root = Path(runs_root)
    _assert_no_reparse_components(root)
    candidate_id = job_id or str(uuid.uuid4())
    try:
        parsed = uuid.UUID(candidate_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise UnsafePathError("job workspace id must be a UUID") from exc
    if str(parsed) != candidate_id:
        raise UnsafePathError("job workspace id must be canonical")
    run_dir = root / str(parsed)
    try:
        if os.name == "nt":
            _create_windows_private_directory(run_dir)
        else:
            run_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise UnsafePathError("job workspace already exists") from exc
    _assert_no_reparse_components(run_dir)
    return run_dir


def validate_run_directory(run_dir: Path, runs_root: Path, job_id: str) -> Path:
    """Require a job workspace to be the canonical UUID child under private/runs."""
    try:
        parsed = uuid.UUID(job_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise UnsafePathError("job workspace id must be a UUID") from exc
    if str(parsed) != job_id:
        raise UnsafePathError("job workspace id must be canonical")
    root = Path(os.path.abspath(str(runs_root)))
    candidate = Path(os.path.abspath(str(run_dir)))
    expected = root / str(parsed)
    if os.path.normcase(str(candidate)).casefold() != os.path.normcase(str(expected)).casefold():
        raise UnsafePathError("job workspace is not its private UUID directory")
    _assert_no_reparse_components(root)
    _assert_no_reparse_components(candidate)
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise UnsafePathError("job workspace is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafePathError("job workspace must be a directory")
    try:
        resolved_root = root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnsafePathError("job workspace could not be resolved safely") from exc
    if not path_is_within(resolved_candidate, resolved_root):
        raise UnsafePathError("job workspace escaped private/runs")
    return resolved_candidate


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).casefold()


def path_is_within(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve(strict=True).relative_to(Path(root).resolve(strict=True))
        return True
    except (ValueError, OSError, RuntimeError):
        # On Windows, relative_to should be case-insensitive, but compare folded
        # normalized spellings as a defense for unusual Python/filesystem mixes.
        candidate = _normalized(path)
        parent = _normalized(root).rstrip(os.sep)
        return candidate == parent or candidate.startswith(parent + os.sep)


def require_disjoint_roots(resource_root: Path, data_root: Path) -> None:
    """Prevent private data writes from landing inside the resource bundle."""
    resource = Path(resource_root).resolve(strict=True)
    data = Path(data_root).resolve(strict=False)
    if path_is_within(resource, data) or path_is_within(data, resource):
        raise UnsafePathError("resource root and data root must be separate, non-overlapping directories")


def same_file_or_alias(first: Path, second: Path) -> bool:
    """Detect textual, resolved, and hard-link aliases without opening files."""
    if _normalized(first) == _normalized(second):
        return True
    try:
        return os.path.samefile(str(first), str(second))
    except (OSError, ValueError):
        return False


def ensure_not_alias(path: Path, inputs: Iterable[Path]) -> None:
    for source in inputs:
        if same_file_or_alias(path, source):
            raise UnsafePathError("output aliases a read-only input")


def validate_owned_file(value: Path, run_dir: Path, inputs: Iterable[Path] = ()) -> Path:
    """Validate that a newly produced artifact is a single-link file in its run."""
    path = Path(value)
    if not path.is_absolute():
        raise UnsafePathError("worker output path must be absolute")
    validate_local_path_syntax(str(path), "worker output")
    _assert_no_reparse_components(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise UnsafePathError("worker output does not exist") from exc
    if not stat.S_ISREG(info.st_mode):
        raise UnsafePathError("worker output must be a regular file")
    if getattr(info, "st_nlink", 1) != 1:
        raise UnsafePathError("worker output must not have hard-link aliases")
    resolved = path.resolve(strict=True)
    if not path_is_within(resolved, run_dir):
        raise UnsafePathError("worker output escaped its private run directory")
    ensure_not_alias(resolved, inputs)
    return resolved


def open_validated_owned_file(value: Path, run_dir: Path, inputs: Iterable[Path] = ()):
    """Open an owned artifact and re-check the opened inode against path races."""
    path = validate_owned_file(Path(value), run_dir, inputs)
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags)
    try:
        # Re-check the full parent chain and run-root containment after open to
        # catch directory junction swaps between validation and the OS open.
        revalidated = validate_owned_file(path, run_dir, inputs)
        if _normalized(revalidated) != _normalized(path):
            raise UnsafePathError("artifact path changed while being opened")
        info = os.fstat(fd)
        current = path.lstat()
        if not stat.S_ISREG(info.st_mode) or _is_reparse(current):
            raise UnsafePathError("artifact changed while being opened")
        if getattr(info, "st_nlink", 1) != 1:
            raise UnsafePathError("artifact has an unapproved hard-link alias")
        if (getattr(info, "st_dev", None), getattr(info, "st_ino", None)) != (
            getattr(current, "st_dev", None), getattr(current, "st_ino", None)
        ):
            raise UnsafePathError("artifact changed while being opened")
        return os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise
