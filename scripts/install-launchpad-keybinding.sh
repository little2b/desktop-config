#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $(id -u) -ne 0 ]]; then
    if command -v pkexec >/dev/null 2>&1 && [[ -n ${WAYLAND_DISPLAY:-}${DISPLAY:-} ]]; then
        exec pkexec /usr/bin/bash "$repo_dir/scripts/install-launchpad-keybinding.sh"
    fi
    echo 'Enter your password in this terminal when sudo prompts.'
    exec sudo /usr/bin/bash "$repo_dir/scripts/install-launchpad-keybinding.sh"
fi
source_file="$repo_dir/system-reference/keyd/clavis-launchpad.conf"
target_file=/etc/keyd/clavis-launchpad.conf
keyd check "$source_file"
shopt -s nullglob
for existing in /etc/keyd/*.conf; do
    if [[ "$existing" != "$target_file" ]]; then
        echo "Existing keyd configuration needs a manual merge: $existing" >&2
        exit 1
    fi
done
if [[ -f "$target_file" ]] && ! cmp -s "$source_file" "$target_file"; then
    cp -a -- "$target_file" "$target_file.bak-$(date +%Y%m%d-%H%M%S)"
fi
install -Dm644 "$source_file" "$target_file"
if systemctl is-active --quiet keyd.service; then
    keyd reload
    systemctl enable keyd.service
else
    systemctl enable --now keyd.service
fi
