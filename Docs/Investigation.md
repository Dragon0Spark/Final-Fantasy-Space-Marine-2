# Proportion and native-code investigation — 2026-10-15

## Scope and delivered code

The host remains FFVII Remake Intergrade, solo, with SM2 required as companion.
The running legacy mesh was inspected and a game-only baseline screenshot saved
locally. No game was launched, intentionally closed or restarted by this work.
The baseline is an older prototype and must not be used as new-release media.

The old fitting code scales Titus to 0.709 of native size, then separately snaps
his joints onto Cloud. At that scale the source upper arm and forearm remain
about 5.04 cm and 5.77 cm longer than the corresponding host segments. The scaled
shoulder span is about 47.72 cm versus 31.87 cm between the host arm origins.
These incompatible anchors are a measured fitting defect, not a cosmetic scale
setting that can fix the whole body.

New original pose/skinning code preserves the donor hierarchy and native lengths.
It supports donor parents occurring after children and rejects cycles, unweighted
vertices and rotation matrices that introduce scale/shear. Six focused numerical
tests pass. An in-memory audit of 188 source bones and 10,240 actual source
vertices passes with errors below 1e-7 and 1e-6 cm respectively. No asset parts
were extracted or written. The adapter reads FFVII asset parts directly in RAM.

This is not applied to the live renderer yet. A correct runtime bridge still
needs mesh creation, materials, animation decoding, skinning updates and host
integration. No corrected in-game screenshot exists. The full build preflight
continues to block release work on unfinished cells.

## Native-code observations

Ghidra 12.1.4 was acquired from the official NSA/Ghidra release; its download
matched the release asset's published SHA-256 digest. It uses the existing
Android Studio Java 21 runtime. No global Java or REA configuration was changed.
The connected REA server has no configured native provider, so focused analysis
used Ghidra's headless CLI directly against each installed executable on E:.

FFVII executable SHA-256:
`64137c36d0937e6b381019830cd6c55b4c038473eb7dbf1166f86f4ffd8345c0`.

Selected reflected native thunks were located from the binary registration pairs,
then decompiled along with selected implementation functions. Findings include:

- Native HP read/write and the manager-relative data access they use.
- Equipment selection branches for weapon, armor and accessory.
- The equipment call constructs/copies a complex structure with strings and
  arrays, rather than returning a simple item identifier.
- Native entry points for damage-source creation, damage events and stagger.

SM2 analysis recovered selected functions referencing its SANI animation subsystem
and shield effects. These are partial native observations, not a full recovery of
combat rules. Reading the installed declarative files also confirms the existence
of gun-strike animation events, parry timing settings and story-mode healing
configuration. Effective rule inheritance and the complete combat implementation
remain to be resolved before using these as host behavior.

Recovered pseudocode, analysis databases and dumps remain local and excluded from
Git and release packages. The repository includes original analysis scripts and
these conclusions, not either game's decompiled code or binary data.

## Live diagnostic failure and recovery boundary

The original game was PID 32588. REA/Frida successfully found the existing loader's
official `execute_lua_in_mod` export and loaded an original diagnostic into the
existing mod state during an existing game-thread HP poll. Runtime observations
identified the local pawn and an available procedural-mesh class. New hooks
registered, but no combat callback was observed.

The game then crashed during the first new poll. The recorded exception is
`0xc0000409`, parameter `2`, in `UE4SS.dll+0xc99945`, on the same game thread.
This records a fail-fast stack-cookie failure; the complete root cause is not
confirmed. Complex equipment-struct marshaling and the hot/reentrant loading
path are suspects, not established causes.

No target executable, asset pak, loader DLL, loader configuration or existing
mod source was changed. Only source in this workspace and transient runtime
instrumentation were used. The process ended; the instrumentation is gone.
Do not relaunch the user's game without fresh launch authorization.

The diagnostic's complex equipment calls and new hook registration are now
disabled by default. Do not repeat the live injection route. A replacement
external observer requests query/read privileges only, verifies the exact host
executable hash and PID identity, and follows the statically recovered layout.
It cannot inject code, write game memory, start or stop processes. Its layout is
still pending a live validation. The crash snapshot does not retain all required
heap ranges, so it cannot prove the new observer works.

## Remaining release gates

- Apply and visually verify the proportion correction in the host.
- Decode and integrate Titus locomotion, attacks, emote and voice in memory.
- Implement combat rules and menu weapon switching against confirmed host APIs.
- Confirm stable gameplay, complete sheets and generated runtime records.
- Resolve original-code license/remix choice, package without game content,
  validate the actual install, pass Melty tests and capture this version in game.

Nothing has been submitted or published on Melty.
