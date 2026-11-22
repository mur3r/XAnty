import unittest
from xgenius.network_diagnostics import classify_webrtc, summarize_dns, diagnose
from types import SimpleNamespace


class DiagnosticsTests(unittest.TestCase):
    def test_failed_ip_measurement_cannot_be_reported_as_a_webrtc_match(self):
        browser=SimpleNamespace(current_window_handle='user',window_handles=['user'])
        browser.switch_to=SimpleNamespace(new_window=lambda kind:None,window=lambda h:None)
        browser.get=lambda url:None;browser.set_script_timeout=lambda timeout:None
        browser.execute_async_script=lambda source:{'ip':'','rtc':['8.8.8.8']}
        browser.close=lambda:None
        result=diagnose(browser,'8.8.8.8')
        self.assertEqual(result['ip'],'')
        self.assertEqual(result['webrtc']['status'],'inconclusive')
    def test_public_webrtc_mismatch_is_reported(self):
        report=classify_webrtc('8.8.8.8',['8.8.8.8','9.9.9.9','192.168.1.2','test.local'])
        self.assertEqual(report['status'],'warning')
        self.assertEqual(report['mismatches'],['9.9.9.9'])

    def test_no_public_webrtc_candidates_is_not_a_pass(self):
        self.assertEqual(classify_webrtc('8.8.8.8',['192.168.1.2','test.local'])['status'],'inconclusive')

    def test_dns_unknown_partial_or_foreign_results_do_not_become_pass(self):
        for status in ('inconclusive','new_status'):
            self.assertEqual(summarize_dns({'verdict':{'status':status}})['status'],'inconclusive')
        self.assertEqual(summarize_dns({'verdict':{'status':'no_leak'},'lookups':2},6)['status'],'inconclusive')
        self.assertEqual(summarize_dns({'verdict':{'status':'split'},'lookups':6},6)['status'],'warning')
