"""Geography must describe the checked exit IP without bypassing the proxy."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xgenius import proxy_service as service


class LocationTests(unittest.TestCase):
    def setUp(self):
        resolver = patch.object(service, "resolve_proxy", side_effect=lambda proxy: proxy)
        resolver.start()
        self.addCleanup(resolver.stop)

    def test_location_is_normalized_and_request_uses_the_checked_proxy(self):
        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(inner, url, **kwargs):
                self.assertIn('/8.8.8.8', url)
                self.assertFalse(inner.trust_env)
                self.assertEqual(inner.proxies['https'], 'http://u:secret@host:80')
                self.assertIn('timeout', kwargs)
                return SimpleNamespace(status_code=200, json=lambda: {
                    'success': True, 'ip': '8.8.8.8', 'country_code': 'US',
                    'country': 'United States', 'region': 'Florida', 'city': 'Miami'})

        with patch('requests.Session', Session):
            result = service.lookup_proxy_location(service.parse_proxy('host:80:u:secret'), '8.8.8.8')
        self.assertEqual(result, {'country_code': 'US', 'country': 'United States',
                                  'region': 'Florida', 'city': 'Miami'})

    def test_equivalent_ipv6_response_forms_are_accepted(self):
        result = service.parse_location_response({'success': True, 'ip': '2001:db8:0:0:0:0:0:1',
            'country_code': 'US', 'city': 'Miami'}, '2001:db8::1')
        self.assertEqual(result['city'], 'Miami')

    def test_mismatched_or_malformed_location_is_not_accepted(self):
        for payload in ({'success': False}, {'success': True, 'ip': '1.1.1.1', 'country_code': 'US'},
                        {'success': True, 'ip': '8.8.8.8', 'country_code': '<script>'}):
            with self.subTest(payload=payload), self.assertRaises(service.ProxyCheckError):
                service.parse_location_response(payload, '8.8.8.8')


if __name__ == '__main__':
    unittest.main()
