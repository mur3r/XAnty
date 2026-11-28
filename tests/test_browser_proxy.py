"""Chrome verifies rotating HTTP proxy routes without opening a page."""

from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit, urlunsplit

from xgenius.proxy_service import ProxyCheckError, parse_proxy


def proxy_module():
    from xgenius import browser_proxy
    return browser_proxy


class BrowserProxyTests(unittest.TestCase):
    def verify(self, connection, proxy='127.0.0.1:8181:user:private-password'):
        module = proxy_module()
        with patch.object(module, 'browser_connection', connection.open):
            browser = SimpleNamespace(_xg_proxy_extension=SimpleNamespace(worker_url=connection.worker_url))
            return module.verify_browser_proxy(browser, parse_proxy(proxy), expected_ip='203.0.113.14')

    def test_each_launch_has_a_fresh_worker_identity_even_with_unchanged_credentials(self):
        proxy = parse_proxy('127.0.0.1:8181:user:private-password')
        first = proxy_module().prepare_proxy_extension(proxy)
        self.addCleanup(first.cleanup)
        second = proxy_module().prepare_proxy_extension(proxy)
        self.addCleanup(second.cleanup)
        self.assertNotEqual(first.worker_url, second.worker_url)

    def test_a_rotating_proxy_exit_is_accepted_when_the_proxy_socket_is_verified(self):
        connection = ChromeProxyConnection()
        self.assertEqual(self.verify(connection), '203.0.113.90')
        self.assertEqual(connection.page_changes, [])
        self.assertEqual(connection.detached, ['worker-session'])
        self.assertTrue(connection.closed)

    def test_a_direct_connection_is_rejected_even_with_a_valid_exit_ip(self):
        connection = ChromeProxyConnection(remote_ip='203.0.113.17')
        with self.assertRaisesRegex(ProxyCheckError, 'configured proxy'):
            self.verify(connection)
        self.assertEqual(connection.detached, ['worker-session'])
        self.assertTrue(connection.closed)

    def test_an_explicit_proxy_authentication_failure_is_reported(self):
        connection = ChromeProxyConnection(error='net::ERR_INVALID_AUTH_CREDENTIALS')
        with self.assertRaisesRegex(ProxyCheckError, 'authentication failed') as caught:
            self.verify(connection)
        self.assertNotIn('private-password', str(caught.exception))
        self.assertEqual(connection.detached, ['worker-session'])
        self.assertTrue(connection.closed)

    def test_an_unreachable_proxy_is_reported_as_a_connection_failure(self):
        connection = ChromeProxyConnection(error='net::ERR_PROXY_CONNECTION_FAILED')
        with self.assertRaisesRegex(ProxyCheckError, 'could not connect'):
            self.verify(connection)
        self.assertEqual(connection.page_changes, [])
        self.assertTrue(connection.closed)

    def test_a_malformed_ip_check_response_fails_verification(self):
        with self.assertRaisesRegex(ProxyCheckError, 'valid public IP'):
            self.verify(ChromeProxyConnection(body='an unrelated response'))

    def test_unavailable_ip_service_uses_an_independent_service_through_the_same_proxy(self):
        connection=ChromeProxyConnection(statuses=[503,200])
        self.assertEqual(self.verify(connection),'203.0.113.90')
        self.assertEqual([urlsplit(url).hostname for url in connection.probes],['api64.ipify.org','checkip.amazonaws.com'])

    def test_ip_service_connection_reset_uses_the_other_service(self):
        connection = ChromeProxyConnection(errors=['net::ERR_CONNECTION_RESET', None])
        self.assertEqual(self.verify(connection), '203.0.113.90')
        self.assertEqual(len(connection.probes), 2)


class ChromeProxyConnection:
    def __init__(self, remote_ip='127.0.0.1', body='{"ip":"203.0.113.90"}', error=None,statuses=None, errors=None):
        self.remote_ip = remote_ip
        self.worker_url = 'chrome-extension://synthetic-proxy-worker/background.js'
        self.body = body
        self.error = error
        self.errors = list(errors or [])
        self.detached = []
        self.closed = False
        self.page_changes = []
        self.probe_url = None
        self.statuses=list(statuses or []);self.probes=[]

    @contextmanager
    def open(self, browser, timeout):
        try:
            yield self
        finally:
            self.closed = True

    def call(self, method, params, session_id=None, timeout=None):
        if method.startswith('Page.') or method in ('Target.createTarget', 'Target.activateTarget'):
            self.page_changes.append(method)
        if method == 'Target.getTargets':
            return {'targetInfos': [
                {'targetId': 'user-tab', 'type': 'page', 'url': 'https://user.example/'},
                {'targetId': 'other-worker', 'type': 'service_worker', 'url': 'chrome-extension://other/background.js'},
                {'targetId': 'proxy-worker', 'type': 'service_worker',
                 'url': self.worker_url}
            ]}
        if method == 'Target.attachToTarget':
            assert params == {'targetId': 'proxy-worker', 'flatten': True}
            return {'sessionId': 'worker-session'}
        if method == 'Target.detachFromTarget':
            self.detached.append(params['sessionId'])
            return {}
        if method == 'Network.enable':
            assert session_id == 'worker-session'
            return {}
        if method == 'Runtime.evaluate':
            assert session_id == 'worker-session'
            if not params.get('awaitPromise'):
                return {'result': {'type': 'boolean', 'value': True}}
            expression = params['expression']
            import re
            url = re.search(r'fetch\(\s*"(https://[^"]+)"', expression).group(1)
            assert urlsplit(url).hostname in ('api.ipify.org','api64.ipify.org','checkip.amazonaws.com')
            if urlsplit(url).hostname=='api.ipify.org':assert parse_qs(urlsplit(url).query)['format'] == ['json']
            parsed=urlsplit(url)
            self.probe_url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path or '/',parsed.query,parsed.fragment))
            self.probes.append(url)
            if self.errors:
                self.error = self.errors.pop(0)
            value = {'error': 'TypeError'} if self.error else {'status': self.statuses.pop(0) if self.statuses else 200, 'body': self.body}
            return {'result': {'type': 'object', 'value': value}}
        raise AssertionError(method)

    def wait_event(self, method, session_id=None, predicate=None, timeout=None):
        assert session_id == 'worker-session'
        response = {
            'Network.requestWillBeSent': {'requestId': 'browser-fetch', 'request': {'url': self.probe_url}},
            'Network.responseReceived': {'requestId': 'browser-fetch', 'response': {
                'url': self.probe_url, 'status': 200, 'remoteIPAddress': self.remote_ip,
                'remotePort': 8181, 'fromDiskCache': False, 'fromServiceWorker': False,
                'fromPrefetchCache': False}},
            'Network.loadingFailed': {'requestId': 'browser-fetch', 'errorText': self.error}
        }[method]
        assert predicate(response)
        return response


if __name__ == '__main__':
    unittest.main()
