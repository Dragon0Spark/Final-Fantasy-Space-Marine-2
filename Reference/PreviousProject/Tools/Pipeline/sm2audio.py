"""Space Marine 2 sounds → WAV, read from the player's own banks (Wwise .bnk + streamed .wem zips).

Event names are hashed (FNV-1, 32-bit, lowercase) to find the Event in the bank's HIRC, then followed
through Play actions and containers down to Sound objects and their media ids. Media comes from the
bank itself (DIDX/DATA) or from the bank's streamed zip; voice lines are named external sources.
Decoding uses vgmstream-cli (bundled, ISC-style license).
"""
from __future__ import annotations

import struct
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

HIRC_SOUND = 2
HIRC_ACTION = 3
HIRC_EVENT = 4
PARENT_ZONE = 24  # bytes of NodeBaseParams that hold FX flags, bus and parent ids


def fnv1_32(name: str) -> int:
    h = 2166136261
    for b in name.lower().encode("ascii"):
        h = (h * 16777619) & 0xFFFFFFFF
        h ^= b
    return h


@dataclass
class Bank:
    version: int
    objects: dict[int, tuple[int, bytes]] = field(default_factory=dict)  # id → (type, body)
    media: dict[int, bytes] = field(default_factory=dict)                 # embedded wem by id


def parse_bank(data: bytes) -> Bank:
    pos = 0
    bank = Bank(0)
    didx: list[tuple[int, int, int]] = []
    data_chunk = b""
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + size]
        if tag == b"BKHD":
            bank.version = struct.unpack_from("<I", body, 0)[0]
        elif tag == b"DIDX":
            didx = [struct.unpack_from("<III", body, i) for i in range(0, len(body), 12)]
        elif tag == b"DATA":
            data_chunk = body
        elif tag == b"HIRC":
            count = struct.unpack_from("<I", body, 0)[0]
            p = 4
            for _ in range(count):
                otype = body[p]
                osize = struct.unpack_from("<I", body, p + 1)[0]
                oid = struct.unpack_from("<I", body, p + 5)[0]
                bank.objects[oid] = (otype, body[p + 9:p + 5 + osize])
                p += 5 + osize
        pos += 8 + size
    for mid, off, size in didx:
        bank.media[mid] = data_chunk[off:off + size]
    return bank


def _event_actions(bank: Bank, body: bytes) -> list[int]:
    # Event: action count is a u8 in recent Wwise versions (>= 122), u32 before.
    if bank.version >= 122:
        n = body[0]
        return list(struct.unpack_from(f"<{n}I", body, 1))
    n = struct.unpack_from("<I", body, 0)[0]
    return list(struct.unpack_from(f"<{n}I", body, 4))


def _sound_media(body: bytes) -> tuple[int, int]:
    """(stream type, source id) of a Sound object's AkBankSourceData."""
    stream_type = body[4]
    source_id = struct.unpack_from("<I", body, 5)[0]
    return stream_type, source_id


def resolve_event(bank: Bank, event_name: str, depth: int = 6) -> list[tuple[int, int]]:
    """Media (stream type, id) reachable from an event: Play actions → containers → sounds."""
    eid = fnv1_32(event_name)
    obj = bank.objects.get(eid)
    if obj is None or obj[0] != HIRC_EVENT:
        return []
    found: list[tuple[int, int]] = []
    seen: set[int] = set()

    def visit(oid: int, d: int) -> None:
        if oid in seen or d < 0 or oid not in bank.objects:
            return
        seen.add(oid)
        otype, body = bank.objects[oid]
        if otype == HIRC_SOUND:
            found.append(_sound_media(body))
            return
        if otype == HIRC_ACTION:
            action_type = struct.unpack_from("<H", body, 0)[0]
            if action_type >> 8 == 0x04:  # Play
                visit(struct.unpack_from("<I", body, 2)[0], d - 1)
            return
        # Containers list their children as plain 32-bit ids after NodeBaseParams; the first bytes
        # hold the container's own parent (DirectParentID), which must not be followed.
        for i in range(PARENT_ZONE, len(body) - 3):
            cid = struct.unpack_from("<I", body, i)[0]
            if cid != oid and cid in bank.objects and bank.objects[cid][0] in (HIRC_SOUND, 5, 6, 9):
                visit(cid, d - 1)

    for aid in _event_actions(bank, obj[1]):
        visit(aid, depth)
    return found


class SM2Sounds:
    """Locates banks, streamed media and voice files in the player's SM2 sound paks."""

    def __init__(self, sm2_root: Path, language: str = "english") -> None:
        self.dir = sm2_root / "client_pc/root/paks/client/default"
        self.language = language
        self.where: dict[str, Path] = {}
        for pak in sorted(self.dir.glob("default_sound_*.pak")):
            with zipfile.ZipFile(pak) as z:
                for n in z.namelist():
                    self.where.setdefault(n, pak)
        self._banks: dict[str, Bank] = {}
        self._streams: dict[str, zipfile.ZipFile] = {}

    def _read(self, inner: str) -> bytes:
        with zipfile.ZipFile(self.where[inner]) as z:
            return z.read(inner)

    def bank(self, name: str) -> Bank:
        if name not in self._banks:
            path = f"sounds/desktop/{name}.bnk"
            if path not in self.where:
                path = f"sounds/desktop/english_us_/{name}.bnk"
            self._banks[name] = parse_bank(self._read(path))
        return self._banks[name]

    def _stream_zip(self, name: str) -> zipfile.ZipFile | None:
        inner = f"sounds/desktop/{name}.zip"
        if inner not in self.where:
            return None
        if name not in self._streams:
            outer = zipfile.ZipFile(self.where[inner])
            self._streams[name] = zipfile.ZipFile(outer.open(inner))
        return self._streams[name]

    def event_wems(self, bank_name: str, event: str) -> list[bytes]:
        bank = self.bank(bank_name)
        out = []
        for _stream_type, mid in resolve_event(bank, event):
            if mid in bank.media:
                out.append(bank.media[mid])
                continue
            zs = self._stream_zip(bank_name)
            if zs is not None and f"{mid}.wem" in zs.namelist():
                out.append(zs.read(f"{mid}.wem"))
        return out

    def voice_wem(self, name: str) -> bytes:
        z = self._stream_zip(f"external_sources_vorbis_{self.language}")
        return z.read(f"{name}.wem")


def decode(vgmstream_cli: Path, wem: bytes, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    src = out_wav.with_suffix(".wem")
    src.write_bytes(wem)
    subprocess.run([str(vgmstream_cli), "-o", str(out_wav), str(src)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    src.unlink()
