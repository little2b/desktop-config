#!/usr/bin/python3
"""Render application colors from the same palette used by Clavis."""
from pathlib import Path
import argparse
import configparser
import hashlib
import io
import json
import os
import re
import subprocess
import shutil
import tempfile
import xml.etree.ElementTree as ET

BASE = Path.home()
SOURCE = BASE / '.local/share/clavis/profiles/default/generated/clavis/colors.json'

def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == text:
        return
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))

def luminance(color):
    values = [v / 255 for v in rgb(color)]
    values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(a * b for a, b in zip(values, [.2126, .7152, .0722]))

def legible(color, background, foreground):
    for n in range(11):
        ratio = n / 10
        mixed = '#' + ''.join(f'{round(a * (1 - ratio) + b * ratio):02x}' for a, b in zip(rgb(color), rgb(foreground)))
        lo, hi = sorted([luminance(mixed), luminance(background)])
        if (hi + .05) / (lo + .05) >= 3:
            return mixed
    return foreground

def ini(data):
    c = configparser.ConfigParser(interpolation=None)
    c.optionxform = str
    c.read_dict(data)
    out = io.StringIO()
    c.write(out, space_around_delimiters=False)
    return out.getvalue()

def render(palette, base):
    required = ['surface', 'surface_container', 'surface_container_high', 'surface_container_low',
                'on_surface', 'on_surface_variant', 'primary', 'primary_container', 'on_primary_container',
                'secondary', 'secondary_container', 'tertiary', 'error', 'outline_variant']
    for key in required:
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(palette.get(key, ''))):
            raise ValueError(f'Invalid Clavis color: {key}')
    p = palette
    bg, fg = p['surface'], p['on_surface']
    dark = luminance(bg) < .4
    normal = [p['on_surface_variant'], p['error'], p['tertiary'], p['secondary'],
              p['primary'], p['tertiary'], p['secondary'], fg]
    normal = [legible(c, bg, fg) for c in normal]
    bright = [legible(p['on_surface_variant'], bg, fg)] + [legible(c, bg, fg) for c in normal[1:7]] + [fg]
    colors = {'primary': {'background': bg, 'foreground': fg},
              'cursor': {'text': bg, 'cursor': p['primary']},
              'selection': {'text': p['on_primary_container'], 'background': p['primary_container']},
              'normal': dict(zip(['black','red','green','yellow','blue','magenta','cyan','white'], normal)),
              'bright': dict(zip(['black','red','green','yellow','blue','magenta','cyan','white'], bright))}
    toml = '# Generated from the current Clavis theme.\n'
    for section, values in colors.items():
        toml += f'\n[colors.{section}]\n' + ''.join(f'{k} = "{v}"\n' for k, v in values.items())
    atomic(base / '.config/alacritty/theme.toml', toml)

    kde = {}
    for group in ['View', 'Window', 'Button', 'Tooltip', 'Header', 'Complementary', 'Selection']:
        background = bg if group == 'View' else p['surface_container']
        foreground = fg
        if group == 'Selection':
            background, foreground = p['primary_container'], p['on_primary_container']
        values = {'BackgroundNormal': background, 'BackgroundAlternate': p['surface_container_low'],
                  'ForegroundNormal': foreground, 'ForegroundInactive': p['on_surface_variant'],
                  'ForegroundActive': p['primary'], 'ForegroundLink': p['primary'],
                  'ForegroundVisited': p['tertiary'], 'ForegroundNegative': p['error'],
                  'ForegroundNeutral': p['secondary'], 'ForegroundPositive': p['tertiary'],
                  'DecorationFocus': p['primary'], 'DecorationHover': p['primary']}
        kde['Colors:' + group] = {k: ','.join(map(str, rgb(v))) for k, v in values.items()}
    kde['General'] = {'Name': 'Clavis Theme', 'Name[zh_CN]': '跟随桌面主题', 'ColorScheme': 'NyxTheme'}
    kde['ColorEffects:Inactive'] = {'Enable': 'false'}
    atomic(base / '.local/share/color-schemes/NyxTheme.colors', ini(kde))

    # A palette-specific ID bypasses Konsole's in-memory color-scheme cache.
    token = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]
    profile = 'NyxTheme-' + token
    kde['General']['ColorScheme'] = profile
    atomic(base / f'.local/share/color-schemes/{profile}.colors', ini(kde))
    terminal = {'General': {'Description': '跟随桌面主题', 'Opacity': '0.94' if dark else '1', 'Blur': 'false'}}
    for key, color in [('Background', bg), ('BackgroundIntense', bg), ('BackgroundFaint', bg),
                       ('Foreground', fg), ('ForegroundIntense', fg), ('ForegroundFaint', p['on_surface_variant'])]:
        terminal[key] = {'Color': ','.join(map(str, rgb(color)))}
    for i in range(8):
        for suffix, color in [('', normal[i]), ('Intense', bright[i]), ('Faint', normal[i])]:
            terminal[f'Color{i}{suffix}'] = {'Color': ','.join(map(str, rgb(color)))}
    atomic(base / f'.local/share/konsole/{profile}.colorscheme', ini(terminal))
    profile_data = {'General': {'Name': '跟随桌面主题', 'Parent': 'FALLBACK/', 'TerminalMargin': '14'},
                    'Appearance': {'ColorScheme': profile, 'Font': 'JetBrainsMono Nerd Font,12,-1,5,50,0,0,0,0,0', 'LineSpacing': '2'},
                    'Scrolling': {'HistoryMode': '1', 'HistorySize': '10000', 'ScrollBarPosition': '2'},
                    'Cursor Options': {'CursorShape': '1', 'BlinkingCursorEnabled': 'true'}}
    atomic(base / f'.local/share/konsole/{profile}.profile', ini(profile_data))

    qss = f'''/* Generated from Clavis; includes the file-view palette bridge. */
QWidget {{ color: {fg}; selection-color: {p['on_primary_container']}; selection-background-color: {p['primary_container']}; }}
QMainWindow, QDialog, QToolBar, QDockWidget, QMenuBar {{ background-color: {p['surface_container']}; }}
DolphinView, DolphinView QGraphicsView, DolphinView QGraphicsView QWidget {{ color: {fg}; background-color: {bg}; }}
QAbstractItemView {{ background-color: {bg}; alternate-background-color: {p['surface_container_low']}; }}
QMenu, QToolTip {{ background-color: {p['surface_container_high']}; color: {fg}; border: 1px solid {p['outline_variant']}; }}
QMenu::item:selected, QToolButton:hover {{ background-color: {p['primary_container']}; color: {p['on_primary_container']}; }}
QLineEdit {{ color: {fg}; background-color: {bg}; selection-background-color: {p['primary_container']}; selection-color: {p['on_primary_container']}; }}
'''
    atomic(base / '.config/nyx-desktop-style/dolphin.qss', qss)
    return profile, qss

def refresh_live(profile, qss):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(dest, path, interface, method, sig=None, args=()):
        params = GLib.Variant(sig, args) if sig else None
        return bus.call_sync(dest, path, interface, method, params, None, Gio.DBusCallFlags.NONE, 1200, None).unpack()
    names = call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames')[0]
    def tree(dest, path):
        return ET.fromstring(call(dest, path, 'org.freedesktop.DBus.Introspectable', 'Introspect')[0])
    def children(dest, path):
        return [path.rstrip('/') + '/' + node.get('name') for node in tree(dest, path).findall('node')]
    for dest in names:
        if not (dest.startswith('org.kde.dolphin-') or dest.startswith('org.kde.konsole-')):
            continue
        try:
            if dest.startswith('org.kde.dolphin-'):
                for path in children(dest, '/dolphin'):
                    if path.rsplit('/', 1)[-1].startswith('Dolphin_'):
                        call(dest, path, 'org.qtproject.Qt.QWidget', 'setStyleSheet', '(s)', (qss,))
            # Konsole also exports sessions from Dolphin's embedded terminal.
            for path in children(dest, '/Sessions'):
                current = call(dest, path, 'org.kde.konsole.Session', 'profile')[0]
                if current in ('Nyx Dusk', '跟随桌面主题') or current.startswith(('NyxTheme-', 'NyxDusk')):
                    pid = call(dest, path, 'org.kde.konsole.Session', 'processId')[0]
                    try:
                        terminal = os.readlink(f'/proc/{pid}/fd/1')
                        if not re.fullmatch(r'/dev/pts/[0-9]+', terminal):
                            continue
                        fd = os.open(terminal, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
                        try:
                            if os.isatty(fd) and os.fstat(fd).st_uid == os.getuid():
                                # Writing to the slave sends terminal OUTPUT, never shell input.
                                # Konsole's OSC 50 updates only colors and preserves running jobs.
                                os.write(fd, f'\x1b]50;ColorScheme={profile}\x07'.encode())
                        finally:
                            os.close(fd)
                    except (OSError, ProcessLookupError):
                        continue
        except GLib.Error:
            # An app may close while being refreshed, or have no terminal yet.
            continue

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--palette', type=Path, default=SOURCE)
    parser.add_argument('--output-root', type=Path, default=BASE)
    parser.add_argument('--no-live', action='store_true')
    args = parser.parse_args()
    profile, qss = render(json.loads(args.palette.read_text()), args.output_root)
    if args.output_root == BASE:
        for file, group, key, value in [('dolphinrc','UiSettings','ColorScheme',''),
                                         ('konsolerc','UiSettings','ColorScheme',''),
                                         ('konsolerc','Desktop Entry','DefaultProfile',profile + '.profile')]:
            subprocess.run(['kwriteconfig6','--file',str(BASE / '.config' / file),'--group',group,'--key',key,value], check=True)
        current = subprocess.check_output(['kreadconfig6','--file','kdeglobals','--group','General','--key','ColorScheme'], text=True).strip()
        if current != profile:
            env = os.environ.copy()
            env['QT_QPA_PLATFORM'] = 'offscreen'
            if shutil.which('plasma-apply-colorscheme'):
                subprocess.run(['plasma-apply-colorscheme', profile], env=env, check=True, capture_output=True, text=True)
            else:
                subprocess.run(['kwriteconfig6', '--file', str(BASE / '.config/kdeglobals'), '--group', 'General', '--key', 'ColorScheme', profile], check=True)
        if not args.no_live:
            refresh_live(profile, qss)
        # Keep bounded history while leaving other user profiles alone.
        profiles = sorted((BASE / '.local/share/konsole').glob('NyxTheme-*.profile'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in profiles[8:]:
            if old.stem != profile:
                old.with_suffix('.colorscheme').unlink(missing_ok=True)
                (BASE / f'.local/share/color-schemes/{old.stem}.colors').unlink(missing_ok=True)
                old.unlink()
    print('Theme synchronized:', profile)

if __name__ == '__main__':
    main()
