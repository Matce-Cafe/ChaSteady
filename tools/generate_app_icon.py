"""Generate an original steady-frame icon using only the Python standard library."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import uuid
import zlib


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "ui/windows/runner/resources/app_icon.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def rounded_rectangle(x, y, left, top, right, bottom, radius):
    if not left <= x <= right or not top <= y <= bottom:
        return False
    cx = min(max(x, left + radius), right - radius)
    cy = min(max(y, top + radius), bottom - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def frame(x, y, offset_x=0, offset_y=0):
    x -= offset_x
    y -= offset_y
    return (rounded_rectangle(x, y, .20, .20, .80, .80, .10)
            and not rounded_rectangle(x, y, .25, .25, .75, .75, .06))


def pixel(x, y):
    if (abs(x - .5) / .455) ** 4 + (abs(y - .5) / .455) ** 4 > 1:
        return (0, 0, 0, 0)
    if frame(x, y):
        return (245, 250, 248, 255)
    if (x - .5) ** 2 + (y - .5) ** 2 <= .085 ** 2:
        return (153, 239, 207, 255)
    if frame(x, y, -.055, .045):
        return (56, 106, 90, 255)
    return (19, 48, 44, 255)


def png_chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def png(size):
    samples = 4
    data = bytearray()
    for row in range(size):
        data.append(0)
        for column in range(size):
            red = green = blue = alpha = 0
            for sy in range(samples):
                for sx in range(samples):
                    r, g, b, a = pixel((column + (sx + .5) / samples) / size,
                                       (row + (sy + .5) / samples) / size)
                    red += r * a
                    green += g * a
                    blue += b * a
                    alpha += a
            rgba = (round(red / alpha), round(green / alpha), round(blue / alpha),
                    round(alpha / (samples * samples))) if alpha else (0, 0, 0, 0)
            data.extend(rgba)
    return (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(bytes(data), 9))
            + png_chunk(b"IEND", b""))


def main():
    images = [png(size) for size in SIZES]
    offset = 6 + 16 * len(images)
    entries = bytearray()
    for size, image in zip(SIZES, images):
        entries.extend(struct.pack("<BBBBHHII", size if size < 256 else 0,
                                   size if size < 256 else 0, 0, 0, 1, 32, len(image), offset))
        offset += len(image)
    payload = struct.pack("<HHH", 0, 1, len(images)) + entries + b"".join(images)
    backup = ROOT / "private" / ("app-icon-" + uuid.uuid4().hex)
    backup.mkdir()
    previous_hash = None
    if TARGET.exists():
        previous = TARGET.read_bytes()
        if len(previous) < 6 or struct.unpack("<HH", previous[:4]) != (0, 1):
            raise RuntimeError("Existing resource is not a Windows icon; refusing to replace")
        previous_hash = hashlib.sha256(previous).hexdigest()
        shutil.copyfile(TARGET, backup / "previous-app-icon.ico")
    temporary = TARGET.with_name("app_icon." + uuid.uuid4().hex + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
    temporary.replace(TARGET)
    manifest = {"generator": "tools/generate_app_icon.py", "original_project_artwork": True,
                "external_artwork_or_service_used": False, "sizes": SIZES,
                "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
                "previous_sha256": previous_hash, "backup": str(backup.relative_to(ROOT))}
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
