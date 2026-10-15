"""Index every file inside Space Marine 2's zip paks (names + sizes), read in place.

Usage: python -I index_sm2_paks.py <sm2 root> <out dir>
Writes one <pak>.txt per pak: "<size>\t<path>" lines.
"""
import sys
import zipfile
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    paks = sorted((root / "client_pc" / "root" / "paks").rglob("*.pak"))
    for pak in paks:
        try:
            with zipfile.ZipFile(pak) as zf:
                lines = [f"{i.file_size}\t{i.filename}" for i in zf.infolist()]
        except zipfile.BadZipFile as exc:
            lines = [f"BAD\t{exc}"]
        rel = pak.relative_to(root).as_posix().replace("/", "__")
        (out_dir / f"{rel}.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"{len(lines):8d} {pak.name}")


if __name__ == "__main__":
    main()
