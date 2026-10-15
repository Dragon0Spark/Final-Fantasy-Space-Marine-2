# MODLOG — SpaceMarineFFVII (Titus in Midgar)

Journal for the Space Marine 2 × FFVII Remake Intergrade mashup. Anything not written here is lost at the
next context compaction.

## Design (agreed with the user, 2026-10-10)
- Host (primary): FINAL FANTASY VII REMAKE INTERGRADE (Epic, `E:\Jeux\Epic Games\FFVIIRemakeIntergrade`,
  AppVersionString `0212_0617_FF7R_FullPCMasterWin64`, Melty slug `final-fantasy-vii-remake`).
- Companion: Warhammer 40,000: Space Marine 2 (Steam 2183900, `E:\SteamLibrary\steamapps\common\Space Marine 2`,
  Melty slug `custom-warhammer-40-000-space-marine-2`). Read from its files only, never launched or hooked
  (it is online-capable with EasyAntiCheat).
- Solo (Remake has no multiplayer).
- Titus replaces Cloud everywhere (field, cutscenes, battle). Setting: Titus only / Cloud only / both.
- Battle as Titus: real-time chainsword combos, parry → gun strike, executions on staggered enemies that
  refill armor, bolter at range, frag/krak grenades; Space Marine 2 survival rules (armor plates, contested
  health). ATB menu stays for party swap, materia and Titus's moves.
- Equipment: weapon slot = melee weapon (Cloud's 6 swords → SM2 melee weapons), accessory slot = gun,
  materia slots kept.
- From SM2: Titus's model, voice lines, weapon/execution SFX; Limit Break = Fury (Fureur).
- HUD: SM2 armor/health bars for Titus + Remake command menu for swaps and materia. Remake music stays.
- Scope v1: Chapter 1 polished + whole game playable from any save.

## Recon
- FF7R: UE 4.18 fork, pak v4 with encrypted index (byte before footer magic = 1), 25 paks, no IoStore.
  Exe `End/Binaries/Win64/ff7remake_.exe` (no Denuvo sections; imports dwmapi.dll and XINPUT1_3.dll).
  No anti-cheat. `um scan`: no loaders installed.
- UE4SS experimental (`UE4SS_v3.0.1-1164-g5e627997`) ships an official custom config
  `zCustomGameConfigs/Final Fantasy 7 Remake` (engine 4.18 override, member layouts, GUObjectArray AOB).
- FF7R saves: `Documents\My Games` does not exist yet → the game has not been run on this PC.
- SM2: Swarm engine; paks are plain zip (`client_pc/root/paks/client/**`). Official mod route = paks in
  `client_pc/root/mods` (+ `pak_config.yaml`) or loose files in `client_pc/root/local`. EasyAntiCheat present.
  Titus: `tpl/cc_titus.tpl/` (`.tpl` 775 KB + `.tpl_data` 28.5 MB geometry), outfits in
  `ssl/characters/player/marine/outfits/story_titus/`, voice in `default_sound_<lang>.pak` (Wwise).
  Official Model Converter only goes glTF/USF → game, no exporter. LibSaber (Wildenhaus, branch
  experimental-2, no license) has `LibSaber.SpaceMarine2` + `SM2ModelExporter`: study only, don't ship.

## Route (chosen)
- Runtime: UE4SS (MIT, bundled with credit) + our Lua/C++ mod in FF7R for gameplay, HUD and audio.
- Assets: a setup-time converter (runs on the player's PC before first launch) reads Titus's model,
  textures and sounds from the player's SM2 paks and Cloud's assets from the player's FF7R paks (pak key
  derived from the player's own exe, never shipped), writes a private `~mods` pak + audio cache.
- Never ship game files, extracted assets or keys.

## Log
- 2026-10-10: interview done; recon above; UE4SS FF7R config found.
- 2026-10-10 21:42: UE4SS experimental + FF7R config loads (Lua mods start, GUObjectArray found; HashTables
  AOB faults → lookups fall back to GUObjectArray). SDK + object dump done (moved to
  `E:\Jeux\_work\SpaceMarineFFVII\ff7r-dump`). Battle data tables are reflected (FEndDataTableBattle*,
  FEndDataTableEquipment/Item/LimitBreak/Materia); battle runtime itself is mostly native.
  `UEndMenuBPAPI` exposes BPGet/SetPlayerHP/HPMax/MP/Limit/LimitLevel per EPlayerType.
- 2026-10-10 21:46: crash (EXCEPTION_ACCESS_VIOLATION reading 0xffffffff inside UE4SS.dll) a few
  minutes after the SDK dump, while the user played. Fix: minimal UE4SS profile — all example mods off,
  hooks AActorTick/UStructLink/LocalPlayerExec/ProcessConsoleExec/CallFunctionByNameWithArguments/
  BeginPlay/EndPlay/LoadMap off; keep ProcessEvent, ProcessInternal, InitGameState, EngineTick,
  GameViewportClientTick. Original FF7R config saved in `_work/UE4SS-settings.ff7r-original.ini`.
  Stability under this profile NOT yet verified in gameplay.
- 2026-10-10/11: SM2 model reader (Tools/Pipeline/sm2tpl.py, own code from LibSaber format notes) decodes
  cc_titus LOD0 (188 bones, matrix_lt = global bind, row-major translation at [12:15]); preview render OK.
  FF7R pak key derived from the player's exe (ff7rkey.py, Windows CNG AES); content entries Oodle (method 4)
  via the game's own Engine/Binaries/ThirdParty/Oodle/Win64/oo2core_7_win64.dll. Cloud = PC0000_00
  (547 bones, 12 material slots, LOD0 100k verts, uv_num 3, up to 8 influences). FName hashes
  (Strihash_DEPRECATED & StrCrc32, 16-bit each) verified 51/51 → ue4names.py.
  Material params: 0:0 Color(_C BC1), 0:2 Metallic/Roughness/Variant (_M BC1: R metal, G rough, B 1),
  0:3 Normal (_N BC5), 1:0 Occlusion (_O BC4), 0:5 DetailOpacity (_B BC1), 0:1 Coverage (_A BC4).
  SM2 textures: albedo BC7 already Ultramarine blue; _spec BC7 (R metal, G gloss, B AO); _nm DXN.
  Fit: scale 0.709, 14 armour sections, ~353k verts. Winding: Titus in UE space and Cloud both have
  face-cross opposite to normals (same convention) → keep indices.
- 2026-10-11 09:30: build_titus.py end to end OK → SpaceMarineFFVII_Titus_P.pak (229 files, 198 MB, pak v4,
  mount ../../../): 14 SMT_* material instances (clones of Cloud's, uexp kept), 70 SMT_* textures (texconv:
  C BC1, M BC1 [R metal, G 255-gloss, B 255], N BC5, O BC4 from spec.B, B 256² black, A BC4), PC0000_00
  with Titus (353,636 verts, 14 sections, 8 influences, LOD1+ removed, KDI removed). Round-trip parse OK.
  Installed in End/Content/Paks/~mods. NOT yet seen in game.
- 2026-10-11: computer-use request (Epic Games Launcher + "FINAL FANTASY VII") denied by the user → no
  in-game test yet. Probe mod SMFF7Probe installed (hooks OnTakeDamage/OnGiveDamage/OnBurstBegin...).
- Audio: SM2 Wwise v150 banks; events resolved by FNV-1(lowercase) → HIRC; skip first 24 bytes of a
  container body (parent ids). VO = external_sources_vorbis_<lang>.zip named .wem. vgmstream r2117
  (ISC-style) decodes. FF7R plays everything through SEAD (USQEXSEADSound : USoundWave, SAB inside
  uexp at ~165, mtrl codec 0x07 HCA). SEAD SAB also defines PCM16 (0x01) → plan: clone a SEAD sound and
  write PCM mtrl; play with USQEXSEADStatics:PlaySound2D from Lua (no extra executable).
