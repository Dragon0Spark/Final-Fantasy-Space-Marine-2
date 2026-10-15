"""Read single assets out of the player's FF7R paks (newest pak wins, like the engine)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import ff7rkey  # noqa: E402
import ue4pak  # noqa: E402


class FF7RPaks:
    def __init__(self, game: Path) -> None:
        self.game = game
        paks = sorted((game / "End/Content/Paks").glob("*.pak"))
        key = ff7rkey.find_key(game / "End/Binaries/Win64/ff7remake_.exe", paks[0])
        if key is None:
            raise RuntimeError("could not find the pak key in ff7remake_.exe")
        self.aes = ff7rkey.AesEcb(key)
        ue4pak.use_oodle(game / "Engine/Binaries/ThirdParty/Oodle/Win64/oo2core_7_win64.dll")
        self.files: dict[str, tuple[ue4pak.PakFile, ue4pak.PakEntry]] = {}
        for pak_path in paks:
            pak = ue4pak.open_pak(pak_path, self.aes)
            for name, entry in pak.entries.items():
                full = (pak.mount + name).replace("../../../", "")
                self.files[full] = (pak, entry)

    def find(self, needle: str) -> list[str]:
        needle = needle.lower()
        return sorted(p for p in self.files if needle in p.lower())

    def read(self, path: str) -> bytes:
        pak, entry = self.files[path]
        return ue4pak.read_entry(pak, entry, self.aes)

    def extract(self, path: str, out_root: Path) -> Path:
        dest = out_root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.read(path))
        return dest

    def extract_asset(self, asset: str, out_root: Path) -> list[Path]:
        """Extract <asset>.uasset with its .uexp / .ubulk companions."""
        stem = asset.rsplit(".", 1)[0] if asset.endswith((".uasset", ".uexp", ".ubulk")) else asset
        out = []
        for ext in (".uasset", ".uexp", ".ubulk"):
            if stem + ext in self.files:
                out.append(self.extract(stem + ext, out_root))
        return out
