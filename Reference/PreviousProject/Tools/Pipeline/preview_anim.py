"""Dev check: skin Titus's SM2 mesh with a decoded SM2 animation and write OBJs for a few frames.

Usage: python -I preview_anim.py <animation path substring> <out dir> [frame ...]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import sheets  # noqa: E402
import sm2anim  # noqa: E402
import sm2tpl  # noqa: E402
import titus_mesh  # noqa: E402

CFG = json.loads((HERE.parent.parent / "Config/paths.json").read_text())


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def main() -> None:
    needle, out = sys.argv[1], Path(sys.argv[2])
    frames = [int(x) for x in sys.argv[3:]] or [0]
    out.mkdir(parents=True, exist_ok=True)
    sm2 = Path(CFG["sm2_root"])
    lib = sm2anim.SM2Animations(sm2)
    hits = lib.find(needle)
    print("animation:", hits[0], f"({len(hits)} matches)")
    anim = lib.load(hits[0])
    print("frames", anim.frames, "fps", anim.fps, "pos tracks", len(anim.pos_tracks), "rot tracks", len(anim.rot_tracks))

    tpl_bytes, data = titus_mesh.read_titus_files(sm2)
    tpl = sm2tpl.read_template(tpl_bytes)
    objs = tpl.objects
    nb = tpl.n_bones
    G_bind = [np.array(o.matrix_lt).reshape(4, 4) for o in objs]
    index = {o.name: i for i, o in enumerate(objs)}
    parent = [o.parent for o in objs]

    def bind_local(i):
        p = parent[i]
        return G_bind[i] @ np.linalg.inv(G_bind[p]) if 0 <= p < len(objs) else G_bind[i]

    track_of = {name: t for t, name in enumerate(anim.tracks)}
    pos_slot = {t: k for k, t in enumerate(anim.pos_tracks)}
    rot_slot = {t: k for k, t in enumerate(anim.rot_tracks)}

    part_rows = sheets.rows("titus_parts")
    parts = []
    for si, s in enumerate(tpl.splits):
        row = part_rows.get(objs[s.node].name)
        if row and row["include"]:
            parts.append(sm2tpl.decode_split(tpl, data, si))

    for fr in frames:
        G = [None] * len(objs)

        def glob(i):
            if G[i] is not None:
                return G[i]
            L = bind_local(i).copy()
            t = track_of.get(objs[i].name)
            if t is not None:
                if t in rot_slot:
                    L[:3, :3] = quat_to_mat(anim.rotations[fr, rot_slot[t]]).T
                if t in pos_slot:
                    L[3, :3] = anim.positions[fr, pos_slot[t]]
            p = parent[i]
            G[i] = L @ glob(p) if 0 <= p < len(objs) else L
            return G[i]

        skin = [np.linalg.inv(G_bind[b]) @ glob(b) for b in range(nb)]
        with open(out / f"frame_{fr:03d}.obj", "w") as f:
            base = 1
            for part in parts:
                P = np.asarray(part.positions)
                Ph = np.concatenate([P, np.ones((len(P), 1))], axis=1)
                newP = np.zeros_like(P)
                for v, infl in enumerate(part.weights):
                    if not infl:
                        infl = [(0, 1.0)]
                    tot = sum(w for _, w in infl) or 1.0
                    acc = np.zeros(4)
                    for b, w in infl:
                        acc += (Ph[v] @ skin[b]) * (w / tot)
                    newP[v] = acc[:3]
                for p in newP:
                    f.write("v %f %f %f\n" % tuple(p))
                for a, b, c in part.triangles:
                    f.write(f"f {a + base} {b + base} {c + base}\n")
                base += len(P)
        print("wrote frame", fr)


if __name__ == "__main__":
    main()
