"""Load and save design sheets (one row per line, so diffs stay readable)."""
from __future__ import annotations

import json
from pathlib import Path

SHEETS = Path(__file__).resolve().parent.parent.parent / "Sheets"


def load(name: str) -> dict:
    return json.loads((SHEETS / f"{name}.json").read_text(encoding="utf-8"))


def rows(name: str) -> dict[str, dict]:
    return {r["id"]: r for r in load(name)["rows"]}


def save(name: str, sheet: dict) -> None:
    head = {k: v for k, v in sheet.items() if k != "rows"}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, indent=2).replace(chr(10), chr(10) + '  ')},")
    lines.append('  "rows": [')
    body = [f"    {json.dumps(r, ensure_ascii=False)}" for r in sheet["rows"]]
    lines.append(",\n".join(body))
    lines.append("  ]")
    lines.append("}")
    (SHEETS / f"{name}.json").write_text("\n".join(lines) + "\n", encoding="utf-8")
