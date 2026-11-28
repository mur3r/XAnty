"""Per-browser authenticated loopback HTTP adapter for an authenticated SOCKS5 proxy."""
import base64
import hmac
import select
import socket
import socketserver
import threading
from secrets import token_urlsafe
from urllib.parse import urlsplit, urlunsplit

import socks

from xgenius.proxy_service import HttpProxy


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        bridge = self.server.bridge
        client, upstream = self.request, None
        response_started = False
        with bridge.lock:
            if bridge.closed:
                return
            bridge.connections.add(client)
        try:
            client.settimeout(15)
            data = b''
            while b'\r\n\r\n' not in data:
                chunk = client.recv(4096)
                if not chunk:
                    return
                data += chunk
                if len(data) > 65536:
                    self.reply(431)
                    return
            header, initial = data.split(b'\r\n\r\n', 1)
            lines = header.split(b'\r\n')
            method, target, version = lines[0].decode('ascii').split(' ')
            headers = []
            authorization = ''
            upgrade = False
            for line in lines[1:]:
                name, value = line.split(b':', 1)
                key = name.strip().lower()
                if key == b'proxy-authorization':
                    authorization = value.strip().decode('ascii')
                elif key not in (b'proxy-connection', b'connection'):
                    headers.append(line)
                    if key == b'upgrade':
                        upgrade = True
            if not hmac.compare_digest(authorization, bridge.authorization):
                client.sendall(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="XAnty"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                return
            if version not in ('HTTP/1.0', 'HTTP/1.1'):
                self.reply(400)
                return
            if method == 'CONNECT':
                parsed = urlsplit('//' + target)
                if parsed.path or parsed.query or parsed.fragment or parsed.username is not None:
                    self.reply(400)
                    return
                host, port = parsed.hostname, parsed.port
            else:
                parsed = urlsplit(target)
                if parsed.scheme != 'http' or parsed.username is not None or parsed.fragment:
                    self.reply(400)
                    return
                host, port = parsed.hostname, parsed.port or 80
            if not host or port is None or not 1 <= port <= 65535:
                self.reply(400)
                return
            # Origin DNS and connections go through the configured upstream.
            upstream = bridge.connect(host, port)
            with bridge.lock:
                if bridge.closed:
                    return
                bridge.connections.add(upstream)
            response = bridge.start_request(upstream, method, target, version, headers, upgrade, initial)
            if method == 'CONNECT':
                client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n' + response)
                response_started = True
            client.settimeout(None)
            upstream.settimeout(None)
            while not bridge.closed:
                readable, _, _ = select.select([client, upstream], [], [], 1)
                for source in readable:
                    block = source.recv(65536)
                    if not block:
                        return
                    target_socket = upstream if source is client else client
                    target_socket.settimeout(15)
                    target_socket.sendall(block)
                    if source is upstream:
                        response_started = True
                    target_socket.settimeout(None)
        except (OSError, ValueError, UnicodeError, socks.ProxyError):
            try:
                if not response_started:
                    self.reply(502)
            except OSError:
                pass
        finally:
            for connection in (client, upstream):
                if connection is None:
                    continue
                with bridge.lock:
                    bridge.connections.discard(connection)
                connection.close()

    def reply(self, status):
        self.request.sendall(f'HTTP/1.1 {status} Proxy Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'.encode('ascii'))


class SocksBridge:
    def __init__(self, upstream):
        self.upstream = upstream
        self.closed = False
        self.lock = threading.Lock()
        self.connections = set()
        self.server = _Server(('127.0.0.1', 0), _Handler)
        self.server.bridge = self
        self.proxy = HttpProxy('127.0.0.1', self.server.server_address[1], token_urlsafe(18), token_urlsafe(24))
        credentials = f'{self.proxy.username}:{self.proxy.password}'.encode()
        self.authorization = 'Basic ' + base64.b64encode(credentials).decode('ascii')
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .1}, daemon=True, name='XAnty SOCKS adapter')
        try:
            self.thread.start()
        except BaseException:
            self.server.server_close()
            raise

    def cleanup(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            connections = list(self.connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def connect(self, host, port):
        proxy = self.upstream
        return socks.create_connection((host, port), timeout=12,
            proxy_type=socks.SOCKS5, proxy_addr=proxy.host, proxy_port=proxy.port,
            proxy_rdns=True, proxy_username=proxy.username or None,
            proxy_password=proxy.password or None)

    def start_request(self, upstream, method, target, version, headers, upgrade, initial):
        if method != 'CONNECT':
            parsed = urlsplit(target)
            path = urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
            # One HTTP request per connection keeps subsequent origins from
            # being sent to the first origin. CONNECT tunnels stay persistent.
            outgoing = f'{method} {path} {version}'.encode('ascii')
            upstream.sendall(b'\r\n'.join([outgoing, *headers,
                b'Connection: Upgrade' if upgrade else b'Connection: close', b'', b'']))
        if initial:
            upstream.sendall(initial)
        return b''
