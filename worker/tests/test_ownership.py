import os
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from cha_stabilizer.errors import AppError
from cha_stabilizer.owned_processes import (
    OwnedProcessRegistry,
    get_active_registry,
    registry_scope,
    spawn_owned_process,
)


class OwnedProcessTests(unittest.TestCase):
    def test_spawn_requires_an_active_owner_and_uses_the_active_registry(self):
        with self.assertRaises(RuntimeError):
            spawn_owned_process([sys.executable, "-c", "pass"])
        registry = OwnedProcessRegistry()
        with registry_scope(registry):
            self.assertIs(get_active_registry(), registry)
            process = spawn_owned_process(
                [sys.executable, "-c", "pass"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = process.communicate(timeout=10)
            registry.discard(process)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(stdout, b"")
        self.assertEqual(stderr, b"")
        self.assertIsNone(get_active_registry())

    def test_owned_process_defaults_streams_to_devnull(self):
        registry = OwnedProcessRegistry()
        fake_process = Mock()
        fake_process.pid = 0
        fake_process._handle = None
        with registry_scope(registry):
            factory = "cha_stabilizer.owned_processes._WindowsJobPopen" if os.name == "nt" else "cha_stabilizer.owned_processes.subprocess.Popen"
            with patch("cha_stabilizer.owned_processes._windows_popen_signature_supported", return_value=True):
                with patch(factory, return_value=fake_process) as popen:
                    spawned = spawn_owned_process([sys.executable, "-c", "pass"], stdout=None, stderr=None)
        self.assertIs(spawned, fake_process)
        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        registry.discard(spawned)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object descendant check")
    def test_windows_job_cancellation_kills_owned_descendants(self):
        result = run_original_handle_fixture(controlled=False)
        self.assertTrue(result["child_in_exact_job"])
        self.assertEqual(result["original_child_wait0_after_cancel"], 0)
        self.assertTrue(result["leader_exited_after_cancel"])
        self.assertFalse(result["forced_cleanup"])
        self.assertTrue(result["first_user_code_after_job_binding"])

    @unittest.skipUnless(os.name == "nt", "Windows post-admission drain check")
    def test_windows_post_admission_drain_preserves_text_and_file_stdio(self):
        result = run_original_handle_fixture(controlled=True)
        self.assertTrue(result["child_in_exact_job"])
        self.assertEqual(result["original_child_wait0_after_cancel"], 0)
        self.assertFalse(result["forced_cleanup"])
        self.assertTrue(result["communicate_timeout_reentry_verified"])
        self.assertTrue(result["stderr_file_verified"])

    def test_cancellation_signals_only_registered_child_handles(self):
        registry = OwnedProcessRegistry()
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with registry_scope(registry):
                process = spawn_owned_process(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.assertIn(process, registry.snapshot())
                registry.cancel_event.set()
                registry.terminate_all(grace_seconds=0.2)
                self.assertIsNotNone(process.poll())
                self.assertIsNone(unrelated.poll())
                registry.discard(process)
            self.assertEqual(registry.snapshot(), [])
        finally:
            if unrelated.poll() is None:
                unrelated.terminate()
                unrelated.wait(timeout=5)


@unittest.skipUnless(os.name == "nt", "Windows admission and cleanup contracts")
class OwnershipAdmissionContractTests(unittest.TestCase):
    """只用原对象的纯内存准入/失败合同，不启动旧 PID fixture。"""

    def test_actual_membership_and_registration_precede_original_thread_resume(self):
        import ctypes
        from types import SimpleNamespace
        import cha_stabilizer.owned_processes as owned
        order = []
        registry = OwnedProcessRegistry()
        process = SimpleNamespace(pid=123, _handle=456)

        def membership(process_handle, job_handle, result):
            self.assertEqual((process_handle, job_handle), (456, 789))
            result._obj.value = True
            order.append("membership")
            return True

        def resume(thread_handle):
            self.assertEqual(thread_handle, 321)
            self.assertIs(registry._children[123], process)
            self.assertEqual(registry._windows_jobs[123], 789)
            order.append("registered_then_resume")
            return 1

        kernel = SimpleNamespace(IsProcessInJob=membership, ResumeThread=resume)
        owned._finish_windows_start(process, registry, 789, 321, kernel)
        self.assertEqual(order, ["membership", "registered_then_resume"])

    def test_membership_unknown_or_cancelled_never_resumes(self):
        from types import SimpleNamespace
        from cha_stabilizer.errors import AppError
        import cha_stabilizer.owned_processes as owned
        for failure in ("query", "not_member", "cancelled"):
            with self.subTest(failure=failure):
                registry = OwnedProcessRegistry()
                if failure == "cancelled":
                    registry.cancel_event.set()
                process = SimpleNamespace(pid=123, _handle=456)
                calls = []
                def membership(process_handle, job_handle, result):
                    result._obj.value = failure != "not_member"
                    return failure != "query"
                kernel = SimpleNamespace(IsProcessInJob=membership, ResumeThread=lambda handle: calls.append(handle) or 1)
                with self.assertRaises(AppError):
                    owned._finish_windows_start(process, registry, 789, 321, kernel)
                self.assertEqual(calls, [])

    def test_unadmitted_windows_process_never_falls_back_to_no_job(self):
        from types import SimpleNamespace
        from cha_stabilizer.errors import AppError
        registry = OwnedProcessRegistry()
        process = SimpleNamespace(pid=123, _handle=None, poll=lambda: 0)
        with patch("cha_stabilizer.owned_processes._create_windows_job", return_value=None):
            with self.assertRaises(AppError):
                registry.add(process)
        self.assertEqual(registry.snapshot(), [])

    def test_cancel_cleanup_failure_is_explicit_and_retains_owner_handle(self):
        from types import SimpleNamespace
        from cha_stabilizer.errors import AppError
        registry = OwnedProcessRegistry()
        process = SimpleNamespace(pid=123, poll=lambda: 0, wait=lambda **kwargs: 0)
        registry._children[123] = process
        registry._windows_jobs[123] = 789
        with patch("cha_stabilizer.owned_processes._close_windows_job", side_effect=OSError("mock drain unknown")):
            with self.assertRaises(AppError):
                registry.terminate_all(grace_seconds=0.0)
        self.assertIs(registry._children[123], process)
        self.assertEqual(registry._windows_jobs[123], 789)

    def test_natural_discard_failure_is_explicit_and_retains_owner_handle(self):
        from types import SimpleNamespace
        from cha_stabilizer.errors import AppError
        registry = OwnedProcessRegistry()
        process = SimpleNamespace(pid=123, poll=lambda: 0)
        registry._children[123] = process
        registry._windows_jobs[123] = 789
        with patch("cha_stabilizer.owned_processes._close_windows_job", side_effect=OSError("mock drain unknown")):
            with self.assertRaises(AppError):
                registry.discard(process)
        self.assertIs(registry._children[123], process)
        self.assertEqual(registry._windows_jobs[123], 789)


@unittest.skipUnless(os.name == "nt", "Windows native creation bridge mocks")
class WindowsCreationBridgeMockTests(unittest.TestCase):
    """全部 Win32 调用均由局部 mock 替代，不创建进程或查询系统。"""

    def exercise(self, failure=None):
        import ctypes
        import contextlib
        from types import SimpleNamespace
        import cha_stabilizer.owned_processes as owned
        calls = []
        registry = OwnedProcessRegistry()
        Startup, Information = owned._windows_structures()
        class FakeHandle(int):
            closed = False
        class Probe(owned._WindowsJobPopen):
            def __setattr__(self, name, value):
                if failure == "assign_handle_memory" and name == "_handle":
                    raise MemoryError("mock Popen handle field allocation failed")
                return object.__setattr__(self, name, value)
            def _close_pipe_fds(self, *args):
                calls.append("close_child_pipes")
            def _filter_handle_list(self, handles):
                return handles
        process = object.__new__(Probe)
        process._owner_registry = registry
        process._child_created = False
        process.returncode = 0
        process.pid = None
        process.stdin = process.stdout = process.stderr = None
        def initialize(pointer, count, flags, size):
            size._obj.value = 128
            if pointer is None:
                ctypes.set_last_error(122)
                return False
            calls.append("initialize_attributes")
            return failure != "initialize"
        def update(pointer, flags, attribute, values, size, previous, returned):
            calls.append(("attribute", attribute))
            if attribute == 0x2000D:
                self.assertEqual(ctypes.cast(values, ctypes.POINTER(ctypes.c_void_p))[0], 789)
            return not (failure == "attribute" and attribute == 0x2000D)
        def create(executable, command, pa, ta, inherit, flags, environment, cwd, startup, information):
            calls.append("create_suspended")
            self.assertEqual(len(registry._native_starts), 1)
            start_owner = next(iter(registry._native_starts))
            self.assertIs(start_owner.information, information._obj)
            self.assertIs(start_owner.process, process)
            self.assertEqual(start_owner.job, 789)
            calls.append("native_owner_exists_before_create")
            self.assertTrue(flags & 4)
            self.assertTrue(flags & 0x80000)
            self.assertTrue(inherit)
            self.assertEqual(startup._obj.startup.stdout, 104)
            self.assertEqual(startup._obj.startup.stderr, 104)
            self.assertEqual(executable, sys.executable)
            if failure == "create":
                return False
            information._obj.process, information._obj.thread, information._obj.pid = 456, 321, 123
            if failure == "cancel":
                registry.cancel_event.set()
            return True
        def membership(process_handle, job_handle, result):
            calls.append("membership")
            result._obj.value = failure != "membership"
            return True
        def resume(handle):
            calls.append("resume_original_thread")
            self.assertEqual(handle, 321)
            self.assertIs(registry._children[123], process)
            self.assertEqual(registry._windows_jobs[123], 789)
            return 0xFFFFFFFF if failure == "resume" else 1
        raw_signaled = [failure not in ("wrap_memory", "wrap_memory_wait", "wrap_memory_retry")]
        allow_raw_termination = [failure != "wrap_memory_retry"]
        def wait_original(handle, timeout):
            calls.append(("wait_original", handle, timeout))
            return 0 if raw_signaled[0] else 258
        def terminate_original(handle, code):
            calls.append(("terminate_original", handle))
            if not allow_raw_termination[0]:
                return False
            if failure != "wrap_memory_wait":
                raw_signaled[0] = True
            return True
        kernel = SimpleNamespace(InitializeProcThreadAttributeList=initialize, UpdateProcThreadAttribute=update,
                                 DeleteProcThreadAttributeList=lambda pointer: calls.append("delete_attributes"),
                                 CreateProcessW=create, IsProcessInJob=membership, ResumeThread=resume,
                                 WaitForSingleObject=wait_original, TerminateProcess=terminate_original,
                                 CloseHandle=lambda handle: calls.append(("close_handle", int(handle))) or not (failure == "thread_close" and int(handle) == 321))
        options = dict(args=[sys.executable, "-c", "pass"], executable=None, preexec_fn=None, close_fds=True,
                       pass_fds=(), cwd=str(__import__("pathlib").Path.cwd()), env={"OWN_TEST": "值"},
                       startupinfo=subprocess.STARTUPINFO(lpAttributeList={"handle_list": [108]}),
                       creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, shell=False,
                       p2cread=100, p2cwrite=-1, c2pread=-1, c2pwrite=104, errread=-1, errwrite=104,
                       unused_restore_signals=True, unused_gid=None, unused_gids=None, unused_uid=None,
                       unused_umask=-1, unused_start_new_session=False, unused_process_group=-1)
        error = None
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(owned, "_windows_api", return_value=(kernel, Startup, Information)))
            stack.enter_context(patch.object(owned, "_create_windows_job", return_value=789))
            stack.enter_context(patch.object(owned, "_handles_inheritable", return_value=True))
            def wrap(handle):
                calls.append("wrap_original_handle")
                if failure in ("wrap_memory", "wrap_memory_wait", "wrap_memory_retry"):
                    raise MemoryError("mock handle wrapper allocation failed")
                return FakeHandle(handle)
            stack.enter_context(patch.object(owned, "_wrap_windows_process_handle", side_effect=wrap))
            stack.enter_context(patch.object(owned, "_close_windows_job", side_effect=lambda *args, **kwargs: calls.append("drain_original_root")))
            try:
                process._execute_child(**options)
            except (AppError, MemoryError, AttributeError) as caught:
                error = caught
            if failure == "wrap_memory_retry":
                self.assertEqual(len(registry._native_starts), 1)
                start = next(iter(registry._native_starts))
                calls.append(("retry_owner_raw_values", start.information.process, start.information.thread, start.job))
                allow_raw_termination[0] = True
                registry.terminate_all()
                registry.assert_quiescent()
                calls.append("raw_owner_retry_confirmed")
        # 这些数字只来自 mock，不能交给任何实际 Win32 Close/Terminate。
        calls.extend(("retained_unclosed_handle", handle) for handle in registry._pending_handles)
        for start in registry._native_starts:
            if start.information.thread:
                calls.append(("retained_unclosed_handle", start.information.thread))
            calls.append(("retained_raw_process", start.information.process))
            calls.append(("retained_raw_job", start.job))
        registry._children.clear()
        registry._windows_jobs.clear()
        registry._pending_handles.clear()
        registry._native_starts.clear()
        registry._cleanup_error = None
        return calls, error

    def test_real_attribute_ids_suspended_and_registration_order(self):
        calls, error = self.exercise()
        self.assertIsNone(error)
        self.assertLess(calls.index(("attribute", 0x20002)), calls.index("create_suspended"))
        self.assertLess(calls.index(("attribute", 0x2000D)), calls.index("create_suspended"))
        self.assertLess(calls.index("membership"), calls.index("resume_original_thread"))
        self.assertEqual(calls.count(("close_handle", 321)), 1)
        self.assertEqual(calls.count("delete_attributes"), 1)
        self.assertEqual(calls.count("close_child_pipes"), 1)
        self.assertNotIn(("close_handle", 789), calls)

    def test_creation_failure_paths_never_resume_and_balance_owned_resources(self):
        for failure in ("initialize", "attribute", "create", "membership", "cancel"):
            with self.subTest(failure=failure):
                calls, error = self.exercise(failure)
                self.assertIsInstance(error, AppError)
                self.assertNotIn("resume_original_thread", calls)
                self.assertEqual(calls.count("close_child_pipes"), 1)
                self.assertEqual(calls.count("delete_attributes"), 0 if failure == "initialize" else 1)
                if failure in ("membership", "cancel"):
                    self.assertIn("drain_original_root", calls)
                    self.assertEqual(calls.count(("close_handle", 321)), 1)
                else:
                    self.assertEqual(calls.count(("close_handle", 789)), 1)

    def test_resume_failure_is_not_success(self):
        calls, error = self.exercise("resume")
        self.assertIsInstance(error, AppError)
        self.assertIn("drain_original_root", calls)
        self.assertEqual(calls.count(("close_handle", 321)), 1)

    def test_wrapper_memory_error_closes_original_process_not_half_constructed_self(self):
        calls, error = self.exercise("wrap_memory")
        self.assertIsInstance(error, MemoryError)
        self.assertNotIn("resume_original_thread", calls)
        self.assertIn("drain_original_root", calls)
        self.assertEqual(calls.count(("close_handle", 456)), 1)
        self.assertEqual(calls.count(("close_handle", 321)), 1)
        self.assertEqual(calls.count("delete_attributes"), 1)
        self.assertEqual(calls.count("close_child_pipes"), 1)

    def test_unconfirmed_raw_signal_retains_preallocated_owner_without_job_close(self):
        calls, error = self.exercise("wrap_memory_wait")
        self.assertIsInstance(error, AppError)
        self.assertNotIn("resume_original_thread", calls)
        self.assertNotIn("drain_original_root", calls)
        self.assertNotIn(("close_handle", 456), calls)
        self.assertNotIn(("close_handle", 321), calls)
        self.assertIn(("retained_raw_process", 456), calls)
        self.assertIn(("retained_unclosed_handle", 321), calls)
        self.assertIn(("retained_raw_job", 789), calls)
        self.assertEqual(calls.count("close_child_pipes"), 1)
        self.assertEqual(calls.count("delete_attributes"), 1)

    def test_retained_raw_owner_can_retry_using_only_original_handles(self):
        calls, error = self.exercise("wrap_memory_retry")
        self.assertIsInstance(error, AppError)
        self.assertIn(("retry_owner_raw_values", 456, 321, 789), calls)
        self.assertIn("raw_owner_retry_confirmed", calls)
        self.assertEqual(calls.count(("close_handle", 456)), 1)
        self.assertEqual(calls.count(("close_handle", 321)), 1)
        self.assertNotIn("resume_original_thread", calls)
        self.assertNotIn(("retained_raw_process", 456), calls)

    def test_popen_field_assignment_memory_error_uses_raw_owner(self):
        calls, error = self.exercise("assign_handle_memory")
        self.assertIsInstance(error, MemoryError)
        self.assertNotIn("resume_original_thread", calls)
        self.assertIn("drain_original_root", calls)
        self.assertEqual(calls.count(("close_handle", 456)), 1)
        self.assertEqual(calls.count(("close_handle", 321)), 1)

    def test_post_resume_handle_close_failure_is_retained_not_success(self):
        calls, error = self.exercise("thread_close")
        self.assertIsInstance(error, AppError)
        self.assertIn(("retained_unclosed_handle", 321), calls)
        self.assertIn("drain_original_root", calls)
        self.assertEqual(calls.count("close_child_pipes"), 1)
        self.assertEqual(calls.count("delete_attributes"), 1)

    def test_native_drain_failures_are_explicit_and_do_not_close_owner_job(self):
        import builtins
        import ctypes
        import types
        from ctypes import wintypes
        import cha_stabilizer.owned_processes as owned
        for phase in ("terminate", "query", "active", "wait_failed", "wait_running", "success"):
            with self.subTest(phase=phase):
                calls = []
                class Call:
                    def __init__(self, function):
                        self.function = function
                    def __call__(self, *args):
                        return self.function(*args)
                def query(*args):
                    args[2]._obj.ActiveProcesses = 1 if phase == "active" else 0
                    return phase != "query"
                state = 0xFFFFFFFF if phase == "wait_failed" else 258 if phase == "wait_running" else 0
                kernel = types.SimpleNamespace(
                    TerminateJobObject=Call(lambda *args: phase != "terminate"),
                    QueryInformationJobObject=Call(query), WaitForSingleObject=Call(lambda *args: state),
                    CloseHandle=Call(lambda *args: calls.append("close_job") or True))
                proxy = types.ModuleType("ctypes")
                proxy.__dict__.update(vars(ctypes))
                proxy.wintypes = wintypes
                proxy.WinDLL = lambda *args, **kwargs: kernel
                def importer(name, globals=None, locals=None, fromlist=(), level=0):
                    return proxy if name == "ctypes" else builtins.__import__(name, globals, locals, fromlist, level)
                ticks = [0.0]
                def tick():
                    ticks[0] += 0.2
                    return ticks[0]
                scope = dict(owned._close_windows_job.__globals__)
                scope["__builtins__"] = dict(vars(builtins), __import__=importer)
                scope["time"] = types.SimpleNamespace(monotonic=tick, sleep=lambda duration: None)
                close = types.FunctionType(owned._close_windows_job.__code__, scope)
                close.__kwdefaults__ = dict(owned._close_windows_job.__kwdefaults__ or {})
                process = types.SimpleNamespace(_handle=456)
                if phase == "success":
                    close(789, terminate=True, process=process)
                    self.assertEqual(calls, ["close_job"])
                else:
                    with self.assertRaises(AppError):
                        close(789, terminate=True, process=process)
                    self.assertEqual(calls, [])

    def test_unknown_private_signature_never_reaches_factory(self):
        from cha_stabilizer.errors import AppError
        registry = OwnedProcessRegistry()
        with registry_scope(registry), patch("cha_stabilizer.owned_processes._windows_popen_signature_supported", return_value=False), \
                patch("cha_stabilizer.owned_processes._WindowsJobPopen") as factory:
            with self.assertRaises(AppError):
                spawn_owned_process([sys.executable, "-c", "pass"])
        factory.assert_not_called()

    def test_audited_315_private_signature_is_supported(self):
        import cha_stabilizer.owned_processes as owned
        self.assertTrue(owned._windows_popen_signature_supported())


_ORIGINAL_HANDLE_PARENT = r'''
import ctypes,json,os,subprocess,sys,time
from ctypes import wintypes as w
k=ctypes.WinDLL("kernel32",use_last_error=True)
class SI(ctypes.Structure):
 _fields_=[("cb",w.DWORD),("r",w.LPWSTR),("d",w.LPWSTR),("t",w.LPWSTR)]+[(n,w.DWORD) for n in ("x","y","cx","cy","xc","yc","fill","flags")]+[("show",w.WORD),("size",w.WORD),("data",ctypes.c_void_p)]+[(n,w.HANDLE) for n in ("stdin","stdout","stderr")]
class PI(ctypes.Structure):
 _fields_=[("process",w.HANDLE),("thread",w.HANDLE),("pid",w.DWORD),("tid",w.DWORD)]
k.GetCurrentProcess.restype=w.HANDLE
k.DuplicateHandle.argtypes=[w.HANDLE,w.HANDLE,w.HANDLE,ctypes.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD];k.DuplicateHandle.restype=w.BOOL
k.CreateProcessW.argtypes=[w.LPCWSTR,w.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,w.BOOL,w.DWORD,ctypes.c_void_p,w.LPCWSTR,ctypes.POINTER(SI),ctypes.POINTER(PI)];k.CreateProcessW.restype=w.BOOL
k.GetProcessTimes.argtypes=[w.HANDLE]+[ctypes.POINTER(w.FILETIME)]*4;k.GetProcessTimes.restype=w.BOOL
k.ResumeThread.argtypes=[w.HANDLE];k.ResumeThread.restype=w.DWORD
k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
supervisor=int(sys.argv[1]);controlled=sys.argv[2]=="1"
print(json.dumps({"kind":"first_user_code"}),flush=True)
if controlled:
 sys.stderr.write("owned-fixture-stderr\n");sys.stderr.flush()
 if sys.stdin.readline()!="CREATE_OWN_CHILD\n":sys.exit(2)
s=SI();s.cb=ctypes.sizeof(s);p=PI()
command=ctypes.create_unicode_buffer(subprocess.list2cmdline([sys.executable,"-I","-B","-c","import time;time.sleep(60)"]))
if not k.CreateProcessW(sys.executable,command,None,None,False,0x08000204,None,os.getcwd(),ctypes.byref(s),ctypes.byref(p)):sys.exit(3)
times=[w.FILETIME() for _ in range(4)]
if not k.GetProcessTimes(p.process,*(ctypes.byref(x) for x in times)):sys.exit(4)
birth=(int(times[0].dwHighDateTime)<<32)|int(times[0].dwLowDateTime)
h=w.HANDLE()
if not k.DuplicateHandle(k.GetCurrentProcess(),p.process,supervisor,ctypes.byref(h),0,False,2):sys.exit(5)
print(json.dumps({"kind":"original_child_handle","handle":h.value,"creation_time_100ns":birth}),flush=True)
previous=int(k.ResumeThread(p.thread))
print(json.dumps({"kind":"original_thread_resume","previous":previous}),flush=True)
k.CloseHandle(p.thread);k.CloseHandle(p.process);k.CloseHandle(supervisor)
if previous!=1:sys.exit(6)
time.sleep(60)
'''


def run_original_handle_fixture(*, controlled=False):
    """新 fake 场景；只操作 CreateProcess/继承/DuplicateHandle 得到的原对象。"""
    import ctypes
    from ctypes import wintypes
    import json
    import msvcrt
    import queue
    import threading
    import tempfile
    from pathlib import Path
    import cha_stabilizer.owned_processes as owned
    root = Path(__file__).resolve().parents[2]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "DuplicateHandle": ([wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
        "GetProcessTimes": ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
        "QueryFullProcessImageNameW": ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
        "PeekNamedPipe": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    def creation(handle):
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
            raise AppError("Own creation time was not available.")
        return (int(values[0].dwHighDateTime) << 32) | int(values[0].dwLowDateTime)
    def image_matches(handle):
        value, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, value, ctypes.byref(size)):
            return False
        return os.path.normcase(os.path.normpath(value.value)) == os.path.normcase(os.path.normpath(sys.executable))
    def in_job(handle, job):
        value = wintypes.BOOL()
        if not kernel.IsProcessInJob(handle, job, ctypes.byref(value)):
            raise AppError("Exact own Job membership was not available.")
        return bool(value.value)
    entered, release = threading.Event(), threading.Event()
    class CapturedRegistry(OwnedProcessRegistry):
        candidate = None
        job = None
        def _register_windows_process(self, process, job_handle):
            super()._register_windows_process(process, job_handle)
            self.candidate, self.job = process, job_handle
            entered.set()
            if not release.wait(timeout=5.0):
                raise AppError("Fixture resume coordination timed out.")
    registry = CapturedRegistry()
    if controlled:
        release.set()
    response = queue.Queue(maxsize=1)
    supervisor = wintypes.HANDLE()
    child = None
    worker = None
    receipt = {"controlled_go": controlled, "forced_cleanup": False, "production_safety_pass": False,
               "existing_pid_lookup_or_control": False, "original_handle_cleanup_only": True,
               "first_user_code_after_job_binding": False, "communicate_timeout_reentry_verified": False}
    log = tempfile.TemporaryFile(mode="w+b")
    try:
        current = kernel.GetCurrentProcess()
        if not kernel.DuplicateHandle(current, current, current, ctypes.byref(supervisor), 0x0040, True, 0):
            raise AppError("Own inherited supervisor handle was not available.")
        startup = subprocess.STARTUPINFO(lpAttributeList={"handle_list": [supervisor.value]})
        def launch():
            try:
                with registry_scope(registry):
                    process = spawn_owned_process([sys.executable, "-I", "-B", "-c", _ORIGINAL_HANDLE_PARENT,
                                                   str(supervisor.value), "1" if controlled else "0"],
                                                  cwd=str(root), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                  stderr=log if controlled else subprocess.STDOUT,
                                                  text=controlled, encoding="utf-8" if controlled else None,
                                                  bufsize=-1 if controlled else 0, startupinfo=startup)
                response.put((process, None))
            except BaseException as error:
                response.put((None, error))
        worker = threading.Thread(target=launch, daemon=True)
        worker.start()
        if not entered.wait(timeout=6.0):
            raise AppError("Native suspended registration did not complete.")
        process = registry.candidate
        receipt["parent_creation_time_100ns"] = creation(process._handle)
        receipt["parent_image_matches_audited_python"] = image_matches(process._handle)
        receipt["parent_in_exact_job_before_resume"] = in_job(process._handle, registry.job)
        if not controlled:
            available = wintypes.DWORD()
            raw_pipe = msvcrt.get_osfhandle(process.stdout.fileno())
            if not kernel.PeekNamedPipe(raw_pipe, None, 0, None, ctypes.byref(available), None):
                raise AppError("Original stdout pipe was not available.")
            receipt["stdout_bytes_before_original_resume"] = int(available.value)
            if available.value != 0 or not receipt["parent_in_exact_job_before_resume"]:
                raise AppError("First-code admission order was not established.")
        release.set()
        worker.join(timeout=6.0)
        launched, error = response.get(timeout=1.0)
        if error is not None:
            raise error
        if launched is not process:
            raise AppError("Original parent object was not retained.")
        def read_message():
            line = process.stdout.readline(4097)
            if len(line) > 4096:
                raise AppError("Fixture protocol line exceeded its budget.")
            return json.loads(line)
        if read_message() != {"kind": "first_user_code"}:
            raise AppError("First user-code marker was not received.")
        receipt["first_user_code_after_job_binding"] = receipt["parent_in_exact_job_before_resume"]
        if controlled:
            process.stdin.write("CREATE_OWN_CHILD\n")
            process.stdin.flush()
        message = read_message()
        if set(message) != {"kind", "handle", "creation_time_100ns"} or message["kind"] != "original_child_handle":
            raise AppError("Original child handle transfer was not verified.")
        child = message["handle"]
        if type(child) is not int or not 0 < child < 2 ** (ctypes.sizeof(ctypes.c_void_p) * 8):
            raise AppError("Original child handle was invalid.")
        birth = creation(child)
        receipt["child_creation_time_100ns"] = birth
        receipt["transferred_creation_time_matches"] = birth == message["creation_time_100ns"]
        receipt["child_image_matches_audited_python"] = image_matches(child)
        receipt["child_in_exact_job"] = in_job(child, registry.job)
        receipt["child_original_thread_resumed_once"] = read_message() == {"kind": "original_thread_resume", "previous": 1}
        if not all(receipt[key] for key in ("transferred_creation_time_matches", "child_image_matches_audited_python",
                                            "child_in_exact_job", "child_original_thread_resumed_once")):
            raise AppError("Original child ownership was not established.")
        try:
            process.communicate(timeout=0.01)
            raise AppError("Fixture parent exited before cancellation.")
        except subprocess.TimeoutExpired:
            pass
        registry.cancel_event.set()
        registry.terminate_all(grace_seconds=0.2)
        receipt["original_child_wait0_after_cancel"] = int(kernel.WaitForSingleObject(child, 0))
        receipt["leader_exited_after_cancel"] = process.poll() is not None
        receipt["child_creation_time_unchanged"] = creation(child) == birth
        output, errors = process.communicate(timeout=2.0)
        receipt["communicate_timeout_reentry_verified"] = isinstance(output, str if controlled else bytes) and errors is None
        registry.assert_quiescent()
        if controlled:
            log.seek(0)
            receipt["stderr_file_verified"] = log.read().replace(b"\r\n", b"\n") == b"owned-fixture-stderr\n"
        if receipt["original_child_wait0_after_cancel"] != 0 or not receipt["leader_exited_after_cancel"]:
            raise AppError("Cancellation did not signal the original owned objects.")
        receipt["status"] = "PASS_POST_ADMISSION_DRAIN_ONLY" if controlled else "PASS_NATIVE_ADMISSION_AND_DRAIN"
    except BaseException as error:
        receipt["status"] = "UNVERIFIED"
        receipt["reason"] = "original_handle_fixture_failed"
        raise AppError("Original-handle fixture did not establish its safety contract.", {"fixture_receipt": receipt}) from error
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=0.2)
        if child:
            if kernel.WaitForSingleObject(child, 0) == 258:
                receipt["forced_cleanup"] = True
                receipt["forced_original_child_termination"] = bool(kernel.TerminateProcess(child, 1))
                receipt["forced_original_child_wait"] = int(kernel.WaitForSingleObject(child, 3000))
            receipt["original_child_handle_closed"] = bool(kernel.CloseHandle(child))
        process = registry.candidate
        if process is not None:
            if process.poll() is None:
                receipt["forced_cleanup"] = True
            try:
                registry.terminate_all(grace_seconds=0.1)
            except AppError:
                receipt["cleanup_unconfirmed"] = True
            for stream in (process.stdin, process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()
            if process.poll() is not None:
                process._handle.Close()
                receipt["original_parent_handle_closed"] = True
        if supervisor.value:
            receipt["inherited_supervisor_handle_closed"] = bool(kernel.CloseHandle(supervisor))
        log.close()
        if receipt["forced_cleanup"]:
            receipt["status"] = "UNVERIFIED_FORCED_CLEANUP"
    return receipt


if __name__ == "__main__":
    unittest.main()
