"""Index every entry in the player's FF7R paks (path, size, compression, encryption, pak).

Usage: python -I index_ff7r_paks.py <ff7r root> <out.tsv>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import ff7rkey  # noqa: E402
import ue4pak  # noqa: E402


def main() -> None:
    game = Path(sys.argv[1])
    out = Path(sys.argv[2])
    paks = sorted((game / "End/Content/Paks").glob("*.pak"))
    key = ff7rkey.find_key(game / "End/Binaries/Win64/ff7remake_.exe", paks[0])
    aes = ff7rkey.AesEcb(key)
    lines = []
    for pak_path in paks:
        pak = ue4pak.open_pak(pak_path, aes)
        for name, e in pak.entries.items():
            lines.append(f"{pak.mount}{name}\t{e.usize}\t{e.compression}\t{int(e.encrypted)}\t{pak_path.name}")
        print(pak_path.name, pak.mount, len(pak.entries))
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
