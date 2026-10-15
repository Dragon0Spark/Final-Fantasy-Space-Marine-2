"""Preflight: lay every sheet's rows and columns over each other before a build.

Lists every unfilled cell, every unverified cell, every cross-sheet reference that does not resolve,
and every game file a sheet names that is missing from the player's own installs.

Usage: python -I preflight.py [--strict]   (--strict also fails on unverified cells)
Exit code 1 when anything blocks the build.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
SHEETS = PROJECT / "Sheets"
CONFIG = json.loads((PROJECT / "Config" / "paths.json").read_text(encoding="utf-8"))
SM2_ROOT = Path(CONFIG["sm2_root"])
FF7R_ROOT = Path(CONFIG["ff7r_root"])

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "External"))


def load_sheets() -> dict[str, dict]:
    out = {}
    for p in sorted(SHEETS.glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def walk(value, path=()):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, path + (i,))
    else:
        yield path, value


class Report:
    def __init__(self) -> None:
        self.blocking: list[str] = []
        self.unfilled: list[str] = []
        self.unverified: list[str] = []

    def print(self) -> None:
        for title, items in (("BLOCKING", self.blocking), ("UNFILLED", self.unfilled),
                             ("UNVERIFIED", self.unverified)):
            print(f"== {title}: {len(items)}")
            for line in items:
                print("  " + line)


def sm2_file_index() -> set[str]:
    names: set[str] = set()
    for pak in (SM2_ROOT / "client_pc/root/paks/client").rglob("*.pak"):
        try:
            with zipfile.ZipFile(pak) as z:
                names.update(z.namelist())
        except zipfile.BadZipFile:
            pass
    return names


def sm2_events() -> set[str]:
    import csv
    import io
    events = set()
    root = SM2_ROOT / "client_pc/root/paks/client/default"
    for pak in ("default_sound_11.pak", "default_sound_5.pak"):
        with zipfile.ZipFile(root / pak) as z:
            for n in z.namelist():
                if n.endswith("events.csv"):
                    for row in csv.reader(io.StringIO(z.read(n).decode("utf-8", "replace"))):
                        if len(row) > 2:
                            events.add(row[2])
    return events


def sm2_vo(lang: str = "english") -> set[str]:
    root = SM2_ROOT / "client_pc/root/paks/client/default"
    with zipfile.ZipFile(root / f"default_sound_{lang}.pak") as z:
        with zipfile.ZipFile(z.open(f"sounds/desktop/external_sources_vorbis_{lang}.zip")) as zi:
            return {n[:-4] for n in zi.namelist()}


def check(strict: bool) -> Report:
    rep = Report()
    sheets = load_sheets()
    ids = {name: {row.get("id") for row in s.get("rows", [])} for name, s in sheets.items()}

    print("indexing SM2 paks...")
    sm2_names = sm2_file_index()
    print("indexing FF7R paks...")
    from ff7rpaks import FF7RPaks
    ff7r = FF7RPaks(FF7R_ROOT)
    events = sm2_events()
    vo = sm2_vo()

    for name, sheet in sheets.items():
        cols = list(sheet.get("columns", {}))
        for row in sheet.get("rows", []):
            rid = f"{name}.{row.get('id')}"
            for col in cols:
                if col not in row:
                    rep.unfilled.append(f"{rid}: column '{col}' missing")
            for path, val in walk(row):
                where = f"{rid}.{'.'.join(str(p) for p in path)}"
                if val is None or val == "":
                    col = path[0] if path else ""
                    rep.unfilled.append(where)
                    continue
                if isinstance(val, str):
                    s = val[1:] if val.startswith("?") else val
                    if val.startswith("?"):
                        rep.unverified.append(where if val == "?" else f"{where} = {val}")
                    m = re.match(r"ref:(\w+)\.(\w+)$", s)
                    if m:
                        if m.group(1) not in ids or m.group(2) not in ids[m.group(1)]:
                            rep.blocking.append(f"{where}: unresolved {s}")
                    if s.startswith("sm2:"):
                        if s[4:] not in sm2_names:
                            rep.blocking.append(f"{where}: SM2 file not found: {s[4:]}")
                    if s.startswith("ff7r:"):
                        if s[5:] not in ff7r.files:
                            rep.blocking.append(f"{where}: FF7R file not found: {s[5:]}")
                    if s.startswith("sm2event:") and s[9:] not in events:
                        rep.blocking.append(f"{where}: SM2 sound event not found: {s[9:]}")
                    if s.startswith("sm2vo:") and s[6:] not in vo:
                        rep.blocking.append(f"{where}: SM2 voice line not found: {s[6:]}")

    check_bone_map(sheets["bone_map"], ff7r, rep)
    check_armor_sets(sheets["armor_sets"], sm2_names, rep)
    if strict:
        rep.blocking += [f"unverified: {u}" for u in rep.unverified]
    return rep


def check_bone_map(sheet: dict, ff7r, rep: Report) -> None:
    import sm2tpl
    from bua.unreal.uasset import Uasset
    import tempfile
    tpl_bytes = None
    for pak in sorted((SM2_ROOT / "client_pc/root/paks/client/default").glob("default_tpl_*.pak")):
        with zipfile.ZipFile(pak) as z:
            if "tpl/cc_titus.tpl/cc_titus.tpl" in z.namelist():
                tpl_bytes = z.read("tpl/cc_titus.tpl/cc_titus.tpl")
                break
    tpl = sm2tpl.read_template(tpl_bytes)
    titus_bones = [o.name for o in tpl.objects[:tpl.n_bones]]
    with tempfile.TemporaryDirectory() as tmp:
        files = ff7r.extract_asset(
            "End/Content/GameContents/Character/Player/PC0000_00_Cloud_Standard/Model/PC0000_00_Skeleton",
            Path(tmp))
        skel = Uasset(str(files[0]), version="ff7r").uexp.skeleton
        cloud_bones = {b.name for b in skel.bones}
    rows = sheet["rows"]
    for b in titus_bones:
        if not any(fnmatch.fnmatchcase(b, r["titus_bone"]) for r in rows):
            rep.blocking.append(f"bone_map: Titus bone '{b}' matches no row")
    for r in rows:
        cb = r["cloud_bones"]
        if isinstance(cb, dict):
            for n in cb:
                if n not in cloud_bones:
                    rep.blocking.append(f"bone_map.{r['id']}: Cloud bone '{n}' not in skeleton")
            if abs(sum(cb.values()) - 1.0) > 1e-6:
                rep.blocking.append(f"bone_map.{r['id']}: weights sum to {sum(cb.values())}")
        if r["align"] == "segment":
            if r["child_titus"] not in titus_bones:
                rep.blocking.append(f"bone_map.{r['id']}: child_titus '{r['child_titus']}' not a Titus bone")
            if r["child_cloud"] not in cloud_bones:
                rep.blocking.append(f"bone_map.{r['id']}: child_cloud '{r['child_cloud']}' not a Cloud bone")
        if "*" not in r["titus_bone"] and r["titus_bone"] not in titus_bones:
            rep.blocking.append(f"bone_map.{r['id']}: '{r['titus_bone']}' is not a Titus bone")


def check_armor_sets(sheet: dict, sm2_names: set[str], rep: Report) -> None:
    for r in sheet["rows"]:
        if not r.get("include"):
            continue
        base = r["sm2_texture"]
        for suffix in ("", "_spec", "_nm"):
            if f"pct/{base}{suffix}.pct.resource" not in sm2_names:
                rep.blocking.append(f"armor_sets.{r['id']}: missing pct/{base}{suffix}.pct.resource")
        alpha = r.get("alpha")
        if alpha:
            a = alpha.lstrip("?")
            if f"pct/{a}.pct.resource" not in sm2_names:
                rep.blocking.append(f"armor_sets.{r['id']}: alpha texture {a} not found")


if __name__ == "__main__":
    strict = "--strict" in sys.argv
    report = check(strict)
    report.print()
    sys.exit(1 if report.blocking else 0)
