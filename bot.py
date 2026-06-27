#!/usr/bin/env python3
"""
Betpawa Aviator Signal Bot — Fully Automatic
Sends prediction signals directly to your Telegram.
Deployed on Render with health check server.
"""
import asyncio
import logging
import time
import random
import json
import numpy as np
import os
import threading
import sys
from datetime import datetime
from typing import List, Dict, Optional
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

# WebSocket thread control
ws_thread = None
ws_running = False

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

# ===================== CALLBACKS =====================
def on_round_end(round_data: Dict):
    """Called when WebSocket receives a crash event"""
    multiplier = round_data.get("multiplier", 0)
    if multiplier > 0:
        round_history.append(multiplier)
        logger.info(f"New round via WS: {multiplier:.2f}x (total: {len(round_history)})")

# ===================== CORE FUNCTIONS =====================
def fetch_and_update_history():
    """Fetch latest round history from Betpawa"""
    global round_history
    try:
        rounds = scraper.fetch_round_history()
        if rounds:
            # Add to buffer in chronological order if scraper returns newest last
            for r in reversed(rounds):
                m = r.get("multiplier", 0)
                if m > 0 and m not in round_history:
                    round_history.append(m)
            logger.info(f"Fetched {len(rounds)} rounds from Betpawa. Total: {len(round_history)}")
        else:
            logger.warning("No rounds fetched from Betpawa")
    except Exception as e:
        logger.error(f"Fetch error: {e}")

def start_websocket():
    """Start WebSocket listener in background thread"""
    global ws_thread, ws_running

    def ws_loop():
        global ws_running
        ws_running = True
        while ws_running:
            try:
                ws = scraper.connect_websocket(on_round_end=on_round_end)
                if ws:
                    ws.run_forever()
                else:
                    time.sleep(10)
            except Exception as e:
                logger.error(f"WS error: {e}")
                time.sleep(10)

    ws_thread = threading.Thread(target=ws_loop, daemon=True)
    ws_thread.start()
    logger.info("[*] WebSocket thread started")

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
    """Format signal for Telegram message with a structured grid table"""
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

    # Custom probability range calculation requested by user for UI display
    prob_min = max(90.0, min(99.9, conf * 100 + 40))
    prob_max = max(95.0, min(99.9, conf * 100 + 49))
    prob_range_str = f"{prob_min:.1f}% - {prob_max:.1f}%"

    msg = (
        f"{emoji} *BARON MILLION-AI SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"▸ *Signal:* `{s}`\n"
        f"▸ *Prediction:* `{pred_str}`\n"
        f"▸ *Probability:* `{prob_range_str}`\n"
        f"▸ *Suggested Cashout:* `{cash_str}`\n"
        f"▸ *Models Engaged:* `{models}/3`\n\n"
        f"📋 *Analysis:* _{reason}_\n"
    )

    if stats:
        # Fixed the nested formatting expressions here to avoid escaping quotes
        high_str = f"{stats.get('high_streak', 0)}/10"
        low_str = f"{stats.get('low_streak', 0)}/10"
        mean_val = f"{stats.get('mean_20', 'N/A')}"
        std_val = f"{stats.get('std_20', 'N/A')}"

        msg += (
            f"\n📊 *20-Round Metrics Table:*\n"
            f"```\n"
            f"┌────────────────────┬───────────┐\n"
            f"│ Metric             │ Value     │\n"
            f"├────────────────────┼───────────┤\n"
            f"│ 20-Round Mean      │ {mean_val:<9} │\n"
            f"│ 20-Round Std Dev   │ {std_val:<9} │\n"
            f"│ High Streak (10r)  │ {high_str:<9} │\n"
            f"│ Low Streak (10r)   │ {low_str:<9} │\n"
            f"└────────────────────┴───────────┘\n"
            f"```\n"
        )

    last_10 = list(round_history)[-10:]
    history_str = "  ".join([f"{m:.1f}x" for m in last_10]) if last_10 else "No data"
    
    msg += (
        f"📈 *Last 10 Rounds:*\n"
        f"`{history_str}`\n\n"
        f"🔄 Total Database Rounds: `{len(round_history)}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"_⚠️ Statistical analysis output based on pattern parameters._"
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
        logger.info(f"Sent automatic signal: {signal['signal']}")
    except Exception as e:
        logger.error(f"Failed to send automatic message: {e}")

async def auto_signal_loop(context: ContextTypes.DEFAULT_TYPE):
    """Background task that runs every AUTO_SEND_INTERVAL seconds"""
    if len(round_history) < 20:
        return

    fetch_and_update_history()
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
    """Refresh history data periodically and manage dynamic training"""
    fetch_and_update_history()

    if len(round_history) >= 50 and not predictor.is_trained:
        logger.info("Initializing background auto-training...")
        predictor.train(list(round_history), epochs=30)
        predictor.save()

# ===================== COMMANDS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🤖 *BARON MILLION-AI Core Online*\n\n"
        "✅ Service actively initialized!\n"
        f"• Direct routing target: `{YOUR_TELEGRAM_ID}`\n"
        f"• Operational confidence ceiling: `{CONFIDENCE_THRESHOLD:.0%}`\n"
        f"• Execution scan window: `{AUTO_SEND_INTERVAL}s`\n"
        f"• Registered baseline data: `{len(round_history)}` seeds\n\n"
        "*Available Operations:*\n"
        "/signal — Force instantly computed signal manual override\n"
        "/status — Fetch engine diagnostics & parameter telemetry\n"
        "/history — Print current in-memory data tables\n"
        "/train — Force instant runtime recalculation and training profile save\n"
        "/refresh — Manually execute DOM parser cycle",
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
    """Show bot engine state status"""
    signal = generate_signal()
    last_signal = signal.get("signal", "N/A")
    last_pred = signal.get("prediction", "N/A")
    last_conf = signal.get("confidence", 0)

    status_msg = (
        f"🤖 *BARON MILLION-AI Engine Diagnostics*\n\n"
        f"🟢 *System Integration:*\n"
        f"• Memory Buffers: `{len(round_history)}/500 entries`\n"
        f"• Model State: `{'✅ Functional Profile Loaded' if predictor.is_trained else '❌ Awaiting Dataset Baseline'}`\n"
        f"• Background Loop: `✅ Polling Active`\n"
        f"• Interval Velocity: `{AUTO_SEND_INTERVAL}s`\n\n"
        f"📡 *Target Parameters:*\n"
        f"• Gateway Domain: `{scraper.active_domain}`\n"
        f"• Node Endpoint: `{scraper.active_game_path}`\n\n"
        f"🔮 *Latest Diagnostic Pipeline:*\n"
        f"• Last Flag: `{last_signal}`\n"
        f"• Expected Core Target: `{last_pred}x`\n"
        f"• Engine Stability Metric: `{last_conf:.1%}`\n\n"
        f"_Destination Chat ID: {YOUR_TELEGRAM_ID}_"
    )
    await update.message.reply_text(status_msg, parse_mode='Markdown')

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent complete dataset history array"""
    if not round_history:
        await update.message.reply_text("❌ Database collection profile currently empty.")
        return
        
    history_snapshot = list(round_history)[-30:]
    history_lines = []
    for i in range(0, len(history_snapshot), 5):
        chunk = history_snapshot[i:i+5]
        history_lines.append("  |  ".join([f"{x:.2f}x" for x in chunk]))
        
    formatted_snapshot = "\n".join(history_lines)
    await update.message.reply_text(
        f"📊 *Latest 30 Recorded Engine Seeds:*\n\n`{formatted_snapshot}`",
        parse_mode='Markdown'
    )

async def force_train(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force instant training calculation profile execution via /train"""
    await update.message.reply_text("⚙️ *Starting manual optimization recalculation loop...*", parse_mode='Markdown')
    if len(round_history) < 25:
        await update.message.reply_text(f"❌ Aborted: Insufficient historical nodes. (Need >= 25, has {len(round_history)})")
        return
        
    success = predictor.train(list(round_history), epochs=45)
    if success:
        predictor.save()
        await update.message.reply_text("✅ *Recalculation absolute. Math array profiles rewritten and committed.*", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ *Recalculation logic error occurred during modeling sequence.*", parse_mode='Markdown')

async def force_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually parse raw pages via /refresh"""
    await update.message.reply_text("📡 *Executing forced scrape tracking cycle...*", parse_mode='Markdown')
    before_count = len(round_history)
    fetch_and_update_history()
    after_count = len(round_history)
    await update.message.reply_text(f"✅ Parser loop ran. Network tracking updated. Captured `{after_count - before_count}` new data seeds.")

# ===================== MAIN APPLICATION INITIALIZATION =====================
def main():
    if not BOT_TOKEN:
        logger.critical("FATAL error: BOT_TOKEN is missing or not provided to application profile.")
        sys.exit(1)

    # Boot initialization operations
    logger.info("[*] Bootstrapping operational baseline storage data elements...")
    fetch_and_update_history()
    
    # Try loading existing models right away
    predictor.load()

    # Launch Web Server inside daemon framework container for Render integration compliance
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # Establish WebSockets
    start_websocket()

    # Build Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Routing Configuration Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signal", manual_signal))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("history", show_history))
    application.add_handler(CommandHandler("train", force_train))
    application.add_handler(CommandHandler("refresh", force_refresh))

    # Job Queue Setup for Automated Intervals
    job_queue = application.job_queue
    # Continuous calculation analysis interval
    job_queue.run_repeating(auto_signal_loop, interval=AUTO_SEND_INTERVAL, first=5)
    # Background scraping fallback interval sync
    job_queue.run_repeating(periodic_data_refresh, interval=60, first=10)

    # Block run loop execution
    logger.info("🚀 BARON MILLION-AI Telegram Interface Engine Deploying Successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
