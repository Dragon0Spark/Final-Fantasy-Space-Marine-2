"""Dev check: fit Titus onto Cloud's skeleton and write OBJs (Titus fitted + Cloud original) to compare."""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "External"))

import numpy as np  # noqa: E402

import sheets  # noqa: E402
import sm2tpl  # noqa: E402
import titus_mesh  # noqa: E402
from bua.unreal.uasset import Uasset  # noqa: E402
from ff7rpaks import FF7RPaks  # noqa: E402

CFG = json.loads((HERE.parent.parent / "Config/paths.json").read_text())
OUT = Path(CFG["work"]) / "fit"
OUT.mkdir(parents=True, exist_ok=True)

paks = FF7RPaks(Path(CFG["ff7r_root"]))
tmp = Path(tempfile.mkdtemp())
files = paks.extract_asset("End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard/Model/PC0000_00", tmp)
cloud = Uasset(str(files[0]), version="ff7r").uexp.mesh
bones = cloud.skeleton.bones

tpl_bytes, data = titus_mesh.read_titus_files(Path(CFG["sm2_root"]))
tpl = sm2tpl.read_template(tpl_bytes)
fit = titus_mesh.fit_skeleton(tpl, bones, sheets.load("bone_map")["rows"])
print("\n".join(fit.report))
secs, log = titus_mesh.build_sections(tpl, data, fit)
print("\n".join(log))

with open(OUT / "titus_fitted.obj", "w") as f:
    base = 1
    for s in secs:
        f.write(f"o {s.armor_id}\n")
        for p in s.positions:
            f.write("v %f %f %f\n" % (p[0], -p[1], p[2]))  # UE → right-handed for viewing
        for t in s.triangles:
            f.write(f"f {t[0] + base} {t[2] + base} {t[1] + base}\n")
        base += len(s.positions)
        print(s.armor_id, "winding agrees:", round(titus_mesh.winding_agrees(s.positions, s.normals, s.triangles), 3))

lod = cloud.LODs[0]
_, cpos, _ = lod.vb.parse()
idx = lod.ib.parse() if hasattr(lod.ib, "parse") else None
cpos = np.asarray(cpos)
with open(OUT / "cloud.obj", "w") as f:
    f.write("o cloud\n")
    for p in cpos:
        f.write("v %f %f %f\n" % (p[0], -p[1], p[2]))
    if idx is not None:
        idx = np.asarray(idx).reshape(-1, 3)
        for t in idx:
            f.write(f"f {t[0] + 1} {t[2] + 1} {t[1] + 1}\n")
print("cloud verts", len(cpos), "bbox", cpos.min(0).round(1), cpos.max(0).round(1))
allp = np.concatenate([s.positions for s in secs])
print("titus bbox", allp.min(0).round(1), allp.max(0).round(1))
