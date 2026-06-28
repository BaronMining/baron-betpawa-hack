import cloudscraper
import json
import time
import random
import re
from typing import List, Dict, Optional, Callable
from datetime import datetime
from bs4 import BeautifulSoup
import urllib.parse

from config import BETPAWA_DOMAINS, GAME_PATHS, USER_AGENTS, BROWSER_HEADERS


class BetpawaScraper:
    """
    Multi-layer anti-detection scraper for Betpawa Aviator.
    Bypasses Cloudflare IUAM, TLS fingerprinting, rate limiting, and bot detection.
    Uses HTTP scraping only — no WebSocket.
    """

    def __init__(self):
        self.active_domain = None
        self.active_game_path = None
        self.session = None
        self.last_fetched_rounds = set()  # Track seen rounds to avoid duplicates
        self._init_session()
        self._discover_endpoints()

    def _get_random_headers(self):
        """Generate random browser-like headers for each request"""
        ua = random.choice(USER_AGENTS)
        headers = BROWSER_HEADERS.copy()
        headers["User-Agent"] = ua
        if random.random() > 0.5:
            headers["Accept-Language"] = "en-GB,en;q=0.9,en-US;q=0.8"
        return headers

    def _init_session(self):
        """
        Initialize a cloudscraper session that bypasses Cloudflare.
        cloudscraper handles JS challenge solving, TLS fingerprint spoofing,
        and cookie persistence automatically.
        """
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
        """Find the correct Betpawa domain and game path for Aviator"""
        print("[*] Discovering Betpawa Aviator endpoints...")
        for domain in BETPAWA_DOMAINS:
            for path in GAME_PATHS:
                url = f"{domain}{path}"
                try:
                    resp = self.session.get(url, timeout=15, allow_redirects=True)
                    if resp.status_code == 200:
                        text_lower = resp.text.lower()
                        if any(kw in text_lower for kw in ["aviator", "spribe", "crash", "multiplier"]):
                            self.active_domain = domain
                            self.active_game_path = path
                            print(f"[✓] Found: {url}")
                            return
                except Exception as e:
                    print(f"[!] {url} -> {str(e)[:50]}")
                    continue
        # Fallback
        self.active_domain = BETPAWA_DOMAINS[0]
        self.active_game_path = GAME_PATHS[0]
        print(f"[!] Using fallback: {self.active_domain}{self.active_game_path}")

    @property
    def base_url(self):
        return f"{self.active_domain}{self.active_game_path}"

    def fetch_page(self) -> Optional[str]:
        """Fetch the Aviator game page, bypassing Cloudflare"""
        for attempt in range(3):
            try:
                self.session.headers.update(self._get_random_headers())
                resp = self.session.get(self.base_url, timeout=30, allow_redirects=True)
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code in (403, 503):
                    print(f"[!] Cloudflare challenge on attempt {attempt+1}, retrying...")
                    time.sleep(5 + random.random() * 5)
                    self._init_session()
                else:
                    print(f"[!] HTTP {resp.status_code}")
                    time.sleep(3)
            except Exception as e:
                print(f"[!] Fetch error (attempt {attempt+1}): {e}")
                time.sleep(5)
        return None

    def _extract_multipliers_from_json(self, data, depth=0) -> List[float]:
        """Recursively extract multiplier values from nested JSON/dict structures"""
        multipliers = []
        if depth > 10:
            return multipliers
        
        if isinstance(data, dict):
            # Check for known multiplier keys
            for key in ['multiplier', 'crash', 'value', 'result', 'finalMultiplier']:
                if key in data:
                    val = data[key]
                    if isinstance(val, (int, float)) and 1.0 <= val <= 1000:
                        multipliers.append(float(val))
            
            # Check for list/array fields containing rounds
            for key in ['history', 'rounds', 'results', 'previousRounds', 'lastRounds', 
                       'multipliers', 'crashHistory', 'data', 'items', 'list',
                       'roundHistory', 'gameHistory', 'recentRounds']:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        multipliers.extend(self._extract_multipliers_from_json(item, depth + 1))
            
            # Recurse into all values
            for v in data.values():
                multipliers.extend(self._extract_multipliers_from_json(v, depth + 1))
                
        elif isinstance(data, list):
            for item in data:
                multipliers.extend(self._extract_multipliers_from_json(item, depth + 1))
        
        return multipliers

    def _parse_rounds_from_html(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse round history from HTML elements on the page"""
        rounds = []
        
        # Look for elements that contain multiplier values
        selectors = [
            '[class*="history"] [class*="value"]',
            '[class*="history"] [class*="multiplier"]',
            '[class*="round"] [class*="value"]',
            '[class*="round"] [class*="multiplier"]',
            '[class*="result"] [class*="value"]',
            '[data-testid*="history"]',
            '[data-testid*="round"]',
            'span[class*="multiplier"]',
            'div[class*="history-item"]',
            'div[class*="round-item"]',
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            for elem in elements:
                text = elem.get_text(strip=True)
                # Match patterns like "1.23x", "2.45", "3.67X"
                mult_match = re.search(r'(\d+\.?\d*)\s*x?', text, re.IGNORECASE)
                if mult_match:
                    val = float(mult_match.group(1))
                    if 1.0 <= val <= 1000:
                        rounds.append({
                            "round_id": f"html_{time.time()}_{random.random()}",
                            "multiplier": val,
                            "timestamp": datetime.now().isoformat(),
                        })
        
        return rounds

    def fetch_round_history(self, max_retries=3) -> List[Dict]:
        """
        Scrape live round history from the Betpawa Aviator game page.
        
        Uses multiple extraction methods:
        1. Parse JSON from script tags (__NEXT_DATA__, __NUXT__, __INITIAL_STATE__)
        2. Extract from embedded JS objects
        3. Parse HTML history elements
        """
        for attempt in range(max_retries):
            html = self.fetch_page()
            if not html:
                continue

            all_rounds = []
            soup = BeautifulSoup(html, 'html.parser')
            scripts = soup.find_all('script')
            
            # Method 1: Parse __NEXT_DATA__ (Next.js apps)
            for script in scripts:
                if script.get('id') == '__NEXT_DATA__':
                    try:
                        data = json.loads(script.string)
                        multipliers = self._extract_multipliers_from_json(data)
                        for m in multipliers:
                            all_rounds.append({
                                "round_id": f"next_{time.time()}_{random.random()}",
                                "multiplier": m,
                                "timestamp": datetime.now().isoformat(),
                            })
                    except (json.JSONDecodeError, AttributeError, TypeError):
                        pass
            
            # Method 2: Parse __NUXT__ (Nuxt.js apps)
            for script in scripts:
                if script.get('id') == '__NUXT__':
                    try:
                        data = json.loads(script.string)
                        multipliers = self._extract_multipliers_from_json(data)
                        for m in multipliers:
                            all_rounds.append({
                                "round_id": f"nuxt_{time.time()}_{random.random()}",
                                "multiplier": m,
                                "timestamp": datetime.now().isoformat(),
                            })
                    except (json.JSONDecodeError, AttributeError, TypeError):
                        pass
            
            # Method 3: Parse __INITIAL_STATE__
            for script in scripts:
                if script.get('id') == '__INITIAL_STATE__':
                    try:
                        data = json.loads(script.string)
                        multipliers = self._extract_multipliers_from_json(data)
                        for m in multipliers:
                            all_rounds.append({
                                "round_id": f"init_{time.time()}_{random.random()}",
                                "multiplier": m,
                                "timestamp": datetime.now().isoformat(),
                            })
                    except (json.JSONDecodeError, AttributeError, TypeError):
                        pass
            
            # Method 4: Parse inline JSON objects from any script
            for script in scripts:
                if script.string:
                    # Look for JSON arrays containing multiplier data
                    json_patterns = [
                        r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                        r'window\.__DATA__\s*=\s*({.*?});',
                        r'const\s+historyData\s*=\s*({.*?});',
                        r'var\s+roundData\s*=\s*({.*?});',
                        r'let\s+gameData\s*=\s*({.*?});',
                    ]
                    for pattern in json_patterns:
                        match = re.search(pattern, script.string, re.DOTALL)
                        if match:
                            try:
                                data = json.loads(match.group(1))
                                multipliers = self._extract_multipliers_from_json(data)
                                for m in multipliers:
                                    all_rounds.append({
                                        "round_id": f"inline_{time.time()}_{random.random()}",
                                        "multiplier": m,
                                        "timestamp": datetime.now().isoformat(),
                                    })
                            except (json.JSONDecodeError, AttributeError):
                                pass
            
            # Method 5: Look for JSON arrays embedded in script tags
            for script in scripts:
                if script.string:
                    # Try to find JSON arrays with multiplier/round data
                    array_patterns = [
                        r'"history"\s*:\s*\[(.*?)\]',
                        r'"rounds"\s*:\s*\[(.*?)\]',
                        r'"results"\s*:\s*\[(.*?)\]',
                        r'"previousRounds"\s*:\s*\[(.*?)\]',
                        r'"lastRounds"\s*:\s*\[(.*?)\]',
                        r'"crashHistory"\s*:\s*\[(.*?)\]',
                        r'"multipliers"\s*:\s*\[(.*?)\]',
                        r'"recentRounds"\s*:\s*\[(.*?)\]',
                        r'"roundHistory"\s*:\s*\[(.*?)\]',
                    ]
                    for pattern in array_patterns:
                        match = re.search(pattern, script.string, re.DOTALL)
                        if match:
                            try:
                                data = json.loads(f"[{match.group(1)}]")
                                for item in data:
                                    if isinstance(item, dict):
                                        m = (item.get('multiplier') or item.get('value') or 
                                             item.get('crash') or item.get('result'))
                                        if m:
                                            all_rounds.append({
                                                "round_id": item.get('id', item.get('roundId', f"array_{time.time()}_{random.random()}")),
                                                "multiplier": float(m),
                                                "timestamp": item.get('timestamp', item.get('time', datetime.now().isoformat())),
                                            })
                                    elif isinstance(item, (int, float)):
                                        if 1.0 <= item <= 1000:
                                            all_rounds.append({
                                                "round_id": f"array_{time.time()}_{random.random()}",
                                                "multiplier": float(item),
                                                "timestamp": datetime.now().isoformat(),
                                            })
                            except (json.JSONDecodeError, ValueError, TypeError):
                                pass
            
            # Method 6: Parse HTML elements for visible round history
            html_rounds = self._parse_rounds_from_html(soup)
            all_rounds.extend(html_rounds)
            
            if all_rounds:
                # Deduplicate by multiplier + fuzzy timestamp
                seen = set()
                unique_rounds = []
                for r in all_rounds:
                    # Create a key based on multiplier rounded to 2 decimals
                    key = f"{round(r['multiplier'], 2)}_{r.get('round_id', '')[:20]}"
                    if key not in seen and r["multiplier"] > 0:
                        seen.add(key)
                        unique_rounds.append(r)
                
                if unique_rounds:
                    return unique_rounds
            
            if attempt < max_retries - 1:
                wait = 3 + random.random() * 3
                print(f"[!] No rounds found on attempt {attempt+1}, retrying in {wait:.0f}s...")
                time.sleep(wait)

        return []

    def extract_game_state(self) -> Optional[Dict]:
        """Extract current game state from the page"""
        html = self.fetch_page()
        if not html:
            return None

        state = {
            "current_multiplier": 1.0,
            "round_active": False,
            "round_id": None
        }

        # Look for current multiplier in various formats
        patterns = [
            r'"currentMultiplier"\s*:\s*(\d+\.?\d*)',
            r'"multiplier"\s*:\s*(\d+\.?\d*)',
            r'data-multiplier="(\d+\.?\d*)"',
            r'class="[^"]*multiplier[^"]*"[^>]*>(\d+\.?\d*)<',
            r'>(\d+\.?\d*)x<',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                val = float(match.group(1))
                if 1.0 <= val <= 100:
                    state["current_multiplier"] = val
                    state["round_active"] = val > 1.01
                    break

        return state
