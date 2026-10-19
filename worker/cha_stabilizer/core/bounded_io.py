"""有界读取自有媒体子进程；不将全片帧 JSON 或日志一次装入内存。"""
import queue
import subprocess
import threading
import time

from .. import owned_processes as owners
from ..errors import AppError, CancelledError, NeedsReviewError


def consume_lines(command, on_line, cancel=None, *, timeout=1800.0, cwd=None,
                  max_line_bytes=16384, max_stdout_bytes=512 * 1024 ** 2,
                  max_stderr_bytes=1024 ** 2):
    registry = owners.get_active_registry()
    if registry is None:
        registry = owners.OwnedProcessRegistry(cancel)
        with owners.registry_scope(registry):
            try:
                return consume_lines(command, on_line, cancel, timeout=timeout, cwd=cwd,
                                     max_line_bytes=max_line_bytes, max_stdout_bytes=max_stdout_bytes,
                                     max_stderr_bytes=max_stderr_bytes)
            finally:
                if registry.snapshot():
                    registry.terminate_all()
    if cancel is not None and cancel.is_set():
        raise CancelledError("Media validation was cancelled before process creation.")
    process = owners.spawn_owned_process(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, bufsize=0, cwd=str(cwd) if cwd else None)
    chunks = queue.Queue(maxsize=32)
    stopping = threading.Event()

    def send(item):
        while not stopping.is_set():
            try:
                chunks.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def read_pipe(pipe, name):
        try:
            while not stopping.is_set():
                chunk = pipe.read(8192)
                if not chunk:
                    break
                send((name, chunk))
        except (OSError, ValueError):
            send(("error", name))
        finally:
            send((name, None))

    readers = [threading.Thread(target=read_pipe, args=(pipe, name), daemon=True,
                                name="bounded-media-" + name)
               for pipe, name in ((process.stdout, "stdout"), (process.stderr, "stderr"))]
    for reader in readers:
        reader.start()
    started = time.monotonic()
    pending = bytearray()
    stderr_tail = bytearray()
    stdout_bytes = stderr_bytes = 0
    ended = set()
    try:
        while len(ended) < 2 or process.poll() is None:
            if cancel is not None and cancel.is_set():
                raise CancelledError("Media validation was cancelled; only owned processes were stopped.")
            if time.monotonic() - started > timeout:
                raise NeedsReviewError("Media validation exceeded its bounded timeout; evidence was not accepted.")
            try:
                name, chunk = chunks.get(timeout=0.1)
            except queue.Empty:
                continue
            if name == "error":
                raise AppError("An owned media validation pipe could not be read.")
            if chunk is None:
                ended.add(name)
                continue
            if name == "stderr":
                stderr_bytes += len(chunk)
                if stderr_bytes > max_stderr_bytes:
                    raise NeedsReviewError("Media validation stderr exceeded its bounded byte budget.")
                stderr_tail.extend(chunk)
                if len(stderr_tail) > 65536:
                    del stderr_tail[:-65536]
                continue
            stdout_bytes += len(chunk)
            if stdout_bytes > max_stdout_bytes:
                raise NeedsReviewError("Media validation stdout exceeded its bounded byte budget.")
            pending.extend(chunk)
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    break
                if newline > max_line_bytes:
                    raise NeedsReviewError("Media validation emitted an oversized line.")
                line = bytes(pending[:newline]).rstrip(b"\r")
                del pending[:newline + 1]
                on_line(line)
            if len(pending) > max_line_bytes:
                raise NeedsReviewError("Media validation emitted an oversized line.")
        if pending:
            on_line(bytes(pending).rstrip(b"\r"))
        return {"returncode": process.returncode, "stderr": bytes(stderr_tail),
                "stdout_bytes": stdout_bytes, "stderr_bytes": stderr_bytes}
    finally:
        stopping.set()
        if process.poll() is None:
            registry.terminate_all()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            registry.terminate_all()
        for reader in readers:
            reader.join(timeout=2.0)
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        registry.discard(process)


def capture_small(command, cancel=None, *, timeout=60.0, max_bytes=2 * 1024 ** 2):
    data = bytearray()

    def append(line):
        if len(data) + len(line) + 1 > max_bytes:
            raise NeedsReviewError("Media metadata exceeded its bounded byte budget.")
        data.extend(line)
        data.extend(b"\n")

    result = consume_lines(command, append, cancel, timeout=timeout, max_line_bytes=max_bytes,
                           max_stdout_bytes=max_bytes)
    if result["returncode"]:
        raise NeedsReviewError("A configured media inspector returned an error.",
                               {"return_code": result["returncode"]})
    return bytes(data)
