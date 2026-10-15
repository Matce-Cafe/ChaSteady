"""Command-line entry point for the loopback ChaSteady application."""
import argparse
import hashlib
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional, Sequence

from .local_server import create_server
from .desktop_protocol import new_native_capability, run_desktop_protocol
from .paths import (
    _WindowsPrivateSecurity,
    _assert_no_reparse_components,
    ensure_desktop_data_root,
    require_disjoint_roots,
    validate_local_path_syntax,
)


_INSTANCE_GUARD = threading.RLock()
_INSTANCE_KEYS = set()


def _windows_current_sid_bytes() -> bytes:
    import ctypes
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error(), "OpenProcessToken for ChaSteady instance lock")
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, required.value, ctypes.byref(required)):
            raise ctypes.WinError(ctypes.get_last_error(), "GetTokenInformation for ChaSteady instance lock")
        user = ctypes.cast(buffer, ctypes.POINTER(SidAndAttributes)).contents
        length = advapi32.GetLengthSid(user.Sid)
        if not length:
            raise ctypes.WinError(ctypes.get_last_error(), "GetLengthSid for ChaSteady instance lock")
        return ctypes.string_at(user.Sid, length)
    finally:
        kernel32.CloseHandle(token)


def _instance_identity(app_root: Path) -> tuple:
    canonical = str(Path(app_root).resolve(strict=True))
    if os.name == "nt":
        root_key = os.path.normcase(canonical).casefold().encode("utf-8")
        sid = _windows_current_sid_bytes()
    else:
        root_key = os.path.normcase(canonical).encode("utf-8")
        sid = str(os.getuid()).encode("ascii")
    digest = hashlib.sha256(root_key + b"\0" + sid).hexdigest()
    return canonical, digest


class LocalInstanceLock:
    """OS-released, app-root/user-scoped lock held for the server lifetime."""

    def __init__(self, app_root: Path):
        self.app_root, self.name_hash = _instance_identity(Path(app_root))
        self._in_process_key = (self.app_root.casefold(), self.name_hash)
        self._registered = False
        self._acquired = False
        self._handle = None
        self._fd = None

    def acquire(self) -> bool:
        with _INSTANCE_GUARD:
            if self._in_process_key in _INSTANCE_KEYS:
                return False
            _INSTANCE_KEYS.add(self._in_process_key)
            self._registered = True
        try:
            acquired = self._acquire_windows() if os.name == "nt" else self._acquire_posix()
        except Exception:
            self._unregister()
            raise
        if not acquired:
            self._unregister()
            return False
        self._acquired = True
        return True

    def _acquire_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        # Global namespace prevents two logon sessions for the same SID/root
        # from independently initializing the shared persistent JobStore.
        mutex_name = "Global\\ChaSteady-{}".format(self.name_hash)
        security = _WindowsPrivateSecurity(inheritable=False, access_mask=0x001F0001)  # MUTEX_ALL_ACCESS
        handle = None
        try:
            kernel32 = security.kernel32
            kernel32.CreateMutexW.argtypes = [
                ctypes.POINTER(security.security_attributes_type), wintypes.BOOL, wintypes.LPCWSTR,
            ]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            handle = kernel32.CreateMutexW(ctypes.byref(security.attributes), False, mutex_name)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error(), "Create ChaSteady single-instance mutex")
            wait = kernel32.WaitForSingleObject(handle, 0)
            if wait == 0x00000102:  # WAIT_TIMEOUT: another process owns this root/user mutex.
                kernel32.CloseHandle(handle)
                return False
            if wait not in (0x00000000, 0x00000080):  # WAIT_OBJECT_0 / WAIT_ABANDONED
                raise ctypes.WinError(ctypes.get_last_error(), "WaitForSingleObject ChaSteady mutex")
            self._handle = handle
            return True
        except Exception:
            if handle:
                kernel32.CloseHandle(handle)
            raise
        finally:
            security.close()

    def _acquire_posix(self) -> bool:
        import fcntl
        import stat

        lock_dir = Path(self.app_root) / "private"
        if not lock_dir.exists():
            lock_dir.mkdir(mode=0o700)
        _assert_no_reparse_components(lock_dir)
        lock_path = lock_dir / ".chasteady-instance-{}.lock".format(self.name_hash)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(lock_path), flags, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(fd)
            raise PermissionError("ChaSteady instance lock is not a private user-owned file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            os.close(fd)
            return False
        self._fd = fd
        return True

    def _unregister(self) -> None:
        if self._registered:
            with _INSTANCE_GUARD:
                _INSTANCE_KEYS.discard(self._in_process_key)
            self._registered = False

    def release(self) -> None:
        if not self._acquired:
            self._unregister()
            return
        try:
            if os.name == "nt" and self._handle:
                import ctypes
                from ctypes import wintypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
                kernel32.ReleaseMutex.restype = wintypes.BOOL
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                kernel32.ReleaseMutex(self._handle)
                kernel32.CloseHandle(self._handle)
                self._handle = None
            elif self._fd is not None:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
                self._fd = None
        finally:
            self._acquired = False
            self._unregister()

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("ChaSteady is already running for this application root and user")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local ChaSteady media workbench.")
    parser.add_argument("--port", type=int, default=0, help="loopback TCP port (0 chooses an ephemeral port)")
    parser.add_argument("--no-browser", action="store_true", help="print the session URL without opening a browser")
    parser.add_argument("--desktop", action="store_true", help="run the private native-supervisor stdio protocol")
    parser.add_argument("--resource-root", help="read-only bundle root used by desktop mode")
    parser.add_argument("--data-root", help="private per-user data root used by desktop mode")
    return parser


def _validate_resource_root(value: str) -> Path:
    validate_local_path_syntax(value, "resource root")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("resource root must be absolute")
    _assert_no_reparse_components(path)
    if not path.is_dir():
        raise ValueError("resource root must be a directory")
    return path.resolve(strict=True)


def _stop_desktop_server(server) -> None:
    # Disable new job submissions, stop/wait owned work and inspections, then
    # wake serve_forever from this stdin thread (never from its own loop).
    server.app.close()
    server.shutdown()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")
    if getattr(sys, "frozen", False) and not args.desktop:
        parser.error("frozen Worker.exe must be started with --desktop and explicit roots")
    if args.desktop:
        if not args.resource_root or not args.data_root:
            parser.error("--desktop requires --resource-root and --data-root")
        try:
            resource_root = _validate_resource_root(args.resource_root)
            require_disjoint_roots(resource_root, Path(args.data_root))
            data_root = ensure_desktop_data_root(Path(args.data_root))
            require_disjoint_roots(resource_root, data_root)
        except (OSError, ValueError) as exc:
            print("Desktop worker roots could not be validated safely: {}".format(exc), file=sys.stderr, flush=True)
            return 2
        app_root = data_root
    else:
        if args.resource_root is not None or args.data_root is not None:
            parser.error("--resource-root and --data-root are available only with --desktop")
        app_root = Path(__file__).resolve().parents[2]
        resource_root = data_root = app_root

    instance_lock = LocalInstanceLock(data_root if args.desktop else app_root)
    try:
        if not instance_lock.acquire():
            print("ChaSteady is already running for this application root and user.", file=sys.stderr, flush=True)
            return 2
    except OSError as exc:
        if args.desktop:
            print("Desktop worker could not safely acquire its data-root lock.", file=sys.stderr, flush=True)
        else:
            print("ChaSteady could not safely acquire its single-instance lock: {}".format(exc), file=sys.stderr, flush=True)
        return 2

    server = None
    serve_thread = None
    try:
        # The JobStore must not be created/restored until the data-root lock is held.
        if args.desktop:
            server = create_server(
                port=args.port, resource_root=resource_root, data_root=data_root, desktop=True,
            )
            serve_thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.25},
                name="cha-stabilizer-http",
                daemon=True,
            )
            serve_thread.start()
            shutdown_event = getattr(server, "_BaseServer__is_shut_down", None)
            deadline = time.monotonic() + 5.0
            while (
                serve_thread.is_alive()
                and shutdown_event is not None
                and shutdown_event.is_set()
                and time.monotonic() < deadline
            ):
                time.sleep(0.001)
            if not serve_thread.is_alive() or (shutdown_event is not None and shutdown_event.is_set()):
                raise RuntimeError("local HTTP server did not start")
            capability = new_native_capability()
            run_desktop_protocol(
                server,
                capability,
                on_end=lambda: _stop_desktop_server(server),
            )
            serve_thread.join()
        else:
            server = create_server(app_root=app_root, port=args.port)
            print("ChaSteady local UI: {}".format(server.session_url), flush=True)
            if not args.no_browser:
                webbrowser.open(server.session_url, new=1, autoraise=True)
            server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        return 0
    except (BrokenPipeError, OSError, RuntimeError, ValueError):
        if args.desktop:
            print("Desktop worker stopped after a startup or private-pipe failure.", file=sys.stderr, flush=True)
            return 2
        raise
    finally:
        try:
            if server is not None:
                if args.desktop and server.app is not None:
                    try:
                        server.app.close()
                    finally:
                        if serve_thread is not None and serve_thread.is_alive():
                            server.shutdown()
                            serve_thread.join()
                server.server_close()
        finally:
            instance_lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
