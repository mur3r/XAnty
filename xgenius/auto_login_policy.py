"""Persisted X sign-in preference; old accounts keep their previous behaviour."""
from typing import Iterable


def is_auto_login_enabled(account: dict) -> bool:
    # Accounts created before the toggle always attempted X sign-in on launch.
    return account.get("auto_login", True) is True


def apply_auto_login(accounts: list[dict], usernames: Iterable[str], enabled: bool) -> int:
    """Update all requested accounts, or none if a name/value is invalid."""
    if type(enabled) is not bool:
        raise ValueError("auto_login must be a boolean")
    selected = set(usernames)
    if not selected:
        raise ValueError("Select at least one account")
    existing = {account["username"] for account in accounts}
    missing = selected - existing
    if missing:
        raise ValueError(f"Accounts not found: {', '.join(sorted(missing))}")
    for account in accounts:
        if account["username"] in selected:
            account["auto_login"] = enabled
    return len(selected)
