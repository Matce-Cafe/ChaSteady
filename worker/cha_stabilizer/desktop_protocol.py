"""Private, line-oriented bootstrap protocol for the native Windows supervisor."""
import io
import json
import os
import re
import secrets
import sys
from typing import Any, Dict, Optional

from .errors import typed_error_message
from .media_leases import MediaLeaseError, MediaLeaseRegistry


PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 1024 * 1024
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ACTION_FIELDS = {
    "web_session": frozenset(),
    "acquire_media": frozenset(("artifact_id",)),
    "release_media": frozenset(("lease_id",)),
    "shutdown": frozenset(),
}


class _ProtocolFatal(ValueError):
    pass


def _default_stream(name: str, standard_handle: int, flags: int, mode: str, *, optional: bool = False):
    stream = getattr(sys, name, None)
    if stream is not None:
        binary = getattr(stream, "buffer", stream)
        if binary is not None:
            return binary
    if os.name != "nt":
        return None
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        handle = kernel32.GetStdHandle(standard_handle)
        raw = handle.value if hasattr(handle, "value") else int(handle or 0)
        if not raw or raw == ctypes.c_void_p(-1).value:
            raise OSError("standard pipe is unavailable")
        fd = msvcrt.open_osfhandle(raw, flags | getattr(os, "O_BINARY", 0))
        return os.fdopen(fd, mode, buffering=0)
    except (AttributeError, ImportError, OSError, ValueError):
        if optional:
            return None
        raise OSError("desktop worker {} pipe is unavailable".format(name))


def new_native_capability() -> str:
    """Create a private process-local capability; callers must never persist it."""
    return secrets.token_urlsafe(48)


def run_desktop_protocol(
    server,
    capability: str,
    *,
    stdin=None,
    stdout=None,
    stderr=None,
    on_end=None,
) -> None:
    """Emit ready, dispatch strict requests, and release every media lease on EOF."""
    stdin = stdin if stdin is not None else _default_stream("stdin", 0xFFFFFFF6, os.O_RDONLY, "rb")
    stdout = stdout if stdout is not None else _default_stream("stdout", 0xFFFFFFF5, os.O_WRONLY, "wb")
    stderr = stderr if stderr is not None else _default_stream("stderr", 0xFFFFFFF4, os.O_WRONLY, "wb", optional=True)
    if stdout is None:
        raise OSError("desktop worker stdout pipe is unavailable")
    if stdin is None:
        stdin = io.BytesIO()
    leases = MediaLeaseRegistry(server.app.jobs)
    try:
        from .windows_pipe_reader import WindowsPipeReader

        pipe_reader = WindowsPipeReader.from_file_object(stdin, MAX_REQUEST_BYTES + 2)
        if pipe_reader is not None:
            stdin = pipe_reader
        ready = {
            "type": "ready",
            "protocol": PROTOCOL_VERSION,
            "pid": int(os.getpid()),
            "origin": "http://127.0.0.1:{}".format(int(server.server_port)),
            "bearer": str(server.app.nonce),
            "native_capability": capability,
        }
        _write_json_line(stdout, ready)
        while True:
            try:
                raw = _read_bounded_line(stdin)
            except _ProtocolFatal:
                _write_diagnostic(stderr, "Desktop protocol input rejected; closing the private session.")
                break
            if raw is None:
                break
            try:
                request = _parse_request(raw)
            except _ProtocolFatal:
                _write_diagnostic(stderr, "Desktop protocol request rejected; closing the private session.")
                break
            request_id = request["request_id"]
            response = _dispatch(server, leases, request, capability)
            response["request_id"] = request_id
            try:
                _write_json_line(stdout, response)
            except (BrokenPipeError, OSError):
                break
            if request.get("action") == "shutdown" and response.get("ok") is True:
                break
    finally:
        leases.close_all()
        if on_end is not None:
            on_end()


def _read_bounded_line(stream) -> Optional[bytes]:
    raw = stream.readline(MAX_REQUEST_BYTES + 2)
    if raw in (b"", ""):
        return None
    if isinstance(raw, str):
        try:
            encoded = raw.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise _ProtocolFatal("input is not UTF-8") from exc
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise _ProtocolFatal("unsupported stdin stream")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise _ProtocolFatal("request is too large")
    if not encoded.endswith(b"\n"):
        # stdin is a line protocol. A short final line is still parsed at EOF;
        # readline's bounded length ensures it cannot allocate an unbounded line.
        if len(encoded) > MAX_REQUEST_BYTES:
            raise _ProtocolFatal("request is too large")
    if encoded.endswith(b"\n"):
        encoded = encoded[:-1]
        if encoded.endswith(b"\r"):
            encoded = encoded[:-1]
    if b"\n" in encoded or b"\r" in encoded:
        raise _ProtocolFatal("one JSON value is required per line")
    if not encoded:
        raise _ProtocolFatal("empty request")
    return encoded


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _ProtocolFatal("duplicate JSON object key")
        value[key] = item
    return value


def _reject_constant(value):
    raise _ProtocolFatal("non-finite JSON number")


def _parse_request(raw: bytes) -> Dict[str, Any]:
    try:
        request = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _ProtocolFatal) as exc:
        raise _ProtocolFatal("invalid JSON") from exc
    if not isinstance(request, dict):
        raise _ProtocolFatal("request must be an object")
    request_id = request.get("request_id")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise _ProtocolFatal("invalid request_id")
    return request


def _dispatch(server, leases: MediaLeaseRegistry, request: Dict[str, Any], capability: str) -> Dict[str, Any]:
    request_id = request["request_id"]
    action = request.get("action")
    common_fields = {"protocol", "request_id", "capability", "action"}
    known_action = isinstance(action, str) and action in _ACTION_FIELDS
    expected = common_fields | (set(_ACTION_FIELDS[action]) if known_action else set())
    if set(request) != expected:
        return _error_response(request_id, "invalid_request", "The desktop request contains missing or unsupported fields.")
    supplied = request.get("capability")
    if (
        not isinstance(supplied, str)
        or len(supplied) > 256
        or not supplied.isascii()
        or not secrets.compare_digest(supplied, capability)
    ):
        return _error_response(request_id, "unauthorized", "The desktop capability is invalid.")
    version = request.get("protocol")
    if isinstance(version, bool) or not isinstance(version, int) or version != PROTOCOL_VERSION:
        return _error_response(request_id, "unsupported_protocol", "The desktop protocol version is not supported.")
    if not known_action:
        return _error_response(request_id, "unsupported_action", "The requested desktop action is not supported.")
    if action == "web_session":
        return {"protocol": PROTOCOL_VERSION, "ok": True, "result": {"url": server.session_url}}
    if action == "acquire_media":
        artifact_id = request.get("artifact_id")
        if not isinstance(artifact_id, str):
            return _error_response(request_id, "invalid_request", "artifact_id must be a registered artifact UUID.")
        try:
            result = leases.acquire(artifact_id)
        except MediaLeaseError as exc:
            return _error_response(request_id, exc.code, str(exc), message_key=exc.message_key)
        return {"protocol": PROTOCOL_VERSION, "ok": True, "result": result}
    if action == "release_media":
        lease_id = request.get("lease_id")
        if not isinstance(lease_id, str):
            return _error_response(request_id, "invalid_request", "lease_id must be a worker-issued UUID.")
        return {
            "protocol": PROTOCOL_VERSION,
            "ok": True,
            "result": {"released": leases.release(lease_id)},
        }
    return {"protocol": PROTOCOL_VERSION, "ok": True, "result": {"shutting_down": True}}


def _error_response(
    request_id: str,
    code: str,
    message: str,
    *,
    message_key: Optional[str] = None,
    args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    typed = typed_error_message(code, message)
    key = message_key or (typed[0] if typed else "nativeProtocol.error.generic")
    typed_args = args if args is not None else (typed[1] if typed else {})
    error = {"code": code, "message_key": key, "message": message, "args": dict(typed_args)}
    return {"protocol": PROTOCOL_VERSION, "request_id": request_id, "ok": False, "error": error}


def _write_json_line(stream, payload: Dict[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    try:
        stream.write(encoded)
    except TypeError:
        stream.write(encoded.decode("utf-8"))
    stream.flush()


def _write_diagnostic(stream, message: str) -> None:
    if stream is None:
        return
    data = (message + "\n").encode("utf-8")
    try:
        stream.write(data)
    except TypeError:
        stream.write(data.decode("utf-8"))
    try:
        stream.flush()
    except (AttributeError, OSError):
        pass
