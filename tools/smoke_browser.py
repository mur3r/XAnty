"""Exercise startup search repair in the actual installed Chromium, without accounts."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from xgenius.browser_search import ensure_search_engine
from xgenius.chromium_versions import ChromiumVersionManager


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<!doctype html><title>XAnty startup smoke</title><p>synthetic profile</p>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@contextmanager
def local_page():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port) + '/'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def check(chrome, driver, directory, seconds=20):
    if seconds < 20 or seconds > 120:
        raise ValueError('Keep the browser alive for 20 to 120 seconds.')
    chrome, driver, directory = Path(chrome).resolve(), Path(driver).resolve(), Path(directory)
    for headless in (True, False):
        mode = 'headless' if headless else 'windowed'
        profile = directory / mode
        options = webdriver.ChromeOptions()
        options.binary_location = str(chrome)
        options.add_argument('--user-data-dir=' + str(profile))
        options.add_argument('--no-first-run')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--disable-features=Translate,MediaRouter,OptimizationHints,InterestFeedContentSuggestions,BackForwardCache')
        if headless:
            options.add_argument('--headless=new')
        else:
            options.add_argument('--start-minimized')
        service = Service(str(driver), **({'creation_flags': 0x08000000} if os.name == 'nt' else {}))
        browser = webdriver.Chrome(service=service, options=options)
        try:
            with local_page() as url:
                browser.get(url)
                selected = browser.current_window_handle
                handles = browser.window_handles
                result = ensure_search_engine(browser, profile)
                if not result.get('ok') or result.get('cached'):
                    raise RuntimeError('The first startup must exercise search configuration.')
                if browser.window_handles != handles or browser.current_window_handle != selected:
                    raise RuntimeError('Search repair replaced or selected a user tab.')
                if not ensure_search_engine(browser, profile).get('cached'):
                    raise RuntimeError('Repeated startup search configuration was not cached.')
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if browser.window_handles != handles or browser.current_window_handle != selected:
                        raise RuntimeError('Startup lost the original browser window.')
                    if browser.execute_script('return document.title') != 'XAnty startup smoke':
                        raise RuntimeError('Startup navigated away from the user page.')
                    time.sleep(.5)
            print('Verified Chromium startup/search repair: ' + json.dumps({
                'version': browser.capabilities['browserVersion'], 'mode': mode,
                'alive_seconds': seconds, 'user_tab_preserved': True}), flush=True)
        finally:
            browser.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chrome', type=Path)
    parser.add_argument('--driver', type=Path)
    parser.add_argument('--install-stable', action='store_true')
    args = parser.parse_args()
    if args.install_stable == bool(args.chrome or args.driver) or bool(args.chrome) != bool(args.driver):
        parser.error('Provide --install-stable or both --chrome and --driver.')
    with tempfile.TemporaryDirectory(prefix='xanty-browser-smoke-') as directory:
        root = Path(directory)
        if args.install_stable:
            pair = ChromiumVersionManager(SimpleNamespace(base_dir=root / 'pair')).install('Stable')
            chrome, driver = pair['chrome_path'], pair['driver_path']
        else:
            chrome, driver = args.chrome, args.driver
        check(chrome, driver, root / 'profiles')


if __name__ == '__main__':
    main()
