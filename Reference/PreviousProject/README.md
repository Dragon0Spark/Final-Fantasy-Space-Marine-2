# Historical prototype source

This directory preserves only the earlier project's authored Python scripts,
JSON design sheets and journal. The original project is unchanged. File hashes
in `provenance.json` identify the imported scripts and sheets.

This is reference material, not the active build or the current source of truth.
In particular, do not execute its converters or preflight: some extract assets,
write converted game paks/audio caches, or depend on unbundled third-party tools.
Those behaviors conflict with the current requirement to read installed game
content in memory without copies. Current design lives in the root `Sheets/`.

No extracted game content, generated game paks, SDK dumps, binaries, game keys,
downloads, third-party libraries, textures, meshes, animations or audio are
included here. The prior build's defects and unverified features remain open.
