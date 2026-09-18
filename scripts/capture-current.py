#!/usr/bin/env python3
"""Refresh the portable desktop snapshot; never copy account stores or live databases."""
import argparse
import configparser
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
METRICS = ['systemMonitorGpuId', 'systemMonitorDiskDevice', 'systemMonitorNetworkInterface', 'storageCapacityDiskDevice']


def clean_settings(value, home):
    if isinstance(value, str):
        return value.replace(str(home), '@HOME@')
    if isinstance(value, list):
        return [clean_settings(item, home) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if re.search(r'password|secret|token|credential|api.?key', key, re.I) and isinstance(item, (str, list, dict)):
                result[key] = type(item)()
            else:
                result[key] = clean_settings(item, home)
        return result
    return value


def capture(home, root=ROOT):
    home = home.expanduser().resolve()
    source = home / '.config/quickshell/clavis'
    if not (home / '.config/quickshell/nyx-dock/shell.qml').is_file():
        raise RuntimeError('The selected home has no nyx-dock installation')
    lock = json.loads((root / 'sources.lock.json').read_text())
    if (source / '.git').exists():
        dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True)
        if dirty.strip():
            raise RuntimeError('Clavis source has uncommitted changes; commit it before capturing a reproducible snapshot')
        lock['clavis']['commit'] = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()

    def put(relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def copy(path, relative):
        if not path.is_file():
            return
        content = path.read_text()
        if relative.startswith('bin/'):
            content = content.replace(str(home) + '/.config/nyx-desktop-style/dolphin.qss', '"$HOME/.config/nyx-desktop-style/dolphin.qss"')
        if relative == 'bin/open-quark-drive':
            content = content.replace(str(home) + '/.local/share/cloud-mounts/quark', '"$HOME/.local/share/cloud-mounts/quark"')
        content = content.replace(str(home) + '/.local/bin/qs', '/usr/bin/qs')
        content = content.replace(str(home), '@HOME@')
        content = content.replace('/usr/libexec/kf6/polkit-kde-authentication-agent-1', '/usr/lib/polkit-kde-authentication-agent-1')
        if path.suffix == '.desktop':
            content = re.sub(r'^Exec=(@HOME@/\.local/bin/[^\s"]+)(.*)$', r'Exec="\1"\2', content, flags=re.M)
            content = re.sub(r'^TryExec=@HOME@/\.local/bin/([^\s]+)$', r'TryExec=/usr/bin/\1', content, flags=re.M)
        if path.suffix in ('.colors', '.colorscheme', '.profile', '.service'):
            content = content.rstrip('\n') + '\n'
        put(relative, content)
        (root / relative).chmod(path.stat().st_mode & 0o777)

    for name in ['config.json', 'ui-preferences.json', 'quick-toggles.json', 'idle-policy.json', 'tray.json']:
        path = home / '.config/clavis' / name
        if not path.is_file():
            continue
        raw = json.loads(path.read_text())
        data = clean_settings(raw, home)
        if name == 'config.json':
            wallpaper = Path(raw['wallpaper']['path'])
            if wallpaper.is_file():
                for previous in (root / 'assets').glob('wallpaper.*'):
                    if previous.suffix != wallpaper.suffix:
                        previous.unlink()
                shutil.copy2(wallpaper, root / ('assets/wallpaper' + wallpaper.suffix))
                data['wallpaper']['folder'] = '@HOME@/Pictures/Wallpapers'
                data['wallpaper']['path'] = '@HOME@/Pictures/Wallpapers/current' + wallpaper.suffix
        if name == 'ui-preferences.json':
            put('hardware/monitor-metrics.json', json.dumps({k: data[k] for k in METRICS if k in data}, indent=2) + '\n')
            for key in METRICS:
                if key in data:
                    data[key] = ''
            data['cloudBackupFolders'] = []
            data['cloudDefaultRemoteName'] = ''
        put('config/clavis/' + name, json.dumps(data, ensure_ascii=False, indent=2) + '\n')

    copy(home / '.config/clavis/primary-display.json', 'hardware/primary-display.json')
    copy(home / '.config/niri/clavis/outputs.kdl', 'hardware/outputs.kdl')
    for relative in ['config.kdl', 'clavis/mouse.kdl', 'clavis/cursor.kdl', 'clavis/layer-rules.kdl', 'clavis/effects.kdl']:
        copy(home / '.config/niri' / relative, 'config/niri/' + relative)
    dock = home / '.config/quickshell/nyx-dock'
    for path in sorted(dock.iterdir()):
        if path.suffix in ('.qml', '.js', '.json', '.svg'):
            copy(path, 'config/quickshell/nyx-dock/' + path.name)
    copy(home / '.local/lib/nyx-dock/uninstall-app.py', 'lib/nyx-dock/uninstall-app.py')
    # Preserve Arch-specific adaptations of the theme bridge and user services.
    for name in ['dolphin', 'konsole', 'key', 'open-quark-drive']:
        copy(home / '.local/bin' / name, 'bin/' + name)
    for name in ['dolphin', 'konsole']:
        copy(home / '.local/share/applications' / ('org.kde.' + name + '.desktop'), 'share/applications/org.kde.' + name + '.desktop')
    copy(home / '.local/share/applications/quark-drive.desktop', 'share/applications/quark-drive.desktop')
    copy(home / '.config/systemd/user/rclone-quark.service', 'config/systemd/user/rclone-quark.service')
    copy(home / '.local/lib/nyx-desktop-style/sync-theme.py', 'lib/nyx-desktop-style/sync-theme.py')
    # The derived theme contains only SVG resources, not caches or account data.
    icon_dir = home / '.local/share/icons/Clavis-Reference'
    for path in sorted(icon_dir.rglob('*')):
        if path.is_file() and (path.suffix == '.svg' or path.name == 'index.theme'):
            copy(path, 'share/icons/Clavis-Reference/' + str(path.relative_to(icon_dir)))
    if home == Path.home().resolve():
        preferences = {'gsettings': [], 'mime': {}}
        for schema, keys in {
            'org.gnome.desktop.interface': ['icon-theme', 'accent-color', 'color-scheme'],
            'org.gnome.nautilus.preferences': ['default-folder-viewer'],
            'org.gnome.nautilus.icon-view': ['default-zoom-level'],
        }.items():
            for key in keys:
                value = subprocess.check_output(['gsettings', 'get', schema, key], text=True).strip()
                preferences['gsettings'].append({'schema': schema, 'key': key, 'value': value})
        for mime in ['inode/directory', 'video/matroska']:
            preferences['mime'][mime] = subprocess.check_output(['xdg-mime', 'query', 'default', mime], text=True).strip()
        put('config/nyx-desktop-style/desktop-preferences.json', json.dumps(preferences, ensure_ascii=False, indent=2) + '\n')
    for name in ['dolphinrc', 'konsolerc', 'plasma-localerc']:
        copy(home / '.config' / name, 'config/' + name)
    for folder in ['alacritty', 'fuzzel', 'gtk-3.0', 'gtk-4.0', 'nyx-desktop-style', 'fcitx5']:
        source_dir = home / '.config' / folder
        for path in sorted(source_dir.rglob('*')):
            if path.is_file() and not any(part.startswith('.') for part in path.relative_to(source_dir).parts) and not re.search(r'\.bak|backup|\.log$|\.lock$', path.name, re.I):
                copy(path, 'config/' + folder + '/' + str(path.relative_to(source_dir)))

    settings = configparser.ConfigParser(interpolation=None)
    settings.optionxform = str
    settings.read(home / '.config/konsolerc')
    profile = settings.get('Desktop Entry', 'DefaultProfile', fallback='')
    if re.fullmatch(r'NyxTheme-[0-9a-f]{12}\.profile', profile):
        for suffix in ['.profile', '.colorscheme']:
            name = Path(profile).with_suffix(suffix).name
            copy(home / '.local/share/konsole' / name, 'share/konsole/' + name)
        for name in [Path(profile).with_suffix('.colors').name, 'NyxTheme.colors']:
            copy(home / '.local/share/color-schemes' / name, 'share/color-schemes/' + name)
    copy(home / '.local/share/clavis/profiles/default/generated/clavis/colors.json', 'share/clavis/profiles/default/generated/clavis/colors.json')
    if (home / '.face').is_file():
        shutil.copy2(home / '.face', root / 'assets/avatar')
    weather = configparser.ConfigParser(interpolation=None)
    weather.read(home / '.config/Clavis/Weather.conf')
    if weather.has_section('manual'):
        saved = configparser.ConfigParser(interpolation=None)
        saved['manual'] = dict(weather['manual'])
        with (root / 'config/Clavis/Weather.conf').open('w') as stream:
            saved.write(stream, space_around_delimiters=False)
    # Keep the previous Rime snapshot. Do not publish newly learned words or
    # personal phrases as a side effect of a desktop configuration backup.
    lock['desktop_snapshot'] = {'captured_at': datetime.now().astimezone().isoformat(timespec='seconds')}
    put('sources.lock.json', json.dumps(lock, ensure_ascii=False, indent=2) + '\n')
    print('Desktop, Dock, application helpers and hardware preferences captured. Existing Rime userdb snapshot preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-home', type=Path, default=Path.home())
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print(f'Plan: capture desktop settings from {args.source_home}; use --apply to refresh this repository.')
        return
    capture(args.source_home)
    subprocess.run(['python3', str(ROOT / 'scripts/update-manifest.py')], check=True)


if __name__ == '__main__':
    main()
