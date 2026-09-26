#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readarray -t source_info < <(python3 - "$repo_dir/sources.lock.json" <<'PY'
import json, sys
source = json.load(open(sys.argv[1]))['icon_theme']
print(source['repository'])
print(source['commit'])
PY
)
[[ ${#source_info[@]} -eq 2 ]] || { echo 'Missing pinned icon theme source.' >&2; exit 1; }
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
git init -q "$task_tmp/source"
git -C "$task_tmp/source" remote add origin "${source_info[0]}"
git -C "$task_tmp/source" fetch --depth 1 origin "${source_info[1]}"
git -C "$task_tmp/source" checkout --detach FETCH_HEAD
destination="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
mkdir -p -- "$destination"
# Keep replaced themes available for rollback rather than letting the upstream
# installer remove the user's only copy of an existing customization.
for theme in MacTahoe MacTahoe-light MacTahoe-dark; do
    if [[ -e "$destination/$theme" || -L "$destination/$theme" ]]; then
        backup_root="${XDG_STATE_HOME:-$HOME/.local/state}/desktop-config-backups"
        mkdir -p -- "$backup_root"
        backup=$(mktemp -d "$backup_root/icon-theme.XXXXXX")
        cp -a -- "$destination/$theme" "$backup/$theme"
    fi
done
(cd "$task_tmp/source" && bash ./install.sh -d "$destination")
echo 'Pinned MacTahoe icon themes installed; cursor preferences are unchanged.'
