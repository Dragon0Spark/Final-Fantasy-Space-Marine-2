"""Read metadata from the player's archives without extracting game content."""

from __future__ import annotations

import argparse
import json
import re
import struct
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArchiveEntry:
    archive: str
    member: str
    size: int
    crc32: str


class Sm2ContentCatalog:
    def __init__(self, game_root: Path) -> None:
        self.game_root = game_root.resolve(strict=True)
        self.archive_root = self.game_root / "client_pc/root/paks/client"
        if not self.archive_root.is_dir():
            raise ValueError("The selected folder is not an installed SM2 client.")

    def find_entries(self, expression: str) -> list[ArchiveEntry]:
        pattern = re.compile(expression, re.IGNORECASE)
        entries = []
        for archive in sorted(self.archive_root.rglob("*.pak")):
            if not zipfile.is_zipfile(archive):
                continue
            with zipfile.ZipFile(archive) as opened:
                for member in opened.infolist():
                    if pattern.search(member.filename):
                        entries.append(ArchiveEntry(
                            archive.relative_to(self.game_root).as_posix(),
                            member.filename, member.file_size, f"{member.CRC:08x}"))
        return entries

    def read_animation_header(self, entry: ArchiveEntry) -> dict:
        # Bound the read: discovery never decodes an animation or writes one out.
        with zipfile.ZipFile(self.game_root / entry.archive) as opened:
            with opened.open(entry.member) as stream:
                header = stream.read(32)
        if len(header) != 32 or header[:4] != b"ETNA":
            return {"format": "unsupported", "verified": False}
        chunk_offset, duration, fps, frames, tracks, curves = struct.unpack_from(
            "<IffIII", header, 8)
        return {
            "format": "ETNA", "version": header[4],
            "duration_s": duration, "fps": fps, "frames": frames,
            "tracks": tracks, "curves": curves,
            "chunk_offset": chunk_offset,
            "verified": 32 <= chunk_offset < entry.size and fps > 0 and frames > 0,
            "pose_decode_verified": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--match", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    catalog = Sm2ContentCatalog(args.game)
    entries = catalog.find_entries(args.match)
    rows = []
    for entry in entries:
        row = asdict(entry)
        if entry.member.endswith(".sani"):
            row["animation"] = catalog.read_animation_header(entry)
        rows.append(row)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        "game_content_extracted": False,
        "game_content_written": False,
        "entries": rows,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"matches": len(rows), "game_content_written": False}))


if __name__ == "__main__":
    main()
