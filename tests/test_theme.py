import configparser
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('theme_sync', ROOT / 'lib/nyx-desktop-style/sync-theme.py')
theme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(theme)


class ThemeTests(unittest.TestCase):
    def test_kde_fallback_applies_colors_and_preserves_user_preferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            target = base / 'kdeglobals'
            target.write_text('[General]\nfont=My Font\n[Other]\nvalue=keep\n')
            scheme = base / 'theme.colors'
            scheme.write_text('[General]\nColorScheme=NyxTheme-test\n[Colors:View]\nBackgroundNormal=10,20,30\nForegroundNormal=240,240,240\n')
            theme.apply_kde_palette(scheme, target)
            parsed = configparser.ConfigParser()
            parsed.read(target)
            self.assertEqual(parsed['General']['font'], 'My Font')
            self.assertEqual(parsed['General']['ColorScheme'], 'NyxTheme-test')
            self.assertEqual(parsed['Colors:View']['BackgroundNormal'], '10,20,30')
            self.assertEqual(parsed['Other']['value'], 'keep')
