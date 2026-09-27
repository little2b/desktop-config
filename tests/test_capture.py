import importlib.util
import unittest
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capture', ROOT / 'scripts/capture-current.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def test_rebase_and_remove_credentials_without_changing_preferences(self):
        source = {'file': '/home/source/Pictures/image.png', 'dark': True,
                  'nested': {'apiKey': 'do-not-publish', 'password': 'private', 'token': 'private', 'cookie': 'private'},
                  'pinned': ['chatgpt', 'org.gnome.Nautilus'], 'sidebarCookieDialStyle': 'numbers'}
        result = capture.clean_settings(source, Path('/home/source'))
        self.assertEqual(result['file'], '@HOME@/Pictures/image.png')
        self.assertEqual(result['nested'], {'apiKey': '', 'password': '', 'token': '', 'cookie': ''})
        self.assertEqual(result['pinned'], source['pinned'])
        self.assertTrue(result['dark'])
        self.assertEqual(source['nested']['apiKey'], 'do-not-publish')
        self.assertEqual(result['sidebarCookieDialStyle'], 'numbers')

    def test_native_dock_and_groups_capture_without_legacy_dock(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home = base / 'source home'
            root = base / 'snapshot'
            for folder in [home / '.config/clavis', home / '.config/quickshell/clavis/Modules/Dock', root]:
                folder.mkdir(parents=True)
            (home / '.config/quickshell/clavis/Modules/Dock/DockHost.qml').write_text('Item {}\n')
            (root / 'sources.lock.json').write_text('{"clavis":{"commit":"fixed"}}')
            dock = {'schemaVersion': 1, 'options': {'autoHide': True},
                    'pinned': [{'kind': 'app', 'desktopId': 'org.clavis.Launchpad'}]}
            groups = {'schemaVersion': 1, 'entries': [{'kind': 'folder', 'id': 'work',
                      'name': 'Work', 'children': ['editor', 'browser']}]}
            (home / '.config/clavis/dock.json').write_text(json.dumps(dock))
            (home / '.config/clavis/launchpad.json').write_text(json.dumps(groups))
            retired = {
                'bin/dolphin': '.local/bin/dolphin',
                'share/applications/org.kde.dolphin.desktop': '.local/share/applications/org.kde.dolphin.desktop',
                'config/dolphinrc': '.config/dolphinrc',
                'config/nyx-desktop-style/dolphin.qss': '.config/nyx-desktop-style/dolphin.qss',
            }
            for snapshot_path, source_path in retired.items():
                for path in [root / snapshot_path, home / source_path]:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('old Dolphin customization\n')
            capture.capture(home, root)
            self.assertEqual(json.loads((root / 'config/clavis/dock.json').read_text()), dock)
            self.assertEqual(json.loads((root / 'config/clavis/launchpad.json').read_text()), groups)
            self.assertFalse((root / 'config/quickshell/nyx-dock').exists())
            for snapshot_path, source_path in retired.items():
                self.assertFalse((root / snapshot_path).exists())
                self.assertTrue((home / source_path).is_file())
            self.assertEqual(json.loads((root / 'sources.lock.json').read_text())['clavis']['commit'], 'fixed')
