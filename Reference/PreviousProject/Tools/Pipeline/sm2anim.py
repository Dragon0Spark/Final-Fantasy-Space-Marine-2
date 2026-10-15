"""Space Marine 2 animations (.sani + .sani_data, "ETNA" v2), read from the player's own paks.

Layout, as decoded so far (own research, no public documentation):
- header: "ETNA", u8 version 2, u8 0, u8 flags, u8 0, u32 offset of the track chunk, f32 duration,
  f32 fps, u32 frames, u32 transform tracks, u32 float curves; then one u32-length name per track/curve.
- chunk 0xF6 (u16 id, u32 end offset): u16 2, u32 counts[7] = animated pos / rot / scale,
  constant pos / rot / scale, animated curves; u16 track index lists for the first six.
  Then f32 data: 14 header floats, then per animated position track (min xyz, step xyz),
  then per animated rotation track (min xyz, step xyz) (quaternion x, y, z; w = +sqrt(1 - x²-y²-z²)).
  Constant values follow in a packed form that is not decoded yet: constant tracks use the
  model's bind pose instead.
- .sani_data chunk 0xF2: all frames of animated positions (u32 per track: x 10 bits, y 11, z 11),
  then all frames of animated rotations (48 bits per track: x, y, z 16 bits each), frame-major.
  value = min + quantized * step.
"""
from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

POS_BITS = (10, 11, 11)


@dataclass
class Animation:
    name: str
    fps: float
    frames: int
    tracks: list[str]
    curves: list[str]
    pos_tracks: list[int]
    rot_tracks: list[int]
    positions: np.ndarray      # (frames, len(pos_tracks), 3) local translation, SM2 space, metres
    rotations: np.ndarray      # (frames, len(rot_tracks), 4) local quaternion x, y, z, w
    events: list[str] = field(default_factory=list)


def _names(sani: bytes, count: int) -> list[str]:
    out = []
    p = 32
    for _ in range(count):
        n = struct.unpack_from("<I", sani, p)[0]
        out.append(sani[p + 4:p + 4 + n].decode("latin-1"))
        p += 4 + n
    return out


def parse(name: str, sani: bytes, data: bytes | None) -> Animation:
    if sani[:4] != b"ETNA":
        raise ValueError(f"{name}: not an ETNA animation")
    off, _dur, fps, frames, ntracks, ncurves = struct.unpack_from("<IffIII", sani, 8)
    names = _names(sani, ntracks + ncurves)
    chunk_id, chunk_end = struct.unpack_from("<HI", sani, off)
    if chunk_id != 0xF6:
        raise ValueError(f"{name}: unsupported layout chunk {chunk_id:#x} (camera-style animation)")
    q = off + 6 + 2
    counts = struct.unpack_from("<7I", sani, q)
    q += 28
    lists = []
    for c in counts[:6]:
        lists.append(list(struct.unpack_from(f"<{c}H", sani, q)))
        q += 2 * c
    pos_a, rot_a = lists[0], lists[1]
    region = sani[q:chunk_end]
    head = 14
    recs = struct.unpack_from(f"<{6 * (len(pos_a) + len(rot_a))}f", region, head * 4)
    pos_rec = np.array(recs[:6 * len(pos_a)], dtype=np.float64).reshape(-1, 6)
    rot_rec = np.array(recs[6 * len(pos_a):], dtype=np.float64).reshape(-1, 6)

    positions = np.zeros((frames, len(pos_a), 3))
    rotations = np.zeros((frames, len(rot_a), 4))
    if data is not None and (pos_a or rot_a):
        body = data[6:]
        n = frames * len(pos_a)
        packed = np.frombuffer(body[:4 * n], dtype="<u4").astype(np.int64).reshape(frames, len(pos_a))
        sh = 0
        for axis, bits in enumerate(POS_BITS):
            comp = (packed >> sh) & ((1 << bits) - 1)
            positions[:, :, axis] = pos_rec[None, :, axis] + comp * pos_rec[None, :, 3 + axis]
            sh += bits
        rbase = 4 * n
        m = frames * len(rot_a)
        u16 = np.frombuffer(body[rbase:rbase + 6 * m], dtype="<u2").astype(np.float64).reshape(frames, len(rot_a), 3)
        xyz = rot_rec[None, :, :3] + u16 * rot_rec[None, :, 3:]
        w = np.sqrt(np.clip(1.0 - (xyz ** 2).sum(axis=2), 0.0, 1.0))
        rotations[:, :, :3] = xyz
        rotations[:, :, 3] = w
    return Animation(name, fps, frames, names[:ntracks], names[ntracks:], pos_a, rot_a, positions, rotations)


class SM2Animations:
    """Finds animations in the player's SM2 default_animation.pak."""

    def __init__(self, sm2_root: Path) -> None:
        self.pak = sm2_root / "client_pc/root/paks/client/default/default_animation.pak"
        self._zip = zipfile.ZipFile(self.pak)
        self.names = {n for n in self._zip.namelist() if n.endswith(".sani")}

    def find(self, needle: str) -> list[str]:
        return sorted(n for n in self.names if needle in n)

    def load(self, path: str) -> Animation:
        sani = self._zip.read(path)
        data_name = path + "_data"
        data = self._zip.read(data_name) if data_name in self._zip.namelist() else None
        return parse(path, sani, data)
