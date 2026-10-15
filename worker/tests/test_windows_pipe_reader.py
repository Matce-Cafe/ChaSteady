import ctypes
import io
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cha_stabilizer.desktop_protocol import (
    MAX_REQUEST_BYTES,
    _ProtocolFatal,
    _read_bounded_line,
    run_desktop_protocol,
)
from cha_stabilizer.windows_pipe_reader import WindowsPipeReader


class WindowsPipeReaderFallbackTests(unittest.TestCase):
    def test_bytesio_uses_existing_reader_path(self):
        self.assertIsNone(WindowsPipeReader.from_file_object(io.BytesIO(b"request\n"), 64))

    def test_regular_file_uses_existing_reader_path(self):
        with tempfile.TemporaryFile("w+b") as stream:
            self.assertIsNone(WindowsPipeReader.from_file_object(stream, 64))

    @unittest.skipIf(os.name == "nt", "Windows-specific pipe implementation")
    def test_non_windows_never_selects_windows_pipe_reader(self):
        class HasFileno:
            def fileno(self):
                return 0

        self.assertIsNone(WindowsPipeReader.from_file_object(HasFileno(), 64))


@unittest.skipUnless(os.name == "nt", "Windows anonymous-pipe API test")
class WindowsPipeReaderTests(unittest.TestCase):
    def _create_pipe_reader(self, max_buffer):
        read_fd, write_fd = os.pipe()
        reader = WindowsPipeReader.from_file_object(read_fd, max_buffer)
        self.assertIsNotNone(reader, "os.pipe read fd must be recognized as FILE_TYPE_PIPE")
        self.addCleanup(self._close_fd, read_fd)
        return read_fd, write_fd, reader

    @staticmethod
    def _close_fd(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    @staticmethod
    def _start_writer(write_fd, chunks, *, delay=0.0):
        errors = []

        def write_all():
            try:
                for chunk in chunks:
                    view = memoryview(chunk)
                    while view:
                        written = os.write(write_fd, view)
                        view = view[written:]
                    if delay:
                        time.sleep(delay)
            except OSError as exc:
                errors.append(type(exc).__name__)
            finally:
                try:
                    os.close(write_fd)
                except OSError:
                    pass

        thread = threading.Thread(target=write_all, daemon=True)
        thread.start()
        return thread, errors

    def test_unknown_file_type_error_does_not_fall_back_to_blocking_reader(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(self._close_fd, read_fd)
        self.addCleanup(self._close_fd, write_fd)

        class UnknownFileType:
            def GetFileType(self, _handle):
                return 0

        with patch("cha_stabilizer.windows_pipe_reader._kernel32", return_value=UnknownFileType()):
            with patch("cha_stabilizer.windows_pipe_reader.ctypes.get_last_error", return_value=5):
                with self.assertRaises(OSError) as caught:
                    WindowsPipeReader.from_file_object(read_fd, 64)
        self.assertEqual(caught.exception.errno, 5)
        self.assertNotIn(str(read_fd), str(caught.exception))
        os.fstat(read_fd)

    def test_broken_no_data_and_not_connected_errors_are_eof(self):
        from ctypes import wintypes

        class FakeKernel:
            def __init__(self, *, peek_error=None, read_error=None, available=0):
                self.peek_error = peek_error
                self.read_error = read_error
                self.available = available

            def PeekNamedPipe(self, _handle, _buffer, _size, _read, total_available, _left):
                if self.peek_error is not None:
                    return False
                ctypes.cast(total_available, ctypes.POINTER(wintypes.DWORD)).contents.value = self.available
                return True

            def ReadFile(self, _handle, _buffer, _size, _read, _overlapped):
                return self.read_error is None

        for error in (38, 109, 232, 233):
            with self.subTest(api="PeekNamedPipe", error=error):
                reader = WindowsPipeReader(
                    123, 64, kernel32=FakeKernel(peek_error=error),
                    get_last_error=lambda error=error: error, idle_sleep=0,
                )
                self.assertEqual(reader.readline(64), b"")
            with self.subTest(api="ReadFile", error=error):
                reader = WindowsPipeReader(
                    123, 64, kernel32=FakeKernel(read_error=error, available=1),
                    get_last_error=lambda error=error: error, idle_sleep=0,
                )
                self.assertEqual(reader.readline(64), b"")

    def test_non_eof_winapi_errors_do_not_disclose_handle_or_path(self):
        reader = WindowsPipeReader(
            0x123456, 64, kernel32=object(), get_last_error=lambda: 5, idle_sleep=0,
        )
        reader._kernel32 = type("FailingPeek", (), {"PeekNamedPipe": lambda *_args: False})()
        with self.assertRaises(OSError) as caught:
            reader.readline(64)
        self.assertEqual(caught.exception.errno, 5)
        self.assertNotIn("123456", str(caught.exception))
        self.assertNotIn("path", str(caught.exception).casefold())

    def test_split_and_coalesced_lines_are_returned_exactly(self):
        read_fd, write_fd, reader = self._create_pipe_reader(128)
        writer, errors = self._start_writer(write_fd, (b"first", b"\nsecond\r\nthird\n"), delay=0.02)

        self.assertEqual(reader.readline(128), b"first\n")
        self.assertEqual(reader.readline(128), b"second\r\n")
        self.assertEqual(reader.readline(128), b"third\n")
        self.assertEqual(reader.readline(128), b"")
        writer.join(timeout=3)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertLessEqual(reader.buffered_bytes, 128)
        os.fstat(read_fd)  # The reader borrowed and did not close the descriptor.

    def test_crlf_and_partial_tail_at_eof_keep_protocol_semantics(self):
        read_fd, write_fd, reader = self._create_pipe_reader(MAX_REQUEST_BYTES + 2)
        writer, errors = self._start_writer(write_fd, (b'{"first":1}\r\npartial',))

        self.assertEqual(_read_bounded_line(reader), b'{"first":1}')
        self.assertEqual(_read_bounded_line(reader), b"partial")
        self.assertIsNone(_read_bounded_line(reader))
        writer.join(timeout=3)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        os.fstat(read_fd)

    def test_readline_size_limit_and_buffer_capacity(self):
        read_fd, write_fd, reader = self._create_pipe_reader(8)
        writer, errors = self._start_writer(write_fd, (b"abcdefghi\n",))

        self.assertEqual(reader.readline(8), b"abcdefgh")
        self.assertLessEqual(reader.buffered_bytes, 8)
        self.assertEqual(reader.readline(8), b"i\n")
        self.assertEqual(reader.readline(8), b"")
        writer.join(timeout=3)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        os.fstat(read_fd)

    def test_protocol_rejects_oversize_without_unbounded_buffering(self):
        read_fd, write_fd, reader = self._create_pipe_reader(MAX_REQUEST_BYTES + 2)
        oversize = b"x" * (MAX_REQUEST_BYTES + 1)
        chunks = (oversize[offset:offset + 65536] for offset in range(0, len(oversize), 65536))
        writer, errors = self._start_writer(write_fd, chunks)

        with self.assertRaises(_ProtocolFatal):
            _read_bounded_line(reader)
        self.assertLessEqual(reader.buffered_bytes, MAX_REQUEST_BYTES + 2)
        writer.join(timeout=5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        os.fstat(read_fd)

    def test_default_protocol_wraps_real_pipe_for_fragmented_strict_requests_and_eof(self):
        from types import SimpleNamespace

        read_fd, write_fd = os.pipe()
        stdin = os.fdopen(read_fd, "rb", buffering=0, closefd=False)
        self.addCleanup(stdin.close)
        self.addCleanup(self._close_fd, read_fd)
        output = io.BytesIO()
        diagnostics = io.BytesIO()
        ended = []
        selected_readers = []
        capability = "test-only-capability"

        class FakeServer:
            server_port = 12345
            session_url = "http://127.0.0.1:12345/#session=test"
            app = SimpleNamespace(jobs=object(), nonce="test-only-bearer")

        valid = json.dumps({
            "protocol": 1,
            "request_id": "fragmented-1",
            "capability": capability,
            "action": "web_session",
        }, separators=(",", ":")).encode("utf-8") + b"\n"
        strict_schema_error = json.dumps({
            "protocol": 1,
            "request_id": "strict-schema-1",
            "capability": capability,
            "action": "web_session",
            "unexpected": True,
        }, separators=(",", ":")).encode("utf-8")  # final partial line is delivered at EOF

        original_factory = WindowsPipeReader.from_file_object

        def observe_reader(stream, max_buffer):
            reader = original_factory(stream, max_buffer)
            selected_readers.append(reader)
            return reader

        chunks = (valid[:3], valid[3:17], valid[17:], strict_schema_error[:11], strict_schema_error[11:])
        writer, errors = self._start_writer(write_fd, chunks, delay=0.02)

        with patch.object(WindowsPipeReader, "from_file_object", side_effect=observe_reader):
            with patch.dict(os.environ):
                os.environ.pop("CHASTEADY_TEST_NONBLOCKING_STDIN", None)
                run_desktop_protocol(
                    FakeServer(), capability, stdin=stdin, stdout=output,
                    stderr=diagnostics, on_end=lambda: ended.append(True),
                )
        writer.join(timeout=3)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(ended, [True])
        self.assertEqual(len(selected_readers), 1)
        reader = selected_readers[0]
        self.assertIsInstance(reader, WindowsPipeReader)
        self.assertLessEqual(reader.buffered_bytes, MAX_REQUEST_BYTES + 2)
        self.assertEqual(diagnostics.getvalue(), b"")

        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(messages[0]["type"], "ready")
        self.assertEqual(messages[0]["protocol"], 1)
        self.assertEqual(messages[1]["request_id"], "fragmented-1")
        self.assertTrue(messages[1]["ok"])
        self.assertEqual(messages[2]["request_id"], "strict-schema-1")
        self.assertFalse(messages[2]["ok"])
        self.assertEqual(messages[2]["error"]["code"], "invalid_request")
        os.fstat(read_fd)  # The borrowed HANDLE remained open after protocol EOF.

    def test_pipe_reader_initialization_error_propagates_through_protocol_cleanup(self):
        from types import SimpleNamespace

        read_fd, write_fd = os.pipe()
        stdin = os.fdopen(read_fd, "rb", buffering=0, closefd=False)
        self.addCleanup(stdin.close)
        self.addCleanup(self._close_fd, read_fd)
        self.addCleanup(self._close_fd, write_fd)
        output = io.BytesIO()
        diagnostics = io.BytesIO()
        ended = []

        class FakeServer:
            server_port = 12345
            session_url = "http://127.0.0.1:12345/#session=test"
            app = SimpleNamespace(jobs=object(), nonce="test-only-bearer")

        with patch("cha_stabilizer.windows_pipe_reader._kernel32", side_effect=OSError("injected")):
            with patch.dict(os.environ):
                os.environ.pop("CHASTEADY_TEST_NONBLOCKING_STDIN", None)
                with self.assertRaisesRegex(OSError, "WinAPI initialization failed"):
                    run_desktop_protocol(
                        FakeServer(), "test-only-capability", stdin=stdin, stdout=output,
                        stderr=diagnostics, on_end=lambda: ended.append(True),
                    )
        self.assertEqual(output.getvalue(), b"")
        self.assertEqual(ended, [True])
        os.fstat(read_fd)

    def test_pipe_read_error_propagates_through_protocol_cleanup(self):
        from types import SimpleNamespace
        from ctypes import wintypes

        class FailingRead:
            def GetFileType(self, _handle):
                return 3

            def PeekNamedPipe(self, _handle, _buffer, _size, _read, total_available, _left):
                ctypes.cast(total_available, ctypes.POINTER(wintypes.DWORD)).contents.value = 1
                return True

            def ReadFile(self, _handle, _buffer, _size, _read, _overlapped):
                return False

        read_fd, write_fd = os.pipe()
        stdin = os.fdopen(read_fd, "rb", buffering=0, closefd=False)
        self.addCleanup(stdin.close)
        self.addCleanup(self._close_fd, read_fd)
        self.addCleanup(self._close_fd, write_fd)
        output = io.BytesIO()
        diagnostics = io.BytesIO()
        ended = []

        class FakeServer:
            server_port = 12345
            session_url = "http://127.0.0.1:12345/#session=test"
            app = SimpleNamespace(jobs=object(), nonce="test-only-bearer")

        with patch("cha_stabilizer.windows_pipe_reader._kernel32", return_value=FailingRead()):
            with patch("cha_stabilizer.windows_pipe_reader.ctypes.get_last_error", return_value=5):
                with self.assertRaisesRegex(OSError, "stdin pipe ReadFile failed"):
                    run_desktop_protocol(
                        FakeServer(), "test-only-capability", stdin=stdin, stdout=output,
                        stderr=diagnostics, on_end=lambda: ended.append(True),
                    )
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(messages[0]["type"], "ready")
        self.assertEqual(ended, [True])
        os.fstat(read_fd)


if __name__ == "__main__":
    unittest.main()
