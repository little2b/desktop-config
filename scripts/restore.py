#!/usr/bin/env python3
"""Restore this private desktop snapshot. Default mode only prints a plan."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def verify(root=ROOT):
    manifest = json.loads((root / 'manifest.json').read_text())
    actual = {str(p.relative_to(root)) for directory in ['config', 'share', 'lib', 'bin', 'rime', 'assets', 'hardware', 'system-reference']
              for p in (root / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    actual.add('sources.lock.json')
    if actual != set(manifest['sha256']):
        raise ValueError('Snapshot file inventory differs from manifest')
    for relative, digest in manifest['sha256'].items():
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Invalid snapshot path: {relative}')
        with path.open('rb') as stream:
            actual_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual_digest != digest:
            raise ValueError(f'Snapshot checksum mismatch: {relative}')


def plan(target_home, same_hardware=False, root=ROOT):
    result = {}
    for source_dir, target_dir in [('config', '.config'), ('share', '.local/share'),
                                   ('lib', '.local/lib'), ('bin', '.local/bin'),
                                   ('rime', '.local/share/fcitx5/rime')]:
        for path in sorted((root / source_dir).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            relative = Path(target_dir) / path.relative_to(root / source_dir)
            result[relative] = (path, path.stat().st_mode & 0o777)
    avatar = root / 'assets/avatar'
    if avatar.exists():
        result[Path('.face')] = (avatar, 0o600)
    for path in (root / 'assets').glob('wallpaper.*'):
        result[Path('Pictures/Wallpapers/current' + path.suffix)] = (path, 0o644)
    if same_hardware:
        result[Path('.config/niri/clavis/outputs.kdl')] = (root / 'hardware/outputs.kdl', 0o644)
        result[Path('.config/clavis/primary-display.json')] = (root / 'hardware/primary-display.json', 0o600)
    rendered = {}
    for relative, (source, mode) in result.items():
        data = source.read_bytes()
        if b'\0' not in data:
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                pass
            else:
                data = text.replace('@HOME@', str(target_home)).encode('utf-8')
        if relative == Path('.config/clavis/ui-preferences.json') and same_hardware:
            settings = json.loads(data)
            settings.update(json.loads((root / 'hardware/monitor-metrics.json').read_text()))
            data = (json.dumps(settings, ensure_ascii=False, indent=2) + '\n').encode()
        if relative.suffix == '.json':
            json.loads(data)
        rendered[relative] = (data, mode)
    return rendered


def destination(target_home, relative):
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError(f'Invalid destination: {relative}')
    path = target_home / relative
    if not path.parent.resolve().is_relative_to(target_home.resolve()):
        raise ValueError(f'Destination parent escapes selected home: {path}')
    if path.exists() and path.is_dir():
        raise ValueError(f'A directory occupies a file destination: {path}')
    return path


def restore(target_home, same_hardware=False, apply=False, root=ROOT):
    target_home = target_home.expanduser().absolute()
    if any(char in str(target_home) for char in '\n\r"\'`$\\'):
        raise ValueError('The target path must not contain quotes, shell substitutions or line breaks')
    verify(root)
    files = plan(target_home, same_hardware, root)
    # Check every destination before touching any file.
    for relative in files:
        destination(target_home, relative)
    print(f'{len(files)} files -> {target_home}; hardware={"preserved" if same_hardware else "reset"}')
    if not apply:
        print('Plan only. Add --apply to restore. Existing files will be backed up.')
        return None
    active_units = []
    if target_home.resolve() == Path.home().resolve():
        for unit in ['clavis-shell.service', 'nyx-dock.service', 'fcitx5-niri.service', 'nyx-theme-sync.path', 'nyx-theme-sync.service']:
            if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', unit], check=False).returncode == 0:
                active_units.append(unit)
        # Fcitx may have been started by desktop autostart rather than this unit.
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid == os.getuid() and (entry / 'comm').read_text().strip() == 'fcitx5':
                    if 'fcitx5-niri.service' not in active_units:
                        active_units.append('fcitx5 (desktop autostart)')
                    break
            except (OSError, UnicodeError):
                continue
        if active_units:
            raise RuntimeError('Stop these services before restoring to an active desktop: ' + ', '.join(active_units))
    target_home.mkdir(parents=True, exist_ok=True)
    destination(target_home, Path('.local/state/desktop-config-backups/.guard'))
    backup_root = target_home / '.local/state/desktop-config-backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=backup_root))
    # LevelDB snapshots must replace whole databases, never merge stale WAL/SST files.
    databases = {Path(*relative.parts[:index + 1]) for relative in files
                 for index, part in enumerate(relative.parts) if part.endswith('.userdb')}
    for relative in sorted(databases):
        path = destination(target_home, relative / '.guard').parent
        if path.exists():
            old = backup / relative
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(old))
    for relative, (data, mode) in files.items():
        path = destination(target_home, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            old = backup / relative
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, old, follow_symlinks=False)
        fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    print(f'Restored. Previous files: {backup}')
    print('Next: build-clavis.sh, then enable-services.sh. No system power policy was applied.')
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-home', type=Path, default=Path.home())
    parser.add_argument('--same-hardware', action='store_true', help='Keep monitor layout, primary display and hardware metric bindings')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    restore(args.target_home, args.same_hardware, args.apply)


if __name__ == '__main__':
    main()
