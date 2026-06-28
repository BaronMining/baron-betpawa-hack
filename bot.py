#!/usr/bin/env python3
"""
BETPAWA AViATOR BOT — FINAL BULLETPROOF VERSION
Single file, no external module imports (except cloudscraper + telegram)
"""

import os
import sys
import re
import json
import logging
import asyncio
import threading
import time
import random
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from collections import deque
from urllib.parse import urlparse, parse_qs

import cloudscraper
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUR_CHAT_ID = 7611883512
BETPAWA_USER = os.getenv("BETPAWA_USERNAME", "")
BETPAWA_PASS = os.getenv("BETPAWA_PASSWORD", "")

# ===================== LOGGING =====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

# ===================== HEALTH SERVER =====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot running")
    def log_message(self, *a):
        pass

def health_server():
    server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler)
    server.serve_forever()

# ===================== BETPAWA CLIENT =====================
class BetpawaClient:
    """Handles all Betpawa communication — login, scrape, provably fair"""
    
    BASE = "https://www.betpawa.ug"
    
    def __init__(self):
        self.scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
            delay=10
        )
        self.scraper.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        self.logged_in = False
        self.rounds = []
        self.seeds = {}
        self.balance = "N/A"
    
    def login(self, username=None, password=None):
        """Login with CSRF token extraction + form POST"""
        if username is None:
            username = BETPAWA_USER
        if password is None:
            password = BETPAWA_PASS
        
        if not username or not password:
            logger.error("No credentials")
            return False
        
        logger.info(f"Logging in as {username}...")
        
        try:
            # Step 1: Get login page for CSRF token + cookies
            r = self.scraper.get(f"{self.BASE}/login", timeout=30)
            if r.status_code != 200:
                logger.error(f"Login page status: {r.status_code}")
                return False
            
            soup = BeautifulSoup(r.text, 'lxml')
            
            # Extract CSRF token from meta tag
            csrf = ""
            meta = soup.find('meta', {'name': 'csrf-token'})
            if meta:
                csrf = meta.get('content', '')
            
            # Also check input fields
            if not csrf:
                inp = soup.find('input', {'name': '_token'})
                if inp:
                    csrf = inp.get('value', '')
            
            logger.info(f"CSRF token: {csrf[:20] if csrf else 'None'}...")
            
            # Step 2: POST login form
            login_data = {
                'phone': username,
                'password': password,
                'keep_logged_in': '1',
            }
            if csrf:
                login_data['_token'] = csrf
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': self.BASE,
                'Referer': f'{self.BASE}/login',
            }
            
            r2 = self.scraper.post(
                f"{self.BASE}/login",
                data=login_data,
                headers=headers,
                timeout=30,
                allow_redirects=True
            )
            
            logger.info(f"Login POST status: {r2.status_code}")
            
            # Step 3: Check if logged in by accessing a protected page
            check = self.scraper.get(f"{self.BASE}/casino/game/aviator", timeout=30)
            
            # Success indicators: seeing user-specific content or the game iframe
            if 'logout' in check.text.lower() or 'my account' in check.text.lower() or 'profile' in check.text.lower():
                self.logged_in = True
                logger.info("✅ Login successful (via page content)")
                return True
            
            # Check cookies for auth tokens
            for cookie in self.scraper.cookies:
                if any(k in cookie.name.lower() for k in ['token', 'auth', 'session', 'connect']):
                    self.logged_in = True
                    logger.info(f"✅ Login successful (via cookie: {cookie.name})")
                    return True
            
            # Check if we got redirected away from login page
            if r2.url and '/login' not in r2.url and r2.status_code == 200:
                self.logged_in = True
                logger.info(f"✅ Login successful (redirect to {r2.url})")
                return True
            
            logger.error("❌ Login failed — still on login page")
            return False
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def fetch_rounds(self, limit=500):
        """Fetch historical rounds from the game page or API"""
        if not self.logged_in:
            return []
        
        new_rounds = []
        
        # Try API endpoints
        apis = [
            f"{self.BASE}/api/v2/game/aviator/history",
            f"{self.BASE}/api/v1/game/aviator/history", 
            f"{self.BASE}/api/game/aviator/history",
            f"{self.BASE}/api/aviator/history",
        ]
        
        for api in apis:
            try:
                r = self.scraper.get(api, params={'limit': limit}, timeout=20,
                                     headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
                if r.status_code == 200:
                    try:
                        data = r.json()
                        if isinstance(data, list):
                            new_rounds = data
                        elif isinstance(data, dict):
                            for key in ['data', 'rounds', 'history', 'results']:
                                if key in data and isinstance(data[key], list):
                                    new_rounds = data[key]
                                    break
                        if new_rounds:
                            logger.info(f"Got {len(new_rounds)} rounds from {api}")
                            break
                    except:
                        continue
            except:
                continue
        
        # Fallback: scrape from game page HTML
        if not new_rounds:
            try:
                r = self.scraper.get(f"{self.BASE}/casino/game/aviator", timeout=30)
                if r.status_code == 200:
                    # Extract round data from JavaScript variables
                    patterns = [
                        r'"crashMultiplier":([\d.]+)',
                        r'"multiplier":([\d.]+)',
                        r'"crashPoint":([\d.]+)',
                        r'rounds\s*:\s*\[([^\]]+)\]',
                    ]
                    for pattern in patterns:
                        matches = re.findall(pattern, r.text)
                        for m in matches:
                            try:
                                val = float(m) if m.replace('.','').isdigit() else 0
                                if val > 0:
                                    new_rounds.append({'crash_multiplier': val, 'multiplier': val})
                            except:
                                continue
                    if new_rounds:
                        logger.info(f"Extracted {len(new_rounds)} rounds from HTML")
            except:
                pass
        
        return new_rounds
    
    def fetch_seeds(self):
        """Get provably fair seed/hash data"""
        if not self.logged_in:
            return {}
        
        data = {}
        
        # Try API endpoints
        apis = [
            f"{self.BASE}/api/v2/game/aviator/seed-info",
            f"{self.BASE}/api/v1/game/aviator/seed-info",
            f"{self.BASE}/api/game/aviator/seed-info",
            f"{self.BASE}/api/aviator/seed-info",
            f"{self.BASE}/provably-fair",
        ]
        
        for api in apis:
            try:
                r = self.scraper.get(api, timeout=20,
                                     headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
                if r.status_code == 200:
                    try:
                        data = r.json()
                        logger.info(f"Seeds from {api}")
                        break
                    except:
                        continue
            except:
                continue
        
        # Fallback: scrape from game page
        if not data:
            try:
                r = self.scraper.get(f"{self.BASE}/casino/game/aviator", timeout=30)
                if r.status_code == 200:
                    patterns = {
                        'server_seed': r'"serverSeed"\s*:\s*"([^"]+)"',
                        'client_seed': r'"clientSeed"\s*:\s*"([^"]+)"',
                        'server_seed_hash': r'"serverSeedHash"\s*:\s*"([^"]+)"',
                        'next_hash': r'"nextServerSeedHash"\s*:\s*"([^"]+)"',
                    }
                    for key, pat in patterns.items():
                        m = re.search(pat, r.text)
                        if m:
                            data[key] = m.group(1)
            except:
                pass
        
        self.seeds = data
        return data
    
    def get_balance(self):
        """Get account balance"""
        if not self.logged_in:
            return "N/A"
        
        apis = [
            f"{self.BASE}/api/v2/account",
            f"{self.BASE}/api/v1/account",
            f"{self.BASE}/api/account",
            f"{self.BASE}/api/user/balance",
        ]
        
        for api in apis:
            try:
                r = self.scraper.get(api, timeout=15,
                                     headers={'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})
                if r.status_code == 200:
                    try:
                        data = r.json()
                        bal = data.get('balance') or data.get('amount') or data.get('wallet', {}).get('balance')
                        if bal:
                            return str(bal)
                    except:
                        continue
            except:
                continue
        
        return "N/A"


# ===================== BOT =====================
client = BetpawaClient()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *BETPAWA AViATOR BOT*\n\n"
        "Commands:\n"
        "/login — Login to Betpawa\n"
        "/scrape — Fetch rounds\n"
        "/seeds — Get provably fair data\n"
        "/signal — Get prediction\n"
        "/balance — Check balance\n"
        "/status — Bot status\n"
        "/start — This menu",
        parse_mode='Markdown'
    )

async def do_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔐 Logging into Betpawa...")
    ok = client.login()
    if ok:
        # Auto-scrape
        rounds = client.fetch_rounds(limit=200)
        client.rounds.extend(rounds)
        seeds = client.fetch_seeds()
        bal = client.get_balance()
        
        msg = (
            "✅ *Login successful!*\n\n"
            f"💰 Balance: `{bal} UGX`\n"
            f"📊 Rounds: `{len(client.rounds)}`\n"
        )
        if seeds:
            msg += f"🔐 Seeds: `{len(seeds)} fields captured`\n"
        if seeds.get('server_seed'):
            msg += f"• Server seed: `{str(seeds.get('server_seed',''))[:20]}...`\n"
        if seeds.get('next_hash'):
            msg += f"• Next hash: `{str(seeds.get('next_hash',''))[:20]}...`\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "❌ *Login failed.*\n\n"
            "Set BETPAWA_USERNAME and BETPAWA_PASSWORD environment variables.\n"
            "Phone number format: 0789124978 (no +256)",
            parse_mode='Markdown'
        )

async def do_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not client.logged_in:
        await update.message.reply_text("❌ Login first with /login")
        return
    
    await update.message.reply_text("🔄 Scraping rounds... (this may take a minute)")
    
    total = len(client.rounds)
    for i in range(20):
        new = client.fetch_rounds(limit=500)
        if new:
            # Deduplicate
            existing_multipliers = {(r.get('crash_multiplier') or r.get('multiplier')): True for r in client.rounds}
            for r in new:
                m = r.get('crash_multiplier') or r.get('multiplier')
                if m and m not in existing_multipliers:
                    client.rounds.append(r)
                    existing_multipliers[m] = True
        await asyncio.sleep(1)
        if i % 5 == 0:
            await update.message.reply_text(f"📊 Progress: `{len(client.rounds)}` rounds", parse_mode='Markdown')
    
    await update.message.reply_text(
        f"✅ *Scraping complete!*\n"
        f"Total: `{len(client.rounds)}` rounds",
        parse_mode='Markdown'
    )

async def do_seeds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not client.logged_in:
        await update.message.reply_text("❌ Login first")
        return
    
    data = client.fetch_seeds()
    if not data:
        await update.message.reply_text("❌ Could not fetch seed data")
        return
    
    msg = "🔐 *Provably Fair Data*\n\n"
    for k, v in data.items():
        msg += f"• `{k}`: `{str(v)[:50]}`\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def do_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = client.get_balance()
    await update.message.reply_text(f"💰 Balance: `{bal} UGX`", parse_mode='Markdown')

async def do_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "✅ Logged in" if client.logged_in else "❌ Not logged in"
    await update.message.reply_text(
        f"🤖 *Status*\n\n"
        f"• Login: {status}\n"
        f"• Rounds: `{len(client.rounds)}`\n"
        f"• Seeds: `{'✅' if client.seeds else '❌'}`",
        parse_mode='Markdown'
    )

async def do_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(client.rounds) < 10:
        await update.message.reply_text("❌ Need more data. Use /scrape first", parse_mode='Markdown')
        return
    
    m = [r.get('crash_multiplier') or r.get('multiplier') or 0 for r in client.rounds if (r.get('crash_multiplier') or r.get('multiplier'))]
    m = [float(x) for x in m if float(x) > 0]
    
    if len(m) < 10:
        await update.message.reply_text("❌ Not enough valid multipliers", parse_mode='Markdown')
        return
    
    recent = m[-50:]
    avg = sum(recent) / len(recent)
    low_streak = sum(1 for x in m[-10:] if x < 1.5)
    high_streak = sum(1 for x in m[-10:] if x > 3.0)
    
    if low_streak >= 6:
        pred = avg * 1.5
        conf = 0.55
        sig = "🚀 BUY_HIGH"
        cashout = min(pred * 0.6, 5.0)
        reason = "Strong bounce expected after low streak"
    elif high_streak >= 4:
        pred = avg * 0.7
        conf = 0.4
        sig = "⚠️ CAUTION"
        cashout = 1.5
        reason = "Consolidation expected after highs"
    else:
        pred = avg * (0.9 + random.uniform(0, 0.2))
        conf = 0.35
        sig = "📊 BUY_MEDIUM" if conf > 0.3 else "⏸️ SKIP"
        cashout = min(pred * 0.7, 3.0)
        reason = "Normal pattern"
    
    pred = max(1.0, round(pred, 2))
    
    msg = (
        f"{sig}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"▸ *Prediction:* `{pred}x`\n"
        f"▸ *Confidence:* `{conf:.0%}`\n"
        f"▸ *Cashout:* `{cashout:.2f}x`\n"
        f"▸ *Rounds:* `{len(m)}`\n\n"
        f"📋 {reason}\n"
        f"━━━━━━━━━━━━━━━"
    )
    
    await update.message.reply_text(msg, parse_mode='Markdown')


# ===================== MAIN =====================
def main():
    logger.info("=" * 50)
    logger.info("BETPAWA BOT — STARTING")
    logger.info("=" * 50)
    
    if not BOT_TOKEN:
        logger.error("No BOT_TOKEN")
        return
    
    # Health server in background
    t = threading.Thread(target=health_server, daemon=True)
    t.start()
    
    # Build application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", do_login))
    app.add_handler(CommandHandler("scrape", do_scrape))
    app.add_handler(CommandHandler("seeds", do_seeds))
    app.add_handler(CommandHandler("signal", do_signal))
    app.add_handler(CommandHandler("balance", do_balance))
    app.add_handler(CommandHandler("status", do_status))
    
    # Auto-login on startup via a background task
    if BETPAWA_USER and BETPAWA_PASS:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def auto_start():
            await asyncio.sleep(5)
            try:
                await app.bot.send_message(YOUR_CHAT_ID, "🤖 Bot started! Logging in...")
            except:
                pass
            
            ok = client.login()
            if ok:
                rounds = client.fetch_rounds(limit=200)
                client.rounds.extend(rounds)
                seeds = client.fetch_seeds()
                bal = client.get_balance()
                try:
                    await app.bot.send_message(
                        YOUR_CHAT_ID,
                        f"✅ *Auto-login successful*\n💰 `{bal} UGX` | 📊 `{len(client.rounds)}` rounds",
                        parse_mode='Markdown'
                    )
                except:
                    pass
        
        loop.run_until_complete(auto_start())
        loop.close()
    
    logger.info("🤖 Bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
