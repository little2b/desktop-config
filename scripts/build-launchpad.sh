#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
build_dir="${XDG_CACHE_HOME:-$HOME/.cache}/desktop-config/launchpad-build"
cmake -S "$repo_dir/components/launchpad" -B "$build_dir" -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build "$build_dir" --parallel "${BUILD_JOBS:-2}"
mkdir -p "$HOME/.local/bin"
# Rename the completed binary so a running instance never sees a partial write.
temporary=$(mktemp "$HOME/.local/bin/.clavis-launchpad.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
install -m 755 "$build_dir/clavis-launchpad" "$temporary"
mv -f -- "$temporary" "$HOME/.local/bin/clavis-launchpad"
echo 'Installed clavis-launchpad. Start the user service to use it.'
