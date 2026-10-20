"""Draw the Woof Cleaner paw icon and write assets/woof.ico (pure standard library)."""
import struct
import sys
import zlib
from pathlib import Path

ORANGE = (201, 111, 45)
WHITE = (255, 255, 255)
SS = 4  # supersampling factor for anti-aliasing

# (cx, cy, rx, ry, colour) in unit coordinates; later shapes paint over earlier ones
SHAPES = [
    (0.50, 0.50, 0.48, 0.48, ORANGE),
    (0.50, 0.64, 0.18, 0.145, WHITE),
    (0.285, 0.43, 0.075, 0.095, WHITE),
    (0.415, 0.30, 0.078, 0.10, WHITE),
    (0.585, 0.30, 0.078, 0.10, WHITE),
    (0.715, 0.43, 0.075, 0.095, WHITE),
]


def render(size: int) -> bytes:
    n = size * SS
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter: none
        for x in range(size):
            r = g = b = a = 0
            for sy in range(SS):
                fy = (y * SS + sy + 0.5) / n
                for sx in range(SS):
                    fx = (x * SS + sx + 0.5) / n
                    col = None
                    for cx, cy, rx, ry, c in SHAPES:
                        if ((fx - cx) / rx) ** 2 + ((fy - cy) / ry) ** 2 <= 1:
                            col = c
                    if col:
                        r += col[0]; g += col[1]; b += col[2]; a += 255
            k = SS * SS
            cov = a // k
            if cov:
                rows += bytes((r * 255 // a, g * 255 // a, b * 255 // a, cov))
            else:
                rows += b"\0\0\0\0"
    return png(size, bytes(rows))


def png(size: int, raw: bytes) -> bytes:
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(sizes):
    images = [render(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(images)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "assets" / "woof.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(ico([16, 24, 32, 48, 64, 128, 256]))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
