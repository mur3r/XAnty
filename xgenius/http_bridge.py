"""Keep HTTP/HTTPS proxy authentication independent of Chrome's auth cache."""
import base64
import socket
import ssl

from xgenius.socks_bridge import SocksBridge


class HttpBridge(SocksBridge):
    """Send Basic credentials on the first upstream request, as requests does.

    Chrome authenticates only to a private per-process loopback endpoint. Each
    upstream connection has this profile's credentials, even on restored tabs,
    and never relies on a provider's 407 challenge or a Chrome extension race.
    """

    def __init__(self, upstream):
        # Match requests' HTTP Basic encoding, including literal reserved chars.
        credentials = f'{upstream.username}:{upstream.password}'.encode('latin-1')
        self.upstream_authorization = b'Proxy-Authorization: Basic ' + base64.b64encode(credentials)
        self.last_error = None
        super().__init__(upstream)

    def connect(self, host, port):
        # Resolve/connect only the configured proxy, never the target origin.
        connection = socket.create_connection((self.upstream.host, self.upstream.port), timeout=12)
        if self.upstream.scheme != 'https':
            return connection
        try:
            return ssl.create_default_context().wrap_socket(connection, server_hostname=self.upstream.host)
        except ssl.SSLCertVerificationError:
            self.last_error = 'HTTPS check failed through the proxy (certificate error).'
            connection.close()
            raise
        except ssl.SSLError:
            self.last_error = 'HTTPS proxy TLS handshake failed. Check protocol and port.'
            connection.close()
            raise
        except BaseException:
            connection.close()
            raise

    def start_request(self, upstream, method, target, version, headers, upgrade, initial):
        outgoing = f'{method} {target} {version}'.encode('ascii')
        connection = [] if method == 'CONNECT' else [
            b'Connection: Upgrade' if upgrade else b'Connection: close']
        upstream.sendall(b'\r\n'.join([outgoing, *headers, self.upstream_authorization,
            *connection, b'', b'']))
        if method != 'CONNECT':
            if initial:
                upstream.sendall(initial)
            return b''
        response = b''
        while b'\r\n\r\n' not in response:
            part = upstream.recv(4096)
            if not part or len(response) + len(part) > 65536:
                raise OSError('Invalid upstream proxy response')
            response += part
        header, remainder = response.split(b'\r\n\r\n', 1)
        status_line = header.split(b'\r\n', 1)[0].split(b' ', 2)
        if len(status_line) < 2 or status_line[0] not in (b'HTTP/1.0', b'HTTP/1.1'):
            raise OSError('Invalid upstream proxy response')
        if status_line[1] == b'407':
            self.last_error = 'Proxy authentication failed (407). Check login and password.'
        if status_line[1] != b'200':
            raise OSError('Upstream proxy rejected the tunnel')
        if initial:
            upstream.sendall(initial)
        return remainder
