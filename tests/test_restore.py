import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import configparser
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('restore', ROOT / 'scripts/restore.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / 'different-user home'

    def test_plan_does_not_write(self):
        restore.restore(self.target)
        self.assertFalse(self.target.exists())

    def test_restore_rebases_paths_and_preserves_existing_file(self):
        destination = self.target / '.config/clavis/dock.json'
        destination.parent.mkdir(parents=True)
        destination.write_text('{"existing": true}')
        old_db = self.target / '.local/share/fcitx5/rime/rime_ice.userdb'
        old_db.mkdir(parents=True)
        (old_db / '999999.log').write_bytes(b'old database log')
        backup = restore.restore(self.target, same_hardware=True, apply=True)
        self.assertEqual((backup / '.config/clavis/dock.json').read_text(), '{"existing": true}')
        desktop = configparser.ConfigParser(interpolation=None)
        desktop.read(self.target / '.local/share/applications/org.kde.dolphin.desktop')
        self.assertEqual(shlex.split(desktop['Desktop Entry']['Exec'])[0], str(self.target / '.local/bin/dolphin'))
        desktop.read(self.target / '.local/share/applications/org.kde.konsole.desktop')
        self.assertEqual(desktop['Desktop Entry']['TryExec'], '/usr/bin/konsole')
        dock = json.loads((self.target / '.config/clavis/dock.json').read_text())
        self.assertIn('org.clavis.Launchpad', [entry.get('desktopId') for entry in dock['pinned']])
        self.assertEqual(json.loads((self.target / '.config/clavis/launchpad.json').read_text()),
                         json.loads((ROOT / 'config/clavis/launchpad.json').read_text()))
        self.assertFalse((self.target / '.config/systemd/user/nyx-dock.service').exists())
        self.assertIn('niri-desktop/niri', (self.target / '.local/bin/niri').read_text())
        config = json.loads((self.target / '.config/clavis/config.json').read_text())
        self.assertTrue(Path(config['wallpaper']['path']).is_file())
        self.assertEqual(config['wallpaper']['folder'], str(self.target / 'Pictures/Wallpapers'))
        niri = (self.target / '.config/niri/config.kdl').read_text()
        self.assertNotIn('/home/nlh', niri)
        self.assertNotIn('@HOME@', niri)
        self.assertIn('/usr/lib/polkit-kde-authentication-agent-1', niri)
        self.assertEqual((self.target / '.config/niri/clavis/outputs.kdl').read_bytes(), (ROOT / 'hardware/outputs.kdl').read_bytes())
        self.assertTrue((self.target / '.local/share/fcitx5/rime/rime_ice.userdb/CURRENT').is_file())
        self.assertTrue(list((self.target / '.local/share/fcitx5/rime/rime_ice.userdb').glob('*.log')))
        self.assertFalse((old_db / '999999.log').exists())
        self.assertEqual((backup / '.local/share/fcitx5/rime/rime_ice.userdb/999999.log').read_bytes(), b'old database log')

    def test_new_hardware_resets_monitor_bindings(self):
        files = restore.plan(self.target, same_hardware=False)
        prefs = json.loads(files[Path('.config/clavis/primary-display.json')][0])
        self.assertIsNone(prefs['primary'])
        self.assertNotIn(b'output "', files[Path('.config/niri/clavis/outputs.kdl')][0])
        self.assertEqual(json.loads(files[Path('.config/clavis/ui-preferences.json')][0])['systemMonitorDiskDevice'], '')
        self.assertNotIn(b'gtk-xft-dpi=', files[Path('.config/gtk-4.0/settings.ini')][0])
        self.assertNotIn(b'Xft.dpi:', files[Path('.config/fcitx5/x11-dpi.Xresources')][0])

    def test_restore_keeps_all_required_niri_fragments_and_gtk_customization(self):
        files = restore.plan(self.target)
        for name in ['outputs', 'mouse', 'cursor', 'layer-rules', 'effects', 'minimize-animation']:
            self.assertIn(Path(f'.config/niri/clavis/{name}.kdl'), files)
        self.assertIn(b'reference-nautilus.css', files[Path('.config/gtk-4.0/gtk.css')][0])
        settings = configparser.ConfigParser()
        settings.read_string(files[Path('.config/kded5rc')][0].decode())
        self.assertFalse(settings.getboolean('Module-gtkconfig', 'autoload'))

    def test_parent_symlink_cannot_escape_target(self):
        self.target.mkdir(parents=True)
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.target / '.config').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'escapes selected home'):
            restore.restore(self.target, apply=True)
        self.assertEqual(list(outside.iterdir()), [])

    def fixture(self):
        fixture = Path(self.temp.name) / 'snapshot'
        (fixture / 'config').mkdir(parents=True)
        (fixture / 'config/test.ini').write_text('original')
        (fixture / 'sources.lock.json').write_text('{}')
        digests = {name: hashlib.sha256((fixture / name).read_bytes()).hexdigest()
                   for name in ['config/test.ini', 'sources.lock.json']}
        (fixture / 'manifest.json').write_text(json.dumps({'sha256': digests}))
        return fixture

    def test_tampered_file_is_rejected_before_restore(self):
        fixture = self.fixture()
        (fixture / 'config/test.ini').write_text('modified')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            restore.restore(self.target, apply=True, root=fixture)
        self.assertFalse(self.target.exists())

    def test_unlisted_file_is_rejected(self):
        fixture = self.fixture()
        (fixture / 'config/unlisted.ini').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            restore.restore(self.target, apply=True, root=fixture)
        self.assertFalse(self.target.exists())

    def test_unsafe_template_path_rejected_before_writes(self):
        path = Path(self.temp.name) / 'bad$dollar'
        with self.assertRaises(ValueError):
            restore.restore(path, apply=True)
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
