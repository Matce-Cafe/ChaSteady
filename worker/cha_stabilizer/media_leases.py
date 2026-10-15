"""Read-handle leases for registered, verified H.264 preview artifacts."""
import os
import stat
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .paths import (
    UnsafePathError,
    _assert_no_reparse_components,
    _is_reparse,
    _normalized,
)


class MediaLeaseError(ValueError):
    """The requested artifact cannot be exposed to the native media player."""

    code = "media_lease_unavailable"
    message_key = "nativeMedia.error.leaseUnavailable"


class _OwnedReadHandle:
    def __init__(self, handle: int, *, windows: bool):
        self.handle = int(handle)
        self.windows = windows
        self._closed = False
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        return self.handle

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self.windows:
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel32.CloseHandle.restype = ctypes.c_int
                kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            else:
                os.close(self.handle)


class MediaLeaseRegistry:
    """Hold the exact verified artifact handle until native playback releases it."""

    MAX_LEASES = 32

    def __init__(self, job_store):
        self.job_store = job_store
        self._leases: Dict[str, Tuple[_OwnedReadHandle, Dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._closed = False

    def acquire(self, artifact_id: str) -> Dict[str, Any]:
        try:
            parsed = uuid.UUID(artifact_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise MediaLeaseError("The requested preview is unavailable.") from exc
        if str(parsed) != artifact_id:
            raise MediaLeaseError("The requested preview is unavailable.")
        with self._lock:
            if self._closed:
                raise MediaLeaseError("The native media service is shutting down.")
            if len(self._leases) >= self.MAX_LEASES:
                raise MediaLeaseError("Too many native media leases are active.")
            try:
                artifact, path, run_dir, inputs = self.job_store.get_artifact(
                    artifact_id, verified_preview=True
                )
            except (KeyError, OSError, ValueError, UnsafePathError) as exc:
                raise MediaLeaseError("Only a registered, verified preview can be opened natively.") from exc
            width, height, audio_present = _preview_metadata(artifact)
            try:
                handle, identity = _open_readonly_handle(path)
            except (OSError, ValueError, UnsafePathError) as exc:
                raise MediaLeaseError("The verified preview could not be opened safely.") from exc
            try:
                # Re-resolve the JobStore record after opening so a rename,
                # reparse swap, hard-link alias, or input alias cannot redirect
                # a handle between validation and the CreateFile/open call.
                try:
                    latest, latest_path, latest_run, latest_inputs = self.job_store.get_artifact(
                        artifact_id, verified_preview=True
                    )
                except (KeyError, OSError, ValueError, UnsafePathError) as exc:
                    raise MediaLeaseError("The registered preview changed while its handle was being opened.") from exc
                if (
                    _normalized(latest_path) != _normalized(path)
                    or _normalized(latest_run) != _normalized(run_dir)
                    or not _same_identity(identity, latest_path)
                    or not _same_preview(latest, artifact)
                    or len(latest_inputs) != len(inputs)
                    or any(_normalized(a) != _normalized(b) for a, b in zip(latest_inputs, inputs))
                ):
                    raise MediaLeaseError("The registered preview changed while its handle was being opened.")
                lease_id = str(uuid.uuid4())
                self._leases[lease_id] = (handle, identity)
                return {
                    "lease_id": lease_id,
                    "handle": handle.value,
                    "width": width,
                    "height": height,
                    "audio_present": audio_present,
                }
            except Exception:
                handle.close()
                raise

    def release(self, lease_id: str) -> bool:
        try:
            parsed = uuid.UUID(lease_id)
        except (ValueError, TypeError, AttributeError):
            return False
        if str(parsed) != lease_id:
            return False
        with self._lock:
            entry = self._leases.pop(lease_id, None)
        if entry is None:
            return False
        entry[0].close()
        return True

    def close_all(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            entries = list(self._leases.values())
            self._leases.clear()
        for handle, _identity in entries:
            handle.close()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._leases)


def _preview_metadata(artifact: Dict[str, Any]) -> Tuple[int, int, bool]:
    metadata = artifact.get("media_metadata")
    if not isinstance(metadata, dict):
        raise MediaLeaseError("Preview media metadata is unavailable.")
    width, height = metadata.get("width"), metadata.get("height")
    bit_depth = metadata.get("bit_depth")
    video_codec = metadata.get("video_codec")
    pixel_format = metadata.get("pixel_format")
    audio_codec = metadata.get("audio_codec")
    if (
        isinstance(width, bool) or not isinstance(width, int) or width < 2 or width > 8192 or width % 2
        or isinstance(height, bool) or not isinstance(height, int) or height < 2 or height > 8192 or height % 2
        or isinstance(bit_depth, bool) or bit_depth != 8
        or not isinstance(video_codec, str) or video_codec.casefold() not in ("h264", "avc")
        or pixel_format != "yuv420p"
        or (audio_codec is not None and (not isinstance(audio_codec, str) or audio_codec.casefold() != "aac"))
    ):
        raise MediaLeaseError("Native playback supports only 8-bit H.264/yuv420p with AAC or no audio.")
    return width, height, audio_codec is not None


def _same_preview(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in (
        "id", "kind", "mime", "validation_scope", "media_metadata"
    ))


def _windows_handle_identity_matches(
    stat_device: Any,
    stat_file: Any,
    legacy_volume: int,
    legacy_file_index: int,
    file_id_volume: Optional[int],
    file_id_128: Optional[bytes],
) -> bool:
    """Match CPython's pre-3.14 or 3.14+ Windows stat identity layouts."""
    try:
        devices = {int(legacy_volume)}
        file_indices = {int(legacy_file_index)}
        if file_id_volume is not None:
            devices.add(int(file_id_volume))
        if file_id_128 is not None and len(file_id_128) == 16:
            # CPython exposes the low 64 bits of FILE_ID_128 as st_ino.
            file_indices.add(int.from_bytes(file_id_128[:8], byteorder="little", signed=False))
        return int(stat_device) in devices and int(stat_file) in file_indices
    except (TypeError, ValueError, OverflowError):
        return False


def _same_identity(identity: Dict[str, Any], path: Path) -> bool:
    try:
        _assert_no_reparse_components(path)
        current = path.lstat()
    except (OSError, UnsafePathError):
        return False
    if not stat.S_ISREG(current.st_mode) or _is_reparse(current) or getattr(current, "st_nlink", 1) != 1:
        return False
    if (
        identity.get("device") != getattr(current, "st_dev", None)
        or identity.get("file") != getattr(current, "st_ino", None)
    ):
        return False
    if "legacy_volume" not in identity:
        return True
    return _windows_handle_identity_matches(
        current.st_dev,
        current.st_ino,
        identity["legacy_volume"],
        identity["legacy_file_index"],
        identity.get("file_id_volume"),
        identity.get("file_id_128"),
    )


def _open_readonly_handle(path: Path) -> Tuple[_OwnedReadHandle, Dict[str, Any]]:
    """Open without write/delete sharing, and compare the handle to its path."""
    path = Path(path)
    _assert_no_reparse_components(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or _is_reparse(before) or getattr(before, "st_nlink", 1) != 1:
        raise MediaLeaseError("Preview is not a single-link ordinary file.")
    if os.name == "nt":
        return _open_windows_handle(path, before)
    return _open_posix_handle(path, before)


def _open_posix_handle(path: Path, before: os.stat_result) -> Tuple[_OwnedReadHandle, Dict[str, Any]]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        _assert_no_reparse_components(path)
        opened = os.fstat(fd)
        current = path.lstat()
        identity = {"device": opened.st_dev, "file": opened.st_ino}
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or _is_reparse(current)
            or opened.st_nlink != 1
            or getattr(current, "st_nlink", 1) != 1
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise MediaLeaseError("Preview identity changed while its read handle was being opened.")
        return _OwnedReadHandle(fd, windows=False), identity
    except Exception:
        os.close(fd)
        raise


def _open_windows_handle(path: Path, before: os.stat_result) -> Tuple[_OwnedReadHandle, Dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("creation_time", FileTime),
            ("last_access_time", FileTime),
            ("last_write_time", FileTime),
            ("volume_serial", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    class FileId128(ctypes.Structure):
        _fields_ = [("identifier", ctypes.c_ubyte * 16)]

    class FileIdInfo(ctypes.Structure):
        _fields_ = [("volume_serial", ctypes.c_ulonglong), ("file_id", FileId128)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateFileW(
        str(path), 0x80000000, 0x00000001, None, 3, 0x00000080 | 0x00200000, None
    )  # GENERIC_READ; FILE_SHARE_READ only; OPEN_EXISTING; OPEN_REPARSE_POINT.
    invalid = ctypes.c_void_p(-1).value
    raw = handle.value if hasattr(handle, "value") else int(handle or 0)
    if not raw or raw == invalid:
        raise MediaLeaseError("The verified preview could not be opened as a protected read handle.")
    try:
        info = ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise MediaLeaseError("The preview handle identity could not be verified.")

        # Python 3.9 reports the legacy 32-bit volume serial in st_dev; newer
        # Windows runtimes expose FILE_ID_INFO's 64-bit volume serial. Keep the
        # legacy handle identity for controlled fallback and query the 128-bit
        # ID where the OS supports it.
        modern_info = FileIdInfo()
        has_modern_id = bool(kernel32.GetFileInformationByHandleEx(
            handle, 18, ctypes.byref(modern_info), ctypes.sizeof(modern_info)
        ))  # FileIdInfo
        file_id_volume = int(modern_info.volume_serial) if has_modern_id else None
        file_id_128 = bytes(modern_info.file_id.identifier) if has_modern_id else None
        legacy_volume = int(info.volume_serial)
        legacy_file_index = (int(info.file_index_high) << 32) | int(info.file_index_low)

        _assert_no_reparse_components(path)
        current = path.lstat()
        if (
            info.attributes & 0x00000400
            or info.number_of_links != 1
            or not stat.S_ISREG(current.st_mode)
            or _is_reparse(current)
            or getattr(current, "st_nlink", 1) != 1
            or int(getattr(before, "st_dev", -2)) != int(getattr(current, "st_dev", -1))
            or int(getattr(before, "st_ino", -2)) != int(getattr(current, "st_ino", -1))
            or not _windows_handle_identity_matches(
                current.st_dev, current.st_ino, legacy_volume, legacy_file_index,
                file_id_volume, file_id_128,
            )
        ):
            raise MediaLeaseError("Preview identity changed or has an unapproved filesystem alias.")
        identity = {
            "device": int(current.st_dev),
            "file": int(current.st_ino),
            "legacy_volume": legacy_volume,
            "legacy_file_index": legacy_file_index,
            "file_id_volume": file_id_volume,
            "file_id_128": file_id_128,
        }
        return _OwnedReadHandle(raw, windows=True), identity
    except Exception:
        kernel32.CloseHandle(handle)
        raise
