import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class CdpTests(unittest.TestCase):
    def module(self):
        from xgenius import browser_cdp
        return browser_cdp

    def test_interleaved_network_event_is_preserved_while_command_completes(self):
        module=self.module()
        messages=[{'method':'Network.responseReceived','sessionId':'s','params':{'requestId':'request'}},
                  {'id':1,'result':{'targetId':'owned'}}]
        socket=SimpleNamespace(send=lambda data:None,settimeout=lambda value:None,recv=lambda:json.dumps(messages.pop(0)),close=lambda:None)
        connection=module.CdpConnection(socket,3)
        self.assertEqual(connection.call('Target.createTarget',{})['targetId'],'owned')
        self.assertEqual(connection.wait_event('Network.responseReceived',session_id='s')['requestId'],'request')

    def test_remote_or_credential_bearing_debugger_addresses_are_rejected(self):
        module=self.module()
        for address in ('remote.test:9222','user:pass@127.0.0.1:9222','127.0.0.1:9222/path'):
            browser=SimpleNamespace(capabilities={'goog:chromeOptions':{'debuggerAddress':address}})
            with self.assertRaises(module.CdpError),patch.object(module.requests,'Session') as request:
                with module.browser_connection(browser):pass
            request.assert_not_called()

    def test_background_target_is_closed_after_body_failure_without_activation(self):
        module=self.module();calls=[]
        class Connection:
            hidden_supported=False
            def call(self,method,params=None,**kwargs):
                calls.append((method,params or {}))
                return {'Target.createTarget':{'targetId':'ours'},'Target.attachToTarget':{'sessionId':'s'},
                        'Target.getTargets':{'targetInfos':[]}}.get(method,{})
        from contextlib import contextmanager
        @contextmanager
        def connect(*args,**kwargs):yield Connection()
        with patch.object(module,'browser_connection',connect):
            with self.assertRaisesRegex(ValueError,'body'):
                with module.background_target(object()) as target:
                    self.assertEqual(target.session_id,'s');raise ValueError('body')
        self.assertIn(('Target.closeTarget',{'targetId':'ours'}),calls)
        self.assertEqual(calls[0],('Target.createTarget',{'url':'about:blank','background':True}))
        self.assertFalse(any(method=='Target.activateTarget' for method,_ in calls))
