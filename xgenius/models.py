"""Browser profile session state and credentials."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from selenium import webdriver


class AuthStatus(Enum):
    OK = "OK"
    PAGE_DOWN = "PAGE_DOWN"
    NEED_RELOGIN = "NEED_RELOGIN"
    LOCKED = "LOCKED"


@dataclass
class AccountCredentials:
    username: str
    password: str
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    headless: bool = False
    group: str = ""
    auth_token: Optional[str] = None
    ct0_token: Optional[str] = None
    auto_login: bool = True
    browser_language: str = ""
    browser_timezone: str = ""
    window_width: int = 1024
    window_height: int = 768
    restore_tabs: bool = True
    extension_set: str = ''
    block_images: bool = False
    block_media: bool = False
    block_fonts: bool = False
    phishing_protection: bool = True
    profile_name: str = ''
    profile_id: str = ''
    profile_number: Optional[int] = None
    icon_text: str = ''


@dataclass
class BrowserConfig:
    headless: bool = False
    window_size: tuple[int, int] = (1920, 1080)


@dataclass
class AccountState:
    username: str
    browser: Optional[webdriver.Chrome] = None
    is_active: bool = False
    status_reason: str = ""
    need_relogin: bool = False
    relogin_in_progress: bool = False
    last_action_time: datetime = field(default_factory=datetime.now)
    auth_token: Optional[str] = None
    ct0_token: Optional[str] = None
    proxy_ip: str = ""
    proxy_status: str = ""
    proxy_error: str = ""
    proxy_location: dict = field(default_factory=dict)
    proxy_location_error: str = ""
    launch_error: str = ""
    launch_error_seq: int = 0
    browser_version: str = ""
    browser_user_agent: str = ""
    session_saved_at: str = ''
    session_save_error: str = ''
