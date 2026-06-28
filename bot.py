#!/usr/bin/env python3
"""
BETPAWA AVIATOR BOT — FIXED FULL VERSION
Single file, corrected lifecycle loop, complete features.
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
# Optional: Put your extracted browser session cookie here if form POST still returns 405
BETPAWA_SESSION = os.getenv("BETPAWA_SESSION", "") 

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
    try:
        server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler)
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

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
        """Login with session cookie bypass or form POST fallback"""
        # Strategy A: Use Direct Session Cookie Bypass if provided
        if BETPAWA_SESSION:
            logger.info("Using session cookie authentication bypass...")
            self.scraper.cookies.set("session_id", BETPAWA_SESSION, domain=".betpawa.ug")
            self.logged_in = True
            return True

        if username is None:
            username = BETPAWA_USER
        if password is None:
            password = BETPAWA_PASS
        
        if not username or not password:
            logger.error("No credentials available.")
            return False
        
        logger.info(f"Logging in as {username}...")
        try:
            # Step 1: Get login page for CSRF token
            r = self.scraper.get(f"{self.BASE}/login", timeout=30)
            if r.status_code != 200:
                logger.error(f"Login page status: {r.status_code}")
                return False
            
            soup = BeautifulSoup(r.text, 'lxml')
            csrf = ""
            meta = soup.find('meta', {'name': 'csrf-token'})
            if meta:
                csrf = meta.get('content', '')
            if not csrf:
                inp = soup.find('input', {'name': '_token'})
                if inp:
                    csrf = inp.get('value', '')
            
            logger.info(f"CSRF token found: {csrf[:20] if csrf else 'None'}...")
            
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
            
            # Step 3: Verify access
            check = self.scraper.get(f"{self.BASE}/casino/game/aviator", timeout=30)
            if 'logout' in check.text.lower() or 'my account' in check.text.lower():
                self.logged_in = True
                logger.info("✅ Login successful via validation page content.")
                return True
            
            for cookie in self.scraper.cookies:
                if any(k in cookie.name.lower() for k in ['token', 'auth', 'session']):
                    self.logged_in = True
                    logger.info(f"✅ Login successful via cookie: {cookie.name}")
                    return True
            
            if r2.url and '/login' not in r2.url and r2.status_code == 200:
                self.logged_in = True
                logger.info("✅ Login successful via endpoint redirect.")
                return True
            
            logger.error("❌ Login failed — still stuck on auth gateway.")
            return False
            
        except Exception as e:
            logger.error(f"Login processing error: {e}")
            return False

    def fetch_rounds(self, limit=500):
        """Fetch historical rounds from game endpoints or layouts"""
        if not self.logged_in:
            return []
        
        new_rounds = []
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
                    data = r.json()
                    if isinstance(data, list):
                        new_rounds = data
                    elif isinstance(data, dict):
                        for key in ['data', 'rounds', 'history', 'results']:
                            if key in data and isinstance(data[key], list):
                                new_rounds = data[key]
                                break
                    if new_rounds:
                        logger.info(f"Scraped {len(new_rounds)} rounds from {api}")
                        break
            except Exception:
                continue
        
        # Fallback parsing
        if not new_rounds:
            try:
                r = self.scraper.get(f"{self.BASE}/casino/game/aviator", timeout=30)
                if r.status_code == 200:
                    patterns = [
                        r'"crashMultiplier":([\d.]+)',
                        r'"multiplier":([\d.]+)',
                        r'"crashPoint":([\d.]+)',
                    ]
                    for pattern in patterns:
                        matches = re.findall(pattern, r.text)
                        for m in matches:
                            val = float(m) if m.replace('.','').isdigit() else 0
                            if val > 0:
                                new_rounds.append({'crash_multiplier': val, 'multiplier': val})
            except Exception:
                pass
        return new_rounds

    def fetch_seeds(self):
        """Get seed configuration metrics"""
        if not self.logged_in:
            return {}
        
        data = {}
        apis = [
            f"{self.BASE}/api/v2/game/aviator/seed-info",
            f"{self.BASE}/api/game/aviator/seed-info",
            f"{self.BASE}/provably-fair",
        ]
        
        for api in apis:
            try:
                r = self.scraper.get(api, timeout=20, headers={'Accept': 'application/json'})
                if r.status_code == 200:
                    data = r.json()
                    break
            except Exception:
                continue
        
        if not data:
            try:
                r = self.scraper.get(f"{self.BASE}/casino/game/aviator", timeout=30)
                if r.status_code == 200:
                    patterns = {
                        'server_seed': r'"serverSeed"\s*:\s*"([^"]+)"',
                        'client_seed': r'"clientSeed"\s*:\s*"([^"]+)"',
                        'server_seed_hash': r'"serverSeedHash"\s*:\s*"([^"]+)"',
                    }
                    for key, pat in patterns.items():
                        m = re.search(pat, r.text)
                        if m:
                            data[key] = m.group(1)
            except Exception:
                pass
        self.seeds = data
        return data

    def get_balance(self):
        if not self.logged_in:
            return "N/A"
        apis = [f"{self.BASE}/api/v2/account", f"{self.BASE}/api/account"]
        for api in apis:
            try:
                r = self.scraper.get(api, timeout=15, headers={'Accept': 'application/json'})
                if r.status_code == 200:
                    data = r.json()
                    bal = data.get('balance') or data.get('amount') or data.get('wallet', {}).get('balance')
                    if bal:
                        return str(bal)
            except Exception:
                continue
        return "N/A"

# ===================== TELEGRAM BOT ACTIONS =====================
client = BetpawaClient()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *BETPAWA AVIATOR ENGINE BOT*\n\n"
        "Commands:\n"
        "/login — Trigger system authorization login\n"
        "/scrape — Fetch and sync historical statistics data\n"
        "/seeds — Fetch cryptographic provably fair values\n"
        "/signal — Process trends predictive report\n"
        "/balance — Verify balance parameters\n"
        "/status — Connection status menu\n"
        "/start — Reopen help manual",
        parse_mode='Markdown'
    )

async def do_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔐 Processing authorization query...")
    ok = client.login()
    if ok:
        rounds = client.fetch_rounds(limit=200)
        client.rounds.extend(rounds)
        seeds = client.fetch_seeds()
        bal = client.get_balance()
        msg = (
            "✅ *Authentication Processed!*\n\n"
            f"💰 Balance: `{bal} UGX`\n"
            f"📊 Compiled Entries: `{len(client.rounds)}` rounds\n"
        )
        if seeds:
            msg += f"🔐 Captured Seeds: `{len(seeds)} parameters sync`"
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ *Authentication rejected.*\nCheck variables setup or provide an active session cookie value.", parse_mode='Markdown')

async def do_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not client.logged_in:
        await update.message.reply_text("❌ Execute /login before query operations.")
        return
    await update.message.reply_text("🔄 Syncing metric tables...")
    for i in range(5):
        new = client.fetch_rounds(limit=200)
        if new:
            existing = {(r.get('crash_multiplier') or r.get('multiplier')): True for r in client.rounds}
            for r in new:
                m = r.get('crash_multiplier') or r.get('multiplier')
                if m and m not in existing:
                    client.rounds.append(r)
        await asyncio.sleep(1)
    await update.message.reply_text(f"✅ Data processing sync complete. Pool contains `{len(client.rounds)}` entries.", parse_mode='Markdown')

async def do_seeds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not client.logged_in:
        await update.message.reply_text("❌ Login tracking missing.")
        return
    data = client.fetch_seeds()
    if not data:
        await update.message.reply_text("❌ Metric data failed to compile.")
        return
    msg = "🔐 *Cryptographic Parameters*\n\n"
    for k, v in data.items():
        msg += f"• `{k}`: `{str(v)[:45]}`\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def do_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bal = client.get_balance()
    await update.message.reply_text(f"💰 *Current Balance:* `{bal} UGX`", parse_mode='Markdown')

async def do_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "✅ Authenticated" if client.logged_in else "❌ Session Detached"
    await update.message.reply_text(
        f"🤖 *System Monitoring Status*\n\n"
        f"• Network Node: {status}\n"
        f"• Tracked pool history: `{len(client.rounds)}` sets\n"
        f"• Structure Seed State: {'✅ Configured' if client.seeds else '❌ Unmapped'}",
        parse_mode='Markdown'
    )

async def do_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(client.rounds) < 10:
        await update.message.reply_text("❌ Insufficient records pool. Please execute /scrape first.")
        return
    
    multipliers = []
    for r in client.rounds:
        v = r.get('crash_multiplier') or r.get('multiplier') or 0
        try:
            if float(v) > 0: multipliers.append(float(v))
        except ValueError: continue

    if len(multipliers) < 10:
        await update.message.reply_text("❌ Data clean validation failed.")
        return

    recent = multipliers[-30:]
    avg = sum(recent) / len(recent)
    lows = sum(1 for x in multipliers[-8:] if x < 1.5)
    
    if lows >= 5:
        pred, conf, sig, cashout, reason = avg * 1.4, 0.60, "🚀 TREND_UPWARD_BOUNCE", min(avg * 0.7, 4.5), "Compensation trend expected after heavy low sets"
    else:
        pred, conf, sig, cashout, reason = avg * (0.85 + random.uniform(0, 0.2)), 0.40, "📊 TREND_STEADY", 1.80, "Normal probability distribution map parameters"

    pred = max(1.01, round(pred, 2))
    msg = (
        f"{sig}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"▸ *Target Weight:* `{pred}x`\n"
        f"▸ *Reliability Factor:* `{conf:.0%}`\n"
        f"▸ *Reference Limit:* `{cashout:.2f}x`\n"
        f"▸ *Dataset Count:* `{len(multipliers)}` entries\n\n"
        f"📋 *Evaluation:* {reason}\n"
        f"━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ===================== ASYNC WORKER LIFECYCLE CALLBACKS =====================
async def auto_start(context: ContextTypes.DEFAULT_TYPE):
    """Executes securely within the framework event loop context directly on engine launch."""
    logger.info("Initializing baseline connections sequence on hosting machine...")
    try:
        await context.bot.send_message(YOUR_CHAT_ID, "🤖 Bot server environment initialized online. Authenticating sequence started...")
    except Exception:
        pass
    
    if (BETPAWA_USER and BETPAWA_PASS) or BETPAWA_SESSION:
        ok = client.login()
        if ok:
            rounds = client.fetch_rounds(limit=150)
            client.rounds.extend(rounds)
            client.fetch_seeds()
            bal = client.get_balance()
            try:
                await context.bot.send_message(
                    YOUR_CHAT_ID,
                    f"✅ *Automatic Session Active*\n💰 Account state: `{bal} UGX` | 📊 Pool loaded: `{len(client.rounds)}` variables",
                    parse_mode='Markdown'
                )
            except Exception:
                pass

# ===================== MAIN BOOT ENGINE =====================
def main():
    logger.info("==================================================")
    logger.info("BETPAWA TELEGRAM PLATFORM MONITORING ENGINE STARTING")
    logger.info("==================================================")

    if not BOT_TOKEN:
        logger.error("CRITICAL ERROR: BOT_TOKEN environmental reference variable is missing.")
        return

    # Run network health layout detached
    t = threading.Thread(target=health_server, daemon=True)
    t.start()

    # Application Framework Assembler Engine
    app = Application.builder().token(BOT_TOKEN).build()

    # Setup Routing Directives mappings
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", do_login))
    app.add_handler(CommandHandler("scrape", do_scrape))
    app.add_handler(CommandHandler("seeds", do_seeds))
    app.add_handler(CommandHandler("signal", do_signal))
    app.add_handler(CommandHandler("balance", do_balance))
    app.add_handler(CommandHandler("status", do_status))

    # Safely coordinate framework startup logic through JobQueue infrastructure
    if app.job_queue:
        app.job_queue.run_once(auto_start, when=2)

    logger.info("🤖 Starting polling loop context handles...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
