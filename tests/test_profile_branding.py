import json
import tempfile
import unittest
from pathlib import Path
from xgenius.config import Config
from xgenius.profile_identity import prepare_identity


class BrandingTests(unittest.TestCase):
    def test_profile_toolbar_popup_contains_full_escaped_name_without_page_permissions(self):
        from xgenius.profile_branding import prepare_branding, EXTENSION_ID
        with tempfile.TemporaryDirectory() as folder:
            config=Config(Path(folder));identity=prepare_identity(config,'alice','Работа <script> & 12','stable',12,'РАБ12')
            profile=config.get_profile_dir('alice');prefs=profile/'Default/Preferences'
            data=json.loads(prefs.read_text());data['extensions']={'pinned_extensions':['existing']};prefs.write_text(json.dumps(data))
            extension=prepare_branding(profile,identity)
            manifest=json.loads((extension/'manifest.json').read_text(encoding='utf-8'))
            self.assertNotIn('permissions',manifest);self.assertNotIn('host_permissions',manifest)
            self.assertNotIn('content_scripts',manifest);self.assertNotIn('chrome_url_overrides',manifest)
            self.assertEqual(manifest['action']['default_title'],identity.name)
            html=(extension/'profile.html').read_text(encoding='utf-8')
            self.assertIn('Работа &lt;script&gt; &amp; 12',html);self.assertNotIn('<script>',html)
            self.assertEqual((extension/'icon32.png').read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
            prepare_branding(profile,identity)
            pinned=json.loads(prefs.read_text())['extensions']['pinned_extensions']
            self.assertEqual(pinned,['existing',EXTENSION_ID])
