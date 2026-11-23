import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xgenius import browser_search


class QuietSearchTests(unittest.TestCase):
    def test_first_repair_is_background_and_verified_result_is_reused(self):
        calls=[]
        browser=SimpleNamespace(capabilities={'browserVersion':'128.0.1.2'},get=lambda url:calls.append(('visible',url)))
        @contextmanager
        def background(browser,url,**kwargs):
            calls.append(('background',url));yield SimpleNamespace(evaluate=lambda *a,**k:{'ok':True,'changed':False,'url':'https://www.google.com/search?q=%s'})
        with tempfile.TemporaryDirectory() as folder,patch.object(browser_search,'background_target',background,create=True):
            result=browser_search.ensure_search_engine(browser,Path(folder))
            self.assertTrue(result['ok']);self.assertTrue(browser_search.ensure_search_engine(browser,Path(folder))['cached'])
        self.assertEqual(calls,[('background','chrome://settings/searchEngines')])

    def test_failed_repair_does_not_write_a_success_marker(self):
        browser=SimpleNamespace(capabilities={'browserVersion':'128.0.1.2'})
        @contextmanager
        def background(*args,**kwargs):yield SimpleNamespace(evaluate=lambda *a,**k:{'ok':False})
        with tempfile.TemporaryDirectory() as folder,patch.object(browser_search,'background_target',background,create=True):
            with self.assertRaises(browser_search.SearchConfigurationError):browser_search.ensure_search_engine(browser,Path(folder))
            self.assertFalse(list(Path(folder).glob('.xanty-search*')))
