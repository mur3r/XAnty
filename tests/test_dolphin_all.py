"""Uncapped Dolphin imports handle pagination, collisions, retries and reruns."""
import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xgenius.config import Config
from xgenius.dolphin_import import API_BASE, DolphinClient, DolphinError
from xgenius.folders import FolderStore
from xgenius.jobs import Job
from xgenius.web.actions import Actions


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code, self.headers = data, status, {}

    def json(self):
        return self.data


class Session:
    def __init__(self, replies):
        self.replies, self.calls, self.headers = replies, [], {}

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        return self.replies.pop(0)

    def close(self):
        pass


class DolphinPaginationTests(unittest.TestCase):
    def test_every_cursor_page_is_read_beyond_the_old_500_profile_limit(self):
        rows = [{'id': i} for i in range(1, 1204)]
        replies = [Response({'data': rows[start:start + 50], 'total': len(rows),
                             'next_page_url': f'{API_BASE}/browser_profiles/list-cursor?cursor={start + 50}'
                             if start + 50 < len(rows) else None}) for start in range(0, len(rows), 50)]
        session = Session(replies)
        self.assertEqual(DolphinClient('fake-token', session).profile_ids(), list(range(1, 1204)))
        self.assertEqual(len(session.calls), 25)

    def test_rate_limits_retry_but_do_not_retry_access_denied(self):
        session = Session([Response({}, 429), Response({'data': []})])
        client = DolphinClient('fake-token', session)
        with patch.object(client, '_wait') as wait:
            client._request('GET', API_BASE + '/folders')
        self.assertEqual(len(session.calls), 2)
        wait.assert_called_once()
        with self.assertRaises(DolphinError):
            DolphinClient('fake-token', Session([Response({}, 401)]))._request('GET', API_BASE + '/folders')


class DolphinAllTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_profiles_collision_names_folders_cookies_and_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Config(Path(directory))
            data = [{'username': 'alice', 'group': 'Existing'}]

            class Manager:
                accounts = {}

                def load_accounts(self):
                    return copy.deepcopy(data)

                def save_accounts(self, value):
                    data[:] = copy.deepcopy(value)

            profiles = [{'id': 1, 'name': '@alice', 'folderId': 9},
                        {'id': 2, 'name': '@alice', 'folderId': 9},
                        {'id': 3, 'name': 'Protected profile', 'folderId': 9}]

            class Client:
                def __init__(self, token, **kwargs):
                    self.token = token

                def profile_pages(self):
                    yield profiles[:2], 3, 'next'
                    yield profiles[2:], 3, None

                def folders(self):
                    return {'9': 'Imported folder'}

                def get_profile(self, number, password=''):
                    if number == 3:
                        raise DolphinError('No access to this Dolphin profile', status=403)
                    return {**profiles[number - 1], 'proxy': {'type': 'http', 'host': 'proxy.test', 'port': 80}}

                def export_cookies(self, number, password='', all_sites=False):
                    if number == 3:
                        return [], 'Cookies unavailable: No access to this Dolphin profile'
                    return [{'name': 'auth_token', 'value': 'private-session', 'domain': '.x.com'},
                            {'name': 'other', 'value': 'other-session', 'domain': 'example.com'}], ''

                def close(self):
                    pass

            engine = SimpleNamespace(config=config, account_manager=Manager(), loop=asyncio.get_running_loop(),
                                     folders=FolderStore(config.base_dir / 'folders.json'), notify=lambda: None,
                                     logger=SimpleNamespace(info=lambda *args: None))
            actions = Actions(engine)
            job = Job('dolphin')
            with patch('xgenius.web.actions.DolphinClient', Client):
                result = await actions.import_dolphin_all('never-save-this-token', job)
                self.assertEqual(len(data), 4)
                self.assertEqual([a['username'] for a in data], ['alice', 'alice_2', 'alice_3', 'dolphin_3'])
                self.assertTrue(data[1]['auto_login'])
                self.assertEqual(data[1]['group'], 'Imported folder')
                self.assertEqual(result['report'][0]['all_cookies'], 2)
                self.assertTrue(result['report'][2]['warnings'])
                self.assertNotIn('never-save-this-token', str(data) + str(job.snapshot()))
                self.assertNotIn('private-session', str(job.snapshot()))
                second = await actions.import_dolphin_all('never-save-this-token', Job('dolphin'))
                self.assertEqual([r['status'] for r in second['report']], ['skipped'] * 3)
                self.assertEqual(len(data), 4)


if __name__ == '__main__':
    unittest.main()
