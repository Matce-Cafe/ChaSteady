"""Subprocess ownership helpers for worker adapters.

Every launched child is placed in a fresh process group/session and registered
with the active job. Cancellation only signals those recorded children; it
never searches for or kills a process by executable name.
"""
import contextvars
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from .errors import AppError, CancelledError


_ACTIVE_REGISTRY = contextvars.ContextVar("chasteady_owned_process_registry", default=None)


class OwnedProcessError(AppError):
    """只公开固定原因；不能把未确认的 own tree 当作已退出。"""
    def __init__(self, reason: str):
        super().__init__("Owned process startup or cleanup could not be confirmed; no completion is claimed.",
                         {"ownership_unconfirmed": True, "reason": reason})


def _windows_structures():
    import ctypes
    from ctypes import wintypes
    class Startup(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR), ("desktop", wintypes.LPWSTR),
                    ("title", wintypes.LPWSTR), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                    ("width", wintypes.DWORD), ("height", wintypes.DWORD), ("xchars", wintypes.DWORD),
                    ("ychars", wintypes.DWORD), ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("show", wintypes.WORD), ("reserved_size", wintypes.WORD), ("reserved_bytes", ctypes.c_void_p),
                    ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]
    class StartupEx(ctypes.Structure):
        _fields_ = [("startup", Startup), ("attributes", ctypes.c_void_p)]
    class Information(ctypes.Structure):
        _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                    ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]
    return StartupEx, Information


def _windows_api():
    import ctypes
    from ctypes import wintypes
    StartupEx, Information = _windows_structures()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    definitions = {
        "InitializeProcThreadAttributeList": ([ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "UpdateProcThreadAttribute": ([ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
        "CreateProcessW": ([wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                            wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(StartupEx), ctypes.POINTER(Information)], wintypes.BOOL),
        "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in definitions.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel, StartupEx, Information


def _finish_windows_start(process, registry, job_handle, thread_handle, kernel) -> None:
    import ctypes
    from ctypes import wintypes
    with registry._lock:
        member = wintypes.BOOL()
        if not kernel.IsProcessInJob(process._handle, job_handle, ctypes.byref(member)) or not member.value:
            raise OwnedProcessError("job_membership_unconfirmed")
        registry._register_windows_process(process, job_handle)
        if registry.cancel_requested():
            raise CancelledError("Owned process creation was cancelled before its original thread resumed.")
        if kernel.ResumeThread(thread_handle) != 1:
            raise OwnedProcessError("original_thread_resume_unconfirmed")


def _windows_popen_signature_supported() -> bool:
    expected = ("self", "args", "executable", "preexec_fn", "close_fds", "pass_fds", "cwd", "env", "startupinfo",
                "creationflags", "shell", "p2cread", "p2cwrite", "c2pread", "c2pwrite", "errread", "errwrite",
                "unused_restore_signals", "unused_gid", "unused_gids", "unused_uid", "unused_umask",
                "unused_start_new_session", "unused_process_group")
    code = getattr(subprocess.Popen._execute_child, "__code__", None)
    return bool(sys.version_info[:2] == (3, 15) and code is not None
                and code.co_varnames[:code.co_argcount] == expected)


class _WindowsNativeResources:
    """CreateProcess 前登记原生资源；包装失败也不依赖半构造 Popen。"""
    __slots__ = ("information", "job", "kernel", "process", "registry", "created", "wrapped")

    def __init__(self, information, job, kernel, process, registry):
        self.information = information
        self.job = job
        self.kernel = kernel
        self.process = process
        self.registry = registry
        self.created = False
        self.wrapped = None

    @property
    def _handle(self):
        return self.information.process

    def close_thread(self) -> None:
        handle = self.information.thread
        if handle:
            if not self.kernel.CloseHandle(handle):
                raise OwnedProcessError("original_thread_handle_close_failed")
            self.information.thread = None

    def cleanup(self, *, deadline: Optional[float] = None) -> None:
        self.process._child_created = False
        deadline = deadline if deadline is not None else time.monotonic() + 5.0
        if self.created is None:
            raise OwnedProcessError("native_creation_outcome_unconfirmed")
        handle = self.information.process if self.created else None
        if handle:
            state = self.kernel.WaitForSingleObject(handle, 0)
            if state == 258:
                if not self.kernel.TerminateProcess(handle, 1):
                    raise OwnedProcessError("raw_process_termination_unconfirmed")
                state = self.kernel.WaitForSingleObject(handle, max(0, int((deadline - time.monotonic()) * 1000)))
            if state != 0:
                raise OwnedProcessError("raw_process_signal_unconfirmed")
        if self.job is not None:
            if self.created:
                _close_windows_job(self.job, terminate=True, process=self, deadline=deadline)
            elif not self.kernel.CloseHandle(self.job):
                raise OwnedProcessError("unstarted_job_handle_close_failed")
            self.job = None
        if self.created:
            self.close_thread()
        if handle:
            # 先解除 Python wrapper 的析构所有权；原值仍由已登记 holder 持有。
            if self.wrapped is not None:
                self.wrapped.closed = True
            if not self.kernel.CloseHandle(handle):
                raise OwnedProcessError("raw_process_handle_close_failed")
            self.information.process = None
            self.wrapped = None
        pid = self.information.pid
        if self.registry._children.get(pid) is self.process:
            self.registry._children.pop(pid, None)
            self.registry._windows_jobs.pop(pid, None)


def _wrap_windows_process_handle(handle):
    return subprocess.Handle(handle)


def _handles_inheritable(handles) -> bool:
    return all(os.get_handle_inheritable(handle) for handle in handles)


class _WindowsJobPopen(subprocess.Popen):
    """保留标准 Popen I/O，只替换固定运行时的原生创建步骤。"""
    def __init__(self, args, *, registry, **kwargs):
        self._owner_registry = registry
        self._handle = None
        self._child_created = False
        super().__init__(args, **kwargs)

    def _execute_child(self, args, executable, preexec_fn, close_fds, pass_fds, cwd, env,
                       startupinfo, creationflags, shell, p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite,
                       unused_restore_signals, unused_gid, unused_gids, unused_uid, unused_umask,
                       unused_start_new_session, unused_process_group):
        import ctypes
        from ctypes import wintypes
        registry = self._owner_registry
        kernel = None
        job = None
        native_owner = None
        attributes = None
        attributes_ready = False
        try:
            kernel, StartupEx, Information = _windows_api()
            if shell or preexec_fn is not None or pass_fds or not close_fds:
                raise OwnedProcessError("unsupported_windows_creation_options")
            startupinfo = startupinfo.copy() if startupinfo is not None else subprocess.STARTUPINFO()
            extra = startupinfo.lpAttributeList or {}
            if not isinstance(extra, dict) or set(extra) - {"handle_list"}:
                raise OwnedProcessError("unsupported_windows_attributes")
            handles = list(extra.get("handle_list", []))
            standard = (p2cread, c2pwrite, errwrite)
            if all(handle != -1 for handle in standard):
                startupinfo.dwFlags |= subprocess.STARTF_USESTDHANDLES
                startupinfo.hStdInput, startupinfo.hStdOutput, startupinfo.hStdError = standard
            if startupinfo.dwFlags & subprocess.STARTF_USESTDHANDLES:
                handles += [startupinfo.hStdInput, startupinfo.hStdOutput, startupinfo.hStdError]
            handles = self._filter_handle_list(list(dict.fromkeys(int(handle) for handle in handles if handle not in (None, -1, 0))))
            if not handles or not _handles_inheritable(handles):
                raise OwnedProcessError("explicit_handle_list_unverified")
            command_args = [os.fsdecode(argument) for argument in args]
            executable = os.fsdecode(executable or command_args[0])
            if not os.path.isabs(executable) or any("\0" in value for value in command_args):
                raise OwnedProcessError("absolute_windows_executable_required")
            command_text = subprocess.list2cmdline(command_args)
            command_units = len(command_text.encode("utf-16-le")) // 2 + 1
            if command_units > 32767:
                raise OwnedProcessError("windows_command_budget_exceeded")
            command = ctypes.create_unicode_buffer(command_text, command_units)
            environment = None
            if env is not None:
                entries = []
                for key, value in env.items():
                    key, value = os.fsdecode(key), os.fsdecode(value)
                    if not key or "\0" in key or "=" in key or "\0" in value:
                        raise OwnedProcessError("windows_environment_unverified")
                    entries.append((key, value))
                environment_text = "\0".join(key + "=" + value for key, value in sorted(entries, key=lambda item: item[0].casefold())) + "\0\0"
                environment = ctypes.create_unicode_buffer(environment_text, len(environment_text.encode("utf-16-le")) // 2 + 1)
            registry.check_cleanup()
            if registry.cancel_requested():
                raise CancelledError("Owned process creation was cancelled before native creation.")
            job = _create_windows_job()
            size = ctypes.c_size_t()
            ctypes.set_last_error(0)
            kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            if ctypes.get_last_error() != 122 or not 0 < size.value <= 65536:
                raise OwnedProcessError("attribute_list_size_unverified")
            attributes = ctypes.create_string_buffer(size.value)
            if not kernel.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
                raise OwnedProcessError("attribute_list_initialization_failed")
            attributes_ready = True
            inherited = (wintypes.HANDLE * len(handles))(*handles)
            jobs = (wintypes.HANDLE * 1)(job)
            # 两个真实 native attributes；不向 stdlib 传未知 job_list 字典键。
            for attribute, value in ((0x00020002, inherited), (0x0002000D, jobs)):
                if not kernel.UpdateProcThreadAttribute(attributes, 0, attribute, ctypes.cast(value, ctypes.c_void_p), ctypes.sizeof(value), None, None):
                    raise OwnedProcessError("required_native_attribute_unavailable")
            startup, information = StartupEx(), Information()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.flags = startupinfo.dwFlags
            startup.startup.show = startupinfo.wShowWindow
            startup.startup.stdin = startupinfo.hStdInput
            startup.startup.stdout = startupinfo.hStdOutput
            startup.startup.stderr = startupinfo.hStdError
            startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            flags = creationflags | 0x00000004 | 0x00080000 | 0x00000400 | 0x08000000
            directory = os.fsdecode(cwd) if cwd is not None else None
            startup_pointer, information_pointer = ctypes.byref(startup), ctypes.byref(information)
            native_owner = _WindowsNativeResources(information, job, kernel, self, registry)
            job = None  # holder 先接收唯一原生 Job 所有权；尚未创建进程。
            # holder 与登记均在原生创建前分配；内存不足时不能丢失原 PI 缓冲区。
            with registry._lock:
                registry.check_cleanup()
                if registry.cancel_requested():
                    native_owner.created = False
                    raise CancelledError("Owned native creation was cancelled before creation.")
                registry._native_starts.add(native_owner)
            native_owner.created = None
            result = kernel.CreateProcessW(executable, command, None, None, True, flags, environment,
                                           directory, startup_pointer, information_pointer)
            native_owner.created = bool(result)
            if not result:
                raise OwnedProcessError("suspended_native_creation_failed")
            native_owner.wrapped = _wrap_windows_process_handle(information.process)
            self._handle = native_owner.wrapped
            self.pid = int(information.pid)
            self._child_created = True
            with registry._lock:
                _finish_windows_start(self, registry, native_owner.job, information.thread, kernel)
                native_owner.close_thread()
                registry._native_starts.remove(native_owner)
                native_owner = None  # 完整 Popen/Job 登记成为唯一 owner；holder 无析构副作用。
        except BaseException:
            if native_owner is not None:
                with registry._lock:
                    try:
                        native_owner.cleanup()
                    except BaseException:
                        registry._cleanup_error = "native_start_cleanup_unconfirmed"
                        raise
                    registry._native_starts.discard(native_owner)
                    if not registry._children and not registry._windows_jobs and not registry._pending_handles and not registry._native_starts:
                        registry._cleanup_error = None
            raise
        finally:
            if attributes_ready:
                kernel.DeleteProcThreadAttributeList(attributes)
            resource_error = None
            if job and not kernel.CloseHandle(job):
                registry._pending_handles.add(int(job))
                resource_error = "unstarted_job_handle_close_failed"
            if resource_error:
                registry._cleanup_error = resource_error
            self._close_pipe_fds(p2cread, p2cwrite, c2pread, c2pwrite, errread, errwrite)
            if resource_error:
                try:
                    registry.terminate_all()
                except AppError as error:
                    raise OwnedProcessError(resource_error) from error
                raise OwnedProcessError(resource_error)
            registry.check_cleanup()


def _create_windows_job(process: Optional[subprocess.Popen] = None) -> Optional[int]:
    """先建立实际 own Job；不再把已运行的 Popen 事后收编成安全准入。"""
    if os.name != "nt":
        return None
    if process is not None:
        raise OwnedProcessError("running_process_admission_forbidden")
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
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise OwnedProcessError("job_creation_failed")
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # 关闭最后一个 own Job handle 时终止成员。
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OwnedProcessError("job_configuration_failed")
        return handle.value if hasattr(handle, "value") else int(handle)
    except Exception as error:
        if handle and not kernel32.CloseHandle(handle):
            raise OwnedProcessError("unstarted_job_handle_close_failed") from error
        if isinstance(error, AppError):
            raise
        raise OwnedProcessError("job_configuration_unavailable") from error


def _close_windows_job(handle: int, terminate: bool = False, *, process=None, deadline: Optional[float] = None) -> None:
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
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    win_handle = wintypes.HANDLE(handle)
    if terminate:
        if not kernel32.TerminateJobObject(win_handle, 1):
            raise OwnedProcessError("job_termination_failed")
        deadline = deadline if deadline is not None else time.monotonic() + 5.0
        while time.monotonic() < deadline:
            info = BasicAccountingInformation()
            returned = wintypes.DWORD()
            if not kernel32.QueryInformationJobObject(
                win_handle, 1, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(returned)
            ):
                raise OwnedProcessError("job_drain_query_failed")
            state = kernel32.WaitForSingleObject(process._handle, 0) if process is not None else 0
            if state not in (0, 258):
                raise OwnedProcessError("original_process_wait_failed")
            if info.ActiveProcesses == 0 and state == 0:
                break
            time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
        else:
            raise OwnedProcessError("job_drain_deadline_unconfirmed")
    if not kernel32.CloseHandle(win_handle):
        raise OwnedProcessError("drained_job_handle_close_failed")


class OwnedProcessRegistry:
    def __init__(self, cancel_event: Optional[threading.Event] = None):
        self.cancel_event = cancel_event or threading.Event()
        self._lock = threading.RLock()
        self._children: Dict[int, subprocess.Popen] = {}
        self._windows_jobs: Dict[int, int] = {}
        self._pending_handles = set()
        self._native_starts = set()
        self._cleanup_error: Optional[str] = None
        self._cancelled = False

    def _register_windows_process(self, process, job_handle) -> None:
        self._children[process.pid] = process
        self._windows_jobs[process.pid] = job_handle

    def check_cleanup(self) -> None:
        if self._cleanup_error:
            raise OwnedProcessError(self._cleanup_error)

    def assert_quiescent(self) -> None:
        with self._lock:
            self.check_cleanup()
            if self._children or self._windows_jobs or self._pending_handles or self._native_starts:
                raise OwnedProcessError("owned_processes_not_quiescent")

    def add(self, process: subprocess.Popen) -> None:
        if os.name == "nt":
            raise OwnedProcessError("running_process_admission_forbidden")
        windows_job = None
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
        if os.name == "nt":
            with self._lock:
                for native_owner in tuple(self._native_starts):
                    if native_owner.process is process:
                        try:
                            native_owner.cleanup()
                        except (OSError, AppError, MemoryError) as error:
                            self._cleanup_error = "native_start_cleanup_unconfirmed"
                            raise OwnedProcessError(self._cleanup_error) from error
                        self._native_starts.discard(native_owner)
                        if not self._children and not self._windows_jobs and not self._pending_handles and not self._native_starts:
                            self._cleanup_error = None
                        self.check_cleanup()
                        return
                windows_job = self._windows_jobs.get(process.pid)
                if windows_job is not None:
                    try:
                        _close_windows_job(windows_job, terminate=True, process=process)
                    except (OSError, AppError) as error:
                        self._cleanup_error = "owned_cleanup_unconfirmed"
                        raise OwnedProcessError(self._cleanup_error) from error
                    self._windows_jobs.pop(process.pid, None)
                    self._children.pop(process.pid, None)
                    if not self._children and not self._pending_handles and not self._native_starts:
                        self._cleanup_error = None
                elif process.pid in self._children:
                    self._cleanup_error = "required_owned_job_missing"
                self.check_cleanup()
            return
        with self._lock:
            self._children.pop(process.pid, None)
        if process.pid > 0:
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
            failures = []
            deadline = time.monotonic() + 5.0
            with self._lock:
                had_owners = bool(self._children or self._windows_jobs or self._pending_handles or self._native_starts)
                for native_owner in tuple(self._native_starts):
                    try:
                        native_owner.cleanup(deadline=deadline)
                    except (OSError, AppError, MemoryError):
                        failures.append("native_start_cleanup_unconfirmed")
                    else:
                        self._native_starts.discard(native_owner)
                for process in list(self._children.values()):
                    if any(owner.process is process for owner in self._native_starts):
                        continue
                    job_handle = self._windows_jobs.get(process.pid)
                    if job_handle is None:
                        failures.append("required_owned_job_missing")
                        continue
                    try:
                        _close_windows_job(job_handle, terminate=True, process=process, deadline=deadline)
                    except (OSError, AppError):
                        failures.append("owned_cleanup_unconfirmed")
                        continue
                    self._windows_jobs.pop(process.pid, None)
                    self._children.pop(process.pid, None)
                if self._pending_handles:
                    kernel, _, _ = _windows_api()
                    for handle in list(self._pending_handles):
                        if kernel.CloseHandle(handle):
                            self._pending_handles.remove(handle)
                        else:
                            failures.append("owned_handle_close_unconfirmed")
                if failures:
                    self._cleanup_error = failures[0]
                elif had_owners and not self._children and not self._windows_jobs and not self._pending_handles and not self._native_starts:
                    self._cleanup_error = None
                self.check_cleanup()
            return
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
        return self.cancel_event.is_set() or self._cancelled or bool(self._cleanup_error)


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
        self.registry.check_cleanup()
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
    registry.check_cleanup()
    if os.name == "nt":
        if not _windows_popen_signature_supported():
            raise OwnedProcessError("unsupported_popen_private_signature")
        return _WindowsJobPopen(args, registry=registry, shell=False, **kwargs)
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
            try:
                stdout, stderr = process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired as error:
                if registry is not None:
                    registry._cleanup_error = "owned_pipe_drain_unconfirmed"
                raise OwnedProcessError("owned_pipe_drain_unconfirmed") from error
        raise
    finally:
        if registry is not None:
            registry.discard(process)
