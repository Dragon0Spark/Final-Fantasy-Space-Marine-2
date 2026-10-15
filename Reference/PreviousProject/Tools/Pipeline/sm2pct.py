"""Space Marine 2 textures (pct resource + pct_mip files) to DDS, read from the player's paks."""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path

# pct header "format" values used by character textures → DXGI formats.
PCT_TO_DXGI = {
    0: 87,   # ARGB8888 → B8G8R8A8_UNORM
    12: 71,  # OXT1 → BC1_UNORM
    13: 71,  # AXT1 → BC1_UNORM
    15: 74,  # XT3 → BC2_UNORM
    17: 77,  # XT5 → BC3_UNORM
    36: 83,  # DXN → BC5_UNORM
    37: 80,  # DXT5A → BC4_UNORM
    49: 95,  # BC6U → BC6H_UF16
    51: 98,  # BC7 → BC7_UNORM
    52: 98,  # BC7A → BC7_UNORM
}


def _yaml_scalar(text: str, key: str) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(key + ":"):
            return s.split(":", 1)[1].strip()
    return None


def parse_pct_resource(text: str) -> dict:
    """Pick the few fields we need out of a res_desc_pct YAML (no YAML dependency)."""
    mips = []
    in_mips = False
    for line in text.splitlines():
        if line.startswith("mipMaps:"):
            in_mips = True
            continue
        if in_mips:
            if line.startswith("- "):
                mips.append(line[2:].strip())
            else:
                in_mips = False
    return {
        "format": int(_yaml_scalar(text, "format")),
        "width": int(_yaml_scalar(text, "sx")),
        "height": int(_yaml_scalar(text, "sy")),
        "mips": mips,
        "tex_type": _yaml_scalar(text, "texType") or "",
    }


def dds_bytes(dxgi: int, width: int, height: int, mips: list[bytes]) -> bytes:
    """A DDS file with a DX10 header holding the given mip chain."""
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000  # caps|height|width|pixelformat|mipcount|linearsize
    header = struct.pack(
        "<4sIIIIIII44s", b"DDS ", 124, flags, height, width, len(mips[0]), 1, len(mips), b"\0" * 44)
    pixel_format = struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    caps = struct.pack("<IIIII", 0x1000 | 0x400000 | 0x8, 0, 0, 0, 0)
    dx10 = struct.pack("<IIIII", dxgi, 3, 0, 1, 0)
    return header + pixel_format + caps + dx10 + b"".join(mips)


class SM2Textures:
    """Finds pct resources and mip files across the player's SM2 paks."""

    def __init__(self, sm2_root: Path) -> None:
        self.paks_dir = sm2_root / "client_pc/root/paks/client"
        self.where: dict[str, Path] = {}
        self._zips: dict[Path, zipfile.ZipFile] = {}
        for pak in sorted(self.paks_dir.rglob("*.pak")):
            name = pak.name
            if not (name.startswith(("default_pct", "resources", "default_td"))):
                continue
            for info in self._zip(pak).infolist():
                self.where.setdefault(info.filename, pak)

    def _zip(self, pak: Path) -> zipfile.ZipFile:
        if pak not in self._zips:
            self._zips[pak] = zipfile.ZipFile(pak)
        return self._zips[pak]

    def read(self, inner: str) -> bytes:
        return self._zip(self.where[inner]).read(inner)

    def has(self, tex_name: str) -> bool:
        return f"pct/{tex_name}.pct.resource" in self.where

    def to_dds(self, tex_name: str) -> tuple[bytes, dict]:
        res = parse_pct_resource(self.read(f"pct/{tex_name}.pct.resource").decode("utf-8", "replace"))
        dxgi = PCT_TO_DXGI.get(res["format"])
        if dxgi is None:
            raise ValueError(f"{tex_name}: unsupported pct format {res['format']}")
        mips = [self.read(f"pct/{m}") for m in res["mips"]]
        return dds_bytes(dxgi, res["width"], res["height"], mips), res
