import cloudscraper
import requests
import logging
import json
import re
from bs4 import BeautifulSoup
from config import *

logger = logging.getLogger(__name__)

class BetpawaAuthenticatedScraper:
    def __init__(self):
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True,
                'mobile': False
            },
            delay=15,
            interpreter='js2py'
        )
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://www.betpawa.ug',
            'Referer': 'https://www.betpawa.ug/',
        })
        self.logged_in = False
        self.active_domain = BETPAWA_BASE_URL
        self.user_data = {}
        self.csrf_token = None

    def _get_csrf_token(self):
        """Extract CSRF token from page"""
        try:
            r = self.session.get(BETPAWA_BASE_URL, timeout=30)
            soup = BeautifulSoup(r.text, 'lxml')
            meta = soup.find('meta', {'name': 'csrf-token'})
            if meta:
                self.csrf_token = meta.get('content')
                logger.info(f"CSRF token acquired")
            return self.csrf_token
        except Exception as e:
            logger.error(f"CSRF fetch error: {e}")
            return None

    def login(self, username=None, password=None):
        """Login to Betpawa"""
        if username is None:
            username = BETPAWA_USERNAME
        if password is None:
            password = BETPAWA_PASSWORD

        if not username or not password:
            logger.error("No credentials provided")
            return False

        logger.info(f"Logging in as {username}...")

        try:
            # First get CSRF token
            self._get_csrf_token()

            # Login payload
            payload = {
                "phone": username,
                "password": password,
                "remember": True
            }

            headers = {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            }
            if self.csrf_token:
                headers['X-CSRF-Token'] = self.csrf_token

            r = self.session.post(
                BETPAWA_LOGIN_URL,
                json=payload,
                headers=headers,
                timeout=30
            )

            logger.info(f"Login response: {r.status_code}")

            if r.status_code == 200:
                try:
                    data = r.json()
                    if data.get('success') or data.get('token') or data.get('data'):
                        self.logged_in = True
                        self.user_data = data
                        logger.info(f"✅ Login successful! Token acquired.")
                        return True
                except:
                    pass

            # Try alternative: form-based login
            if not self.logged_in:
                r2 = self.session.post(
                    f"{BETPAWA_BASE_URL}/login",
                    data={
                        'phone': username,
                        'password': password,
                        '_token': self.csrf_token or ''
                    },
                    timeout=30
                )
                if 'token' in r2.text or 'session' in r2.text or r2.status_code == 200:
                    self.logged_in = True
                    logger.info(f"✅ Login successful (form method)!")
                    return True

            logger.error(f"❌ Login failed: {r.status_code} {r.text[:200]}")
            return False

        except Exception as e:
            logger.error(f"❌ Login exception: {e}")
            return False

    def fetch_round_history(self, limit=500):
        """Fetch historical round data"""
        if not self.logged_in:
            logger.error("Not logged in")
            return []

        rounds = []
        try:
            headers = {
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json',
            }

            r = self.session.get(
                BETPAWA_GAME_HISTORY_URL,
                params={'limit': limit, 'offset': 0},
                headers=headers,
                timeout=30
            )

            logger.info(f"History response: {r.status_code}")

            if r.status_code == 200:
                try:
                    data = r.json()
                    if isinstance(data, list):
                        rounds = data
                    elif isinstance(data, dict):
                        rounds = data.get('data', data.get('rounds', data.get('history', [])))
                except:
                    # Try regex extraction
                    matches = re.findall(r'"crashMultiplier":([\d.]+)', r.text)
                    for m in matches:
                        rounds.append({'crash_multiplier': float(m)})

            logger.info(f"Retrieved {len(rounds)} rounds")
            return rounds

        except Exception as e:
            logger.error(f"History fetch error: {e}")
            return []

    def fetch_provably_fair_data(self):
        """Get seed/hash data"""
        if not self.logged_in:
            return {"success": False}

        try:
            r = self.session.get(
                BETPAWA_SEED_INFO_URL,
                timeout=30
            )

            if r.status_code == 200:
                try:
                    data = r.json()
                    return {
                        "success": True,
                        "server_seed": data.get('server_seed'),
                        "client_seed": data.get('client_seed'),
                        "server_seed_hash": data.get('server_seed_hash'),
                        "next_server_seed_hash": data.get('next_server_seed_hash'),
                        "nonce": data.get('nonce'),
                        "rounds": data.get('rounds', [])
                    }
                except:
                    pass

            # Parse from HTML
            soup = BeautifulSoup(r.text, 'lxml')
            seeds = {}
            for inp in soup.find_all('input', {'type': 'hidden'}):
                name = inp.get('name', '')
                value = inp.get('value', '')
                if 'seed' in name.lower() or 'hash' in name.lower():
                    seeds[name] = value

            if seeds:
                return {"success": True, **seeds}

            return {"success": False}

        except Exception as e:
            logger.error(f"Seed fetch error: {e}")
            return {"success": False}

    def get_account_info(self):
        """Get account balance info"""
        if not self.logged_in:
            return {"balance": "N/A", "currency": "UGX"}

        try:
            r = self.session.get(
                f"{BETPAWA_BASE_URL}/api/v2/account",
                timeout=30
            )
            if r.status_code == 200:
                try:
                    data = r.json()
                    return {
                        "balance": data.get('balance', 'N/A'),
                        "currency": data.get('currency', 'UGX'),
                        "name": data.get('name', ''),
                        "phone": data.get('phone', '')
                    }
                except:
                    pass
        except:
            pass

        return {"balance": "N/A", "currency": "UGX"}
