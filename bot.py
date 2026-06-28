#!/usr/bin/env python3
"""
Betpawa Aviator Signal Bot — Fully Automatic
Sends prediction signals directly to your Telegram via scraping.
No WebSocket — pure HTTP data collection.
"""

import asyncio
import logging
import time
import random
import os
import threading
import sys
from datetime import datetime
from typing import Dict, Optional
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    BOT_TOKEN, YOUR_TELEGRAM_ID,
    CONFIDENCE_THRESHOLD, AUTO_SEND_INTERVAL
)
from scraper import BetpawaScraper
from predictor import MultiModelPredictor

# ===================== SETUP =====================

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Global state
scraper = BetpawaScraper()
predictor = MultiModelPredictor()

# Ring buffer of recent multipliers
round_history: deque = deque(maxlen=500)

# ===================== HEALTH SERVER FOR RENDER =====================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        status = f"Betpawa Aviator Bot is running | Rounds: {len(round_history)} | Trained: {predictor.is_trained}"
        self.wfile.write(status.encode())

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"[*] Health server listening on port {port}")
    server.serve_forever()

# ===================== CORE FUNCTIONS =====================

def fetch_and_update_history():
    """Fetch latest round history from Betpawa via HTTP scraping"""
    global round_history
    try:
        rounds = scraper.fetch_round_history()
        if rounds:
            new_count = 0
            for r in rounds:
                m = r.get("multiplier", 0)
                rid = r.get("round_id", "")
                if m > 0:
                    # Avoid exact duplicates
                    if not round_history or abs(m - round_history[-1]) > 0.001 or rid:
                        round_history.append(m)
                        new_count += 1
            if new_count > 0:
                logger.info(f"Fetched {new_count} new rounds. Total: {len(round_history)}")
        else:
            logger.debug("No new rounds in this fetch cycle")
    except Exception as e:
        logger.error(f"Fetch error: {e}")

def generate_signal() -> Dict:
    """Generate signal from current history"""
    if len(round_history) < 20:
        return {
            "signal": "WAIT",
            "reason": f"Collecting data ({len(round_history)}/20 rounds)",
            "confidence": 0,
            "prediction": None,
            "suggested_cashout": None,
            "timestamp": datetime.now().isoformat(),
        }

    history_list = list(round_history)
    return predictor.generate_signal(history_list)

def format_signal(signal: Dict) -> str:
    """Format signal for Telegram message"""
    signal_emojis = {
        "BUY_HIGH": "🚀", "BUY_MEDIUM": "📈", "BUY_LOW": "📊",
        "SKIP": "⏸️", "WAIT": "⏳", "CAUTION": "⚠️",
        "OPPORTUNITY": "💎", "DANGER": "☠️", "AVOID": "🚫",
        "ERROR": "❌"
    }

    s = signal.get("signal", "N/A")
    emoji = signal_emojis.get(s, "❓")
    pred = signal.get("prediction")
    conf = signal.get("confidence", 0)
    cashout = signal.get("suggested_cashout")
    reason = signal.get("reason", "")
    stats = signal.get("stats", {})
    models = signal.get("model_count", 0)

    pred_str = f"{pred}x" if pred else "N/A"
    cash_str = f"{cashout}x" if cashout else "N/A"
    conf_str = f"{conf:.1%}" if conf else "0%"

    msg = (
        f"{emoji} *BETPAWA AViATOR SIGNAL*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"▸ *Signal:* `{s}`\n"
        f"▸ *Prediction:* `{pred_str}`\n"
        f"▸ *Confidence:* `{conf_str}`\n"
        f"▸ *Suggested Cashout:* `{cash_str}`\n"
        f"▸ *Model:* `Statistical Analysis`\n\n"
        f"📋 *Analysis:* _{reason}_\n"
    )

    if stats:
        msg += (
            f"\n📊 *20-Round Stats:*\n"
            f"▹ Mean: `{stats.get('mean_20', 'N/A')}x`\n"
            f"▹ Std Dev: `{stats.get('std_20', 'N/A')}x`\n"
            f"▹ High Streak: `{stats.get('high_streak', 0)}/10`\n"
            f"▹ Low Streak: `{stats.get('low_streak', 0)}/10`\n"
        )

    msg += (
        f"\n📈 *Last 10 Rounds:*\n"
        f"`{'  '.join([f'{m:.2f}x' for m in list(round_history)[-10:]])}`\n"
        f"\n🔄 Total rounds tracked: `{len(round_history)}`\n"
        f"━━━━━━━━━━━━━━━\n"
        f"_⚠️ Statistical analysis only. Betpawa Aviator uses provably fair RNG._"
    )

    return msg

# ===================== TELEGRAM HANDLERS =====================

async def send_signal(context: ContextTypes.DEFAULT_TYPE):
    """Send signal to your Telegram ID"""
    signal = generate_signal()
    msg = format_signal(signal)

    try:
        await context.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=msg,
            parse_mode='Markdown',
            disable_web_page_preview=True,
        )
        logger.info(f"Sent signal: {signal['signal']} ({signal.get('prediction', 'N/A')}x)")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")

async def auto_signal_loop(context: ContextTypes.DEFAULT_TYPE):
    """Background task that runs every AUTO_SEND_INTERVAL seconds"""
    if len(round_history) < 20:
        logger.info(f"Still collecting data... {len(round_history)}/20 rounds")
        return

    signal = generate_signal()
    conf = signal.get("confidence", 0)
    sig_type = signal.get("signal", "SKIP")

    should_send = False
    if conf >= CONFIDENCE_THRESHOLD:
        should_send = True
    elif sig_type in ("OPPORTUNITY", "DANGER", "CAUTION") and conf >= 0.3:
        should_send = True
    elif sig_type in ("BUY_HIGH", "BUY_MEDIUM") and conf >= 0.4:
        should_send = True

    if should_send:
        await send_signal(context)

async def periodic_data_refresh(context: ContextTypes.DEFAULT_TYPE):
    """Refresh history data periodically"""
    fetch_and_update_history()

    # Auto-train if we have enough data and model isn't trained
    if len(round_history) >= 50 and not predictor.is_trained:
        logger.info("Auto-training model...")
        predictor.train(list(round_history), epochs=30)
        predictor.save()

# ===================== COMMANDS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start"""
    await update.message.reply_text(
        "🤖 *Betpawa Aviator Signal Bot*\n\n"
        "✅ *Active and running!*\n"
        f"• Auto-sending signals to your chat\n"
        f"• Confidence threshold: `{CONFIDENCE_THRESHOLD:.0%}`\n"
        f"• Check interval: `{AUTO_SEND_INTERVAL}s`\n"
        f"• Data points: `{len(round_history)}`\n\n"
        "*Commands:*\n"
        "/signal — Manual signal now\n"
        "/status — Bot status & stats\n"
        "/history — Recent rounds\n"
        "/refresh — Force data refresh",
        parse_mode='Markdown'
    )

async def manual_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual /signal command"""
    fetch_and_update_history()
    await update.message.reply_chat_action("typing")
    signal = generate_signal()
    msg = format_signal(signal)
    await update.message.reply_text(
        msg,
        parse_mode='Markdown',
        disable_web_page_preview=True,
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status"""
    signal = generate_signal()
    last_signal = signal.get("signal", "N/A")
    last_pred = signal.get("prediction", "N/A")
    last_conf = signal.get("confidence", 0)

    status_msg = (
        f"🤖 *Betpawa Aviator Bot — Status*\n\n"
        f"🟢 *System:*\n"
        f"• Data points: `{len(round_history)}/500`\n"
        f"• Model trained: `{'✅' if predictor.is_trained else '❌'}`\n"
        f"• Auto-send: `✅ Enabled`\n"
        f"• Interval: `{AUTO_SEND_INTERVAL}s`\n\n"
        f"📡 *Betpawa:*\n"
        f"• Domain: `{scraper.active_domain}`\n"
        f"• Path: `{scraper.active_game_path}`\n\n"
        f"🔮 *Last Signal:*\n"
        f"• Signal: `{last_signal}`\n"
        f"• Prediction: `{last_pred}x`\n"
        f"• Confidence: `{last_conf:.1%}`\n\n"
        f"_Sending to chat ID 7611883512_"
    )

    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent rounds"""
    if not round_history:
        await update.message.reply_text("❌ No data yet.")
        return

    data = list(round_history)[-50:]
    lines = []
    for i in range(0, len(data), 10):
        chunk = data[i:i+10]
        row = " ".join([
            f"{'🔴' if m>=5 else '🟠' if m>=3 else '🟡' if m>=2 else '🟢' if m>=1.5 else '⚪'}`{m:.2f}x`"
            for m in chunk
        ])
        lines.append(row)

    msg = f"📜 *Last {len(data)} Rounds*\n\n" + "\n".join(lines) + \
          f"\n\n_🟢≥1.5  🟡≥2.0  🟠≥3.0  🔴≥5.0_"

    await update.message.reply_text(msg, parse_mode='Markdown')

async def force_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force refresh data from Betpawa"""
    await update.message.reply_chat_action("typing")
    msg = await update.message.reply_text("🔄 Refreshing data...")
    fetch_and_update_history()
    await msg.edit_text(
        f"✅ Refreshed! Now tracking `{len(round_history)}` rounds.",
        parse_mode='Markdown'
    )

# ===================== STARTUP =====================

async def startup_notification(app):
    """Send startup notification"""
    await asyncio.sleep(5)

    try:
        await app.bot.send_message(
            chat_id=YOUR_TELEGRAM_ID,
            text=(
                "🤖 *Betpawa Aviator Bot — ONLINE*\n\n"
                "✅ Connected and operational!\n"
                "🔍 Scraping Betpawa Aviator data...\n"
                "📊 Collecting initial rounds...\n\n"
                "_You will receive signals automatically within 2 minutes._\n"
                "_Send /status to check progress._"
            ),
            parse_mode='Markdown'
        )
        logger.info("Startup notification sent")
    except Exception as e:
        logger.error(f"Startup notification failed: {e}")

# ===================== MAIN =====================

def main():
    logger.info("=" * 50)
    logger.info("Betpawa Aviator Signal Bot — Starting")
    logger.info(f"Target chat ID: {YOUR_TELEGRAM_ID}")
    logger.info(f"Confidence threshold: {CONFIDENCE_THRESHOLD}")
    logger.info(f"Auto-send interval: {AUTO_SEND_INTERVAL}s")
    logger.info("=" * 50)

    # Check token
    if not BOT_TOKEN or BOT_TOKEN == "":
        logger.error("❌ BOT_TOKEN not set! Set it in Render environment variables.")
        run_health_server()
        return

    # Start health server in background thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("[*] Health server thread started")

    # Fetch initial data
    logger.info("[*] Initial data fetch...")
    fetch_and_update_history()

    # Build Telegram app
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("signal", manual_signal))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("history", show_history))
    app.add_handler(CommandHandler("refresh", force_refresh))

    # Background tasks
    if app.job_queue:
        app.job_queue.run_repeating(auto_signal_loop, interval=AUTO_SEND_INTERVAL, first=15)
        app.job_queue.run_repeating(periodic_data_refresh, interval=20, first=5)

    # Startup notification
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(startup_notification(app))
        loop.close()
    except Exception as e:
        logger.error(f"Startup notification error: {e}")

    logger.info("🤖 Bot is running. Sending signals automatically...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
