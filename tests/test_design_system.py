import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'xgenius/web/static'


def contrast(one, two):
    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        channels = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(channels, (.2126, .7152, .0722)))
    bright, dark = sorted((luminance(one), luminance(two)), reverse=True)
    return (bright + .05) / (dark + .05)


class DesignSystemTests(unittest.TestCase):
    def test_text_and_primary_actions_have_readable_contrast_in_both_themes(self):
        css = (STATIC / 'design-system.css').read_text(encoding='utf-8')
        base = re.search(r':root\s*\{(.*?)\}', css, re.S).group(1)
        light = re.search(r':root\[data-theme=light\]\s*\{(.*?)\}', css, re.S).group(1)
        parse = lambda block: dict(re.findall(r'(--color-[\w-]+):\s*(#[0-9a-fA-F]{6});', block))
        for name, palette in (('dark', parse(base)), ('light', {**parse(base), **parse(light)})):
            for text in ('--color-text', '--color-text-secondary', '--color-text-muted', '--color-accent-ink'):
                for background in ('--color-bg', '--color-sidebar', '--color-card', '--color-control'):
                    with self.subTest(theme=name, text=text, background=background):
                        self.assertGreaterEqual(contrast(palette[text], palette[background]), 4.5)
            for background in ('--color-primary', '--color-primary-hover', '--color-primary-active'):
                with self.subTest(theme=name, button=background):
                    self.assertGreaterEqual(contrast(palette['--color-on-primary'], palette[background]), 4.5)

    def test_every_referenced_css_token_is_defined(self):
        css = '\n'.join((STATIC / name).read_text(encoding='utf-8') for name in ('style.css', 'design-system.css', 'profiles-screen.css', 'premium-surfaces.css', 'motion.css'))
        declared = set(re.findall(r'(--[\w-]+)\s*:', css))
        referenced = set(re.findall(r'var\((--[\w-]+)', css))
        self.assertEqual(referenced - declared, set())

    def test_preview_inlines_all_stylesheets_and_preserves_the_live_assets(self):
        spec = importlib.util.spec_from_file_location('premium_preview', ROOT / 'tools/build_preview.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            for path in STATIC.iterdir():
                if path.suffix in ('.js', '.css') or path.name == 'index.html':
                    shutil.copyfile(path, temporary / path.name)
            with patch.object(module, 'STATIC', temporary):
                html = module.build().read_text(encoding='utf-8')
            self.assertIn('--color-bg: #0C0A14', html)
            self.assertNotRegex(html, r'<link rel="stylesheet"')
        self.assertLess((STATIC / 'index.html').read_text(encoding='utf-8').index('style.css'),
                        (STATIC / 'index.html').read_text(encoding='utf-8').index('design-system.css'))

