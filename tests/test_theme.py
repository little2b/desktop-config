import configparser
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('theme_sync', ROOT / 'lib/nyx-desktop-style/sync-theme.py')
theme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(theme)


class ThemeTests(unittest.TestCase):
    def test_fcitx_palette_change_updates_theme_without_overwriting_input_preferences(self):
        palette = json.loads((ROOT / 'share/clavis/profiles/default/generated/clavis/colors.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / '.config/fcitx5/conf/classicui.conf'
            config.parent.mkdir(parents=True)
            config.write_text('Font="Custom Font 14"\nVertical Candidate List=True\n')
            previous = config.read_bytes()
            for background, foreground, selected, selected_text in [
                ('#f5e5db', '#211a14', '#ffdcbf', '#2d1600'),
                ('#302b26', '#efe0d5', '#5c3d1b', '#ffdcbf'),
            ]:
                with self.subTest(background=background):
                    palette.update(surface_container_high=background, on_surface=foreground,
                                   primary_container=selected, on_primary_container=selected_text)
                    theme.render(palette, base)
                    theme_dir = base / '.local/share/fcitx5/themes/ClavisWallpaper'
                    parsed = configparser.ConfigParser()
                    parsed.read(theme_dir / 'theme.conf')
                    self.assertEqual(parsed['InputPanel/Background']['Color'], background)
                    self.assertEqual(parsed['InputPanel']['NormalColor'], foreground)
                    self.assertEqual(parsed['InputPanel/Highlight']['Color'], selected)
                    self.assertEqual(parsed['InputPanel']['HighlightCandidateColor'], selected_text)
                    self.assertEqual(parsed['Menu/Background']['Color'], background)
                    for section in ['InputPanel/PrevPage', 'InputPanel/NextPage', 'Menu/CheckBox', 'Menu/SubMenu']:
                        ET.parse(theme_dir / parsed[section]['Image'])
                    self.assertEqual(config.read_bytes(), previous)

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
