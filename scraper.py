import cloudscraper
import websocket
import json
import time
import random
import re
import requests
from typing import List, Dict, Optional, Callable
from datetime import datetime
from bs4 import BeautifulSoup
import urllib.parse

from config import BETPAWA_DOMAINS, GAME_PATHS, USER_AGENTS, BROWSER_HEADERS


class BetpawaScraper:
    """
    Multi-layer anti-detection scraper for Betpawa Aviator.
    Bypasses Cloudflare IUAM, TLS fingerprinting, rate limiting, and bot detection.
    """

    def __init__(self):
        self.active_domain = None
        self.active_game_path = None
        self.session = None
        self._init_session()
        self._discover_endpoints()

    def _get_random_headers(self):
        ua = random.choice(USER_AGENTS)
        headers = BROWSER_HEADERS.copy()
        headers["User-Agent"] = ua
        if random.random() > 0.5:
            headers["Accept-Language"] = "en-GB,en;q=0.9,en-US;q=0.8"
        return headers

    def _init_session(self):
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
        self.active_domain = BETPAWA_DOMAINS[0]
        self.active_game_path = GAME_PATHS[0]
        print(f"[!] Using fallback: {self.active_domain}{self.active_game_path}")

    @property
    def base_url(self):
        return f"{self.active_domain}{self.active_game_path}"

    def fetch_page(self):
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

    def fetch_round_history(self, max_retries=3):
        """Scrape live round history from the game page"""
        for attempt in range(max_retries):
            html = self.fetch_page()
            if not html:
                continue

            rounds = []
            soup = BeautifulSoup(html, 'html.parser')

            # Method 1: Parse script tags with embedded JSON
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string:
                    for pattern in [
                        r'"history"\s*:\s*\[(.*?)\]',
                        r'"rounds"\s*:\s*\[(.*?)\]',
                        r'"results"\s*:\s*\[(.*?)\]',
                        r'"previousRounds"\s*:\s*\[(.*?)\]',
                        r'"lastRounds"\s*:\s*\[(.*?)\]',
                        r'"crashHistory"\s*:\s*\[(.*?)\]',
                        r'"multipliers"\s*:\s*\[(.*?)\]',
                    ]:
                        match = re.search(pattern, script.string, re.DOTALL)
                        if match:
                            try:
                                data = json.loads(f"[{match.group(1)}]")
                                for item in data:
                                    if isinstance(item, dict):
                                        multiplier = item.get('multiplier') or item.get('value') or item.get('crash') or item.get('result')
                                        if multiplier:
                                            rounds.append({
                                                "round_id": item.get('id', item.get('roundId', str(time.time()))),
                                                "multiplier": float(multiplier),
                                                "timestamp": item.get('timestamp', item.get('time', datetime.now().isoformat())),
                                            })
                                    elif isinstance(item, (int, float)):
                                        rounds.append({
                                            "round_id": str(time.time()),
                                            "multiplier": float(item),
                                            "timestamp": datetime.now().isoformat(),
                                        })
                            except (json.JSONDecodeError, ValueError):
                                pass

            # Method 2: Parse HTML history elements
            history_elements = soup.select(
                '[class*="history"], [class*="round"], [class*="result"], '
                '[class*="multiplier"], [data-testid*="history"], '
                '[class*="previous"], [class*="crash"], [class*="game-history"]'
            )
            for elem in history_elements:
                text = elem.get_text(strip=True)
                mult_match = re.search(r'(\d+\.?\d*)\s*x?', text)
                if mult_match:
                    val = float(mult_match.group(1))
                    if 1.0 <= val <= 1000:
                        rounds.append({
                            "round_id": str(time.time() + random.random()),
                            "multiplier": val,
                            "timestamp": datetime.now().isoformat(),
                        })

            # Method 3: Parse __NEXT_DATA__ or __NUXT__
            for script in scripts:
                if script.get('id') in ('__NEXT_DATA__', '__NUXT__', '__INITIAL_STATE__'):
                    try:
                        data = json.loads(script.string)

                        def find_rounds(obj, depth=0):
                            if depth > 6:
                                return []
                            results = []
                            if isinstance(obj, dict):
                                for key in ['history', 'rounds', 'results', 'previousRounds', 'lastRounds', 'multipliers', 'crashHistory', 'data']:
                                    if key in obj:
                                        val = obj[key]
                                        if isinstance(val, list):
                                            for item in val:
                                                if isinstance(item, dict):
                                                    m = item.get('multiplier') or item.get('value') or item.get('crash') or item.get('result')
                                                    if m:
                                                        results.append({
                                                            "round_id": item.get('id', item.get('roundId', str(time.time()))),
                                                            "multiplier": float(m),
                                                            "timestamp": item.get('timestamp', item.get('time', datetime.now().isoformat())),
                                                        })
                                                elif isinstance(item, (int, float)):
                                                    results.append({
                                                        "round_id": str(time.time()),
                                                        "multiplier": float(item),
                                                        "timestamp": datetime.now().isoformat(),
                                                    })
                                for v in obj.values():
                                    results.extend(find_rounds(v, depth + 1))
                            elif isinstance(obj, list):
                                for item in obj:
                                    results.extend(find_rounds(item, depth + 1))
                            return results

                        rounds = find_rounds(data)
                    except (json.JSONDecodeError, AttributeError):
                        pass

            if rounds:
                seen = set()
                unique = []
                for r in rounds:
                    rid = r.get("round_id", "")
                    if rid not in seen and r["multiplier"] > 0:
                        seen.add(rid)
                        unique.append(r)
                return unique

            print(f"[!] No rounds found on attempt {attempt+1}, retrying...")
            time.sleep(5)

        return []

    def connect_websocket(self, on_round_end=None):
        """Connect to Betpawa Spribe WebSocket for live data"""
        html = self.fetch_page()
        if not html:
            print("[!] Cannot fetch page for WS discovery")
            return None

        # Extract WebSocket URL from page
        ws_url = None
        patterns = [
            r'wss?://[^"\'\s]+/ws[^"\'\s]*',
            r'wss?://[^"\'\s]+/socket[^"\'\s]*',
            r'wss?://[^"\'\s]+/game[^"\'\s]*',
            r'wss?://[^"\'\s]+/spribe[^"\'\s]*',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html)
            for m in matches:
                if any(kw in m.lower() for kw in ['aviator', 'spribe', 'game', 'socket', 'ws']):
                    ws_url = m
                    break
            if ws_url:
                break

        if not ws_url:
            netloc = urllib.parse.urlparse(self.active_domain).netloc
            ws_candidates = [
                f"wss://{netloc}/ws",
                f"wss://{netloc}/socket.io",
                f"wss://{netloc}/game/aviator/ws",
                f"wss://spribe.{netloc}/ws",
                f"wss://{netloc}/aviator/ws",
            ]
            ws_url = ws_candidates[0]

        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type", "") or data.get("event", "")
                if msg_type in ("crash", "round_end", "game_over", "result"):
                    multiplier = data.get("multiplier") or data.get("finalMultiplier") or data.get("value") or 0
                    round_id = data.get("roundId") or data.get("id") or data.get("round_id") or ""
                    if multiplier and float(multiplier) > 0 and on_round_end:
                        on_round_end({
                            "round_id": round_id,
                            "multiplier": float(multiplier),
                            "timestamp": datetime.now().isoformat(),
                            "hash": data.get("hash", ""),
                        })
            except json.JSONDecodeError:
                pass

        def on_error(ws, error):
            print(f"[!] WS error: {error}")

        def on_close(ws, code, msg):
            print(f"[*] WS closed: {code} - {msg}")

        def on_open(ws):
            ws.send(json.dumps({"type": "subscribe", "channel": "game", "game": "aviator"}))
            ws.send(json.dumps({"event": "subscribe", "data": {"channel": "game:aviator"}}))
            ws.send(json.dumps({"type": "join", "game": "aviator"}))
            print("[✓] WS connected and subscribed")

        ws = websocket.WebSocketApp(
            ws_url,
            header={"User-Agent": random.choice(USER_AGENTS)},
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        return ws
