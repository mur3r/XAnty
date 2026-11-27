import sys
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "xgenius" / "proxy_service.py"
spec = importlib.util.spec_from_file_location("proxy_service", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ProxyCheckError = module.ProxyCheckError
check_proxy = module.check_proxy
parse_ip_response = module.parse_ip_response
parse_proxy = module.parse_proxy


class ProxyFormatTests(unittest.TestCase):
    def test_legacy_credentials_and_reserved_characters(self):
        proxy = parse_proxy("proxy.example:8080:my@user:p@ss:word")
        self.assertEqual(proxy.server, "http://proxy.example:8080")
        self.assertEqual(proxy.requests_url, "http://my%40user:p%40ss%3Aword@proxy.example:8080")

    def test_url_format_and_no_auth(self):
        self.assertEqual(parse_proxy("http://user:p%40ss@proxy.example:8080").password, "p@ss")
        self.assertEqual(parse_proxy("proxy.example:8080").requests_url, "http://proxy.example:8080")

    def test_missing_invalid_and_unsupported_proxy_fail_closed(self):
        for raw in ("", "not-a-proxy", "host:99999:user:pass", "socks4://host:1080", "host:80:user:",
                    "http://proxy.example,direct:8080", "http://http=proxy.example:8080"):
            with self.subTest(raw=raw), self.assertRaises(ProxyCheckError):
                parse_proxy(raw)

    def test_ip_response(self):
        self.assertEqual(parse_ip_response('{"ip": "2001:db8::1"}'), "2001:db8::1")
        with self.assertRaises(ProxyCheckError):
            parse_ip_response("Not an IP")


class ProxyCheckTests(unittest.TestCase):
    def setUp(self):
        resolver = patch.object(module, "resolve_proxy", side_effect=lambda proxy: proxy)
        resolver.start()
        self.addCleanup(resolver.stop)

    def _fake_requests(self, status=200, text='{"ip":"203.0.113.20"}', error=None):
        class RequestException(Exception):
            pass

        class Timeout(RequestException):
            pass

        class ProxyError(RequestException):
            pass

        class SSLError(RequestException):
            pass

        class FakeSession:
            trust_env = True
            proxies = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url, **kwargs):
                self.check = (url, kwargs, self.trust_env, self.proxies.copy())
                if error == "proxy_auth":
                    raise ProxyError("http://user:secret@host:8000 responded 407")
                if error:
                    raise error
                return types.SimpleNamespace(status_code=status, text=text)

        session = FakeSession()
        exceptions = types.SimpleNamespace(Timeout=Timeout, ProxyError=ProxyError,
                                           SSLError=SSLError, RequestException=RequestException)
        fake = types.SimpleNamespace(Session=lambda: session, exceptions=exceptions)
        return fake, session, ProxyError

    def test_check_pins_both_schemes_to_proxy_and_disables_environment(self):
        fake, session, _ = self._fake_requests()
        with patch.dict(sys.modules, {"requests": fake}):
            self.assertEqual(check_proxy(parse_proxy("host:8000:user:pass")), "203.0.113.20")
        url, kwargs, trust_env, proxies = session.check
        self.assertTrue(url.startswith("https://"))
        self.assertEqual(trust_env, False)
        self.assertEqual(proxies["http"], "http://user:pass@host:8000")
        self.assertEqual(proxies["https"], proxies["http"])
        self.assertIn("timeout", kwargs)

    def test_an_unavailable_ip_service_falls_back_without_using_a_direct_connection(self):
        import requests
        from unittest.mock import Mock
        with requests.Session() as session:
            session.get = Mock(side_effect=[requests.exceptions.ConnectionError('reset'),
                                           types.SimpleNamespace(status_code=200, text='203.0.113.25')])
            with patch('requests.Session', return_value=session):
                self.assertEqual(check_proxy(parse_proxy('host:8000:user:pass')), '203.0.113.25')
            self.assertEqual(session.get.call_count, 2)
            self.assertFalse(session.trust_env)
            self.assertEqual(session.proxies['http'], session.proxies['https'])
            self.assertEqual(session.get.call_args.kwargs['allow_redirects'], False)

    def test_authentication_failure_has_safe_message(self):
        fake, _, _ = self._fake_requests(status=407)
        with patch.dict(sys.modules, {"requests": fake}):
            with self.assertRaisesRegex(ProxyCheckError, "407") as caught:
                check_proxy(parse_proxy("host:8000:user:secret"))
        self.assertNotIn("secret", str(caught.exception))

    def test_proxy_library_error_does_not_expose_credentials(self):
        fake, _, _ = self._fake_requests(error="proxy_auth")
        with patch.dict(sys.modules, {"requests": fake}):
            with self.assertRaisesRegex(ProxyCheckError, "authentication failed") as caught:
                check_proxy(parse_proxy("host:8000:user:secret"))
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
