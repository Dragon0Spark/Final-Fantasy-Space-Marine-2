"""Find the pak AES key inside the player's own FF7R executable (no key is shipped).

The key is proved by decrypting the pak index: it must start with the mount point "../../../".
AES runs through Windows CNG (bcrypt.dll), so no third-party crypto package is needed.
"""
from __future__ import annotations

import ctypes
import re
import struct
import sys
from ctypes import wintypes
from pathlib import Path

_bcrypt = ctypes.WinDLL("bcrypt")
_BCRYPT_ALG = ctypes.c_void_p
_BCRYPT_KEY = ctypes.c_void_p


def _check(status: int, what: str) -> None:
    if status != 0:
        raise OSError(f"{what} failed: NTSTATUS {status & 0xFFFFFFFF:#x}")


class AesEcb:
    """AES-256-ECB decryptor backed by Windows CNG."""

    _alg = None

    def __init__(self, key: bytes) -> None:
        if AesEcb._alg is None:
            alg = _BCRYPT_ALG()
            _check(_bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(alg), "AES", None, 0), "open AES")
            mode = ctypes.create_unicode_buffer("ChainingModeECB")
            _check(_bcrypt.BCryptSetProperty(alg, "ChainingMode", mode, ctypes.sizeof(mode), 0),
                   "set ECB")
            AesEcb._alg = alg
        self._key = _BCRYPT_KEY()
        self._key_bytes = ctypes.create_string_buffer(key, len(key))
        _check(_bcrypt.BCryptGenerateSymmetricKey(AesEcb._alg, ctypes.byref(self._key), None, 0,
                                                  self._key_bytes, len(key), 0), "make key")

    def decrypt(self, data: bytes) -> bytes:
        assert len(data) % 16 == 0
        src = ctypes.create_string_buffer(data, len(data))
        dst = ctypes.create_string_buffer(len(data))
        out_len = wintypes.ULONG()
        _check(_bcrypt.BCryptDecrypt(self._key, src, len(data), None, None, 0, dst, len(data),
                                     ctypes.byref(out_len), 0), "decrypt")
        return dst.raw[:out_len.value]

    def close(self) -> None:
        if self._key:
            _bcrypt.BCryptDestroyKey(self._key)
            self._key = _BCRYPT_KEY()


def _index_probe(pak: Path) -> bytes:
    """First 16 bytes of the (encrypted) pak index."""
    from ue4pak import read_footer
    footer = read_footer(pak)
    with open(pak, "rb") as fh:
        fh.seek(footer["index_offset"])
        return fh.read(16)


def _looks_like_index(block: bytes) -> bool:
    n = struct.unpack_from("<i", block)[0]
    return 4 <= n <= 256 and block[4:13] == b"../../../"


def _mov_imm_candidates(code: bytes):
    """Keys stored as eight `mov dword [reg+disp], imm32` instructions (UE 4.20+ callbacks)."""
    pat = re.compile(rb"\xC7(?:\x45.|\x44\x24.|\x40.|\x41.|\x01)(.{4})", re.S)
    hits = [(m.start(), m.group(1)) for m in pat.finditer(code)]
    for i in range(len(hits) - 7):
        window = hits[i:i + 8]
        if window[-1][0] - window[0][0] <= 8 * 9:
            yield b"".join(h[1] for h in window)


def _string_candidates(data: bytes):
    """Pre-4.20 keys compiled in as a 32-character ANSI string."""
    for m in re.finditer(rb"(?<![\x21-\x7e])([\x21-\x7e]{32})\x00", data):
        yield m.group(1)
    for m in re.finditer(rb"0x([0-9A-Fa-f]{64})", data):
        yield bytes.fromhex(m.group(1).decode())


def find_key(exe: Path, pak: Path) -> bytes | None:
    probe = _index_probe(pak)
    data = exe.read_bytes()
    seen = set()
    for source in (_mov_imm_candidates(data), _string_candidates(data)):
        for cand in source:
            if cand in seen:
                continue
            seen.add(cand)
            aes = AesEcb(cand)
            try:
                if _looks_like_index(aes.decrypt(probe)):
                    return cand
            finally:
                aes.close()
    return None


if __name__ == "__main__":
    game = Path(sys.argv[1])
    key = find_key(game / "End/Binaries/Win64/ff7remake_.exe",
                   game / "End/Content/Paks/pakchunk0-WindowsNoEditor.pak")
    print("key found" if key else "key NOT found")
