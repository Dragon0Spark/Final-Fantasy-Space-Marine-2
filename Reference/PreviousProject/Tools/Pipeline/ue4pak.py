"""Minimal UE4 .pak reader/writer for Final Fantasy VII Remake Intergrade.

Reads the player's paks in place (index + single entries) and writes small
uncompressed mod paks for End/Content/Paks/~mods.
"""
from __future__ import annotations

import hashlib
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

PAK_MAGIC = 0x5A6F12E1
COMPRESS_ZLIB = 1
COMPRESS_OODLE = 4

_oodle = None


def use_oodle(dll_path: Path) -> None:
    """Load the game's own Oodle library (FF7R ships oo2core_7_win64.dll)."""
    global _oodle
    import ctypes
    lib = ctypes.WinDLL(str(dll_path))
    fn = lib.OodleLZ_Decompress
    fn.restype = ctypes.c_int64
    fn.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64,
                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int64,
                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int]
    _oodle = (ctypes, fn)


def _decompress(method: int, raw: bytes, out_size: int) -> bytes:
    if method == COMPRESS_ZLIB:
        return zlib.decompress(raw)
    if method == COMPRESS_OODLE:
        if _oodle is None:
            raise RuntimeError("Oodle block found: call use_oodle() with the game's oo2core dll")
        ctypes, fn = _oodle
        dst = ctypes.create_string_buffer(out_size)
        n = fn(raw, len(raw), dst, out_size, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if n != out_size:
            raise RuntimeError(f"Oodle returned {n}, expected {out_size}")
        return dst.raw
    raise ValueError(f"unsupported compression method {method}")


class Reader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self) -> int:
        v = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def raw(self, n: int) -> bytes:
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def fstring(self) -> str:
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            s = self.raw(-n * 2)
            return s.decode("utf-16-le").rstrip("\0")
        return self.raw(n).decode("utf-8", "replace").rstrip("\0")


@dataclass
class PakEntry:
    path: str
    offset: int
    size: int
    usize: int
    compression: int
    hash: bytes
    blocks: list[tuple[int, int]] = field(default_factory=list)
    encrypted: bool = False
    block_size: int = 0


@dataclass
class PakFile:
    path: Path
    version: int
    mount: str
    entries: dict[str, PakEntry]
    footer: dict


def _read_entry_header(r: Reader, version: int) -> PakEntry:
    offset = r.u64()
    size = r.u64()
    usize = r.u64()
    compression = r.u32()
    if version <= 1:
        r.u64()  # timestamp
    sha = r.raw(20)
    blocks = []
    if version >= 3:
        if compression != 0:
            count = r.u32()
            for _ in range(count):
                blocks.append((r.u64(), r.u64()))
        encrypted = r.u8() != 0
        block_size = r.u32()
    else:
        encrypted = False
        block_size = 0
    return PakEntry("", offset, size, usize, compression, sha, blocks, encrypted, block_size)


def read_footer(path: Path) -> dict:
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        end = fh.tell()
        tail_len = min(end, 512)
        fh.seek(end - tail_len)
        tail = fh.read(tail_len)
    # Find the magic scanning from the end (footer size differs by version).
    for back in range(44, tail_len + 1):
        at = tail_len - back
        if struct.unpack_from("<I", tail, at)[0] == PAK_MAGIC:
            version, index_offset, index_size = struct.unpack_from("<IQQ", tail, at + 4)
            if 1 <= version <= 12 and index_offset < end:
                pre = tail[:at]
                return {
                    "magic_at": end - back,
                    "version": version,
                    "index_offset": index_offset,
                    "index_size": index_size,
                    "hash": tail[at + 24:at + 44].hex(),
                    "after": tail[at + 44:].hex(),
                    "before": pre[-21:].hex(),
                    "file_size": end,
                }
    raise ValueError(f"no pak footer in {path}")


def _encrypted_index(footer: dict) -> bool:
    return footer["version"] >= 4 and footer["before"][-2:] == "01"


def open_pak(path: Path, aes=None) -> PakFile:
    """Read a pak's index; `aes` (an object with .decrypt) is needed for encrypted indexes."""
    footer = read_footer(path)
    with open(path, "rb") as fh:
        fh.seek(footer["index_offset"])
        index = fh.read(footer["index_size"])
    if _encrypted_index(footer):
        if aes is None:
            raise ValueError(f"{path.name} has an encrypted index")
        index = aes.decrypt(index)
    r = Reader(index)
    mount = r.fstring()
    count = r.u32()
    entries: dict[str, PakEntry] = {}
    for _ in range(count):
        name = r.fstring()
        e = _read_entry_header(r, footer["version"])
        e.path = name
        entries[name] = e
    return PakFile(path, footer["version"], mount, entries, footer)


def _align16(n: int) -> int:
    return (n + 15) & ~15


def read_entry(pak: PakFile, entry: PakEntry, aes=None) -> bytes:
    if entry.encrypted and aes is None:
        raise ValueError(f"{entry.path} is encrypted")
    with open(pak.path, "rb") as fh:
        header_size = 8 * 3 + 4 + 20 + (8 if pak.version <= 1 else 0)
        if pak.version >= 3:
            header_size += (4 + 16 * len(entry.blocks) if entry.compression else 0) + 1 + 4
        data_start = entry.offset + header_size
        if entry.compression == 0:
            fh.seek(data_start)
            raw = fh.read(_align16(entry.size) if entry.encrypted else entry.size)
            if entry.encrypted:
                raw = aes.decrypt(raw)[:entry.size]
            return raw
        out = bytearray()
        remaining = entry.usize
        for start, stop in entry.blocks:
            # Block offsets are relative to the entry start from v5 on.
            base = entry.offset if pak.version >= 5 else 0
            fh.seek(base + start)
            size = stop - start
            raw = fh.read(_align16(size) if entry.encrypted else size)
            if entry.encrypted:
                raw = aes.decrypt(raw)[:size]
            block_out = min(entry.block_size or remaining, remaining)
            out += _decompress(entry.compression, raw, block_out)
            remaining -= block_out
        return bytes(out)


def write_pak(out_path: Path, mount: str, files: dict[str, bytes], version: int) -> None:
    """Write an uncompressed, unencrypted pak (entry paths relative to mount)."""
    body = bytearray()
    records = []
    for name, data in files.items():
        sha = hashlib.sha1(data).digest()
        offset = len(body)
        header = struct.pack("<QQQI", 0, len(data), len(data), 0)
        if version <= 1:
            header += struct.pack("<Q", 0)
        header += sha
        if version >= 3:
            header += struct.pack("<BI", 0, 0)
        body += header + data
        records.append((name, offset, len(data), sha))
    index = bytearray()
    m = mount.encode("utf-8") + b"\0"
    index += struct.pack("<i", len(m)) + m
    index += struct.pack("<I", len(records))
    for name, offset, size, sha in records:
        n = name.encode("utf-8") + b"\0"
        index += struct.pack("<i", len(n)) + n
        index += struct.pack("<QQQI", offset, size, size, 0)
        if version <= 1:
            index += struct.pack("<Q", 0)
        index += sha
        if version >= 3:
            index += struct.pack("<BI", 0, 0)
    footer = bytearray()
    if version >= 7:
        footer += b"\0" * 16  # encryption key guid
    if version >= 4:
        footer += b"\0"  # index not encrypted
    footer += struct.pack("<IIQQ", PAK_MAGIC, version, len(body), len(index))
    footer += hashlib.sha1(index).digest()
    if version >= 8:
        footer += b"\0" * (32 * 5 if version > 8 else 32 * 4)  # compression method names
    out_path.write_bytes(bytes(body + index + footer))


if __name__ == "__main__":
    p = Path(sys.argv[1])
    f = read_footer(p)
    print(f)
