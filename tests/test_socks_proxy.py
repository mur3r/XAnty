"""Authenticated SOCKS, remote DNS and the Chrome HTTP adapter use real loopback sockets."""
import base64
import select
import socket
import socketserver
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests

from xgenius import proxy_service as service
from xgenius.proxy_service import HttpProxy, ProxyCheckError, parse_proxy
from xgenius.socks_bridge import SocksBridge


def receive(stream, size):
    result = b''
    while len(result) < size:
        part = stream.recv(size - len(result))
        if not part:
            raise OSError('Unexpected EOF')
        result += part
    return result


class SocksHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(5)
            version, size = receive(self.request, 2)
            receive(self.request, size)
            self.request.sendall(b'\x05\x02')
            version, size = receive(self.request, 2)
            username = receive(self.request, size)
            password = receive(self.request, receive(self.request, 1)[0])
            valid = username == b'user' and password == b'private-socks-password'
            self.request.sendall(b'\x01\x00' if valid else b'\x01\x01')
            if not valid:
                return
            version, command, reserved, kind = receive(self.request, 4)
            if kind == 3:
                host = receive(self.request, receive(self.request, 1)[0]).decode()
            elif kind == 1:
                host = socket.inet_ntoa(receive(self.request, 4))
            else:
                return
            port = int.from_bytes(receive(self.request, 2), 'big')
            self.server.targets.append((host, port))
            with socket.create_connection(('127.0.0.1', port), timeout=5) as remote:
                self.request.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
                while True:
                    readable, _, _ = select.select([self.request, remote], [], [], 5)
                    if not readable:
                        return
                    for stream in readable:
                        block = stream.recv(65536)
                        if not block:
                            return
                        (remote if stream is self.request else self.request).sendall(block)
        except OSError:
            pass


class Origin(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers)))
        body = b'{"ip":"203.0.113.20"}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            while data := self.request.recv(65536):
                self.request.sendall(data)
        except OSError:
            pass


class SocksProxyTests(unittest.TestCase):
    def setUp(self):
        service._PROTOCOL_CACHE.clear()
        self.servers = []
        self.origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        self.origin.requests = []
        self.start(self.origin)
        self.socks = socketserver.ThreadingTCPServer(('127.0.0.1', 0), SocksHandler)
        self.socks.daemon_threads = True
        self.socks.targets = []
        self.start(self.socks)
        self.proxy = HttpProxy('127.0.0.1', self.socks.server_address[1], 'user', 'private-socks-password', 'socks5')
        self.url = f'http://origin.invalid:{self.origin.server_address[1]}/test?q=1'

    def start(self, server):
        self.servers.append(server)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def test_explicit_socks_and_legacy_strings_preserve_auth_and_remote_dns(self):
        parsed = parse_proxy('socks5://user:p%40ss@proxy.example:1080')
        self.assertEqual(parsed.scheme, 'socks5')
        self.assertEqual(parsed.requests_url, 'socks5h://user:p%40ss@proxy.example:1080')
        legacy = HttpProxy(self.proxy.host, self.proxy.port, self.proxy.username, self.proxy.password)
        with patch.object(service, 'IP_CHECK_URLS', (self.url,)):
            self.assertEqual(service.check_proxy(legacy), '203.0.113.20')
        self.assertEqual(self.socks.targets[0][0], 'origin.invalid')

    def test_adapter_authenticates_both_hops_and_does_not_forward_proxy_credentials(self):
        bridge = SocksBridge(self.proxy)
        self.addCleanup(bridge.cleanup)
        with requests.Session() as session:
            session.trust_env = False
            session.proxies = {'http': bridge.proxy.requests_url, 'https': bridge.proxy.requests_url}
            response = session.get(self.url, timeout=5)
        self.assertEqual(response.status_code, 200)
        path, headers = self.origin.requests[0]
        self.assertEqual(path, '/test?q=1')
        self.assertNotIn('Proxy-Authorization', headers)
        self.assertNotIn('private-socks-password', str(headers))
        self.assertEqual(self.socks.targets[0][0], 'origin.invalid')

    def test_adapter_requires_its_ephemeral_local_credentials_before_contacting_socks(self):
        bridge = SocksBridge(self.proxy)
        self.addCleanup(bridge.cleanup)
        with requests.Session() as session:
            session.trust_env = False
            session.proxies = {'http': bridge.proxy.server}
            response = session.get(self.url, timeout=5)
        self.assertEqual(response.status_code, 407)
        self.assertEqual(self.socks.targets, [])

    def test_bad_socks_credentials_are_safe_and_never_connect_directly(self):
        bad = HttpProxy(self.proxy.host, self.proxy.port, 'user', 'wrong-secret', 'socks5')
        with patch.object(service, 'IP_CHECK_URLS', (self.url,)):
            with self.assertRaises(ProxyCheckError) as caught:
                service.check_proxy(bad)
        self.assertNotIn('wrong-secret', str(caught.exception))
        self.assertIn('authentication', str(caught.exception))
        self.assertEqual(self.origin.requests, [])

    def test_connect_tunnel_relays_bytes_and_cleanup_closes_live_connections(self):
        echo = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Echo)
        echo.daemon_threads = True
        self.start(echo)
        bridge = SocksBridge(self.proxy)
        self.addCleanup(bridge.cleanup)
        with socket.create_connection(('127.0.0.1', bridge.proxy.port), timeout=5) as client:
            request = (f'CONNECT origin.invalid:{echo.server_address[1]} HTTP/1.1\r\n'
                       f'Proxy-Authorization: {bridge.authorization}\r\n\r\n').encode()
            client.sendall(request)
            header = b''
            while b'\r\n\r\n' not in header:
                header += client.recv(1)
            self.assertIn(b'200 Connection Established', header)
            client.sendall(b'opaque TLS tunnel bytes')
            self.assertEqual(receive(client, 23), b'opaque TLS tunnel bytes')
            bridge.cleanup()
            self.assertEqual(client.recv(1), b'')
        self.assertFalse(bridge.thread.is_alive())
        bridge.cleanup()  # Repeated cleanup is safe after a failed browser launch.

    def test_an_offline_probe_does_not_poison_protocol_detection_after_recovery(self):
        with patch.object(service.time, 'monotonic', return_value=0), \
                patch.object(service.socket, 'create_connection', side_effect=OSError()):
            self.assertFalse(service._socks5_port(self.proxy.host, self.proxy.port))
        with patch.object(service.time, 'monotonic', return_value=6):
            self.assertTrue(service._socks5_port(self.proxy.host, self.proxy.port))


if __name__ == '__main__':
    unittest.main()
