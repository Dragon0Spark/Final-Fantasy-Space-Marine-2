# Validation boundaries

The archive discovery tool opened the installed SM2 ZIP archives read-only and
wrote metadata only: entry paths, sizes, CRCs and bounded animation headers.
The animation and media bytes are not present in this repository.

The For the Emperor animation header was found and checked. Decoding, retargeting,
voice selection and host playback are not verified.

The sheet preflight currently fails on 16 unfinished cells. This is an expected
release/build block, not a successful gameplay test. Do not replace those cells
with success text without obtaining the corresponding evidence.

The initial host probe was loaded into the already-running legacy session and
the game crashed. No combat or equipment change was verified by it. The revised
source disables its complex equipment call and new hooks; a separate external
query/read-only observer is pending live validation. Registering a callback is
not evidence that it fired or controls gameplay. See `Investigation.md`.

The metadata-only Melty recipe check is exploratory. A real packaged release
still needs full file inspection, recipe validation, one-click installation,
successful gameplay checks and media. No such release exists yet.
