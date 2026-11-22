"""
AccountManager: состояние аккаунтов, файлы accounts/groups, токены, экспорт.
"""

import asyncio
import gc
import json
import os
import re
import threading
import time
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from xgenius.accounts.auth import AuthMixin
from xgenius.accounts.health import HealthMixin
from xgenius.browser import BrowserManager
from xgenius.config import Config
from xgenius.logger import Logger
from xgenius.models import AccountState, BrowserConfig


class AccountManager(HealthMixin, AuthMixin):

    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self.accounts: Dict[str, AccountState] = {}
        self._data_lock = threading.RLock()
        self.browser_manager = BrowserManager(config, BrowserConfig())

        # --- CACHE AND WORKER FOR GUI OPTIMIZATION ---
        self._cache_lock = threading.Lock()
        self.cached_data = []
        self.stop_worker = False
        threading.Thread(target=self._background_worker, daemon=True).start()
    

    def _background_worker(self):
        while not self.stop_worker:
            try:
                rows = []
                for index, account in enumerate(self.load_accounts()):
                    username = account["username"]
                    state = self.accounts.get(username)
                    reason = state.status_reason if state else ""
                    opened = bool(state and state.browser)
                    rows.append({
                        "index": index, "account": account, "username": username,
                        "status_text": reason or ("OPEN" if opened else "CLOSED"),
                        "status_color": "#d35400" if reason else ("#27ae60" if opened else "gray"),
                        "last_launch": state.last_action_time.strftime("%H:%M:%S") if opened else "N/A",
                    })
                with self._cache_lock:
                    self.cached_data = rows
                time.sleep(3)
            except Exception as exc:
                self.logger.error(f"Account list refresh failed: {exc}")
                time.sleep(5)

    def get_table_data(self):
        with self._cache_lock:
            return list(self.cached_data)

    def load_accounts(self) -> List[dict]:
        with self._data_lock:
            return self._load_accounts()

    def _load_accounts(self) -> List[dict]:
        try:
            if self.config.accounts_file.exists():
                with open(self.config.accounts_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("accounts", [])
            return []
        except Exception as e:
            self.logger.error(f"Failed to load accounts: {e}")
            return []

    def save_accounts(self, accounts: List[dict]) -> None:
        with self._data_lock:
            self._save_accounts(accounts)

    def _save_accounts(self, accounts: List[dict]) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.config.base_dir,
                                             prefix='accounts_', suffix='.tmp', delete=False) as f:
                temporary = f.name
                json.dump({"accounts": accounts}, f, indent=4, ensure_ascii=False)
            os.replace(temporary, self.config.accounts_file)
        except Exception as e:
            self.logger.error(f"Failed to save accounts: {e}")
            raise
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    async def get_auth_tokens(self, browser: webdriver.Chrome) -> tuple[Optional[str], Optional[str]]:
        """Получение токенов авторизации из браузера"""
        try:
            loop = asyncio.get_event_loop()
            # Получаем все cookies
            cookies = await loop.run_in_executor(None, lambda: browser.get_cookies())
            
            auth_token = None
            ct0_token = None
            
            # Ищем нужные куки
            for cookie in cookies:
                if cookie.get('name') == 'auth_token':
                    auth_token = cookie.get('value')
                elif cookie.get('name') == 'ct0':
                    ct0_token = cookie.get('value')
            
            # Если не нашли в куках, пробуем получить из localStorage через JavaScript
            if not auth_token or not ct0_token:
                try:
                    tokens = await loop.run_in_executor(None, lambda: browser.execute_script(
                        """
                        try {
                            return {
                                'auth_token': localStorage.getItem('auth_token'),
                                'ct0': localStorage.getItem('ct0')
                            };
                        } catch(e) {
                            return null;
                        }
                        """
                    ))
                    
                    if tokens and isinstance(tokens, dict):
                        if not auth_token and tokens.get('auth_token'):
                            auth_token = tokens['auth_token']
                        if not ct0_token and tokens.get('ct0'):
                            ct0_token = tokens['ct0']
                except Exception:
                    pass
            
            self.logger.info(f"Получены токены: auth_token={'SET' if auth_token else 'N/A'}, ct0={'SET' if ct0_token else 'N/A'}")
            return auth_token, ct0_token
            
        except Exception as e:
            self.logger.error(f"Ошибка получения токенов: {e}")
            return None, None

