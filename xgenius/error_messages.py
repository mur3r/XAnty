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
