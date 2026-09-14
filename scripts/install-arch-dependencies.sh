#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ -f /etc/arch-release ]] || { echo 'This installer is for Arch Linux only.' >&2; exit 1; }
[[ $(id -u) -ne 0 ]] || { echo 'Run as your desktop user, not root.' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'Install python first: sudo pacman -Syu --needed git github-cli python curl' >&2; exit 1; }
# Arch librime includes librime-lua.so; it is not a separate librime-lua package.
sudo pacman -Syu --needed git python curl github-cli fcitx5 fcitx5-rime fcitx5-configtool \
    fcitx5-gtk fcitx5-qt librime xorg-xrdb xwayland-satellite \
    xdg-desktop-portal-gnome xdg-desktop-portal-gtk xdg-user-dirs \
    polkit-kde-agent breeze breeze-gtk plasma-integration dolphin konsole alacritty fuzzel \
    noto-fonts noto-fonts-cjk noto-fonts-emoji fontconfig kconfig python-gobject \
    wl-clipboard swaylock playerctl brightnessctl
release=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["arch_installer"]["release"])' "$repo_dir/sources.lock.json")
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
base_url="https://github.com/StatIndet/quickshell/releases/download/$release"
curl --fail --location "$base_url/install-arch.sh" -o "$task_tmp/install-arch.sh"
curl --fail --location "$base_url/SHA256SUMS" -o "$task_tmp/SHA256SUMS"
python3 - "$task_tmp" <<'PY'
import hashlib,sys
from pathlib import Path
root=Path(sys.argv[1]);rows=[line.split() for line in (root/'SHA256SUMS').read_text().splitlines()]
matches=[r[0] for r in rows if len(r)==2 and r[1].lstrip('*')=='install-arch.sh']
with (root/'install-arch.sh').open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
assert len(matches)==1 and digest==matches[0], 'Installer checksum mismatch'
PY
# Upstream resolves key-cli/keytop releases and third-party build dependencies.
# Optional keyboard/performance privileges and starting services remain disabled.
bash "$task_tmp/install-arch.sh" --non-interactive --keyboard-access=no --power-access=no \
    --enable-shell=no --enable-clipboard=no --start-now=no
