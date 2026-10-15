"""List every missing sheet cell and unresolved reference; block unfinished builds."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


class SheetPreflight:
    def __init__(self, sheet_root: Path) -> None:
        self.sheet_root = sheet_root

    def check(self) -> dict:
        sheets = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.sheet_root.glob("*.json"))
        }
        findings = []
        identities = {}
        for name, sheet in sheets.items():
            seen = set()
            identities[name] = seen
            for row in sheet.get("rows", []):
                row_id = row.get("id")
                if not row_id or row_id in seen:
                    findings.append({"cell": name, "reason": "missing or duplicate row id"})
                seen.add(row_id)

        for name, sheet in sheets.items():
            for row in sheet.get("rows", []):
                for column in sheet.get("columns", []):
                    cell = f"{name}.{row.get('id')}.{column}"
                    if column not in row or row[column] is None or row[column] == "":
                        findings.append({"cell": cell, "reason": "unfilled or unverified"})
                        continue
                    for value in self.walk(row[column]):
                        if isinstance(value, str) and value.startswith("ref:"):
                            match = re.fullmatch(r"ref:([\w]+)\.([\w]+)", value)
                            if not match or match[2] not in identities.get(match[1], set()):
                                findings.append({"cell": cell, "reason": f"unresolved {value}"})
                        if isinstance(value, str) and value.startswith("Unassigned:"):
                            findings.append({"cell": cell, "reason": "runtime binding not verified"})
        if not sheets:
            findings.append({"cell": "sheets", "reason": "no design sheets"})
        return {"can_build": not findings, "findings": findings}

    def walk(self, value):
        if isinstance(value, dict):
            for child in value.values():
                yield from self.walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from self.walk(child)
        else:
            yield value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheets", type=Path, default=Path("Sheets"))
    parser.add_argument("--report", type=Path, default=Path("Reports/preflight.json"))
    args = parser.parse_args()
    report = SheetPreflight(args.sheets).check()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["can_build"] else 1)


if __name__ == "__main__":
    main()
