"""Reader for Space Marine 2 (Swarm engine) template models: <name>.tpl + <name>.tpl_data.

Reads the player's own files in place and returns plain Python data: the object graph (nodes and
bones with their matrices), the inverse bind matrices, and per-submesh vertices, normals, UVs,
skin weights, triangles and material texture names.

Format notes (field layout learned from the community's LibSaber research, reimplemented here):
- Header "1SER" "tpl\\0" ... then "TPL1" and a property bitset (name, state, skin, bbox, lods,
  texture list, geometry graph).
- The geometry graph "OGM1" holds per-object property columns, then sentinel sections
  (0 header, 2 streams, 3 geoms, 4 splits, 5 refs, 0xFFFF end). Stream bytes live in .tpl_data.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

# Vertex stream feature bits (index in the stream's flag bitset).
FVF_VERT = 0
FVF_VERT_2D = 2
FVF_VERT_COMPR = 3
FVF_WEIGHT4 = 7
FVF_INDICES = 9
FVF_NORM = 10
FVF_NORM_COMPR = 11
FVF_TANG = (12, 13, 14, 15, 16)
FVF_TANG_COMPR = 17
FVF_COLOR = (22, 23, 24, 46, 47, 63)
FVF_TEX = (25, 26, 27, 28, 29, 59)
FVF_TEX_COMPR = (30, 31, 32, 33, 34, 60)
FVF_TEX_4D = (35, 36, 37, 38, 39, 61)
FVF_NORM_IN_VERT4 = 45
FVF_MASKING = 67
FVF_BS_INFO = 68
FVF_WEIGHT8 = 69
FVF_INDICES16 = 70

MESH_HAS_TRANSFORM = 3
MESH_HAS_BONE_IDS = 9
MESH_HAS_UV_SCALING = 30

OBJ_IS_BONE = 0x800


class Reader:
    def __init__(self, data: bytes, pos: int = 0) -> None:
        self.data = data
        self.pos = pos

    def _unpack(self, fmt: str):
        v = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += struct.calcsize(fmt)
        return v

    def u8(self) -> int:
        return self._unpack("<B")[0]

    def i16(self) -> int:
        return self._unpack("<h")[0]

    def u16(self) -> int:
        return self._unpack("<H")[0]

    def i32(self) -> int:
        return self._unpack("<i")[0]

    def u32(self) -> int:
        return self._unpack("<I")[0]

    def u64(self) -> int:
        return self._unpack("<Q")[0]

    def f32(self) -> float:
        return self._unpack("<f")[0]

    def vec3(self) -> tuple:
        return self._unpack("<3f")

    def mat4(self) -> tuple:
        return self._unpack("<16f")

    def raw(self, n: int) -> bytes:
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def str32(self) -> str:
        return self.raw(self.i32()).decode("latin-1")

    def str16(self) -> str:
        return self.raw(self.i16()).decode("latin-1")

    def cstr(self) -> str:
        end = self.data.index(b"\0", self.pos)
        s = self.data[self.pos:end].decode("latin-1")
        self.pos = end + 1
        return s

    def bits(self, count: int) -> list[bool]:
        raw = self.raw((count + 7) // 8)
        return [bool(raw[i >> 3] >> (i & 7) & 1) for i in range(count)]

    def bitset16(self) -> list[bool]:
        return self.bits(self.u16())

    def bitset32(self) -> list[bool]:
        return self.bits(self.i32())


@dataclass
class TplObject:
    index: int
    name: str = ""
    state: int = 0
    parent: int = -1
    matrix_lt: tuple = ()
    matrix_model: tuple = ()
    split_index: int = -1
    num_splits: int = 0


@dataclass
class Stream:
    flags: list[bool]
    stride: int = 0
    length: int = 0
    start: int = 0

    def has(self, bit: int) -> bool:
        return bit < len(self.flags) and self.flags[bit]

    @property
    def kind(self) -> str:
        if self.has(FVF_VERT):
            return "vertex"
        if any(self.has(b) for b in FVF_TANG[:4]) or any(self.has(b) for b in FVF_TEX[:5]):
            return "interleaved"
        if not any(self.flags):
            return "face"
        if self.has(FVF_INDICES):
            return "boneid"
        return "unknown"


@dataclass
class Geom:
    flags: list[bool]
    streams: list[tuple[int, int]]  # (stream index, byte offset inside the stream)

    def has(self, bit: int) -> bool:
        return bit < len(self.flags) and self.flags[bit]


@dataclass
class Split:
    vertex_offset: int = 0
    vertex_count: int = 0
    face_offset: int = 0
    face_count: int = 0
    node: int = -1
    skin_compound: int = -1
    geom: int = -1
    bone_ids: list[int] = field(default_factory=list)
    uv_scale: dict = field(default_factory=dict)
    position: tuple | None = None
    scale: tuple | None = None
    material: dict = field(default_factory=dict)


@dataclass
class Template:
    name: str = ""
    state: int = 0
    n_bones: int = 0
    inv_bind: list = field(default_factory=list)
    lod_bones: list = field(default_factory=list)
    bbox: tuple = ()
    lods: list = field(default_factory=list)  # (object id, lod index, last)
    textures: list = field(default_factory=list)
    objects: list[TplObject] = field(default_factory=list)
    streams: list[Stream] = field(default_factory=list)
    geoms: list[Geom] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)
    root: int = 0


# ---------------------------------------------------------------- material scripting values

def _read_value(r: Reader, kind: int, static: bool):
    if kind == 1:
        return r.i32()
    if kind == 2:
        return r.f32()
    if kind == 3:
        return r.u8() != 0
    if kind == 4:
        return r.str32()
    if kind == 6:
        return [_read_value(r, r.u32(), static) for _ in range(r.u32())]
    if kind == 7:
        return _read_object(r, static)
    raise ValueError(f"unknown scripting value type {kind} at {r.pos}")


def _read_object(r: Reader, static: bool) -> dict:
    obj = {}
    for _ in range(r.u32()):
        if static:
            name = r.cstr()
            r.u32()
        else:
            name = r.str32()
        obj[name] = _read_value(r, r.u32(), static)
    return obj


# ---------------------------------------------------------------- template

def _skip_flagged_floats(r: Reader) -> None:
    mask = r.u32()
    for _ in range(32):
        if mask & 1:
            r.raw(8)
        mask = ((mask << 1) | (mask >> 31)) & 0xFFFFFFFF


def _read_header(r: Reader) -> None:
    assert r.raw(4) == b"1SER", "not a Swarm serialized file"
    assert r.raw(4) == b"tpl\0", "not a template"
    r.u64(), r.u64(), r.u64(), r.i32()
    r.raw(16)  # resource guid / tag
    r.i32()
    count = r.i32()
    r.i32()
    for _ in range(count):
        r.u16(), r.u8(), r.u8(), r.u64(), r.u64(), r.str32()


def _read_skin(r: Reader, tpl: Template) -> None:
    tpl.n_bones = r.u32()
    r.u16(), r.u8()
    while True:
        sentinel = r.u16()
        end = r.u32()
        if sentinel == 0xFFFF:
            break
        if sentinel == 0:
            tpl.inv_bind = [r.mat4() for _ in range(tpl.n_bones)]
        elif sentinel == 1:
            tpl.lod_bones = [r.u16() for _ in range(r.u32())]
        r.pos = end


def _read_lod_defs(r: Reader, tpl: Template) -> None:
    count = r.i32()
    r.i32()
    lods = [[-1, 0, False] for _ in range(count)]
    if r.u8():
        for lod in lods:
            lod[0] = r.i16()
    if r.u8():
        for lod in lods:
            lod[1] = r.u8()
    if r.u8():
        for lod in lods:
            lod[2] = r.u8() != 0
    tpl.lods = [tuple(x) for x in lods]


def _read_tex_list(r: Reader, tpl: Template) -> None:
    count = r.u32()
    r.u16()
    r.u32()
    tpl.textures = [r.str16() for _ in range(count)]
    assert r.u16() == 0xFFFF
    r.u32()


def _read_objects(r: Reader, tpl: Template) -> None:
    count = r.i16()
    objs = [TplObject(i) for i in range(count)]
    r.u16()
    props = r.u16()
    r.u16()

    def column(reader_fn):
        if r.u8() == 0:
            return None
        return [reader_fn() for _ in objs]

    ids = names = None
    for p in range(props):
        if p == 0:
            ids = column(r.i16)
        elif p == 1:
            names = column(r.str32)
        elif p == 2:
            if r.u8():
                for o in objs:
                    flags = r.bitset16()
                    o.state = sum(1 << i for i, b in enumerate(flags) if b)
        elif p == 3:
            parents = column(r.i16)
            if parents:
                for o, v in zip(objs, parents):
                    o.parent = v
        elif p in (4, 5, 6, 7):
            column(r.i16)  # next, prev, child, anim number
        elif p == 8:
            column(r.str32)  # affixes
        elif p == 9:
            m = column(r.mat4)
            if m:
                for o, v in zip(objs, m):
                    o.matrix_lt = v
        elif p == 10:
            m = column(r.mat4)
            if m:
                for o, v in zip(objs, m):
                    o.matrix_model = v
        elif p == 11:
            if r.u8():
                present = r.bits(count)
                for o, has in zip(objs, present):
                    if not has:
                        continue
                    r.i32()
                    gflags = r.u8()
                    if gflags & 1:
                        o.split_index = r.u32()
                    if gflags & 2:
                        o.num_splits = r.u32()
                    if gflags & 4:
                        r.raw(24)
                    if gflags & 8:
                        r.raw(60)
        elif p == 12:
            column(r.str32)  # source id
        elif p == 13:
            if r.u8():
                r.raw(60 * count)
        elif p == 14:
            column(r.str16)  # read-only name
        elif p == 15:
            if r.u8():
                raise NotImplementedError("read-only affixes")
        elif p in (16, 17):
            column(r.str32)
        else:
            raise NotImplementedError(f"object property {p}")
    if ids:
        for o, v in zip(objs, ids):
            o.index = v
    if names:
        for o, v in zip(objs, names):
            o.name = v
    tpl.objects = objs


def _read_streams(r: Reader, tpl: Template, count: int) -> None:
    section_end = r.i32()
    streams = [Stream([]) for _ in range(count)]
    while r.pos < section_end:
        sid = r.i16()
        end = r.i32()
        if sid == 0:
            for s in streams:
                s.flags = r.bitset16()
        elif sid == 1:
            for s in streams:
                s.stride = r.u16()
        elif sid == 2:
            for s in streams:
                s.length = r.u32()
        elif sid == 3:
            for s in streams:
                s.start = r.pos
                r.pos += s.length
        r.pos = end
    tpl.streams = streams


def _read_geoms(r: Reader, tpl: Template, count: int) -> None:
    section_end = r.i32()
    geoms = [Geom([], []) for _ in range(count)]
    while r.pos < section_end:
        sid = r.i16()
        end = r.i32()
        if sid == 0:
            for g in geoms:
                g.flags = r.bitset16()
        elif sid == 2:
            for g in geoms:
                g.streams = [(r.i32(), r.i32()) for _ in range(r.u8())]
        r.pos = end
    tpl.geoms = geoms


def _read_splits(r: Reader, tpl: Template, count: int) -> None:
    section_end = r.i32()
    splits = [Split() for _ in range(count)]
    while r.pos < section_end:
        sid = r.i16()
        end = r.i32()
        if sid == 0 and splits:
            extra = (end - r.pos) // len(splits) > 12
            for s in splits:
                (s.vertex_offset, s.vertex_count, s.face_offset, s.face_count) = struct.unpack_from(
                    "<4H", r.data, r.pos)
                r.pos += 8
                s.node = r.i16()
                s.skin_compound = r.i16()
                if extra:
                    _skip_flagged_floats(r)
        elif sid == 1:
            for s in splits:
                s.geom = r.i32()
        elif sid == 2:
            for _ in splits:
                r.u16()
                n = r.u8()
                while True:
                    sub = r.u16()
                    sub_end = r.u32()
                    r.pos = sub_end
                    if sub == 0xFFFF:
                        break
                _skip_flagged_floats(r)
        elif sid == 3:
            for s in splits:
                if tpl.geoms[s.geom].has(MESH_HAS_BONE_IDS):
                    s.bone_ids = [r.i16() for _ in range(r.u8())]
        elif sid == 4:
            for s in splits:
                if tpl.geoms[s.geom].has(MESH_HAS_UV_SCALING):
                    for _ in range(r.u8()):
                        ch = r.u8()
                        s.uv_scale[ch] = r.i16()
        elif sid == 5:
            for s in splits:
                if tpl.geoms[s.geom].has(MESH_HAS_TRANSFORM):
                    s.position = r._unpack("<3h")
                    s.scale = r._unpack("<3h")
        elif sid in (6, 7, 8):
            for s in splits:
                s.node = r.u16()
                if sid == 6:
                    s.material = {"_text": r.str32()}
                else:
                    s.material = _read_object(r, static=(sid == 7))
        r.pos = end
    tpl.splits = splits


def _read_geometry(r: Reader, tpl: Template) -> None:
    assert r.raw(4) == b"OGM1"
    head = r.u32()
    var_count = head & 0xFFFF
    r.u16()
    flags = r.u8() if var_count <= 8 else r.u16()
    if flags & 1:
        _read_objects(r, tpl)
    if flags & 2:
        count = r.i32()
        if r.u8():
            for _ in range(count):
                r.raw(2 + 8 + 4 + 2)
    if flags & 4:
        count = r.i32()
        if r.u8():
            for _ in range(count):
                r.i32()
                r.str32()
    if flags & 8:
        count = r.u32()
        props = r.u32()
        for p in range(props):
            if r.u8() == 0:
                continue
            for _ in range(count):
                if p in (0, 1):
                    r.raw(4 * r.i32())
                elif p == 2:
                    n = r.i32()
                    r.u32()
                    if r.u8():
                        r.raw(4 * n)
                elif p == 3:
                    r.raw(24)
                elif p == 4:
                    r.f32()
                elif p == 5:
                    r.u8()
    vb_offsets = vb_sizes = None
    if flags & 16:
        r.i32()
        mflags = r.u8()
        if mflags & 1:
            n, props = r.i32(), r.i32()
            cols = []
            for _ in range(props):
                cols.append([r.i32() for _ in range(n)] if r.u8() else None)
            vb_offsets = cols[1] if len(cols) > 1 else None
            n, props = r.i32(), r.i32()
            sizes = None
            for p in range(props):
                if r.u8() == 0:
                    continue
                if p == 0:
                    sizes = [r.i32() for _ in range(n)]
                elif p == 1:
                    for _ in range(n):
                        r.i32()
                elif p == 3:
                    for _ in range(n):
                        if r.u8():
                            r.u16()
                else:
                    raise NotImplementedError("vbuffer info old flags")
            vb_sizes = sizes
    if flags & 32:
        count = r.i32()
        if r.u8():
            names = [r.str32() for _ in range(count)]
        else:
            names = None
    else:
        names = None
    if flags & 64:
        count = r.i32()
        ids = [r.u16() for _ in range(count)]
        if names:
            for i, n in zip(ids, names):
                if not tpl.objects[i].name:
                    tpl.objects[i].name = n
    if flags & 128:
        count = r.i32()
        for i in range(count):
            tpl.objects[i].matrix_lt = r.mat4()
    if flags & 256:
        count = r.i32()
        for i in range(count):
            tpl.objects[i].matrix_model = r.mat4()
    if flags & 512:
        count, props = r.i32(), r.i32()
        for p in range(props):
            if r.u8():
                for _ in range(count):
                    r.i16()

    counts = {}
    while r.pos < len(r.data):
        sentinel = r.u16()
        if sentinel == 0:
            end = r.u32()
            tpl.root = r.i16()
            counts = {"nodes": r.i32(), "streams": r.i32(), "geoms": r.i32(), "splits": r.i32()}
            r.pos = end
        elif sentinel == 5:
            r.pos = r.u32()
        elif sentinel == 2:
            _read_streams(r, tpl, counts["streams"])
        elif sentinel == 3:
            _read_geoms(r, tpl, counts["geoms"])
        elif sentinel == 4:
            _read_splits(r, tpl, counts["splits"])
        elif sentinel == 0xFFFF:
            r.u32()
            break
        else:
            raise ValueError(f"unknown geometry sentinel {sentinel:#x} at {r.pos - 2}")

    # Stream bytes are packed back to back in .tpl_data, optionally remapped.
    offset = 0
    for i, s in enumerate(tpl.streams):
        s.start = offset
        offset += s.length
    if vb_offsets and vb_sizes:
        running = 0
        starts = []
        for i in range(len(tpl.streams)):
            starts.append(running)
            if i < len(vb_sizes):
                running += vb_sizes[i]
        for i, s in enumerate(tpl.streams):
            s.start = vb_offsets[i] if i < len(vb_offsets) and vb_offsets[i] else s.start


def read_template(tpl_bytes: bytes) -> Template:
    r = Reader(tpl_bytes)
    _read_header(r)
    assert r.raw(4) == b"TPL1"
    flags = r.bitset32()
    tpl = Template()

    def has(bit: int) -> bool:
        return bit < len(flags) and flags[bit]

    if has(0):
        tpl.name = r.str32()
    if has(1):
        r.str32()
    if has(2):
        r.u16()
        tpl.state = r.u32()
    if has(3):
        r.str32()
    if has(4):
        r.str32()
    if has(5):
        _read_skin(r, tpl)
    if has(6):
        raise NotImplementedError("templates with embedded animation tracks")
    if has(8):
        tpl.bbox = (r.vec3(), r.vec3())
    if has(9):
        _read_lod_defs(r, tpl)
    if has(10):
        _read_tex_list(r, tpl)
    if has(11):
        _read_geometry(r, tpl)
    return tpl


# ---------------------------------------------------------------- vertex decoding

def _snorm16(v: int) -> float:
    return v / 32767.0


def _normal_from_i16(w: int) -> tuple:
    if w == -32768:
        w = 0
    a = abs(w)
    x = (-1.0 + 2.0 * math.modf(a / 181.0)[0]) * (181.0 / 179.0)
    z = (-1.0 + 2.0 * math.modf(a / 181.0 / 181.0)[0]) * (181.0 / 180.0)
    y = math.copysign(1.0, w) * math.sqrt(max(0.0, min(1.0, 1.0 - x * x - z * z)))
    return (x, y, z)


@dataclass
class MeshPart:
    split: int
    node: int
    positions: list
    normals: list
    uvs: list
    weights: list  # per vertex: list of (bone object id, weight)
    triangles: list
    material: dict


def decode_split(tpl: Template, data: bytes, split_index: int) -> MeshPart:
    s = tpl.splits[split_index]
    geom = tpl.geoms[s.geom]
    positions, normals, uvs, weights, tris = [], [], [], [], []
    scale = (1.0, 1.0, 1.0)
    pos_off = (0.0, 0.0, 0.0)
    if s.scale is not None:
        scale = tuple(float(v) for v in s.scale)
        pos_off = tuple(float(v) for v in s.position)
    for stream_idx, sub_off in geom.streams:
        st = tpl.streams[stream_idx]
        kind = st.kind
        if kind == "vertex":
            base = st.start + sub_off + s.vertex_offset * st.stride
            for i in range(s.vertex_count):
                r = Reader(data, base + i * st.stride)
                if st.has(FVF_VERT_COMPR):
                    x, y, z, w = r._unpack("<4h")
                    p = (_snorm16(x) * scale[0] + pos_off[0], _snorm16(y) * scale[1] + pos_off[1],
                         _snorm16(z) * scale[2] + pos_off[2])
                    n = _normal_from_i16(w) if st.has(FVF_NORM_IN_VERT4) else None
                else:
                    x, y, z = r._unpack("<3f")
                    p = (x * scale[0] + pos_off[0], y * scale[1] + pos_off[1], z * scale[2] + pos_off[2])
                    n = None
                    if st.has(FVF_NORM_IN_VERT4):
                        f = r.f32()
                        n = tuple(-1.0 + 2.0 * math.modf(f * k)[0]
                                  for k in (1 / 256.0, 1 / 65536.0, 1 / 16777216.0))
                vw = []
                if st.has(FVF_WEIGHT4) or st.has(FVF_WEIGHT8):
                    nw = 8 if st.has(FVF_WEIGHT8) else 4
                    wts = [r.u8() / 255.0 for _ in range(nw)]
                    if st.has(FVF_INDICES16):
                        idx = [r.i16() for _ in range(nw)]
                    elif st.has(FVF_INDICES):
                        idx = [r.u8() for _ in range(nw)]
                    else:
                        idx = []
                    vw = [(b, wt) for b, wt in zip(idx, wts) if wt > 0]
                if st.has(FVF_MASKING):
                    r.i32()
                if st.has(FVF_NORM) and not st.has(FVF_NORM_IN_VERT4):
                    if st.has(FVF_NORM_COMPR):
                        n = _normal_from_i16(r.i16())
                    else:
                        n = r.vec3()
                positions.append(p)
                normals.append(n)
                weights.append(vw)
        elif kind == "interleaved":
            base = st.start + sub_off + s.vertex_offset * st.stride
            for i in range(s.vertex_count):
                r = Reader(data, base + i * st.stride)
                comp_t = st.has(FVF_TANG_COMPR)
                for b in FVF_TANG:
                    if st.has(b):
                        r.raw(4 if comp_t else 16)
                for b in FVF_COLOR:
                    if st.has(b):
                        r.raw(4)
                if st.has(FVF_BS_INFO):
                    r.raw(2)
                uv = None
                for ch, (bt, bc) in enumerate(zip(FVF_TEX, FVF_TEX_COMPR)):
                    if not st.has(bt):
                        continue
                    if st.has(bc):
                        u, v = r._unpack("<2h")
                        u, v = _snorm16(u), 1.0 - _snorm16(v)
                    else:
                        u, v = r._unpack("<2f")
                        v = 1.0 - v
                    k = s.uv_scale.get(ch, 1)
                    if uv is None:
                        uv = (u * k, v * k)
                uvs.append(uv)
        elif kind == "face" and st.stride == 6:
            base = st.start + sub_off + s.face_offset * st.stride
            for i in range(s.face_count):
                a, b, c = struct.unpack_from("<3H", data, base + i * 6)
                tris.append((a - s.vertex_offset, b - s.vertex_offset, c - s.vertex_offset))
    return MeshPart(split_index, s.node, positions, normals, uvs, weights, tris, s.material)
