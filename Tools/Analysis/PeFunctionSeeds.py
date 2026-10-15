"""Locate native registration thunks in the installed UE executable, read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PeSection:
    name: str
    rva: int
    virtual_size: int
    file_offset: int
    file_size: int
    executable: bool


class PeFunctionSeeds:
    def __init__(self, executable: Path) -> None:
        self.executable = executable
        self.data = executable.read_bytes()
        if self.data[:2] != b"MZ":
            raise ValueError("Not a PE executable")
        pe_offset = struct.unpack_from("<I", self.data, 0x3C)[0]
        if self.data[pe_offset:pe_offset + 4] != b"PE\0\0":
            raise ValueError("Invalid PE header")
        section_count = struct.unpack_from("<H", self.data, pe_offset + 6)[0]
        optional_size = struct.unpack_from("<H", self.data, pe_offset + 20)[0]
        optional = pe_offset + 24
        if struct.unpack_from("<H", self.data, optional)[0] != 0x20B:
            raise ValueError("Expected a PE32+ executable")
        self.image_base = struct.unpack_from("<Q", self.data, optional + 24)[0]
        self.sections = []
        for index in range(section_count):
            offset = optional + optional_size + 40 * index
            name, size, rva, raw_size, raw_offset = struct.unpack_from("<8sIIII", self.data, offset)
            flags = struct.unpack_from("<I", self.data, offset + 36)[0]
            self.sections.append(PeSection(name.rstrip(b"\0").decode("ascii"), rva,
                                           size, raw_offset, raw_size, bool(flags & 0x20000000)))

    def offset_to_va(self, offset: int) -> int:
        for section in self.sections:
            if section.file_offset <= offset < section.file_offset + section.file_size:
                return self.image_base + section.rva + offset - section.file_offset
        raise ValueError("Offset outside file-backed PE sections")

    def is_code_pointer(self, address: int) -> bool:
        return any(section.executable and
                   self.image_base + section.rva <= address <
                   self.image_base + section.rva + section.virtual_size
                   for section in self.sections)

    def find_registration(self, function_name: str) -> list[dict]:
        text = function_name.encode("ascii") + b"\0"
        rows = []
        string_offset = self.data.find(text)
        while string_offset >= 0:
            string_va = self.offset_to_va(string_offset)
            pointer = struct.pack("<Q", string_va)
            reference_offset = self.data.find(pointer)
            while reference_offset >= 0:
                if reference_offset + 16 <= len(self.data):
                    function_va = struct.unpack_from("<Q", self.data, reference_offset + 8)[0]
                    if self.is_code_pointer(function_va):
                        rows.append({
                            "name": function_name,
                            "string_va": hex(string_va),
                            "table_va": hex(self.offset_to_va(reference_offset)),
                            "function_va": hex(function_va),
                            "interpretation": "candidate UE native registration pair; decompile to confirm",
                        })
                reference_offset = self.data.find(pointer, reference_offset + 1)
            string_offset = self.data.find(text, string_offset + 1)
        return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--functions", nargs="+", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    reader = PeFunctionSeeds(args.exe)
    rows = [row for name in args.functions for row in reader.find_registration(name)]
    report = {
        "binary_sha256": hashlib.sha256(reader.data).hexdigest(),
        "image_base": hex(reader.image_base), "target_executed": False,
        "binary_copied": False, "registration_candidates": rows,
        "unresolved": [name for name in args.functions if not any(row["name"] == name for row in rows)],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
