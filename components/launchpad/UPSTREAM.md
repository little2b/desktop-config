# Launchpad for Niri

Based on [cccp00-cup/macos-launchpad-for-linux](https://github.com/cccp00-cup/macos-launchpad-for-linux), commit `c4db4d8a708cf27935534f6bc87c72318940190f` (2026-09-25), GPL-3.0. The original QML interaction design and drag/folder regression tests are retained.

This adaptation uses LayerShellQt for Niri, the Clavis wallpaper and saved Launchpad layout, XDG desktop entries, background icon preparation, and one opening/closing animation for the whole menu. KDE GlobalAccel is replaced by local IPC, so Clavis and Niri can invoke `clavis-launchpad --toggle`.

Build with CMake and Qt 6, LayerShellQt, and GIO. `scripts/build-launchpad.sh` at the repository root builds and installs the executable. The user service runs `clavis-launchpad --background`. `--show`, `--hide`, `--toggle`, `--status`, and `--watch` are local IPC clients; `--output NAME` chooses the screen.

The layout is shared with Clavis at `~/.config/clavis/launchpad.json`; the backend preference is `~/.config/clavis/launchpad-backend.json`. Set `external` to `false` to select the built-in menu.

Applications run in separate systemd user scopes so restarting the launcher does not close them. Temporarily unavailable entries remain in the saved layout and reappear after installation. The Clavis Settings entry is supplied through Clavis IPC.

Validation: configure with `-DBUILD_TESTING=ON`, build, and run `ctest --test-dir BUILD_DIR --output-on-failure`. The interaction tests, XDG/layout tests, and daemon IPC tests use temporary configuration; the GUI tests run offscreen.
