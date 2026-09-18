#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
for command in niri qs key keytop fcitx5 rclone; do
    command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
[[ -x /usr/local/bin/key ]] || { echo 'Install the pinned source key-cli backend first; see README.md.' >&2; exit 1; }
niri validate -c "$HOME/.config/niri/config.kdl"
fc-cache -f "$HOME/.local/share/fonts"
"$HOME/.local/bin/apply-desktop-preferences"
# Only user services are changed; network and login services belong to the OS setup.
systemctl --user daemon-reload
systemctl --user enable clavis-shell.service clavis-clipboard.service nyx-dock.service fcitx5-niri.service nyx-theme-sync.path
if systemctl --user is-active --quiet niri.service; then
    systemctl --user start clavis-shell.service clavis-clipboard.service nyx-dock.service fcitx5-niri.service nyx-theme-sync.path
    systemctl --user start nyx-theme-sync.service
else
    echo 'Services enabled. Log in using the Niri session to start the desktop.'
fi
