"""Track the exact Chrome process, independently of X sign-in and Selenium RPCs."""
from typing import Optional

import psutil


def track_browser_process(browser) -> None:
    browser._xg_browser_process = None
    try:
        driver = psutil.Process(browser.service.process.pid)
        for process in driver.children(recursive=True):
            if process.name().lower() not in ('chrome.exe', 'chrome', 'chromium.exe', 'chromium'):
                continue
            if any(value.startswith('--type=') for value in process.cmdline()):
                continue
            browser._xg_browser_process = process
            return
    except (AttributeError, psutil.Error):
        pass


def browser_process_alive(browser) -> Optional[bool]:
    if browser is None:
        return False
    try:
        process = getattr(browser, '_xg_browser_process', None)
        if process is not None and (not process.is_running() or process.status() == psutil.STATUS_ZOMBIE):
            return False
        driver = getattr(getattr(browser, 'service', None), 'process', None)
        poll = getattr(driver, 'poll', None)
        if callable(poll) and poll() is not None:
            return False
        return True if process is not None else None
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied:
        return None
