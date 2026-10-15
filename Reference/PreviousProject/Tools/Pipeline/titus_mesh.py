"""Fit Titus (SM2 template) onto Cloud's FF7R skeleton and build injection primitives.

Steps (driven by Sheets/bone_map.json, titus_parts.json, armor_sets.json):
1. decode Titus's LOD0 parts from the player's SM2 paks;
2. convert SM2 space (Y up, metres, +Z forward) to UE space (Z up, cm, +X forward);
3. scale Titus to Cloud's height and fit every bone onto Cloud's bind pose
   (snap = translate, segment = rotate the limb segment onto Cloud's, inherit = follow parent);
4. re-skin every vertex onto Cloud's bones (bone_map shares, max 8 influences);
5. group by armour set → one FF7R section/material each, with tangents for normal mapping.
"""
from __future__ import annotations

import fnmatch
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import sheets
import sm2tpl

# SM2 (x right-of-viewer = Titus's left, y up, z forward) → UE (x forward, y right, z up), metres → cm.
SM2_TO_UE = np.array([[0.0, 0.0, 1.0],
                      [-1.0, 0.0, 0.0],
                      [0.0, 1.0, 0.0]])
MAX_INFLUENCES = 8


# ---------------------------------------------------------------- inputs

def read_titus_files(sm2_root: Path, name: str = "cc_titus") -> tuple[bytes, bytes]:
    tpl_path = f"tpl/{name}.tpl/{name}.tpl"
    data_path = f"tpl/{name}.tpl/{name}.tpl_data"
    tpl_bytes = data_bytes = None
    for pak in sorted((sm2_root / "client_pc/root/paks/client/default").glob("default_tpl_*.pak")):
        with zipfile.ZipFile(pak) as z:
            names = set(z.namelist())
            if tpl_bytes is None and tpl_path in names:
                tpl_bytes = z.read(tpl_path)
            if data_bytes is None and data_path in names:
                data_bytes = z.read(data_path)
    if tpl_bytes is None or data_bytes is None:
        raise FileNotFoundError(f"{name} not found in the Space Marine 2 paks")
    return tpl_bytes, data_bytes


def quat_to_mat(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def cloud_bind_globals(bones) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for b in bones:
        m = np.eye(4)
        m[:3, :3] = quat_to_mat(b.rot)
        m[:3, 3] = b.trans
        out.append(out[b.parent] @ m if b.parent >= 0 else m)
    return out


# ---------------------------------------------------------------- fitting

def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -0.999999:
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        axis /= np.linalg.norm(axis)
        k = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
        return np.eye(3) + 2 * k @ k
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k * (1.0 / (1.0 + c))


@dataclass
class Fit:
    scale: float
    titus_joints: np.ndarray            # (n_bones, 3) UE cm, scaled
    transforms: np.ndarray              # (n_bones, 4, 4) fit transform per Titus bone
    cloud_shares: list[dict[int, float]]  # per Titus bone: cloud bone index → share
    report: list[str] = field(default_factory=list)


def fit_skeleton(tpl: sm2tpl.Template, cloud_bones, bone_rows: list[dict]) -> Fit:
    n = tpl.n_bones
    objs = tpl.objects
    names = [o.name for o in objs[:n]]
    index = {nm: i for i, nm in enumerate(names)}
    parent = [o.parent if 0 <= o.parent < n else -1 for o in objs[:n]]

    cloud_names = {b.name: i for i, b in enumerate(cloud_bones)}
    cloud_g = cloud_bind_globals(cloud_bones)
    cj = {nm: cloud_g[i][:3, 3] for nm, i in cloud_names.items()}

    raw = np.array([o.matrix_lt[12:15] for o in objs[:n]], dtype=np.float64)
    ue = (SM2_TO_UE @ raw.T).T * 100.0
    # Height fit: Titus head over ankles onto Cloud's head over ankles.
    t_h = ue[index["HEAD"], 2] - ue[index["FOOT1L"], 2]
    c_h = cj["C_Head_a"][2] - cj["L_Foot_a"][2]
    scale = c_h / t_h
    tj = ue * scale

    def row_for(name: str) -> dict:
        for r in bone_rows:
            if fnmatch.fnmatchcase(name, r["titus_bone"]):
                return r
        raise KeyError(name)

    rows = [row_for(nm) for nm in names]
    transforms = np.zeros((n, 4, 4))
    done = [False] * n
    report = [f"scale {scale:.4f} (Titus {t_h:.1f} cm head-to-ankle, Cloud {c_h:.1f} cm)"]

    def fit(i: int) -> np.ndarray:
        if done[i]:
            return transforms[i]
        r = rows[i]
        t = np.eye(4)
        if r["align"] == "snap":
            cloud = next(iter(r["cloud_bones"]))
            t[:3, 3] = cj[cloud] - tj[i]
        elif r["align"] == "segment":
            cloud = next(iter(r["cloud_bones"]))
            a = tj[index[r["child_titus"]]] - tj[i]
            b = cj[r["child_cloud"]] - cj[cloud]
            rot = _rotation_between(a, b)
            t[:3, :3] = rot
            t[:3, 3] = cj[cloud] - rot @ tj[i]
        else:  # inherit
            p = parent[i]
            while p >= 0 and rows[p]["align"] == "inherit" and not done[p]:
                p = parent[p]
            t = fit(p).copy() if p >= 0 else np.eye(4)
            if p < 0:
                report.append(f"bone {names[i]} has no fitted ancestor: identity")
        transforms[i] = t
        done[i] = True
        return t

    for i in range(n):
        fit(i)

    shares: list[dict[int, float]] = []
    for i in range(n):
        j = i
        while rows[j]["cloud_bones"] == "parent":
            j = parent[j]
            if j < 0:
                raise ValueError(f"bone {names[i]} inherits but has no mapped ancestor")
        shares.append({cloud_names[k]: float(v) for k, v in rows[j]["cloud_bones"].items()})
    return Fit(scale, tj, transforms, shares, report)


# ---------------------------------------------------------------- mesh

@dataclass
class Section:
    armor_id: str
    positions: np.ndarray   # (v, 3) UE cm
    normals: np.ndarray     # (v, 3)
    uvs: np.ndarray         # (v, 2) UE convention (top-left origin)
    joints: list[list[int]]   # cloud bone indices (global), per vertex
    weights: list[list[float]]
    triangles: np.ndarray   # (f, 3) local indices


def _part_splits(tpl: sm2tpl.Template, part_rows: dict[str, dict]) -> list[int]:
    out = []
    for i, s in enumerate(tpl.splits):
        name = tpl.objects[s.node].name
        row = part_rows.get(name)
        if row is not None and row["include"]:
            out.append(i)
    return out


def build_sections(tpl: sm2tpl.Template, data: bytes, fit: Fit) -> tuple[list[Section], list[str]]:
    part_rows = sheets.rows("titus_parts")
    armor = {r["sm2_texture"]: r for r in sheets.load("armor_sets")["rows"] if r["include"]}
    log: list[str] = []
    groups: dict[str, list[sm2tpl.MeshPart]] = {}
    for si in _part_splits(tpl, part_rows):
        part = sm2tpl.decode_split(tpl, data, si)
        tex = part.material.get("layer0", {}).get("texName", "")
        row = armor.get(tex)
        if row is None:
            log.append(f"split {si} ({tpl.objects[part.node].name}) uses unlisted texture {tex!r}: skipped")
            continue
        groups.setdefault(row["id"], []).append(part)

    sections: list[Section] = []
    for armor_id, parts in groups.items():
        pos, nrm, uv, jnt, wgt, tri = [], [], [], [], [], []
        base = 0
        for p in parts:
            P = np.asarray(p.positions, dtype=np.float64)
            N = np.asarray([n if n is not None else (0.0, 1.0, 0.0) for n in p.normals], dtype=np.float64)
            P = (SM2_TO_UE @ P.T).T * 100.0 * fit.scale
            N = (SM2_TO_UE @ N.T).T
            newP = np.zeros_like(P)
            newN = np.zeros_like(N)
            for v, infl in enumerate(p.weights):
                if not infl:
                    infl = [(0, 1.0)]
                total = sum(w for _, w in infl) or 1.0
                m = np.zeros((4, 4))
                for b, w in infl:
                    m += fit.transforms[b] * (w / total)
                newP[v] = m[:3, :3] @ P[v] + m[:3, 3]
                newN[v] = m[:3, :3] @ N[v]
                acc: dict[int, float] = {}
                for b, w in infl:
                    for cb, share in fit.cloud_shares[b].items():
                        acc[cb] = acc.get(cb, 0.0) + w * share / total
                top = sorted(acc.items(), key=lambda kv: -kv[1])[:MAX_INFLUENCES]
                s = sum(w for _, w in top) or 1.0
                jnt.append([cb for cb, _ in top])
                wgt.append([w / s for _, w in top])
            newN /= np.maximum(np.linalg.norm(newN, axis=1, keepdims=True), 1e-8)
            pos.append(newP)
            nrm.append(newN)
            # SM2 UVs were decoded as (u, 1-v); UE keeps the DirectX top-left origin.
            uv.append(np.array([(u[0], 1.0 - u[1]) if u else (0.0, 0.0) for u in p.uvs]))
            tri.append(np.asarray(p.triangles, dtype=np.int64) + base)
            base += len(P)
        sections.append(Section(armor_id, np.concatenate(pos), np.concatenate(nrm), np.concatenate(uv),
                                jnt, wgt, np.concatenate(tri)))
        log.append(f"section {armor_id}: {base} vertices, {sum(len(t) for t in tri)} triangles")
    return sections, log


def winding_agrees(positions: np.ndarray, normals: np.ndarray, tris: np.ndarray) -> float:
    """Share of triangles whose cross product points along the vertex normals."""
    a, b, c = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
    face = np.cross(b - a, c - a)
    vn = normals[tris[:, 0]] + normals[tris[:, 1]] + normals[tris[:, 2]]
    return float(np.mean(np.einsum("ij,ij->i", face, vn) > 0))


def tangents(positions: np.ndarray, normals: np.ndarray, uvs: np.ndarray, tris: np.ndarray):
    """Per-vertex tangent and bitangent sign from UV derivatives (accumulated per face)."""
    p0, p1, p2 = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
    w0, w1, w2 = uvs[tris[:, 0]], uvs[tris[:, 1]], uvs[tris[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = w1 - w0, w2 - w0
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-12, 1e-12, r)
    sdir = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / r[:, None]
    tdir = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / r[:, None]
    tan = np.zeros_like(positions)
    bit = np.zeros_like(positions)
    for k in range(3):
        np.add.at(tan, tris[:, k], sdir)
        np.add.at(bit, tris[:, k], tdir)
    t = tan - normals * np.einsum("ij,ij->i", normals, tan)[:, None]
    bad = np.linalg.norm(t, axis=1) < 1e-8
    t[bad] = np.cross(normals[bad], [0.0, 0.0, 1.0])
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-8)
    sign = np.where(np.einsum("ij,ij->i", np.cross(normals, t), bit) < 0.0, -1.0, 1.0)
    return t, sign
