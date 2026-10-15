import os
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

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
            with patch("cha_stabilizer.owned_processes._create_windows_job", return_value=None):
                with patch("cha_stabilizer.owned_processes.subprocess.Popen", return_value=fake_process) as popen:
                    spawned = spawn_owned_process([sys.executable, "-c", "pass"], stdout=None, stderr=None)
        self.assertIs(spawned, fake_process)
        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        registry.discard(spawned)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object descendant check")
    def test_windows_job_cancellation_kills_owned_descendants(self):
        import ctypes
        from ctypes import wintypes

        registry = OwnedProcessRegistry()
        child_pid = None
        parent = None
        with registry_scope(registry):
            try:
                script = (
                    "import subprocess,sys,time; time.sleep(0.8); "
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                    "print(child.pid,flush=True); time.sleep(60)"
                )
                parent = spawn_owned_process(
                    [sys.executable, "-c", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                line = parent.stdout.readline().strip()
                child_pid = int(line)
                self.assertTrue(registry._windows_jobs.get(parent.pid))
                registry.cancel_event.set()
                registry.terminate_all(grace_seconds=0.2)
                self.assertIsNotNone(parent.poll())

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel32.OpenProcess.restype = wintypes.HANDLE
                kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel32.WaitForSingleObject.restype = wintypes.DWORD
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                handle = kernel32.OpenProcess(0x00100000, False, child_pid)  # SYNCHRONIZE
                if handle:
                    try:
                        state = kernel32.WaitForSingleObject(handle, 0)
                    finally:
                        kernel32.CloseHandle(handle)
                    self.assertEqual(state, 0)  # WAIT_OBJECT_0
            finally:
                if parent is not None and parent.stdout is not None:
                    parent.stdout.close()
                if registry.snapshot():
                    registry.terminate_all(grace_seconds=0.1)
                if child_pid is not None:
                    cleanup = ctypes.WinDLL("kernel32", use_last_error=True)
                    cleanup.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                    cleanup.OpenProcess.restype = wintypes.HANDLE
                    cleanup.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                    cleanup.WaitForSingleObject.restype = wintypes.DWORD
                    cleanup.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                    cleanup.TerminateProcess.restype = wintypes.BOOL
                    cleanup.CloseHandle.argtypes = [wintypes.HANDLE]
                    cleanup.CloseHandle.restype = wintypes.BOOL
                    handle = cleanup.OpenProcess(0x00100001, False, child_pid)
                    if handle:
                        try:
                            if cleanup.WaitForSingleObject(handle, 0) == 258:
                                cleanup.TerminateProcess(handle, 1)
                                cleanup.WaitForSingleObject(handle, 3000)
                        finally:
                            cleanup.CloseHandle(handle)

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


if __name__ == "__main__":
    unittest.main()
