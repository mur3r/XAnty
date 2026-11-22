"""Small browser session probes and driver error classification."""
from typing import Optional

PAGE_PROBE_JS = r"""
return {
  hasLoginForm: !!document.querySelector("input[name='text'][autocomplete='username']"),
  text: (document.body?.innerText || '').slice(0, 2000).toLowerCase()
};
"""
LOGIN_PATHS = ("/i/flow/login", "/login", "/logout")
LOCK_PATHS = ("/account/access", "/account/suspended", "/login_challenge", "consent_violation_flow")


def is_x_url(url: Optional[str]) -> bool:
    if not url:
        return False
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in {
        "x.com", "www.x.com", "mobile.x.com",
        "twitter.com", "www.twitter.com", "mobile.twitter.com",
    }


_TIMEOUT_MARKERS = ("read timed out", "timed out", "timeout")
_CLOSED_MARKERS = (
    "chrome not reachable", "invalid session id", "session deleted", "no such window",
    "target window already closed", "not connected to devtools", "disconnected",
    "target page, context or browser has been closed", "websocketwithurl",
    "connection refused", "winerror 10061", "failed to establish a new connection",
    "browser has been closed", "web view not found", "no such execution context",
    "session not created", "actively refused",
)
_CLOSED_TYPES = ("InvalidSessionIdException", "NoSuchWindowException")


def classify_driver_error(exc: BaseException) -> str:
    """
    'closed'  — браузер/драйвер мёртв, нужно пересоздавать;
    'timeout' — команда не успела (перегруз сервера / долгая загрузка), браузер жив;
    'other'   — всё остальное (элемент не найден и т.п.).
    """
    name = type(exc).__name__
    msg = str(exc).lower()
    if name in _CLOSED_TYPES:
        return "closed"
    if name == "TimeoutException" or any(m in msg for m in _TIMEOUT_MARKERS):
        # "timed out receiving message from renderer" — тоже временное
        if not any(m in msg for m in ("connection refused", "winerror 10061", "chrome not reachable")):
            return "timeout"
    if any(m in msg for m in _CLOSED_MARKERS):
        return "closed"
    return "other"
