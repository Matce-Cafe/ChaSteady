"""Nonblocking polling reader for a borrowed Windows stdin pipe HANDLE."""
import ctypes
import io
import os
import time


FILE_TYPE_PIPE = 3
_READ_CHUNK_BYTES = 4096
_IDLE_SLEEP_SECONDS = 0.01
_EOF_ERRORS = frozenset((38, 109, 232, 233))  # HANDLE_EOF, BROKEN_PIPE, NO_DATA, PIPE_NOT_CONNECTED


def _kernel32():
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    kernel32.GetFileType.restype = wintypes.DWORD
    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    return kernel32


class WindowsPipeReader:
    """Expose bounded ``readline`` semantics without owning/closing the HANDLE."""

    def __init__(self, handle, max_buffer, *, kernel32=None, get_last_error=None,
                 idle_sleep=_IDLE_SLEEP_SECONDS, owner=None):
        if os.name != "nt":
            raise OSError("Windows stdin pipe reader is unavailable on this platform")
        if isinstance(max_buffer, bool) or not isinstance(max_buffer, int) or max_buffer <= 0:
            raise ValueError("max_buffer must be a positive integer")
        self._handle_value = int(handle)
        if self._handle_value <= 0:
            raise ValueError("borrowed stdin pipe handle is invalid")
        self._max_buffer = max_buffer
        self._buffer = bytearray()
        self._eof = False
        self._idle_sleep = max(0.0, float(idle_sleep))
        self._kernel32 = kernel32 or _kernel32()
        self._get_last_error = get_last_error or ctypes.get_last_error
        self._owner = owner  # Keep the borrowed file object alive; never close it.

    @classmethod
    def from_file_object(cls, stream, max_buffer, *, idle_sleep=_IDLE_SLEEP_SECONDS):
        """Return a reader for a genuine pipe, otherwise None without taking ownership.

        A stream without a file descriptor (for example ``BytesIO``) and known
        non-pipe Windows handles keep their existing ``readline`` behavior.
        Once a valid Windows descriptor is present, WinAPI detection/initialization
        errors are surfaced instead of silently selecting a potentially blocking
        reader for a pipe.
        """
        if os.name != "nt":
            return None
        if isinstance(stream, int):
            descriptor = stream
            owner = None
        else:
            try:
                descriptor = stream.fileno()
            except (AttributeError, io.UnsupportedOperation, ValueError):
                return None
            owner = stream
        if isinstance(descriptor, bool) or not isinstance(descriptor, int):
            raise OSError("standard input descriptor is unavailable")
        try:
            import msvcrt
        except ImportError as exc:
            raise OSError("standard input WinAPI initialization failed") from exc
        try:
            handle = msvcrt.get_osfhandle(descriptor)
        except (OSError, TypeError, ValueError) as exc:
            raise OSError("standard input handle lookup failed") from exc
        if handle in (-1, 0, None):
            raise OSError("standard input handle is invalid")
        try:
            kernel32 = _kernel32()
        except Exception as exc:
            raise OSError("standard input WinAPI initialization failed") from exc
        from ctypes import wintypes

        try:
            file_type = int(kernel32.GetFileType(wintypes.HANDLE(handle)))
        except Exception as exc:
            raise OSError("standard input file type query failed") from exc
        if file_type == 0:  # FILE_TYPE_UNKNOWN; do not risk a blocking fallback.
            error = ctypes.get_last_error()
            raise OSError(error, "standard input file type query failed")
        if file_type != FILE_TYPE_PIPE:
            return None
        # After FILE_TYPE_PIPE is established, any reader initialization failure
        # must propagate. Runtime PeekNamedPipe/ReadFile errors likewise surface
        # from readline(), while the protocol's finally block still owns cleanup.
        return cls(handle, max_buffer, kernel32=kernel32, idle_sleep=idle_sleep, owner=owner)

    @property
    def buffered_bytes(self):
        return len(self._buffer)

    def _peek_available(self):
        from ctypes import wintypes

        available = wintypes.DWORD()
        ok = self._kernel32.PeekNamedPipe(
            wintypes.HANDLE(self._handle_value), None, 0, None, ctypes.byref(available), None,
        )
        if ok:
            return int(available.value)
        error = self._get_last_error()
        if error in _EOF_ERRORS:
            self._eof = True
            return 0
        raise OSError(error, "stdin pipe PeekNamedPipe failed")

    def _read_available(self, remaining_limit):
        from ctypes import wintypes

        available = self._peek_available()
        if available <= 0:
            if not self._eof and self._idle_sleep:
                time.sleep(self._idle_sleep)
            return
        capacity = min(self._max_buffer - len(self._buffer), remaining_limit, _READ_CHUNK_BYTES)
        count = min(available, capacity)
        if count <= 0:
            return
        output = ctypes.create_string_buffer(count)
        bytes_read = wintypes.DWORD()
        ok = self._kernel32.ReadFile(
            wintypes.HANDLE(self._handle_value), output, count, ctypes.byref(bytes_read), None,
        )
        if not ok:
            error = self._get_last_error()
            if error in _EOF_ERRORS:
                self._eof = True
                return
            raise OSError(error, "stdin pipe ReadFile failed")
        received = min(int(bytes_read.value), count)
        if received == 0:
            self._eof = True
            return
        self._buffer.extend(output.raw[:received])

    def _take(self, count):
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result

    def readline(self, size=-1):
        if size is None or size < 0:
            limit = self._max_buffer
        else:
            limit = min(int(size), self._max_buffer)
        if limit <= 0:
            return b""

        while True:
            newline = self._buffer.find(b"\n", 0, min(len(self._buffer), limit))
            if newline >= 0:
                return self._take(newline + 1)
            if len(self._buffer) >= limit:
                return self._take(limit)
            if self._eof:
                if self._buffer:
                    return self._take(min(len(self._buffer), limit))
                return b""
            self._read_available(limit - len(self._buffer))
