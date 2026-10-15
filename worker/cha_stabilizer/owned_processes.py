"""Subprocess ownership helpers for worker adapters.

Every launched child is placed in a fresh process group/session and registered
with the active job. Cancellation only signals those recorded children; it
never searches for or kills a process by executable name.
"""
import contextvars
import os
import signal
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional


_ACTIVE_REGISTRY = contextvars.ContextVar("chasteady_owned_process_registry", default=None)


def _create_windows_job(process: subprocess.Popen) -> Optional[int]:
    """Assign a tracked Windows child to a kill-on-close Job Object when possible."""
    if os.name != "nt":
        return None
    handle = None
    try:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel32.CloseHandle(handle)
            return None
        process_handle = getattr(process, "_handle", None)
        if hasattr(process_handle, "value"):
            process_handle = process_handle.value
        if not process_handle or not kernel32.AssignProcessToJobObject(handle, process_handle):
            kernel32.CloseHandle(handle)
            return None
        return handle.value if hasattr(handle, "value") else int(handle)
    except Exception:
        if handle:
            try:
                import ctypes
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
            except Exception:
                pass
        return None


def _close_windows_job(handle: int, terminate: bool = False) -> None:
    if os.name != "nt" or not handle:
        return
    import ctypes
    from ctypes import wintypes

    class BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    win_handle = wintypes.HANDLE(handle)
    if terminate:
        kernel32.TerminateJobObject(win_handle, 1)
        # Process termination is asynchronous. Wait for this exact Job Object to
        # drain before returning, rather than treating leader exit as group exit.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            info = BasicAccountingInformation()
            returned = wintypes.DWORD()
            if not kernel32.QueryInformationJobObject(
                win_handle, 1, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned)
            ):
                break
            if info.ActiveProcesses == 0:
                break
            time.sleep(0.025)
    kernel32.CloseHandle(win_handle)


class OwnedProcessRegistry:
    def __init__(self, cancel_event: Optional[threading.Event] = None):
        self.cancel_event = cancel_event or threading.Event()
        self._lock = threading.RLock()
        self._children: Dict[int, subprocess.Popen] = {}
        self._windows_jobs: Dict[int, int] = {}
        self._cancelled = False

    def add(self, process: subprocess.Popen) -> None:
        windows_job = _create_windows_job(process)
        with self._lock:
            if self._cancelled or self.cancel_event.is_set():
                should_cancel = True
            else:
                self._children[process.pid] = process
                if windows_job:
                    self._windows_jobs[process.pid] = windows_job
                should_cancel = False
        if should_cancel:
            if windows_job:
                _close_windows_job(windows_job, terminate=True)
            else:
                self._signal_one(process)

    def discard(self, process: subprocess.Popen) -> None:
        windows_job = None
        with self._lock:
            self._children.pop(process.pid, None)
            windows_job = self._windows_jobs.pop(process.pid, None)
        if windows_job:
            # Closing a kill-on-close Job Object also reaps any descendant that
            # outlived the registered direct child. No process-name search occurs.
            try:
                _close_windows_job(windows_job, terminate=True)
            except OSError:
                pass
        elif os.name != "nt" and process.pid > 0:
            # Each POSIX Popen was launched as a new session/process-group
            # leader. Reap surviving descendants before forgetting ownership.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                return
            time.sleep(0.05)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    def snapshot(self) -> List[subprocess.Popen]:
        with self._lock:
            return list(self._children.values())

    @staticmethod
    def _signal_one(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                # CTRL_BREAK targets only the process group created by this
                # helper. A child-only terminate is the fallback when there is
                # no console to receive the control event.
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                except (OSError, ValueError, AttributeError):
                    process.terminate()
            else:
                if process.pid > 0:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except (OSError, ProcessLookupError):
                        if process.poll() is None:
                            process.terminate()
        except (OSError, ProcessLookupError):
            pass

    def terminate_all(self, grace_seconds: float = 1.5) -> None:
        with self._lock:
            self._cancelled = True
            children = list(self._children.values())
        if os.name == "nt":
            # Terminate registered Job Objects before signaling leaders. If a
            # leader exits first, Windows can otherwise leave its descendants
            # running outside the state we can observe via Popen.wait().
            fallback = []
            with self._lock:
                for process in children:
                    job_handle = self._windows_jobs.pop(process.pid, None)
                    if job_handle:
                        try:
                            _close_windows_job(job_handle, terminate=True)
                        except OSError:
                            pass
                    elif process.poll() is None:
                        fallback.append(process)
            for process in fallback:
                self._signal_one(process)
            deadline = time.monotonic() + max(0.0, grace_seconds)
            for process in fallback:
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    pass
                if process.poll() is None:
                    try:
                        # Exact recorded Popen handle only; no name-based lookup.
                        process.kill()
                    except OSError:
                        pass
            for process in children:
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
        else:
            for process in children:
                self._signal_one(process)
            deadline = time.monotonic() + max(0.0, grace_seconds)
            for process in children:
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    pass
            # A process-group leader may exit on SIGTERM while its own child is
            # still alive. Kill only each freshly-created owned session/group,
            # even if the recorded leader already exited.
            for process in children:
                if process.pid <= 0:
                    continue
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
        with self._lock:
            for process in children:
                if process.poll() is not None:
                    self._children.pop(process.pid, None)

    def cancel_requested(self) -> bool:
        return self.cancel_event.is_set() or self._cancelled


def get_active_registry() -> Optional[OwnedProcessRegistry]:
    """Return the current job process registry, if a job owns this context."""
    return _ACTIVE_REGISTRY.get()


class registry_scope:
    """Context manager making a job registry available to worker adapters."""

    def __init__(self, registry: OwnedProcessRegistry):
        self.registry = registry
        self._token = None

    def __enter__(self):
        self._token = _ACTIVE_REGISTRY.set(self.registry)
        return self.registry

    def __exit__(self, exc_type, exc_value, traceback):
        if self._token is not None:
            _ACTIVE_REGISTRY.reset(self._token)
        return False


def spawn_owned_process(args: Any, **kwargs: Any) -> subprocess.Popen:
    """Launch a shell-free child in a new process group and register ownership."""
    registry = _ACTIVE_REGISTRY.get()
    if registry is None:
        raise RuntimeError("worker child process launched outside a job ownership scope")
    if registry.cancel_requested():
        raise RuntimeError("job cancellation was requested before child launch")
    if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)) or not args:
        raise TypeError("owned process args must be a non-empty argument sequence")
    if kwargs.pop("shell", False):
        raise ValueError("owned worker processes must not use a shell")
    # Adapters cannot detach children from the recorded process group.
    kwargs.pop("start_new_session", None)
    kwargs.pop("creationflags", None)
    kwargs.setdefault("close_fds", True)
    # Never inherit the worker's stdout/stderr. Desktop stdout is a framed JSON
    # protocol pipe; adapters that need process output must opt into PIPE/file.
    if kwargs.get("stdout") is None:
        kwargs["stdout"] = subprocess.DEVNULL
    if kwargs.get("stderr") is None:
        kwargs["stderr"] = subprocess.DEVNULL
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(args, shell=False, **kwargs)
    registry.add(process)
    return process


def run_owned_process(args: Any, *, timeout: Optional[float] = None, **kwargs: Any) -> subprocess.CompletedProcess:
    """Run a recorded child and release it from the active registry."""
    registry = _ACTIVE_REGISTRY.get()
    process = spawn_owned_process(args, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        if registry is not None:
            registry.terminate_all()
        else:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        raise
    finally:
        if registry is not None:
            registry.discard(process)
