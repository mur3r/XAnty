import json
import unittest
from unittest.mock import patch
from xgenius.preferences import read_preferences
from tests import test_profile_management as fixtures


class PresentationApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ProfileApiTests.asyncSetUp
    asyncTearDown=fixtures.ProfileApiTests.asyncTearDown

    async def test_frame_preference_is_removed_even_from_old_saved_preferences(self):
        folder=self.engine.config.base_dir/'prefs';folder.mkdir(exist_ok=True)
        (folder/'preferences.json').write_text(json.dumps({'window_frames':True,'session_autosave':False}))
        response=await self.client.get('/api/preferences');self.assertEqual(response.status,200)
        data=await response.json();self.assertNotIn('window_frames',data);self.assertFalse(data['session_autosave'])

    async def test_short_icon_text_persists_and_invalid_label_does_not_change_profile(self):
        response=await self.client.patch('/api/accounts/metadata',json={'usernames':['alice'],'metadata':{'icon_text':'Раб12'}})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual(self.am.load_accounts()[0]['icon_text'],'Раб12')
        for bad in ('too-long-name','a\nb'):
            response=await self.client.patch('/api/accounts/metadata',json={'usernames':['alice'],'metadata':{'icon_text':bad}})
            self.assertEqual(response.status,400)
        self.assertEqual(self.am.load_accounts()[0]['icon_text'],'Раб12')
