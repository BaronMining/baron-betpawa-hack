"""
Betpawa login and authenticated data extraction module.
Logs into Betpawa, maintains session, extracts game data.
"""
import cloudscraper
import requests
import json
import re
import time
import random
import hashlib
import hmac
import struct
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from config import (
    BETPAWA_USERNAME, BETPAWA_PASSWORD,
    BETPAWA_DOMAINS, GAME_PATHS, USER_AGENTS, BROWSER_HEADERS
)


class BetpawaAuthenticatedScraper:
    """
    Authenticated scraper for Betpawa Aviator.
    Logs in, maintains session, extracts provably fair data
    including seeds, hashes, and historical rounds.
    """
    
    def __init__(self):
        self.session = None
        self.active_domain = None
        self.active_game_path = None
        self.logged_in = False
        self.auth_token = None
        self.csrf_token = None
        
        # Provably fair data
        self.server_seeds = []
        self.client_seeds = []
        self.round_hashes = []
        self.round_history = []
        
        # Initialize
        self._init_session()
        self._discover_endpoints()
    
    def _get_random_headers(self):
        ua = random.choice(USER_AGENTS)
        headers = BROWSER_HEADERS.copy()
        headers["User-Agent"] = ua
        return headers
    
    def _init_session(self):
        """Initialize cloudscraper session for Cloudflare bypass"""
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False,
                'desktop': True,
            },
            delay=5,
            interpreter='native',
        )
        self.session.headers.update(self._get_random_headers())
    
    def _discover_endpoints(self):
        """Find available Betpawa domain"""
        for domain in BETPAWA_DOMAINS:
            try:
                resp = self.session.get(domain, timeout=15)
                if resp.status_code == 200:
                    self.active_domain = domain
                    for path in GAME_PATHS:
                        url = f"{domain}{path}"
                        test = self.session.get(url, timeout=10)
                        if test.status_code == 200:
                            self.active_game_path = path
                            print(f"[✓] Found: {url}")
                            return
                    # If no game path works, just use domain
                    self.active_game_path = GAME_PATHS[0]
                    print(f"[✓] Domain: {domain}")
                    return
            except Exception as e:
                print(f"[!] {domain}: {str(e)[:40]}")
                continue
        
        self.active_domain = BETPAWA_DOMAINS[0]
        self.active_game_path = GAME_PATHS[0]
        print(f"[!] Using fallback: {self.active_domain}")
    
    def login(self, username: str = None, password: str = None) -> bool:
        """
        Login to Betpawa account.
        
        Betpawa uses standard form-based auth with CSRF tokens.
        After login, we extract the auth token/session cookie.
        """
        if username is None:
            username = BETPAWA_USERNAME
        if password is None:
            password = BETPAWA_PASSWORD
        
        if not username or not password:
            print("[!] No credentials provided. Set BETPAWA_USERNAME and BETPAWA_PASSWORD.")
            return False
        
        print(f"[*] Logging in as {username}...")
        
        try:
            # Step 1: Get login page to extract CSRF token
            login_url = f"{self.active_domain}/login"
            resp = self.session.get(login_url, timeout=15)
            
            if resp.status_code != 200:
                print(f"[!] Login page returned {resp.status_code}")
                return False
            
            # Extract CSRF token from page
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            csrf_input = soup.find('input', {'name': re.compile(r'csrf|_token|authenticity_token', re.I)})
            if csrf_input:
                self.csrf_token = csrf_input.get('value', '')
            
            # Also check meta tags
            csrf_meta = soup.find('meta', {'name': re.compile(r'csrf-token', re.I)})
            if csrf_meta:
                self.csrf_token = csrf_meta.get('content', '')
            
            # Extract from cookies if present
            for cookie in self.session.cookies:
                if 'csrf' in cookie.name.lower() or 'xsrf' in cookie.name.lower():
                    self.csrf_token = cookie.value
            
            # Step 2: Submit login form
            login_data = {
                'username': username,
                'password': password,
            }
            
            # Try different common field names
            possible_username_fields = ['username', 'email', 'phone', 'login', 'phoneNumber']
            possible_password_fields = ['password', 'pass', 'pwd', 'password_confirmation']
            
            # Use the right field names based on what Betpawa expects
            # Betpawa uses phone number as username
            login_data = {
                'phoneNumber': username,
                'password': password,
            }
            
            if self.csrf_token:
                login_data['_token'] = self.csrf_token
                login_data['csrf_token'] = self.csrf_token
            
            # Try multiple login endpoints
            login_endpoints = [
                f"{self.active_domain}/login",
                f"{self.active_domain}/api/login",
                f"{self.active_domain}/api/v1/auth/login",
                f"{self.active_domain}/auth/login",
                f"{self.active_domain}/user/login",
            ]
            
            for endpoint in login_endpoints:
                try:
                    self.session.headers.update({
                        'X-Requested-With': 'XMLHttpRequest',
                        'Content-Type': 'application/x-www-form-urlencoded',
                    })
                    
                    login_resp = self.session.post(endpoint, data=login_data, timeout=15)
                    
                    if login_resp.status_code == 200 or login_resp.status_code == 302:
                        # Check if login was successful by looking for redirect or success response
                        if login_resp.status_code == 302:
                            redirect_url = login_resp.headers.get('Location', '')
                            self.session.get(urljoin(self.active_domain, redirect_url), timeout=10)
                        
                        # Check for auth tokens in cookies
                        for cookie in self.session.cookies:
                            if any(kw in cookie.name.lower() for kw in ['token', 'auth', 'session', 'jwt', 'bearer']):
                                self.auth_token = cookie.value
                        
                        # Try to parse JSON response for token
                        try:
                            json_resp = login_resp.json()
                            if isinstance(json_resp, dict):
                                for key in ['token', 'access_token', 'auth_token', 'data']:
                                    if key in json_resp:
                                        val = json_resp[key]
                                        if isinstance(val, dict):
                                            for subkey in ['token', 'access_token', 'auth_token']:
                                                if subkey in val:
                                                    self.auth_token = val[subkey]
                                        elif isinstance(val, str):
                                            self.auth_token = val
                        except:
                            pass
                        
                        # Verify login by accessing the game page
                        game_url = f"{self.active_domain}{self.active_game_path}"
                        verify = self.session.get(game_url, timeout=15)
                        
                        if verify.status_code == 200:
                            # Check if we're logged in (look for account-specific elements)
                            if 'logout' in verify.text.lower() or 'my account' in verify.text.lower() or username.lower() in verify.text.lower():
                                self.logged_in = True
                                print(f"[✓] Successfully logged in as {username}")
                                
                                # Extract any embedded auth from the page
                                self._extract_auth_from_page(verify.text)
                                return True
                            else:
                                # Still might be logged in — check for iframe game
                                if 'spribe' in verify.text.lower() or 'iframe' in verify.text.lower():
                                    self.logged_in = True
                                    print(f"[✓] Logged in (game iframe detected)")
                                    return True
                
                except Exception as e:
                    print(f"[!] Login attempt to {endpoint}: {e}")
                    continue
            
            # If endpoint attempts failed, try direct cookie-based approach
            # Some Betpawa versions use direct API auth
            try:
                api_login_data = {
                    "phone": username,
                    "password": password,
                    "grant_type": "password",
                }
                api_endpoints = [
                    f"{self.active_domain}/api/auth/login",
                    f"{self.active_domain}/api/v1/auth/login",
                    f"{self.active_domain}/oauth/token",
                ]
                for api_url in api_endpoints:
                    try:
                        resp = self.session.post(api_url, json=api_login_data, timeout=15)
                        if resp.status_code == 200:
                            data = resp.json()
                            if 'access_token' in data:
                                self.auth_token = data['access_token']
                                self.session.headers.update({
                                    'Authorization': f'Bearer {self.auth_token}'
                                })
                                self.logged_in = True
                                print(f"[✓] API login successful")
                                return True
                    except:
                        continue
            except:
                pass
            
            print("[!] Login failed — check credentials")
            return False
            
        except Exception as e:
            print(f"[!] Login error: {e}")
            return False
    
    def _extract_auth_from_page(self, html: str):
        """Extract any auth tokens or embedded data from page"""
        patterns = [
            r'"token"\s*:\s*"([^"]+)"',
            r'"accessToken"\s*:\s*"([^"]+)"',
            r'"authToken"\s*:\s*"([^"]+)"',
            r'"sessionToken"\s*:\s*"([^"]+)"',
            r'"jwt"\s*:\s*"([^"]+)"',
            r'"apiKey"\s*:\s*"([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                token = match.group(1)
                if len(token) > 10:
                    self.auth_token = token
                    self.session.headers.update({
                        'Authorization': f'Bearer {self.auth_token}'
                    })
                    break
    
    def fetch_game_iframe_url(self) -> Optional[str]:
        """Extract the Spribe game iframe URL from the game page"""
        if not self.logged_in:
            print("[!] Not logged in")
            return None
        
        game_url = f"{self.active_domain}{self.active_game_path}"
        
        try:
            resp = self.session.get(game_url, timeout=15)
            if resp.status_code != 200:
                return None
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Look for iframe with Spribe game
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if any(kw in src.lower() for kw in ['spribe', 'aviator', 'game', 'casino']):
                    print(f"[✓] Found game iframe: {src[:80]}...")
                    return src
            
            # Also check for JavaScript game loaders
            scripts = soup.find_all('script')
            url_patterns = [
                r'https?://[^"\'\s]+spribe[^"\'\s]+launch[^"\'\s]*',
                r'https?://[^"\'\s]+spribe[^"\'\s]+game[^"\'\s]*',
                r'https?://[^"\'\s]+/launch/[^"\'\s]+',
            ]
            for script in scripts:
                if script.string:
                    for pattern in url_patterns:
                        match = re.search(pattern, script.string)
                        if match:
                            url = match.group(0)
                            print(f"[✓] Found game URL: {url[:80]}...")
                            return url
            
            return None
            
        except Exception as e:
            print(f"[!] Error fetching game page: {e}")
            return None
    
    def fetch_provably_fair_data(self) -> Dict:
        """
        Fetch provably fair data from the game.
        This includes server seeds, client seeds, hashes, and round results.
        
        Spribe's provably fair system:
        - Each round uses: server_seed + client_seed1 + client_seed2 + client_seed3
        - Hashed with SHA-512
        - First 13 hex chars converted to crash multiplier
        - Formula: crash = (100 - 3) / (100 * (1 - h)) where h = hex_to_decimal / 16^13
        """
        if not self.logged_in:
            return {"success": False, "error": "Not logged in"}
        
        # Try accessing the provably fair settings page
        pf_urls = [
            f"{self.active_domain}/provably-fair",
            f"{self.active_domain}/game/provably-fair",
            f"{self.active_domain}/aviator/provably-fair",
            f"{self.active_domain}/api/game/aviator/provably-fair",
        ]
        
        pf_data = {
            "server_seed": None,
            "server_seed_hash": None,
            "client_seed": None,
            "next_server_seed_hash": None,
            "rounds": [],
        }
        
        for url in pf_urls:
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code == 200:
                    data = resp.json() if 'application/json' in resp.headers.get('Content-Type', '') else {}
                    if isinstance(data, dict):
                        pf_data.update(data)
                        print(f"[✓] Provably fair data from {url}")
                        break
            except:
                continue
        
        # Try to extract from the game page itself
        game_url = f"{self.active_domain}{self.active_game_path}"
        try:
            resp = self.session.get(game_url, timeout=15)
            if resp.status_code == 200:
                html = resp.text
                
                # Extract seed values
                seed_patterns = [
                    r'"serverSeed"\s*:\s*"([^"]+)"',
                    r'"server_seed"\s*:\s*"([^"]+)"',
                    r'"clientSeed"\s*:\s*"([^"]+)"',
                    r'"client_seed"\s*:\s*"([^"]+)"',
                    r'"nextServerSeedHash"\s*:\s*"([^"]+)"',
                    r'"next_server_seed_hash"\s*:\s*"([^"]+)"',
                    r'"serverSeedHash"\s*:\s*"([^"]+)"',
                    r'"hash"\s*:\s*"([^"]+)"',
                ]
                
                for pattern in seed_patterns:
                    match = re.search(pattern, html)
                    if match:
                        key = pattern.split('"')[1]
                        pf_data[key] = match.group(1)
                
                # Extract round history with hashes
                round_patterns = [
                    r'"rounds"\s*:\s*\[(.*?)\]',
                    r'"history"\s*:\s*\[(.*?)\]',
                    r'"results"\s*:\s*\[(.*?)\]',
                ]
                
                for pattern in round_patterns:
                    match = re.search(pattern, html, re.DOTALL)
                    if match:
                        try:
                            rounds_data = json.loads(f"[{match.group(1)}]")
                            for r in rounds_data:
                                if isinstance(r, dict):
                                    pf_data["rounds"].append(r)
                        except:
                            pass
                
        except Exception as e:
            print(f"[!] Error extracting from game page: {e}")
        
        pf_data["success"] = True
        return pf_data
    
    def fetch_round_history(self, limit: int = 500) -> List[Dict]:
        """
        Fetch historical round data from the authenticated API.
        """
        if not self.logged_in:
            print("[!] Not logged in")
            return []
        
        all_rounds = []
        
        # Try API endpoints for round history
        api_endpoints = [
            f"{self.active_domain}/api/game/aviator/history?limit={limit}",
            f"{self.active_domain}/api/v1/games/aviator/rounds?limit={limit}",
            f"{self.active_domain}/api/aviator/history?limit={limit}",
            f"{self.active_domain}/game/aviator/api/history?limit={limit}",
        ]
        
        for endpoint in api_endpoints:
            try:
                resp = self.session.get(endpoint, timeout=15)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if isinstance(data, dict):
                            for key in ['rounds', 'data', 'results', 'history', 'records']:
                                if key in data and isinstance(data[key], list):
                                    all_rounds.extend(data[key])
                                    break
                        elif isinstance(data, list):
                            all_rounds.extend(data)
                        
                        if all_rounds:
                            print(f"[✓] Got {len(all_rounds)} rounds from {endpoint}")
                            break
                    except:
                        pass
            except:
                continue
        
        # Also scrape from the HTML page if API fails
        if not all_rounds:
            game_url = f"{self.active_domain}{self.active_game_path}"
            try:
                resp = self.session.get(game_url, timeout=15)
                if resp.status_code == 200:
                    # Extract from JavaScript variables
                    patterns = [
                        r'"history"\s*:\s*\[(.*?)\]',
                        r'"rounds"\s*:\s*\[(.*?)\]',
                        r'"results"\s*:\s*\[(.*?)\]',
                        r'"previousRounds"\s*:\s*\[(.*?)\]',
                        r'"multipliers"\s*:\s*\[(.*?)\]',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, resp.text, re.DOTALL)
                        if match:
                            try:
                                data = json.loads(f"[{match.group(1)}]")
                                for item in data:
                                    if isinstance(item, dict):
                                        m = item.get('multiplier') or item.get('value') or item.get('crash') or item.get('result')
                                        if m:
                                            all_rounds.append({
                                                "multiplier": float(m),
                                                "round_id": item.get('id', item.get('roundId', '')),
                                                "hash": item.get('hash', item.get('serverSeed', '')),
                                                "timestamp": item.get('timestamp', ''),
                                            })
                                    elif isinstance(item, (int, float)):
                                        all_rounds.append({
                                            "multiplier": float(item),
                                        })
                            except:
                                pass
                        if all_rounds:
                            break
            except:
                pass
        
        return all_rounds
    
    def extract_seeds_from_round(self, round_data: Dict) -> Optional[Dict]:
        """Extract provably fair seeds from a round's data"""
        seeds = {
            "server_seed": round_data.get("serverSeed") or round_data.get("server_seed"),
            "client_seed": round_data.get("clientSeed") or round_data.get("client_seed"),
            "nonce": round_data.get("nonce") or round_data.get("round", 0),
            "hash": round_data.get("hash") or round_data.get("serverSeedHash"),
            "multiplier": round_data.get("multiplier") or round_data.get("result"),
        }
        
        # Only return if we have meaningful data
        if seeds["server_seed"] and seeds["multiplier"]:
            return seeds
        return None
    
    def get_account_info(self) -> Dict:
        """Get account information"""
        info = {"balance": 0, "username": "", "currency": "UGX"}
        
        # Try balance API
        balance_endpoints = [
            f"{self.active_domain}/api/user/balance",
            f"{self.active_domain}/api/v1/user/balance",
            f"{self.active_domain}/api/account/balance",
        ]
        
        for endpoint in balance_endpoints:
            try:
                resp = self.session.get(endpoint, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        for key in ['balance', 'amount', 'wallet']:
                            if key in data:
                                val = data[key]
                                if isinstance(val, dict):
                                    info['balance'] = float(val.get('amount', val.get('balance', 0)))
                                else:
                                    info['balance'] = float(val)
                        break
            except:
                continue
        
        return info
