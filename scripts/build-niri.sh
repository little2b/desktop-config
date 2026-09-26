#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_dir=${NIRI_SOURCE_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/niri-desktop-source}
prefix_dir="$HOME/.local/lib/niri-desktop"
readarray -t source_info < <(python3 - "$repo_dir/sources.lock.json" "$repo_dir" <<'PY'
import hashlib, json, sys
from pathlib import Path
source = json.loads(Path(sys.argv[1]).read_text())['niri']
patch = Path(sys.argv[2]) / source['patch']
assert hashlib.sha256(patch.read_bytes()).hexdigest() == source['patch_sha256'], 'Niri patch checksum mismatch'
for value in [source['repository'], source['commit'], str(patch)]:
    print(value)
PY
)
[[ ${#source_info[@]} -eq 3 ]] || { echo 'Invalid pinned Niri source.' >&2; exit 1; }
if [[ ! -e "$source_dir" ]]; then
    mkdir -p -- "$source_dir"
    git -C "$source_dir" init -q
    git -C "$source_dir" remote add origin "${source_info[0]}"
    git -C "$source_dir" fetch --depth 1 origin "${source_info[1]}"
    git -C "$source_dir" checkout --detach FETCH_HEAD
    git -C "$source_dir" apply --index "${source_info[2]}"
else
    [[ $(git -C "$source_dir" rev-parse HEAD) == "${source_info[1]}" ]] || {
        echo 'Existing Niri source differs from the pinned version; choose another NIRI_SOURCE_DIR.' >&2; exit 1;
    }
    if ! git -C "$source_dir" diff --binary --full-index HEAD | cmp -s - "${source_info[2]}" \
        || [[ -n $(git -C "$source_dir" ls-files --others --exclude-standard) ]]; then
        echo 'Existing Niri source has different local changes; preserve them before rebuilding.' >&2
        exit 1
    fi
fi
command -v cargo >/dev/null || { echo 'Install Rust through install-arch-dependencies.sh first.' >&2; exit 1; }
cargo build --manifest-path "$source_dir/Cargo.toml" --locked --release --package niri \
    --target-dir "$source_dir/target" --jobs "${CARGO_BUILD_JOBS:-4}"
mkdir -p -- "$prefix_dir" "$HOME/.local/bin"
temporary=$(mktemp "$prefix_dir/.niri.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
install -m 755 "$source_dir/target/release/niri" "$temporary"
mv -f -- "$temporary" "$prefix_dir/niri"
echo "Pinned Niri is ready: $prefix_dir/niri"
echo 'The running compositor was not restarted. The new version takes effect at the next Niri login.'
