#!/usr/bin/python3
"""Resolve a desktop entry, then use its package manager's removal confirmation."""
from pathlib import Path
import argparse
import configparser
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=20)

def app_dirs():
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    roots = [data] + [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]
    roots += [Path.home() / '.local/share/flatpak/exports/share', Path('/var/lib/flatpak/exports/share')]
    return list(dict.fromkeys(root / 'applications' for root in roots))

def desktop_files(app_id, directories):
    name = app_id if app_id.endswith('.desktop') else app_id + '.desktop'
    if not app_id or '/' in app_id or '\\' in app_id or '\0' in app_id or len(app_id) > 256:
        raise ValueError('无效的应用标识')
    result = []
    for directory in directories:
        direct = directory / name
        if direct.is_file():
            result.append(direct)
        elif directory.is_dir():
            result.extend(p for p in directory.rglob('*.desktop') if str(p.relative_to(directory)).replace('/', '-') == name)
    return result

def owner(path, execute=run):
    if shutil.which('pacman'):
        provider = 'pacman'
        command = ['/usr/bin/pacman', '-Qqo', '--', str(path)]
    elif shutil.which('rpm'):
        provider = 'rpm'
        command = ['/usr/bin/rpm', '-qf', '--qf', '%{NAME}\n', '--', str(path)]
    else:
        return None
    result = execute(command)
    names = result.stdout.strip().splitlines()
    if result.returncode == 0 and len(names) == 1 and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+._-]*', names[0]):
        return {'provider': provider, 'package': names[0]}
    return None

def executable(command):
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    if not words:
        return None
    if Path(words[0]).name == 'env':
        words = words[1:]
        while words and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', words[0]):
            words.pop(0)
    if not words or words[0].startswith('-'):
        return None
    name = Path(words[0]).name
    # An interpreter's package is not the package of the application it runs.
    if name in ('sh', 'bash', 'dash', 'zsh', 'fish', 'env', 'flatpak', 'snap', 'java', 'node', 'electron') or name.startswith(('python', 'perl', 'ruby')):
        return None
    path = words[0] if Path(words[0]).is_absolute() else shutil.which(words[0])
    resolved = Path(path).resolve() if path and Path(path).is_file() else None
    if resolved and (resolved.name in ('snap', 'flatpak', 'env', 'sh', 'bash', 'java', 'node', 'electron') or resolved.name.startswith(('python', 'perl', 'ruby'))):
        return None
    return str(resolved) if resolved else None

def resolve(app_id, directories=None, execute=run):
    files = desktop_files(app_id, directories if directories is not None else app_dirs())
    if not files:
        raise ValueError('找不到这个应用的启动入口，可能已经卸载')
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(files[0], encoding='utf-8')
    entry = parser['Desktop Entry']
    name = entry.get('Name[zh_CN]', entry.get('Name', app_id))
    info = {'id': app_id, 'name': name, 'desktop': str(files[0]),
            'desktop_hash': hashlib.sha256(files[0].read_bytes()).hexdigest(), 'provider': 'manual'}
    command = entry.get('Exec', '')
    binary = executable(command)
    info['location'] = str(Path(binary).parent) if binary else str(files[0].parent)
    if entry.get('Type', 'Application') != 'Application' or re.search(r'--app(?:-id)?(?:=|\s)', command):
        info.update(provider='web', reason='这是网页应用或快捷方式，请在对应浏览器的应用管理页面中卸载。不会卸载浏览器本身。')
        return info
    flatpak_id = entry.get('X-Flatpak', '')
    if flatpak_id:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]+', flatpak_id):
            raise ValueError('无效的 Flatpak 应用标识')
        result = execute(['/usr/bin/flatpak', 'list', '--app', '--columns=application,installation'])
        matches = []
        for line in result.stdout.splitlines():
            fields = line.split('\t')
            if len(fields) == 2 and fields[0] == flatpak_id:
                matches.append(fields[1])
        expected = 'user' if files[0].is_relative_to(Path.home() / '.local/share/flatpak') else 'system' if files[0].is_relative_to(Path('/var/lib/flatpak')) else None
        if expected in matches:
            matches = [expected]
        if len(matches) == 1:
            info.update(provider='flatpak', package=flatpak_id, installation=matches[0])
            return info
        if len(matches) > 1:
            raise ValueError('此应用在多个位置安装，请在 Flatpak 软件管理器中选择要卸载的副本')
        raise ValueError('Flatpak 中没有找到这个已安装应用')
    for file in files:
        package = owner(file, execute)
        if package:
            info.update(package)
            return info
    if binary:
        package = owner(binary, execute)
        if package:
            info.update(package)
            return info
    info['reason'] = '这是手动安装的应用，系统没有登记卸载方式。请使用其安装器或专用卸载程序处理。'
    return info

def removal_command(info):
    if info['provider'] == 'pacman':
        return ['/usr/bin/pkexec', '/usr/bin/pacman', '-R', '--', info['package']]
    if info['provider'] == 'rpm':
        # DNF shows the full dependency transaction and asks for confirmation.
        return ['/usr/bin/pkexec', '/usr/bin/dnf', 'remove', '--', info['package']]
    if info['provider'] == 'flatpak':
        location = info['installation']
        scope = '--user' if location == 'user' else '--system' if location == 'system' else '--installation=' + location
        return ['/usr/bin/flatpak', 'uninstall', scope, '--', info['package']]
    return None

def still_installed(info):
    if info['provider'] == 'pacman':
        return run(['/usr/bin/pacman', '-Q', '--', info['package']]).returncode == 0
    if info['provider'] == 'rpm':
        return run(['/usr/bin/rpm', '-q', '--', info['package']]).returncode == 0
    location = info['installation']
    scope = '--user' if location == 'user' else '--system' if location == 'system' else '--installation=' + location
    return run(['/usr/bin/flatpak', 'info', scope, '--', info['package']]).returncode == 0

def cleanup_launcher(info):
    local = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'applications'
    path = Path(info['desktop'])
    # Only discard an unchanged user override after its package is gone.
    if path.is_relative_to(local) and path.is_file() and not path.is_symlink():
        if hashlib.sha256(path.read_bytes()).hexdigest() == info['desktop_hash']:
            run(['/usr/bin/gio', 'trash', '--', str(path)])
    qs = shutil.which('qs')
    if qs:
        run([qs, 'ipc', '-c', 'nyx-dock', 'call', 'dock', 'forgetApplication', info['id']])

def clean_text(value):
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', '', str(value))

def main():
    parser = argparse.ArgumentParser(description='从 Launchpad 卸载应用')
    parser.add_argument('app_id')
    parser.add_argument('--inspect', action='store_true', help='只读取安装信息，不执行卸载')
    args = parser.parse_args()
    try:
        info = resolve(args.app_id)
        if args.inspect:
            print(json.dumps(info, ensure_ascii=False))
            return 0
        if not sys.stdin.isatty():
            raise ValueError('请在终端中运行卸载，以便确认软件包变更')
        print('\n卸载应用：' + clean_text(info['name']))
        command = removal_command(info)
        if command is None:
            print('\n' + info['reason'])
            print('位置：' + clean_text(info['location']))
            input('\n按 Enter 关闭。')
            return 0
        print('安装方式：' + {'rpm': '系统软件包（RPM）', 'pacman': '系统软件包（pacman / AUR）', 'flatpak': 'Flatpak'}[info['provider']])
        print('软件包：' + clean_text(info['package']))
        print('\n软件管理器会列出卸载清单并请求确认；取消即可保留应用。\n', flush=True)
        env = os.environ.copy()
        env.update(LANG='zh_CN.UTF-8', LC_ALL='zh_CN.UTF-8', LANGUAGE='zh_CN:zh')
        result = subprocess.run(command, env=env)
        if result.returncode == 0 and not still_installed(info):
            cleanup_launcher(info)
            print('\n卸载完成，已更新 Dock 和应用分组。')
        else:
            print('\n卸载未完成或已取消，应用的固定项和分组保持不变。')
        input('\n按 Enter 关闭。')
        return result.returncode
    except (ValueError, OSError, configparser.Error, subprocess.SubprocessError) as error:
        if args.inspect:
            print(json.dumps({'error': str(error)}, ensure_ascii=False))
        else:
            print('\n无法卸载：' + clean_text(error))
            if sys.stdin.isatty():
                input('\n按 Enter 关闭。')
        return 1
    except (EOFError, KeyboardInterrupt):
        return 130

if __name__ == '__main__':
    sys.exit(main())
