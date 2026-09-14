#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
root = Path(__file__).resolve().parents[1]
paths = []
for directory in ['config', 'share', 'lib', 'bin', 'rime', 'assets', 'hardware', 'system-reference']:
    paths.extend(p for p in (root / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
paths.append(root / 'sources.lock.json')
result = {}
for p in sorted(paths):
    with p.open('rb') as stream:
        result[str(p.relative_to(root))] = hashlib.file_digest(stream, 'sha256').hexdigest()
(root / 'manifest.json').write_text(json.dumps({'sha256': result}, ensure_ascii=False, indent=2) + '\n')
print(f'Manifest updated: {len(result)} files')
