# Titus in Midgar — development journal

## Accepted design

- Host: Final Fantasy VII Remake Intergrade. Solo.
- Required companion: Warhammer 40,000: Space Marine 2.
- Titus replaces Cloud and brings his Space Marine gameplay and animations.
- Keep FFVII's equipment and command menus, party switching and materia.
- Melee and ranged weapon changes use FFVII's menus.
- Preserve the earlier requirements: armor, contested health, parry/gun strike,
  executions, grenades and Fury. Cloud animations apply only to Cloud weapons.
- New requirement: the real For the Emperor emote, gesture and voice together.
  Default: cosmetic, cancellable, without a combat buff.
- First validation slice: Chapter 1 encounter, chainsword, bolter, equipment
  change and emote. This is a validation slice, not removal of the full scope.

## Current evidence

- Working folder was empty at intake. The earlier source project was located at
  `E:/Jeux/Merge Games/SpaceMarineFFVII`; it remains untouched.
- FFVII: `E:/Jeux/Epic Games/FFVIIRemakeIntergrade`.
- SM2: `E:/SteamLibrary/steamapps/common/Space Marine 2`.
- Prior model pak is already installed in FFVII, but is not approved for this
  project's distribution or copying. Do not package it or run the old converter.
- The old arm/chest deformation, animation decoding and combat integration are
  unresolved. Do not claim the earlier prototype as the new playable build.
- Existing SDK is useful evidence about reflected signatures, not runtime proof.
- No game was running when inspected. Launch and input permission are pending.
- MIT/remix choice asked asynchronously; publishing is pending the answer.

## Architecture boundary

All game content stays in its installed archives. Read only, decode in memory,
release memory when no longer needed. No extracted asset folders, generated game
content paks, WAV caches, shipped original content or copied community mods.
Original code, design sheets, archive entry identifiers and measurement reports
may be stored. Never include executable keys or decrypted source in reports.

Use the existing MIT UE4SS integration for initial FFVII read-only diagnostics.
The candidate recipe with bundled runtime files passed a metadata-only Melty
one-click check on 2026-10-15. This does not prove the runtime works or that a
complete release has passed review. No release was submitted.

## Next evidence needed

1. Resolve the localized emote voice and decode its animation from installed archives.
2. Validate source bindings and equipment API signatures without extracting assets.
3. With launch/input permission, verify combat and equipment callbacks in FFVII.
4. Implement the in-memory model/animation/audio bridge and all gameplay rows.
5. Build only after the complete sheet preflight passes; test in game, package,
   run Melty installation tests, obtain real gameplay media, then request publish.

## 2026-10-15 progress

- Created private GitHub repository at
  `https://github.com/Dragon0Spark/Final-Fantasy-Space-Marine-2` on the creator's
  explicit request. Local Git authentication can access it. The connected GitHub
  app currently returns 404 for this repository; local authenticated Git is the
  working route. No token was written into project files or shown in output.
- Original read-only archive discovery found the actual emote:
  `animation/primaris/tacticus/special/emote/solo/tacticus_emote_solo_for_the_emperror_intercessor.sani`.
  ETNA v2 header: 3.2 seconds, 30 fps, 97 frames, 282 transform tracks.
  Header validity does not prove pose decoding or successful playback.
- Its corresponding sound-event resource exists:
  `sounds/events/char_tacticus_emote_solo_for_the_emperror.sound_event.resource`.
  Actual media/locale selection and playback remain unverified.
- Metadata reports live in ignored `Reports/`. No game content was extracted.
- The old reflected function/parameter dump identifies
  `BPGetCurrentEquipment(PlayerType, EquipType)` returning EndDataTableEquipment,
  with UniqueID and UniqueIndex. Category 0 is Weapon, 2 is Accessory, player 0
  is Cloud. These are historical signatures to verify at runtime.
- Prepared an original read-only diagnostics script under Tools/Diagnostics.
  It observes combat events and polls equipment through host APIs on the game
  thread. It is not installed or run and implements no Titus gameplay yet.
- Complete sheet preflight reports 16 unfinished cells and blocks the gameplay
  build. Nothing was packaged, uploaded, submitted, tested in game or published.
- Historical authored scripts/sheets and journal are preserved under
  Reference/PreviousProject with checksums. These are not active build inputs;
  their extraction/cache-writing paths must not be executed for this project.
