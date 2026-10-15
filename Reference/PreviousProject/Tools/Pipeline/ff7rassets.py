"""Make new FF7R assets by cloning the player's own Cloud assets (renamed, with new data).

Used for Titus's material instances (clones of Cloud's) and textures (clones of Cloud's texture
assets with converted SM2 pixels injected). Names get correct UE 4.18 FName hashes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

import ue4names
from bua.unreal.dds import DDS
from bua.unreal.uasset import Uasset

CLOUD = "/Game/GameContents/Character/Player/PC0000_00_Cloud_Standard"
TEX_DIR = CLOUD + "/Texture"
MAT_DIR = CLOUD + "/Material"


def game_path_to_file(game_path: str) -> str:
    """/Game/GameContents/X → End/Content/GameContents/X."""
    assert game_path.startswith("/Game/")
    return "End/Content/" + game_path[len("/Game/"):]


class _RawUexp:
    """Keeps an export's .uexp bytes as they are (only the .uasset's names change)."""

    def __init__(self, path: Path) -> None:
        self.data = path.read_bytes()

    def save(self, path: str) -> int:
        Path(path).write_bytes(self.data)
        return len(self.data)


def rehash(asset: Uasset) -> None:
    asset.hash_list = [ue4names.name_hash_bytes(n) for n in asset.name_list]


def new_guid(asset: Uasset) -> None:
    asset.header.guid_hash = uuid.uuid4().bytes


def clone(src_uasset: Path, out_root: Path, new_game_path: str, renames: dict[str, str],
          inject_dds: Path | None = None) -> Path:
    """Load src (with its uexp/ubulk), rename names, optionally inject a DDS, save under new_game_path."""
    asset = Uasset(str(src_uasset), version="ff7r")
    missing = [old for old in renames if old not in asset.name_list]
    if missing:
        raise KeyError(f"{src_uasset.name}: names not found {missing}")
    asset.name_list = [renames.get(n, n) for n in asset.name_list]
    rehash(asset)
    new_guid(asset)
    if inject_dds is not None:
        dds = DDS.load(str(inject_dds))
        asset.uexp.texture.inject_dds(dds)
    elif asset.asset_type not in ("Texture2D", "SkeletalMesh", "StaticMesh", "Skeleton", "AnimSequence"):
        asset.uexp = _RawUexp(src_uasset.with_suffix(".uexp"))
    out = out_root / (game_path_to_file(new_game_path) + ".uasset")
    out.parent.mkdir(parents=True, exist_ok=True)
    asset.save(str(out))
    return out


# ---------------------------------------------------------------- textures

class TexConv:
    """Microsoft DirectXTex texconv (MIT), bundled with the converter."""

    def __init__(self, exe: Path) -> None:
        self.exe = exe

    def run(self, src: Path, out_dir: Path, fmt: str, *extra: str) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.exe), "-nologo", "-y", "-f", fmt, "-o", str(out_dir), *extra, str(src)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out_dir / (src.stem + (".png" if fmt.lower() == "png" else ".dds"))

    def to_png(self, dds: Path, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.exe), "-nologo", "-y", "-ft", "png", "-m", "1", "-f", "R8G8B8A8_UNORM",
               "-o", str(out_dir), str(dds)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out_dir / (dds.stem + ".png")

    def encode(self, png: Path, out_dir: Path, fmt: str, size: int | None = None) -> Path:
        extra = ["-m", "0"]
        if size:
            extra += ["-w", str(size), "-h", str(size)]
        return self.run(png, out_dir, fmt, *extra)


def build_texture_set(sm2tex, texconv: TexConv, tex: str, alpha: str | None, work: Path) -> dict[str, Path]:
    """Convert one SM2 texture set into FF7R-ready DDS files: C, M, N, O, B (+A)."""
    work.mkdir(parents=True, exist_ok=True)

    def sm2_png(name: str) -> Path:
        dds_bytes, _ = sm2tex.to_dds(name)
        src = work / f"{name}.dds"
        src.write_bytes(dds_bytes)
        return texconv.to_png(src, work / "png")

    out: dict[str, Path] = {}
    albedo = sm2_png(tex)
    out["C"] = texconv.encode(albedo, work / "C", "BC1_UNORM")

    spec = np.asarray(Image.open(sm2_png(tex + "_spec")).convert("RGBA"))
    m = np.zeros((spec.shape[0], spec.shape[1], 3), dtype=np.uint8)
    m[..., 0] = spec[..., 0]            # metal
    m[..., 1] = 255 - spec[..., 1]      # roughness = 1 - gloss
    m[..., 2] = 255                     # variant (Cloud's maps keep it at 1)
    mp = work / "png" / f"{tex}_M.png"
    Image.fromarray(m, "RGB").save(mp)
    out["M"] = texconv.encode(mp, work / "M", "BC1_UNORM")

    ao = np.repeat(spec[..., 2:3], 3, axis=2)
    op = work / "png" / f"{tex}_O.png"
    Image.fromarray(ao, "RGB").save(op)
    out["O"] = texconv.encode(op, work / "O", "BC4_UNORM")

    nrm = sm2_png(tex + "_nm")
    out["N"] = texconv.encode(nrm, work / "N", "BC5_UNORM")

    black = work / "png" / "black_256.png"
    if not black.exists():
        Image.new("RGB", (256, 256), (0, 0, 0)).save(black)
    out["B"] = texconv.encode(black, work / "B", "BC1_UNORM")

    if alpha:
        a = np.asarray(Image.open(sm2_png(alpha)).convert("RGBA"))
        ap = work / "png" / f"{tex}_A.png"
        Image.fromarray(np.repeat(a[..., :1], 3, axis=2), "RGB").save(ap)
        out["A"] = texconv.encode(ap, work / "A", "BC4_UNORM")
    return out


TEMPLATE_TEXTURE = {
    "C": "PC0000_00_BodyA_C", "M": "PC0000_00_BodyA_M", "N": "PC0000_00_BodyA_N",
    "O": "PC0000_00_BodyA_O", "B": "PC0000_00_BodyA_B", "A": "PC0000_00_BodyA_A",
}


def make_textures(cloud_dir: Path, out_root: Path, set_id: str, dds: dict[str, Path]) -> dict[str, str]:
    """Clone Cloud's texture assets as SMT_<set>_<X> with the converted pixels. Returns X → game path."""
    made = {}
    for ch, src_dds in dds.items():
        tmpl = TEMPLATE_TEXTURE[ch]
        new_name = f"SMT_{set_id}_{ch}"
        renames = {f"{TEX_DIR}/{tmpl}": f"{TEX_DIR}/{new_name}", tmpl: new_name}
        clone(cloud_dir / "Texture" / f"{tmpl}.uasset", out_root, f"{TEX_DIR}/{new_name}", renames, src_dds)
        made[ch] = f"{TEX_DIR}/{new_name}"
    return made


def make_material(cloud_dir: Path, out_root: Path, set_id: str, template: str, channels: list[str]) -> str:
    """Clone one of Cloud's material instances as SMT_<set>, pointing at SMT_<set>_<X> textures."""
    src = cloud_dir / "Material" / f"{template}.uasset"
    asset = Uasset(str(src), version="ff7r", ignore_uexp=True)
    new_name = f"SMT_{set_id}"
    renames = {f"{MAT_DIR}/{template}": f"{MAT_DIR}/{new_name}", template: new_name}
    for n in asset.name_list:
        if n.startswith(f"{TEX_DIR}/PC0000_00_") or (n.startswith("PC0000_00_") and n != template):
            ch = n.rsplit("_", 1)[-1]
            if ch in channels:
                short = f"SMT_{set_id}_{ch}"
                renames[n] = f"{TEX_DIR}/{short}" if n.startswith("/Game/") else short
    clone(src, out_root, f"{MAT_DIR}/{new_name}", renames)
    return f"{MAT_DIR}/{new_name}"
