import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('capture', ROOT / 'scripts/capture-current.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def test_rebase_and_remove_credentials_without_changing_preferences(self):
        source = {'file': '/home/source/Pictures/image.png', 'dark': True,
                  'nested': {'apiKey': 'do-not-publish', 'password': 'private', 'token': 'private'},
                  'pinned': ['chatgpt', 'org.kde.dolphin']}
        result = capture.clean_settings(source, Path('/home/source'))
        self.assertEqual(result['file'], '@HOME@/Pictures/image.png')
        self.assertEqual(result['nested'], {'apiKey': '', 'password': '', 'token': ''})
        self.assertEqual(result['pinned'], source['pinned'])
        self.assertTrue(result['dark'])
        self.assertEqual(source['nested']['apiKey'], 'do-not-publish')
