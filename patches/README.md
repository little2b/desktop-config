# Niri compatibility patch

`niri-desktop.patch` records the complete local changes used by the installed
Niri build: the HiDPI Genie coordinate correction, its geometry tests, and
PipeWire SHM mapping/frame pacing adjustments. Apply it only to the commit in
`sources.lock.json`; the installer verifies the patch SHA-256 first.

The patched source is [StatIndet/niri-edge](https://github.com/StatIndet/niri-edge),
derived from [niri-wm/niri](https://github.com/niri-wm/niri). Its GPL-3.0-or-later
license applies to the source and these changes. The installer downloads the
complete source, license and notices before building; no machine-specific
executable is stored in this repository.
