import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from xgenius.process_utils import hard_close_browser


class ProcessOwnershipTests(unittest.TestCase):
    def test_exited_driver_pid_is_never_resolved_as_a_new_process(self):
        unrelated=SimpleNamespace(children=lambda recursive:[],kill=Mock())
        browser=SimpleNamespace(_xg_pid=12345,service=SimpleNamespace(process=SimpleNamespace(pid=12345,poll=lambda:0)),quit=lambda:None)
        with patch('xgenius.process_utils.psutil.pid_exists',return_value=True), \
                patch('xgenius.process_utils.psutil.Process',return_value=unrelated) as lookup:
            hard_close_browser(browser,timeout=0.01)
        lookup.assert_not_called()
        unrelated.kill.assert_not_called()
