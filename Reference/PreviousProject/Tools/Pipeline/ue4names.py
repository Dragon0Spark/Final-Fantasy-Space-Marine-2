"""UE 4.18 FNameEntrySerialized hashes, so renamed or added names load like cooked ones.

NonCasePreservingHash = FCrc::Strihash_DEPRECATED(name) & 0xFFFF
CasePreservingHash    = FCrc::StrCrc32(name) & 0xFFFF
Stored as two little-endian uint16 after each name.
"""
from __future__ import annotations

import struct


def _table(poly: int) -> list[int]:
    out = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ poly if crc & 1 else crc >> 1
        out.append(crc & 0xFFFFFFFF)
    return out


def _table_msb(poly: int) -> list[int]:
    out = []
    for i in range(256):
        crc = i << 24
        for _ in range(8):
            crc = ((crc << 1) ^ poly) if crc & 0x80000000 else (crc << 1)
        out.append(crc & 0xFFFFFFFF)
    return out


_CRC32_LSB = _table(0xEDB88320)          # FCrc::CRCTablesSB8[0]
_CRC32_DEPRECATED = _table_msb(0x04C11DB7)  # FCrc::CRCTable_DEPRECATED


def _upper(ch: int) -> int:
    return ch - 32 if 97 <= ch <= 122 else ch


def strihash_deprecated(name: str) -> int:
    h = 0
    for c in name:
        ch = _upper(ord(c))
        h = ((h >> 8) & 0x00FFFFFF) ^ _CRC32_DEPRECATED[(h ^ ch) & 0xFF]
    return h & 0xFFFFFFFF


def strcrc32(name: str) -> int:
    crc = 0xFFFFFFFF
    for c in name:
        ch = ord(c)
        for _ in range(4):
            crc = (crc >> 8) ^ _CRC32_LSB[(crc ^ ch) & 0xFF]
            ch >>= 8
    return (~crc) & 0xFFFFFFFF


def name_hash_bytes(name: str) -> bytes:
    return struct.pack("<HH", strihash_deprecated(name) & 0xFFFF, strcrc32(name) & 0xFFFF)
