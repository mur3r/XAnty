"""Real sockets cover preemptive auth, per-profile isolation and closed routing."""
import base64
import socket
import ssl
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

from xgenius.http_bridge import HttpBridge
from xgenius.proxy_service import HttpProxy, parse_proxy, resolve_proxy


class StrictProxy(BaseHTTPRequestHandler):
    def authorized(self):
        token = self.headers.get('Proxy-Authorization', '')
        self.server.requests.append((self.command, self.path, dict(self.headers)))
        if token not in self.server.allowed:
            # Some gateways reject an unauthenticated request without supplying
            # a usable challenge. Preemptive clients still work with this server.
            self.send_response(407)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return False
        return True

    def do_GET(self):
        if self.authorized():
            body = b'{"ip":"203.0.113.90"}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.authorized():
            body = self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_CONNECT(self):
        if self.authorized():
            self.send_response(200)
            self.end_headers()
            while True:
                body = self.connection.recv(65536)
                if not body:
                    return
                self.connection.sendall(body)

    def log_message(self, *args):
        pass


def authorization(user, password):
    return 'Basic ' + base64.b64encode(f'{user}:{password}'.encode('latin-1')).decode('ascii')


class HttpBridgeTests(unittest.TestCase):
    scheme = 'http'

    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), StrictProxy)
        self.server.daemon_threads = True
        self.server.requests = []
        self.server.allowed = {authorization('user', 'synthetic:p@ss%word')}
        if self.scheme == 'https':
            self.configure_tls()
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.proxy = HttpProxy('127.0.0.1', self.server.server_port, 'user', 'synthetic:p@ss%word', self.scheme)

    def configure_tls(self):
        from ipaddress import ip_address
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'XAnty test proxy')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1'))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
        self.cert_file = Path(directory.name) / 'proxy.pem'
        key_file = Path(directory.name) / 'proxy.key'
        self.cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.cert_file, key_file)
        self.server.socket = server_context.wrap_socket(self.server.socket, server_side=True)
        self.trusted_context = ssl.create_default_context(cafile=str(self.cert_file))
        self.tls_patch = patch('xgenius.http_bridge.ssl.create_default_context', return_value=self.trusted_context)
        self.tls_patch.start()
        self.addCleanup(self.tls_patch.stop)

    def bridge(self, proxy=None):
        bridge = HttpBridge(proxy or self.proxy)
        self.addCleanup(bridge.cleanup)
        return bridge

    def request(self, bridge, method='GET', **kwargs):
        with requests.Session() as session:
            session.trust_env = False
            session.proxies = {'http': bridge.proxy.requests_url, 'https': bridge.proxy.requests_url}
            return session.request(method, 'http://origin.invalid/test?q=1', timeout=5, **kwargs)

    def test_first_request_has_upstream_credentials_and_never_local_credentials(self):
        bridge = self.bridge()
        self.assertEqual(self.request(bridge).status_code, 200)
        method, target, headers = self.server.requests[0]
        self.assertEqual((method, target), ('GET', 'http://origin.invalid/test?q=1'))
        self.assertEqual(headers['Proxy-Authorization'], authorization('user', self.proxy.password))
        self.assertNotIn(bridge.proxy.password, str(headers))
        self.assertEqual(len(self.server.requests), 1)

    def test_post_body_is_relayed_without_waiting_for_a_response_first(self):
        self.assertEqual(self.request(self.bridge(), 'POST', data=b'form=test').content, b'form=test')

    def test_local_auth_is_required_before_contacting_upstream(self):
        bridge = self.bridge()
        with requests.Session() as session:
            session.trust_env = False
            session.proxies = {'http': bridge.proxy.server}
            self.assertEqual(session.get('http://origin.invalid/', timeout=5).status_code, 407)
        self.assertEqual(self.server.requests, [])

    def tunnel(self, bridge):
        stream = socket.create_connection(('127.0.0.1', bridge.proxy.port), timeout=5)
        self.addCleanup(stream.close)
        stream.sendall((f'CONNECT origin.invalid:443 HTTP/1.1\r\nHost: origin.invalid:443\r\n'
                        f'Proxy-Authorization: {bridge.authorization}\r\n\r\n').encode())
        header = b''
        while b'\r\n\r\n' not in header:
            part = stream.recv(1)
            if not part:
                break
            header += part
        return stream, header

    def test_connect_authenticates_before_tunneling_and_cleanup_closes_sockets(self):
        bridge = self.bridge()
        stream, header = self.tunnel(bridge)
        self.assertIn(b'200 Connection Established', header)
        stream.sendall(b'opaque TLS bytes')
        self.assertEqual(stream.recv(16), b'opaque TLS bytes')
        self.assertEqual(self.server.requests[0][0:2], ('CONNECT', 'origin.invalid:443'))
        bridge.cleanup()
        self.assertEqual(stream.recv(1), b'')
        self.assertFalse(bridge.thread.is_alive())
        bridge.cleanup()

    def test_upstream_407_is_safe_and_never_opens_a_direct_connection(self):
        bad = replace(self.proxy, password='wrong-secret')
        bridge = self.bridge(bad)
        real_connect = socket.create_connection
        calls = []
        def connect(address, *args, **kwargs):
            calls.append(address)
            return real_connect(address, *args, **kwargs)
        with patch('xgenius.http_bridge.socket.create_connection', side_effect=connect):
            _, header = self.tunnel(bridge)
        self.assertIn(b'502', header)
        self.assertIn('407', bridge.last_error)
        self.assertNotIn('wrong-secret', bridge.last_error)
        self.assertEqual(set(calls), {('127.0.0.1', bridge.proxy.port), (self.proxy.host, self.proxy.port)})

    def test_concurrent_profiles_use_their_own_credentials_on_the_same_endpoint(self):
        other = replace(self.proxy, username='second', password='second-password')
        self.server.allowed.add(authorization(other.username, other.password))
        first, second = self.bridge(), self.bridge(other)
        self.assertNotEqual(first.proxy.password, second.proxy.password)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(self.request, (first, second)))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual({row[2]['Proxy-Authorization'] for row in self.server.requests}, self.server.allowed)


class HttpsBridgeTests(HttpBridgeTests):
    scheme = 'https'

    def test_untrusted_tls_proxy_is_rejected_before_sending_credentials(self):
        self.tls_patch.stop()
        bridge = self.bridge()
        self.assertEqual(self.request(bridge).status_code, 502)
        self.assertEqual(self.server.requests, [])
        self.assertIn('certificate error', bridge.last_error)
        self.assertNotIn(self.proxy.password, bridge.last_error)

    def test_large_connect_stream_survives_tls_record_boundaries(self):
        stream, header = self.tunnel(self.bridge())
        self.assertIn(b'200 Connection Established', header)
        payload = bytes(range(256)) * 1024
        stream.sendall(payload)
        received = b''
        while len(received) < len(payload):
            block = stream.recv(65536)
            if not block:
                break
            received += block
        self.assertEqual(received, payload)

    def test_ip_check_connects_to_the_tls_proxy_with_certificate_validation(self):
        from xgenius import proxy_service
        session_class = requests.Session
        def session():
            instance = session_class()
            instance.verify = str(self.cert_file)
            return instance
        with patch('requests.Session', side_effect=session), \
                patch.object(proxy_service, 'IP_CHECK_URLS', ('http://origin.invalid/ip',)):
            self.assertEqual(proxy_service.check_proxy(self.proxy), '203.0.113.90')
        self.assertEqual(self.server.requests[0][1], 'http://origin.invalid/ip')


class ExplicitProxyFormatTests(unittest.TestCase):
    def test_optional_protocol_prefix_preserves_legacy_credentials(self):
        for prefix, scheme in (('', 'http'), ('http://', 'http'), ('https://', 'https'), ('socks5://', 'socks5')):
            with self.subTest(prefix=prefix):
                proxy = parse_proxy(prefix + 'proxy.example:8080:my@user:p@ss:%word')
                self.assertEqual((proxy.host, proxy.port, proxy.username, proxy.password, proxy.scheme),
                                 ('proxy.example', 8080, 'my@user', 'p@ss:%word', scheme))
        proxy = parse_proxy('socks5://[::1]:1080:user:password')
        self.assertEqual((proxy.host, proxy.port, proxy.scheme), ('::1', 1080, 'socks5'))

    def test_explicit_http_is_respected_on_a_port_that_also_supports_socks(self):
        with patch('xgenius.proxy_service._socks5_port', return_value=True) as detect:
            self.assertEqual(resolve_proxy(parse_proxy('http://proxy.example:8080:user:pass')).scheme, 'http')
            detect.assert_not_called()
            self.assertEqual(resolve_proxy(parse_proxy('proxy.example:8080:user:pass')).scheme, 'socks5')


if __name__ == '__main__':
    unittest.main()
