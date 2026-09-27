#!/usr/bin/python3
"""Apply the verified readiness workaround to one known ChatGPT build only."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

ARCHIVE = Path('/usr/lib/chatgpt/resources/app.asar')
BACKUPS = Path('/var/lib/chatgpt-startup-fix')
VERSION = '26.924.22138'
ORIGINAL_SHA256 = 'e760b31c75ec647ee29450463fd8b83d8cd9157682a53776fa746009bb13ed55'
PATCHED_SHA256 = 'b48c0a1a91c3db8f54706d5a0c1b82d82a4ce035961294ff6f3bbd51e2c268f3'
ENTRY_SHA256 = 'ad40a386a4abee10b41b0958f803a00d043b3c4adc530c711687a466935abda0'
ENTRY_PATH = '.vite/build/early-bootstrap.js'
BEFORE = 'async function o(){await t.a();'
AFTER = 'async function o(){await n.app.whenReady();await t.a();'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def entry(header, name):
    value = header
    for component in name.split('/'):
        value = value['files'][component]
    return value


def inspect(path):
    with path.open('rb') as stream:
        prefix = stream.read(16)
        marker, header_size, payload_size, json_size = struct.unpack('<4I', prefix)
        if marker != 4 or header_size != payload_size + 4 or json_size > header_size - 8:
            raise ValueError('Unexpected ASAR header; refusing to modify it')
        header = json.loads(stream.read(json_size))
        package = entry(header, 'package.json')
        stream.seek(8 + header_size + int(package['offset']))
        version = json.loads(stream.read(package['size']))['version']
        if version != VERSION:
            return version, header, header_size, json_size, b''
        bootstrap = entry(header, ENTRY_PATH)
        stream.seek(8 + header_size + int(bootstrap['offset']))
        source = stream.read(bootstrap['size'])
    return version, header, header_size, json_size, source


def stage(source_path, target_path):
    if source_path.resolve() == target_path.resolve():
        raise ValueError('Staging requires a separate destination')
    version, header, header_size, json_size, source = inspect(source_path)
    if version != VERSION or digest(source_path) != ORIGINAL_SHA256:
        raise ValueError('Build or archive hash does not match the verified original')
    if hashlib.sha256(source).hexdigest() != ENTRY_SHA256:
        raise ValueError('Bootstrap hash does not match')
    text = source.decode()
    if text.count(BEFORE) != 1 or text.count('//# sourceMappingURL=early-bootstrap.js.map') != 1:
        raise ValueError('Unexpected bootstrap code')
    patched = text.replace(BEFORE, AFTER).split('//# sourceMappingURL=early-bootstrap.js.map')[0].encode()
    if len(patched) > len(source):
        raise ValueError('Patched entry would change archive offsets')
    patched = patched.ljust(len(source), b' ')
    updated = copy.deepcopy(header)
    bootstrap = entry(updated, ENTRY_PATH)
    integrity = bootstrap['integrity']
    if integrity['algorithm'] != 'SHA256':
        raise ValueError('Unexpected entry integrity algorithm')
    integrity['hash'] = hashlib.sha256(patched).hexdigest()
    block_size = integrity['blockSize']
    integrity['blocks'] = [hashlib.sha256(patched[i:i + block_size]).hexdigest()
                           for i in range(0, len(patched), block_size)]
    encoded = json.dumps(updated, separators=(',', ':'), ensure_ascii=False).encode()
    if len(encoded) != json_size:
        raise ValueError('Header size changed')
    shutil.copy2(source_path, target_path)
    with target_path.open('r+b') as stream:
        stream.seek(16)
        stream.write(encoded)
        stream.seek(8 + header_size + int(bootstrap['offset']))
        stream.write(patched)
        stream.flush()
        os.fsync(stream.fileno())
    actual_version, actual_header, _, _, actual_source = inspect(target_path)
    if actual_version != version or actual_header != updated or actual_source != patched:
        raise ValueError('Verification of staged archive failed')
    if digest(target_path) != PATCHED_SHA256:
        raise ValueError('Patched archive does not match the reviewed result')
    return {'version': version, 'original_sha256': ORIGINAL_SHA256,
            'patched_sha256': digest(target_path),
            'bootstrap_original_sha256': ENTRY_SHA256,
            'bootstrap_patched_sha256': integrity['hash'],
            'change': 'Wait for app.whenReady() before existing startup checks'}


def apply():
    version, _, _, _, _ = inspect(ARCHIVE)
    if version != VERSION:
        print(f'chatgpt-startup-fix: build {version} is outside this fix; left unchanged')
        return
    if os.geteuid() != 0:
        raise PermissionError('Applying the system repair requires root')
    current_hash = digest(ARCHIVE)
    backup = BACKUPS / version
    manifest_path = backup / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if current_hash == manifest['patched_sha256']:
            print(f'chatgpt-startup-fix: {version} already repaired')
            return
    if current_hash != ORIGINAL_SHA256:
        raise ValueError('Installed archive was changed; refusing an unverified modification')
    backup.mkdir(mode=0o700, parents=True, exist_ok=True)
    original = backup / 'app.asar.original'
    if not original.exists():
        shutil.copy2(ARCHIVE, original)
    if digest(original) != ORIGINAL_SHA256:
        raise ValueError('Original backup integrity check failed')
    metadata = ARCHIVE.stat()
    descriptor, temporary_name = tempfile.mkstemp(prefix='.app.asar.startup-fix-', dir=ARCHIVE.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        manifest = stage(ARCHIVE, temporary)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.chmod(temporary, metadata.st_mode & 0o7777)
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        os.chmod(manifest_path, 0o600)
        os.replace(temporary, ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'chatgpt-startup-fix: repaired {version}; backup: {original}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', nargs=2, metavar=('SOURCE', 'DESTINATION'))
    args = parser.parse_args()
    if args.stage:
        print(json.dumps(stage(*(Path(p) for p in args.stage)), indent=2))
    else:
        apply()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'chatgpt-startup-fix: {error}', file=sys.stderr)
        sys.exit(1)
