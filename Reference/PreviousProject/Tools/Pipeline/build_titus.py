"""Build Titus into the player's FF7R: converted textures, materials and Cloud's mesh, packed as a ~mods pak.

Usage: python -I build_titus.py --ff7r <FF7R folder> --sm2 <SM2 folder> --texconv <texconv.exe>
                                --out <pak path> [--work <temp dir>]
Everything is read from the two installed games; the outputs stay on this PC.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "External"))

import numpy as np  # noqa: E402

import ff7rassets  # noqa: E402
import sheets  # noqa: E402
import sm2tpl  # noqa: E402
import titus_mesh  # noqa: E402
import ue4pak  # noqa: E402
from bua.unreal.uasset import Uasset  # noqa: E402
from ff7rpaks import FF7RPaks  # noqa: E402
from sm2pct import SM2Textures  # noqa: E402

CLOUD_DIR = "End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard"
UV_MAPS = 3  # Cloud's LOD0 carries three UV channels; Titus's single UV set fills all three.


class SlotMaterial:
    def __init__(self, game_path: str) -> None:
        self.import_name = game_path.rsplit("/", 1)[-1]
        self.slot_name = self.import_name
        self.asset_path = game_path


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def to_u8(v: np.ndarray) -> np.ndarray:
    return np.clip(np.rint((v + 1.0) * 127.0), 0, 255).astype(np.uint8)


def quantize_weights(ws: list[float]) -> list[int]:
    q = [int(round(w * 255)) for w in ws]
    if q:
        q[int(np.argmax(q))] += 255 - sum(q)
    return q


def primitives_for(sections, slot_ids: list[int], bone_count: int) -> dict:
    prim = {"BONES": [None] * bone_count, "MATERIAL_IDS": slot_ids, "POSITIONS": [], "NORMALS": [],
            "UV_MAPS": [[] for _ in range(UV_MAPS)], "INDICES": [], "VERTEX_GROUPS": [], "JOINTS": [],
            "WEIGHTS": [], "VERTEX_COUNTS": []}
    for s in sections:
        tan, sign = titus_mesh.tangents(s.positions, s.normals, s.uvs, s.triangles)
        packed = np.concatenate([to_u8(tan), to_u8(sign[:, None]), to_u8(s.normals),
                                 np.full((len(sign), 1), 127, np.uint8)], axis=1)
        group = sorted({b for js in s.joints for b in js})
        if len(group) > 255:
            raise ValueError(f"section {s.armor_id} uses {len(group)} bones (max 255)")
        local = {b: i for i, b in enumerate(group)}
        for js, ws in zip(s.joints, s.weights):
            q = quantize_weights(ws)
            prim["JOINTS"].append([local[b] for b in js] + [0] * (8 - len(js)))
            prim["WEIGHTS"].append(q + [0] * (8 - len(q)))
        prim["POSITIONS"] += s.positions.astype(np.float32).tolist()
        prim["NORMALS"] += packed.tolist()
        uv = s.uvs.astype(np.float32).tolist()
        for m in prim["UV_MAPS"]:
            m += uv
        prim["INDICES"].append(s.triangles.reshape(-1).astype(int).tolist())
        prim["VERTEX_GROUPS"].append(group)
        prim["VERTEX_COUNTS"].append(len(s.positions))
    return prim


def redirect_slot(asset: Uasset, material, game_path: str) -> None:
    """Point an existing material slot's import at a new material (slot name kept)."""
    imp = asset.imports[-material.import_id - 1]
    pkg = asset.imports[-imp.parent_import_id - 1]
    short = game_path.rsplit("/", 1)[-1]
    for name in (short, game_path):
        if name not in asset.name_list:
            asset.name_list.append(name)
    imp.name_id = asset.name_list.index(short)
    pkg.name_id = asset.name_list.index(game_path)


def inject_mesh(mesh_uasset: Path, sections, materials: list[str], out_root: Path) -> Path:
    asset = Uasset(str(mesh_uasset), version="ff7r")
    mesh = asset.uexp.mesh
    while len(mesh.materials) < len(materials):
        mesh.add_material_slot(asset, SlotMaterial(materials[len(mesh.materials)]))
    for i, game_path in enumerate(materials):
        redirect_slot(asset, mesh.materials[i], game_path)
    prim = primitives_for(sections, list(range(len(sections))), len(mesh.skeleton.bones))
    mesh.remove_LODs()
    lod = mesh.LODs[0]
    lod.import_from_blender(prim)
    lod.update_material_ids(list(range(len(mesh.materials))))
    ff7rassets.rehash(asset)
    out = out_root / CLOUD_DIR / "Model" / mesh_uasset.name
    out.parent.mkdir(parents=True, exist_ok=True)
    asset.save(str(out))
    return out


def build(ff7r_root: Path, sm2_root: Path, texconv_exe: Path, out_pak: Path, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    src = work / "src"
    out_root = work / "pak_root"
    if out_root.exists():
        shutil.rmtree(out_root)

    log("reading FF7R paks (key from your ff7remake_.exe)")
    paks = FF7RPaks(ff7r_root)
    for p in paks.find(CLOUD_DIR + "/"):
        if p.endswith(".uasset") and ("/Model/PC0000_00" in p or "/Material/" in p or "/Texture/" in p):
            paks.extract_asset(p, src)
    cloud_dir = src / CLOUD_DIR

    log("reading Titus from your Space Marine 2")
    tpl_bytes, data = titus_mesh.read_titus_files(sm2_root)
    tpl = sm2tpl.read_template(tpl_bytes)
    cloud = Uasset(str(cloud_dir / "Model/PC0000_00.uasset"), version="ff7r").uexp.mesh
    fit = titus_mesh.fit_skeleton(tpl, cloud.skeleton.bones, sheets.load("bone_map")["rows"])
    for line in fit.report:
        log(line)
    sections, notes = titus_mesh.build_sections(tpl, data, fit)
    for line in notes:
        log(line)

    log("converting armour textures")
    sm2tex = SM2Textures(sm2_root)
    texconv = ff7rassets.TexConv(texconv_exe)
    armor = sheets.rows("armor_sets")
    materials = []
    for s in sections:
        row = armor[s.armor_id]
        alpha = row["alpha"] if row["alpha"] not in ("none", None) else None
        dds = ff7rassets.build_texture_set(sm2tex, texconv, row["sm2_texture"], alpha, work / "tex" / s.armor_id)
        ff7rassets.make_textures(cloud_dir, out_root, s.armor_id, dds)
        materials.append(ff7rassets.make_material(cloud_dir, out_root, s.armor_id, row["template_material"],
                                                  list(dds)))
        log(f"  {s.armor_id}: {', '.join(sorted(dds))}")

    log("injecting Titus into Cloud's mesh")
    inject_mesh(cloud_dir / "Model/PC0000_00.uasset", sections, materials, out_root)

    log("packing")
    files = {}
    for f in sorted(out_root.rglob("*")):
        if f.is_file():
            files[f.relative_to(out_root).as_posix()] = f.read_bytes()
    out_pak.parent.mkdir(parents=True, exist_ok=True)
    ue4pak.write_pak(out_pak, "../../../", files, version=4)
    log(f"wrote {out_pak} ({len(files)} files, {out_pak.stat().st_size // 1024 // 1024} MB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ff7r", required=True, type=Path)
    ap.add_argument("--sm2", required=True, type=Path)
    ap.add_argument("--texconv", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--work", type=Path, default=Path(tempfile.gettempdir()) / "SpaceMarineFFVII_build")
    a = ap.parse_args()
    build(a.ff7r, a.sm2, a.texconv, a.out, a.work)


if __name__ == "__main__":
    main()
