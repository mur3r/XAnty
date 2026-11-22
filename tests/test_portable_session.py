"""Old closed Chrome profiles can be packaged without their Windows encryption key."""
import base64
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from xgenius.portable_session import normalize_session, read_chrome_session


class PortableSessionTests(unittest.TestCase):
    def test_decrypts_domain_bound_chrome_cookies_without_changing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = AESGCM.generate_key(bit_length=256)
            domain = '.example.com'
            nonce = os.urandom(12)
            value = hashlib.sha256(domain.encode()).digest() + b'portable-session-value'
            encrypted = b'v10' + nonce + AESGCM(key).encrypt(nonce, value, None)
            (root / 'Local State').write_text(json.dumps({'os_crypt': {'encrypted_key': base64.b64encode(b'DPAPIencrypted-key').decode()}}))
            path = root / 'Default/Network/Cookies'
            path.parent.mkdir(parents=True)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('CREATE TABLE meta (key TEXT, value TEXT)')
                connection.execute("INSERT INTO meta VALUES ('version', '24')")
                connection.execute('CREATE TABLE cookies (host_key TEXT,name TEXT,value TEXT,encrypted_value BLOB,path TEXT,expires_utc INTEGER,is_secure INTEGER,is_httponly INTEGER,samesite INTEGER)')
                connection.execute('INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?)', (domain, 'session', '', encrypted, '/', 0, 1, 1, 2))
                connection.execute('INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?,?)', (domain, 'protected', '', b'v20not-readable', '/', 0, 1, 1, 2))
                connection.commit()
            original = path.read_bytes()
            with patch('xgenius.portable_session._unprotect', return_value=key):
                cookies, failed = read_chrome_session(root)
            self.assertEqual(len(cookies), 1)
            self.assertEqual(cookies[0]['value'], 'portable-session-value')
            self.assertEqual(cookies[0]['sameSite'], 'Strict')
            self.assertEqual(failed, 1)
            self.assertEqual(path.read_bytes(), original)

    def test_normalizes_both_cookie_expiry_formats_and_rejects_invalid_domains(self):
        cookies = normalize_session([{'name': 'one', 'value': '1', 'domain': '.x.com', 'expiry': 1900000000},
                                     {'name': 'two', 'value': '2', 'domain': 'example.com', 'expirationDate': 1900000001}])
        self.assertEqual([c['expires'] for c in cookies], [1900000000, 1900000001])
        with self.assertRaises(ValueError):
            normalize_session([{'name': 'one', 'value': '1', 'domain': 'https://example.com'}])


if __name__ == '__main__':
    unittest.main()
