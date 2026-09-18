#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f /etc/arch-release ]] || { echo 'Run this on the new Arch system, not Fedora.' >&2; exit 1; }
for argument in "$@"; do
    [[ "$argument" == --same-hardware ]] || { echo 'Usage: setup-arch.sh [--same-hardware]' >&2; exit 2; }
done
python3 "$script_dir/restore.py" "$@"
"$script_dir/install-arch-dependencies.sh"
"$script_dir/install-key-cli.sh"
python3 "$script_dir/restore.py" --apply "$@"
"$script_dir/build-clavis.sh"
"$script_dir/enable-services.sh"
