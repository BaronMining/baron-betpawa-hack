#!/usr/bin/env python3
"""
Betpawa Aviator Millionaire Bot
Logs into Betpawa, extracts 10,000+ rounds + provably fair seed data,
analyzes SHA-512 hash chain, generates maximum accuracy signals.
"""

import asyncio
import logging
import time
import os
import threading
import sys
import random
from datetime import datetime
from typing import Dict
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    MessageHandler, filters, ConversationHandler, CallbackQueryHandler
)

from config import (
    BOT_TOKEN, YOUR_TELEGRAM_ID,
    BETPAWA_USERNAME, BETPAWA_PASSWORD,
    CONFIDENCE_THRESHOLD, AUTO_SEND_INTERVAL
)
from betpawa_login import BetpawaAuthenticatedScraper
from predictor import AviatorPredictor

# ===================== SETUP =====================

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Global state
scraper = BetpawaAuthenticatedScraper()
predictor = AviatorPredictor()

# User credentials storage (in-memory for this session)
user_credentials = {
    "username": BETPAWA_USERNAME,
    "password": BETPAWA_PASSWORD,
}

# Bot conversation states
AWAITING_USERNAME, AWAITING_PASSWORD = range(2)

# ===================== HEALTH SERVER =====================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        status = (
            f"Betpawa Aviator Bot | Logged in: {scraper.logged_in} | "
            f"Rounds: {len(predictor.round_history)} | "
            f"Seeds: {len(predictor.seed_data)}"
        )
        self.wfile.write(status.encode())
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"[*] Health server on port {port}")
    server.serve_forever()

# ===================== SIGNAL GENERATION =====================

def format_signal(signal: Dict) -> str:
    """Format signal for Telegram"""
    emojis = {
        "BUY_HIGH": "🚀", "BUY_MEDIUM": "📈", "BUY_LOW": "📊",
        "SKIP": "⏸️", "WAIT": "⏳", "CAUTION": "⚠️",
        "OPPORTUNITY": "💎", "DANGER": "☠️", "AVOID": "🚫",
        "ERROR": "❌"
    }

    s = signal.get("signal", "N/A")
    emoji = emojis.get(s, "❓")
    pred = signal.get("prediction")
    conf = signal.get("confidence", 0)
    cashout = signal.get("suggested_cashout")
    reason = signal.get("reason", "")
    stats = signal.get("stats", {})
    points = signal.get("data_points", 0)

    pred_str = f"{pred}x" if pred else "N/A"
    cash_str = f"{cashout}x" if cashout else "N/A"
    conf_str = f"{conf:.1%}" if conf else "0%"

    msg = (
        f"{emoji} *BETPAWA AViATOR MILLIONAIRE SIGNAL*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"▸ *Signal:* `{s}`\n"
        f"▸ *Prediction:* `{pred_str}`\n"
        f"▸ *Confidence:* `{conf_str}`\n"
        f"▸ *Cashout:* `{cash_str}`\n"
        f"▸ *Data:* `{points} rounds analyzed`\n\n"
        f"📋 *Analysis:* _{reason}_\n"
    )

    if stats:
        msg += (
            f"\n📊 *Stats:*\n"
            f"▹ Current Mean: `{stats.get('recent_mean', 'N/A')}x`\n"
            f"▹ High Streak: `{stats.get('recent_high_streak', 0)}/10`\n"
            f"▹ Low Streak: `{stats.get('recent_low_streak', 0)}/10`\n"
        )

    msg += (
        f"\n━━━━━━━━━━━━━━━\n"
        f"_Strategy: Cash out at suggested level for max profit_"
    )

    return msg

async def send_signal(context: ContextTypes.DEFAULT_TYPE):
    """Send signal to Telegram"""
    signal = predictor.generate_signal()
    msg = format_signal(signal)

    try:
        await context.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=msg,
            parse_mode='Markdown',
            disable_web_page_preview=True,
        )
        logger.info(f"Signal sent: {signal['signal']} | {signal.get('prediction', 'N/A')}x | {signal.get('confidence', 0):.1%}")
    except Exception as e:
        logger.error(f"Send failed: {e}")

async def auto_signal_loop(context: ContextTypes.DEFAULT_TYPE):
    """Background signal loop"""
    if len(predictor.round_history) < 20:
        logger.info(f"Collecting... {len(predictor.round_history)}/20")
        return

    signal = predictor.generate_signal()
    conf = signal.get("confidence", 0)
    sig_type = signal.get("signal", "SKIP")

    should_send = False
    if conf >= CONFIDENCE_THRESHOLD:
        should_send = True
    elif sig_type in ("OPPORTUNITY", "DANGER", "CAUTION") and conf >= 0.3:
        should_send = True
    elif sig_type in ("BUY_HIGH", "BUY_MEDIUM") and conf >= 0.4:
        should_send = True
    elif sig_type == "BUY_HIGH" and conf >= 0.3:
        should_send = True

    if should_send:
        await send_signal(context)

async def refresh_data(context: ContextTypes.DEFAULT_TYPE):
    """Periodically refresh game data"""
    if not scraper.logged_in:
        if user_credentials["username"] and user_credentials["password"]:
            scraper.login(user_credentials["username"], user_credentials["password"])
        return

    new_rounds = scraper.fetch_round_history(limit=50)
    if new_rounds:
        predictor.load_historical_data(new_rounds)
        logger.info(f"Refreshed: {len(new_rounds)} new data points")

# ===================== TELEGRAM COMMANDS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    status = "✅ Logged in" if scraper.logged_in else "❌ Not logged in"
    data_count = len(predictor.round_history)
    seed_count = len(predictor.seed_data)

    msg = (
        f"🤖 *BETPAWA MILLIONAIRE BOT*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"🔥 *Mission:* Extract provably fair data, analyze SHA-512 chain,\n"
        f"and generate maximum-profit signals.\n\n"
        f"📊 *Status:*\n"
        f"• Login: `{status}`\n"
        f"• Rounds collected: `{data_count}`\n"
        f"• Seeds captured: `{seed_count}`\n\n"
        f"*Commands:*\n"
        f"/login — Enter Betpawa credentials\n"
        f"/scrape — Scrape 10,000 rounds\n"
        f"/verify — Verify provably fair\n"
        f"/signal — Get prediction\n"
        f"/analyze — Deep analysis report\n"
        f"/status — Full status\n"
        f"/start — This menu"
    )

    keyboard = [
        [InlineKeyboardButton("🔑 Login", callback_data="login"),
         InlineKeyboardButton("📊 Scrape", callback_data="scrape")],
        [InlineKeyboardButton("🔮 Signal", callback_data="signal"),
         InlineKeyboardButton("📈 Analyze", callback_data="analyze")],
    ]

    await update.message.reply_text(
        msg, parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start login conversation"""
    await update.message.reply_text(
        "🔐 *Login to Betpawa*\n\n"
        "Send me your Betpawa phone number/username:",
        parse_mode='Markdown'
    )
    return AWAITING_USERNAME

async def receive_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive username"""
    context.user_data['bp_username'] = update.message.text.strip()
    await update.message.reply_text(
        "✅ Got it! Now send me your password:",
        parse_mode='Markdown'
    )
    return AWAITING_PASSWORD

async def receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive password and login"""
    username = context.user_data.get('bp_username', '')
    password = update.message.text.strip()

    # Store credentials
    user_credentials["username"] = username
    user_credentials["password"] = password

    await update.message.reply_text("🔐 Logging into Betpawa...")

    success = scraper.login(username, password)

    if success:
        await update.message.reply_text(
            "✅ *Login successful!*\n\n"
            "Now scraping round history and provably fair data...\n"
            "This will take a few minutes for 10,000 rounds.",
            parse_mode='Markdown'
        )

        # Fetch initial rounds
        rounds = scraper.fetch_round_history(limit=1000)
        if rounds:
            predictor.load_historical_data(rounds)

        # Get provably fair data
        pf_data = scraper.fetch_provably_fair_data()
        if pf_data.get("success"):
            await update.message.reply_text(
                f"✅ *Provably Fair Data Captured*\n\n"
                f"• Server seed: `{str(pf_data.get('server_seed', 'N/A'))[:20]}...`\n"
                f"• Client seed: `{str(pf_data.get('client_seed', 'N/A'))[:20]}...`\n"
                f"• Next hash: `{str(pf_data.get('next_server_seed_hash', 'N/A'))[:20]}...`\n"
                f"• Rounds: `{len(pf_data.get('rounds', []))}`\n\n"
                f"Use /analyze for full report",
                parse_mode='Markdown'
            )

        # Get account info
        account = scraper.get_account_info()
        await update.message.reply_text(
            f"💰 *Account:* Balance: `{account.get('balance', 'N/A')} {account.get('currency', 'UGX')}`\n"
            f"📊 *Total rounds scraped:* `{len(predictor.round_history)}`",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *Login failed!*\n\n"
            "Check your credentials and try again with /login",
            parse_mode='Markdown'
        )

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel login"""
    await update.message.reply_text("❌ Login cancelled.")
    return ConversationHandler.END

async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scrape 10,000 rounds"""
    if not scraper.logged_in:
        await update.message.reply_text(
            "❌ Not logged in. Use /login first.",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        "🔄 *Scraping 10,000 rounds...*\n"
        "This will take several minutes.\n"
        "I'll notify you when complete.",
        parse_mode='Markdown'
    )

    total = 0
    max_rounds = 10000
    batch_size = 500

    for i in range(max_rounds // batch_size):
        rounds = scraper.fetch_round_history(limit=batch_size)
        if rounds:
            predictor.load_historical_data(rounds)
            total += len(rounds)

        await asyncio.sleep(2)

        if i % 2 == 0:
            try:
                await update.message.reply_text(
                    f"📊 *Progress:* `{total}/{max_rounds} rounds scraped`",
                    parse_mode='Markdown'
                )
            except:
                pass

    await update.message.reply_text(
        f"✅ *Complete!*\n\n"
        f"📊 Total rounds: `{len(predictor.round_history)}`\n"
        f"🔐 Seeds captured: `{len(predictor.seed_data)}`\n"
        f"📈 Use /analyze for deep analysis",
        parse_mode='Markdown'
    )

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify provably fair hashes"""
    if not predictor.seed_data:
        await update.message.reply_text(
            "❌ No seed data available. Scrape rounds first.",
            parse_mode='Markdown'
        )
        return

    analysis = predictor.hash_analyzer.analyze_seed_chain(predictor.seed_data[:100])

    verified = analysis.get("verified_rounds", 0)
    failed = analysis.get("failed_rounds", 0)
    total = analysis.get("total_rounds", 0)

    msg = (
        f"🔐 *Provably Fair Verification*\n\n"
        f"• Rounds checked: `{total}`\n"
        f"• Verified: `{verified}` ✅\n"
        f"• Failed: `{failed}` ❌\n"
        f"• Integrity: `{'PASS' if failed == 0 else 'ANOMALY DETECTED'}`\n\n"
    )

    if analysis.get("anomalies"):
        msg += "⚠️ *Anomalies found:*\n"
        for a in analysis["anomalies"][:5]:
            msg += f"• Round {a.get('round', '?')}: expected `{a.get('expected', '?')}x` got `{a.get('actual', '?')}x`\n"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show deep analysis"""
    analysis = predictor.get_analysis_summary()
    if not analysis:
        await update.message.reply_text(
            "❌ No analysis data. Scrape rounds first.",
            parse_mode='Markdown'
        )
        return

    stats = analysis.get("statistics", {})
    dist = analysis.get("distribution", {})
    strat = analysis.get("strategy", {})

    msg = (
        f"📈 *DEEP ANALYSIS REPORT*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📊 *Statistics ({analysis.get('total_multipliers', 0)} rounds):*\n"
        f"• Mean: `{stats.get('mean', 'N/A')}x`\n"
        f"• Median: `{stats.get('median', 'N/A')}x`\n"
        f"• Std Dev: `{stats.get('std', 'N/A')}x`\n"
        f"• Max: `{stats.get('max', 'N/A')}x`\n"
        f"• Min: `{stats.get('min', 'N/A')}x`\n\n"
        f"📊 *Distribution:*\n"
    )

    for k, v in dist.items():
        msg += f"• {k}: `{v.get('pct', 'N/A')}` ({v.get('count', 0)} rounds)\n"

    msg += "\n🎯 *Best Strategies:*\n"
    for k, v in list(strat.items())[:5]:
        msg += f"• {k}: Avg next `{v.get('avg_next_crash', 'N/A')}x` | Win 2x: `{v.get('probability_above_2', 'N/A')}`\n"

    for cashout_level in [1.5, 2.0, 3.0, 5.0]:
        rate = analysis.get(f"win_rate_{cashout_level}x", "N/A")
        msg += f"\n• Win rate at `{cashout_level}x`: `{rate}`"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get current signal"""
    await update.message.reply_chat_action("typing")
    signal = predictor.generate_signal()
    msg = format_signal(signal)
    await update.message.reply_text(
        msg, parse_mode='Markdown',
        disable_web_page_preview=True
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show full status"""
    login_status = "✅ Logged in" if scraper.logged_in else "❌ Not logged in"
    data_count = len(predictor.round_history)
    seed_count = len(predictor.seed_data)

    analysis = predictor.get_analysis_summary()
    stats = analysis.get("statistics", {}) if analysis else {}

    msg = (
        f"🤖 *BETPAWA BOT STATUS*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"🔐 {login_status}\n"
        f"• Domain: `{scraper.active_domain}`\n\n"
        f"📊 *Data:*\n"
        f"• Rounds: `{data_count}/10000`\n"
        f"• Seeds: `{seed_count}`\n"
        f"• Model: `✅ Active`\n\n"
        f"📈 *Stats:*\n"
        f"• Mean: `{stats.get('mean', 'N/A')}x`\n"
        f"• Max: `{stats.get('max', 'N/A')}x`\n\n"
        f"⚙️ *Settings:*\n"
        f"• Confidence threshold: `{CONFIDENCE_THRESHOLD:.0%}`\n"
        f"• Interval: `{AUTO_SEND_INTERVAL}s`\n"
        f"• Target chat: `{YOUR_TELEGRAM_ID}`"
    )

    await update.message.reply_text(msg, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses"""
    query = update.callback_query
    await query.answer()

    if query.data == "login":
        await query.edit_message_text(
            "Send /login to enter your Betpawa credentials",
            parse_mode='Markdown'
        )
    elif query.data == "scrape":
        await query.edit_message_text("Starting scrape...")
        await scrape_command(update, context)
    elif query.data == "signal":
        await query.edit_message_text("Generating signal...")
        await signal_command(update, context)
    elif query.data == "analyze":
        await query.edit_message_text("Running analysis...")
        await analyze_command(update, context)

# ===================== STARTUP =====================

async def startup_notification(app):
    """Send startup notification"""
    await asyncio.sleep(10)
    try:
        msg = (
            "🤖 *BETPAWA MILLIONAIRE BOT — ONLINE*\n\n"
            "✅ Connected and ready!\n"
            "📊 Use /login to enter credentials\n"
            "🔐 Bot will extract provably fair data\n"
            "💰 Then signals start automatically"
        )
        await app.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=msg,
            parse_mode='Markdown'
        )
        logger.info("Startup notification sent")
    except Exception as e:
        logger.error(f"Startup notification failed: {e}")

    # Auto-login if credentials exist as env vars
    if user_credentials["username"] and user_credentials["password"]:
        logger.info("Auto-logging in...")
        if scraper.login():
            rounds = scraper.fetch_round_history(limit=500)
            if rounds:
                predictor.load_historical_data(rounds)
            try:
                await app.bot.send_message(
                    chat_id=YOUR_TELEGRAM_ID,
                    text=f"✅ Auto-logged in! Scraped {len(predictor.round_history)} rounds.",
                    parse_mode='Markdown'
                )
            except:
                pass

# ===================== MAIN =====================

def main():
    logger.info("=" * 50)
    logger.info("BETPAWA MILLIONAIRE BOT — Starting")
    logger.info(f"Target: {YOUR_TELEGRAM_ID}")
    logger.info("=" * 50)

    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set!")
        run_health_server()
        return

    # Start health server
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # Build app
    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for login
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('login', login_command)],
        states={
            AWAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_username)],
            AWAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("scrape", scrape_command))
    app.add_handler(CommandHandler("verify", verify_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("signal", signal_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Background tasks
    if app.job_queue:
        app.job_queue.run_repeating(auto_signal_loop, interval=AUTO_SEND_INTERVAL, first=30)
        app.job_queue.run_repeating(refresh_data, interval=30, first=15)

    # Startup notification
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(startup_notification(app))
        loop.close()
    except Exception as e:
        logger.error(f"Startup error: {e}")

    logger.info("🤖 Bot running. Use /login to connect Betpawa account.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
