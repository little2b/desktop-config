#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PATH="$HOME/.local/bin:$PATH"
source_dir=${CLAVIS_SOURCE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/clavis-source}
prefix_dir="$HOME/.local/lib/clavis-runtime"
readarray -t source_info < <(python3 - "$repo_dir/sources.lock.json" <<'PY'
import json,sys
v=json.load(open(sys.argv[1]))['clavis']
for key in ['repository','branch','commit']: print(v[key])
PY
)
if [[ ! -e "$source_dir" ]]; then
    git clone --branch "${source_info[1]}" --single-branch "${source_info[0]}" "$source_dir"
    git -C "$source_dir" checkout --detach "${source_info[2]}"
else
    [[ -d "$source_dir/.git" ]] || { echo "Not a Git checkout: $source_dir" >&2; exit 1; }
    [[ -z $(git -C "$source_dir" status --porcelain) ]] || { echo 'Source has local changes; preserve or commit them before building.' >&2; exit 1; }
    [[ $(git -C "$source_dir" rev-parse HEAD) == "${source_info[2]}" ]] || { echo 'Existing source differs from the pinned snapshot. Choose another CLAVIS_SOURCE_DIR.' >&2; exit 1; }
fi
python3 - "$repo_dir/assets/weather-icons.tar.gz" "$source_dir/assets/icons/weather/meteocons" <<'PY'
import sys,tarfile
from pathlib import Path
p=Path(sys.argv[2]);p.mkdir(parents=True,exist_ok=True)
with tarfile.open(sys.argv[1]) as archive: archive.extractall(p,filter='data')
PY
cmake -S "$source_dir" -B "$source_dir/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    -DCMAKE_INSTALL_PREFIX="$prefix_dir" -DCLAVIS_QML_INSTALL_DIR="$prefix_dir/lib/qml" \
    -DCMAKE_INSTALL_RPATH="$prefix_dir/lib"
cmake --build "$source_dir/build" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-4}"
if systemctl --user is-active --quiet clavis-shell.service; then
    echo 'Stop clavis-shell.service before installing its native plugins.' >&2
    exit 1
fi
cmake --install "$source_dir/build" --component ClavisNative
entry="$HOME/.config/quickshell/clavis"
mkdir -p -- "$(dirname -- "$entry")"
if [[ -e "$entry" || -L "$entry" ]]; then
    if [[ $(readlink -f -- "$entry") != "$(readlink -f -- "$source_dir")" ]]; then
        mkdir -p -- "$HOME/.local/state"
        backup_dir=$(mktemp -d "$HOME/.local/state/desktop-config-source.XXXXXX")
        mv -- "$entry" "$backup_dir/clavis"
        ln -s -- "$source_dir" "$entry"
    fi
else
    ln -s -- "$source_dir" "$entry"
fi
echo "Clavis source and native modules ready: $source_dir"
