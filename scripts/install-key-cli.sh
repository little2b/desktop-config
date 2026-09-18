#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readarray -t source_info < <(python3 - "$repo_dir/sources.lock.json" <<'PY'
import json, sys
source = json.load(open(sys.argv[1]))['key_cli']
print(source['repository'])
print(source['commit'])
PY
)
task_tmp=$(mktemp -d)
trap 'rm -rf -- "$task_tmp"' EXIT
git init -q "$task_tmp/source"
git -C "$task_tmp/source" remote add origin "${source_info[0]}"
git -C "$task_tmp/source" fetch --depth 1 origin "${source_info[1]}"
git -C "$task_tmp/source" checkout --detach FETCH_HEAD
if command -v pkexec >/dev/null 2>&1; then
    mkdir "$task_tmp/bin"
    install -m 700 "$repo_dir/scripts/pkexec-sudo" "$task_tmp/bin/sudo"
    export PATH="$task_tmp/bin:$PATH"
fi
"$task_tmp/source/scripts/install.sh"
/usr/local/bin/key tool status
