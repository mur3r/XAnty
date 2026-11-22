"""Session URL validation must not mistake a lookalike host for X."""
import importlib.util
import unittest
from pathlib import Path


module_path = Path(__file__).resolve().parents[1] / "xgenius" / "core" / "page_state.py"
spec = importlib.util.spec_from_file_location("session_page_state", module_path)
page_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page_state)


class SessionURLTests(unittest.TestCase):
    def test_real_hosts(self):
        for url in ("https://x.com/home", "https://www.x.com/login", "https://twitter.com/home"):
            with self.subTest(url=url):
                self.assertTrue(page_state.is_x_url(url))

    def test_lookalikes_and_browser_errors(self):
        for url in ("https://x.com.evil.example/home", "https://x.com@evil.example/home",
                    "http://x.com/home", "chrome-error://chromewebdata/", "about:blank"):
            with self.subTest(url=url):
                self.assertFalse(page_state.is_x_url(url))


if __name__ == "__main__":
    unittest.main()
