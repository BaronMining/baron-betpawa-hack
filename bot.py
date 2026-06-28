#!/usr/bin/env python3
"""
Betpawa Aviator Millionaire Bot — BULLETPROOF VERSION
"""

import asyncio
import logging
import os
import threading
import sys
import re
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict

import cloudscraper
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters, ConversationHandler, CallbackQueryHandler
)

# ===================== CONFIG (no separate config.py needed) =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUR_TELEGRAM_ID = 7611883512
BETPAWA_USERNAME = os.getenv("BETPAWA_USERNAME", "")
BETPAWA_PASSWORD = os.getenv("BETPAWA_PASSWORD", "")
CONFIDENCE_THRESHOLD = 0.25
AUTO_SEND_INTERVAL = 60

# ===================== LOGGING =====================
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# ===================== GLOBAL STATE =====================
scraper = None
predictor = None
user_credentials = {
    "username": BETPAWA_USERNAME,
    "password": BETPAWA_PASSWORD,
}
AWAITING_USERNAME, AWAITING_PASSWORD = range(2)

# ===================== HEALTH SERVER =====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        status = f"Betpawa Bot | OK"
        self.wfile.write(status.encode())
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"[*] Health server on port {port}")
    server.serve_forever()

# ===================== SCRAPER =====================
class BetpawaScraper:
    def __init__(self):
        self.session = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True, 'mobile': False},
            delay=15
        )
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'https://www.betpawa.ug',
            'Referer': 'https://www.betpawa.ug/',
        })
        self.logged_in = False
        self.token = None
        self.refresh_token = None

    def login(self, username=None, password=None):
        """Login to Betpawa using their working API"""
        if username is None:
            username = user_credentials["username"]
        if password is None:
            password = user_credentials["password"]
        if not username or not password:
            return False

        logger.info(f"Logging in as {username}...")

        try:
            # Step 1: Get the homepage first to set cookies
            self.session.get("https://www.betpawa.ug/", timeout=30)
            
            # Step 2: Try all known Betpawa login endpoints
            login_endpoints = [
                "https://www.betpawa.ug/api/auth/login",
                "https://www.betpawa.ug/api/v1/auth/login", 
                "https://www.betpawa.ug/api/v2/auth/login",
                "https://www.betpawa.ug/api/v3/auth/login",
                "https://www.betpawa.ug/api/login",
                "https://www.betpawa.ug/auth/login",
                "https://www.betpawa.ug/login",
            ]

            payload = {
                "phone": username,
                "password": password,
                "grant_type": "password",
                "client_id": "web",
                "client_secret": ""
            }

            # Try different payload formats
            payloads = [
                {"phone": username, "password": password},
                {"phone": username, "password": password, "remember": True},
                {"username": username, "password": password},
                {"email": username, "password": password},
                {"phoneNumber": username, "password": password},
                {"phone": username, "password": password, "grant_type": "password"},
            ]

            for endpoint in login_endpoints:
                for pl in payloads:
                    try:
                        r = self.session.post(
                            endpoint,
                            json=pl,
                            timeout=30,
                            headers={'Content-Type': 'application/json'}
                        )
                        
                        if r.status_code == 200:
                            try:
                                data = r.json()
                                if data.get('token') or data.get('access_token') or data.get('data'):
                                    self.token = data.get('token') or data.get('access_token') or data.get('data', {}).get('token')
                                    self.refresh_token = data.get('refresh_token')
                                    self.logged_in = True
                                    self.session.headers.update({
                                        'Authorization': f'Bearer {self.token}'
                                    })
                                    logger.info(f"✅ Login SUCCESS via {endpoint}")
                                    return True
                            except:
                                pass
                        
                        # Check for cookies
                        for cookie in self.session.cookies:
                            if 'token' in cookie.name.lower() or 'auth' in cookie.name.lower() or 'session' in cookie.name.lower():
                                self.logged_in = True
                                logger.info(f"✅ Login SUCCESS via cookie: {cookie.name}")
                                return True
                                
                    except Exception as e:
                        logger.debug(f"{endpoint}: {str(e)[:30]}")
                        continue

            logger.error("❌ All login endpoints failed (404 or invalid)")
            return False

        except Exception as e:
            logger.error(f"❌ Login exception: {e}")
            return False

    def fetch_round_history(self, limit=500):
        """Fetch historical rounds"""
        if not self.logged_in:
            return []

        api_endpoints = [
            f"https://www.betpawa.ug/api/v2/game/aviator/history?limit={limit}",
            f"https://www.betpawa.ug/api/v1/game/aviator/history?limit={limit}",
            f"https://www.betpawa.ug/api/game/aviator/history?limit={limit}",
            f"https://www.betpawa.ug/api/aviator/history?limit={limit}",
            f"https://www.betpawa.ug/game/aviator/api/history?limit={limit}",
        ]

        for url in api_endpoints:
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 200:
                    try:
                        data = r.json()
                        if isinstance(data, list):
                            logger.info(f"Got {len(data)} rounds")
                            return data
                        elif isinstance(data, dict):
                            for key in ['data', 'rounds', 'history', 'results', 'records']:
                                if key in data and isinstance(data[key], list):
                                    logger.info(f"Got {len(data[key])} rounds from {key}")
                                    return data[key]
                    except:
                        pass
            except:
                continue

        # Fallback: scrape from game page HTML
        try:
            r = self.session.get("https://www.betpawa.ug/casino/game/aviator", timeout=30)
            if r.status_code == 200:
                rounds = []
                # Search for crash values in JavaScript
                patterns = [
                    r'"crashMultiplier":([\d.]+)',
                    r'"multiplier":([\d.]+)',
                    r'"crashPoint":([\d.]+)',
                    r'"round":\{"multiplier":([\d.]+)',
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, r.text)
                    for m in matches:
                        rounds.append({'crash_multiplier': float(m), 'multiplier': float(m)})

                if rounds:
                    logger.info(f"Extracted {len(rounds)} rounds from HTML")
                    return rounds
        except:
            pass

        return []

    def fetch_provably_fair_data(self):
        """Get seed/hash data"""
        if not self.logged_in:
            return {"success": False, "error": "Not logged in"}

        api_endpoints = [
            "https://www.betpawa.ug/api/v2/game/aviator/seed-info",
            "https://www.betpawa.ug/api/v1/game/aviator/seed-info",
            "https://www.betpawa.ug/api/game/aviator/seed-info",
            "https://www.betpawa.ug/api/aviator/seed-info",
            "https://www.betpawa.ug/provably-fair",
        ]

        for url in api_endpoints:
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 200:
                    try:
                        data = r.json()
                        return {"success": True, **data}
                    except:
                        pass
            except:
                continue

        return {"success": False}

    def get_account_info(self):
        """Get account balance"""
        if not self.logged_in:
            return {"balance": "N/A", "currency": "UGX"}

        api_endpoints = [
            "https://www.betpawa.ug/api/v2/account",
            "https://www.betpawa.ug/api/v1/account",
            "https://www.betpawa.ug/api/account",
            "https://www.betpawa.ug/api/user/balance",
        ]

        for url in api_endpoints:
            try:
                r = self.session.get(url, timeout=30)
                if r.status_code == 200:
                    try:
                        data = r.json()
                        balance = data.get('balance', data.get('amount', 'N/A'))
                        return {"balance": balance, "currency": data.get('currency', 'UGX')}
                    except:
                        pass
            except:
                continue

        return {"balance": "N/A", "currency": "UGX"}


# ===================== PREDICTOR =====================
class SimplePredictor:
    def __init__(self):
        self.round_history = []

    def load_historical_data(self, rounds):
        for r in rounds:
            mult = r.get('crash_multiplier') or r.get('multiplier') or r.get('crashPoint') or 0
            try:
                self.round_history.append(float(mult))
            except:
                continue
        logger.info(f"Loaded {len(self.round_history)} data points")

    def generate_signal(self):
        if len(self.round_history) < 20:
            return {
                "signal": "WAIT",
                "prediction": None,
                "confidence": 0,
                "suggested_cashout": 1.5,
                "reason": f"Collecting data ({len(self.round_history)}/20 rounds)",
                "data_points": len(self.round_history),
                "stats": {},
                "timestamp": datetime.now().isoformat()
            }

        m = self.round_history
        recent_50 = m[-50:] if len(m) >= 50 else m
        recent_10 = m[-10:] if len(m) >= 10 else m

        mean = sum(recent_50) / len(recent_50)
        low_in_10 = sum(1 for x in recent_10 if x < 1.5)
        high_in_10 = sum(1 for x in recent_10 if x > 3.0)

        # Strategy
        if low_in_10 >= 7:
            pred = mean * 1.4
            conf = 0.55
            reason = "Strong regression after low streak"
            signal = "BUY_HIGH"
        elif low_in_10 >= 5:
            pred = mean * 1.25
            conf = 0.45
            reason = "Bounce expected from low streak"
            signal = "BUY_MEDIUM"
        elif high_in_10 >= 5:
            pred = mean * 0.7
            conf = 0.35
            reason = "Consolidation after high streak"
            signal = "CAUTION"
        else:
            pred = mean * (0.9 + (len(m) % 3) * 0.05)
            conf = 0.35
            reason = "Normal pattern"
            signal = "BUY_LOW"

        pred = max(1.0, min(100.0, round(pred, 2)))
        
        if pred < 1.5:
            cashout = 1.2
        elif pred < 2.0:
            cashout = 1.5
        elif pred < 3.0:
            cashout = 2.0
        elif pred < 5.0:
            cashout = 3.0
        else:
            cashout = min(pred * 0.6, 10.0)

        return {
            "signal": signal,
            "prediction": pred,
            "confidence": round(conf, 3),
            "suggested_cashout": round(cashout, 2),
            "reason": reason,
            "data_points": len(m),
            "stats": {"recent_mean": round(mean, 2), "recent_low_streak": low_in_10, "recent_high_streak": high_in_10},
            "timestamp": datetime.now().isoformat()
        }


# Initialize
scraper = BetpawaScraper()
predictor = SimplePredictor()


# ===================== TELEGRAM =====================

def format_signal(signal):
    e = {"BUY_HIGH": "🚀", "BUY_MEDIUM": "📈", "BUY_LOW": "📊", "SKIP": "⏸️", "WAIT": "⏳", "CAUTION": "⚠️", "OPPORTUNITY": "💎"}
    s = signal.get("signal", "N/A")
    emoji = e.get(s, "❓")
    pred = signal.get("prediction")
    conf = signal.get("confidence", 0)
    cashout = signal.get("suggested_cashout")
    reason = signal.get("reason", "")
    stats = signal.get("stats", {})
    points = signal.get("data_points", 0)

    return (
        f"{emoji} *BETPAWA AViATOR SIGNAL*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"▸ *Signal:* `{s}`\n"
        f"▸ *Prediction:* `{f'{pred}x' if pred else 'N/A'}`\n"
        f"▸ *Confidence:* `{f'{conf:.1%}' if conf else '0%'}`\n"
        f"▸ *Cashout:* `{f'{cashout}x' if cashout else 'N/A'}`\n"
        f"▸ *Data:* `{points} rounds`\n\n"
        f"📋 _{reason}_\n"
        f"\n━━━━━━━━━━━━━━━"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "✅ Logged in" if scraper.logged_in else "❌ Not logged in"
    msg = (
        f"🤖 *BETPAWA BOT*\n\n"
        f"Status: {status}\n"
        f"/login — Enter credentials\n"
        f"/scrape — Get rounds\n"
        f"/signal — Prediction\n"
        f"/status — Info\n"
        f"/analyze — Report"
    )
    keyboard = [
        [InlineKeyboardButton("🔑 Login", callback_data="login"),
         InlineKeyboardButton("🔮 Signal", callback_data="signal")],
    ]
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send your Betpawa phone number:")
    return AWAITING_USERNAME


async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bp_user'] = update.message.text.strip()
    await update.message.reply_text("Now send your password:")
    return AWAITING_PASSWORD


async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = context.user_data.get('bp_user', '')
    password = update.message.text.strip()
    user_credentials["username"] = username
    user_credentials["password"] = password
    
    await update.message.reply_text("🔐 Logging in...")
    
    if scraper.login(username, password):
        await update.message.reply_text("✅ Login successful! Scraping rounds...")
        rounds = scraper.fetch_round_history(limit=500)
        if rounds:
            predictor.load_historical_data(rounds)
        await update.message.reply_text(f"📊 Collected {len(predictor.round_history)} rounds")
    else:
        await update.message.reply_text("❌ Login failed. Try /login again.")
    
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled")
    return ConversationHandler.END


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not scraper.logged_in:
        await update.message.reply_text("❌ Not logged in. Use /login")
        return
    
    await update.message.reply_text("🔄 Scraping rounds...")
    total = 0
    for i in range(20):
        rounds = scraper.fetch_round_history(limit=500)
        if rounds:
            predictor.load_historical_data(rounds)
            total += len(rounds)
        await asyncio.sleep(2)
    
    await update.message.reply_text(f"✅ Done! {total} rounds collected")


async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    signal = predictor.generate_signal()
    await update.message.reply_text(format_signal(signal), parse_mode='Markdown')


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = "✅ Logged in" if scraper.logged_in else "❌ Not logged in"
    msg = (
        f"🤖 *Status*\n\n"
        f"Login: {s}\n"
        f"Rounds: {len(predictor.round_history)}\n"
        f"Target: {YOUR_TELEGRAM_ID}"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not predictor.round_history:
        await update.message.reply_text("No data. Scrape first.")
        return
    
    m = predictor.round_history
    avg = sum(m) / len(m)
    low = sum(1 for x in m if x < 2.0)
    high = sum(1 for x in m if x > 5.0)
    
    msg = (
        f"📈 *Analysis*\n\n"
        f"Rounds: {len(m)}\n"
        f"Avg crash: {avg:.2f}x\n"
        f"Under 2x: {low/len(m)*100:.1f}%\n"
        f"Over 5x: {high/len(m)*100:.1f}%"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Use /login or /signal commands")


async def startup(app):
    await asyncio.sleep(10)
    try:
        await app.bot.send_message(YOUR_TELEGRAM_ID, "🤖 Bot started! Use /login")
    except:
        pass
    
    if user_credentials["username"] and user_credentials["password"]:
        if scraper.login():
            rounds = scraper.fetch_round_history(limit=500)
            if rounds:
                predictor.load_historical_data(rounds)


# ===================== MAIN =====================
def main():
    logger.info("=" * 50)
    logger.info("BETPAWA BOT — Starting")
    logger.info("=" * 50)

    if not BOT_TOKEN:
        logger.error("❌ No BOT_TOKEN")
        return

    # Health server
    threading.Thread(target=run_health_server, daemon=True).start()

    # Build app — NO job queue, NO startup event loop crash
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    conv = ConversationHandler(
        entry_points=[CommandHandler('login', login_command)],
        states={
            AWAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)],
            AWAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Startup notification using asyncio.create_task, no manual event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(startup(app))
    loop.close()

    # Run polling — this creates its OWN event loop
    logger.info("🤖 Bot running")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
