"""Bounded diagnostics suitable for the local interface and logs."""
import re

from xgenius.proxy_service import ProxyCheckError, parse_proxy


def safe_launch_error(error, account):
    message = str(error)
    secrets = [account.get(key) for key in ('password', 'auth_token', 'ct0_token')]
    try:
        proxy = parse_proxy(account.get('proxy'))
        secrets.append(proxy.password)
    except ProxyCheckError:
        if account.get('proxy'):
            secrets.append(account['proxy'])
    message = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1***@', message)
    for secret in sorted((str(s) for s in secrets if s), key=len, reverse=True):
        message = message.replace(secret, '***')
    return message.split('Stacktrace:')[0].strip()[:600] or 'Browser could not start. Check Chrome and ChromeDriver.'


def launch_diagnostic(error, account):
    """Stable categories for actionable UI text; raw credentials never leave here."""
    detail = safe_launch_error(error, account)
    lowered = detail.casefold()
    if any(s in lowered for s in ('only supports chrome', 'version mismatch', 'current browser version', 'driver version')):
        category = 'version'
    elif any(s in lowered for s in ('proxy', 'прокси', 'socks', 'tunnel', 'err_proxy')):
        category = 'proxy'
    elif any(s in lowered for s in ('already in use', 'profile is busy', 'profile lease', 'уже используется', 'profile lock')):
        category = 'profile_busy'
    elif any(s in lowered for s in ('no chrome binary', 'cannot find chrome', 'chrome.exe', 'chromedriver.exe', 'no such file', 'winerror 2')):
        category = 'missing_browser'
    elif any(s in lowered for s in ('timeout', 'timed out', 'тайм')):
        category = 'timeout'
    elif any(s in lowered for s in ('invalid', 'settings', 'configuration', 'timezone', 'extension')):
        category = 'configuration'
    else:
        category = 'unknown'
    return {'category': category, 'detail': detail}
