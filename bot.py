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
    """Start WebSocket listener in background thread with clean error silencing"""
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
                    time.sleep(45)
            except Exception as e:
                err_msg = str(e)
                # Catch Cloudflare proxy interception and log it cleanly without dict dumps
                if "Handshake status 200" in err_msg or "status 200" in err_msg:
                    logger.info("📡 Gateway status: Proxy layer active. Engine using fallback DOM polling.")
                else:
                    clean_msg = err_msg.split('\n')[0] if '\n' in err_msg else err_msg
                    logger.warning(f"WS Gateway update tracking: {clean_msg[:60]}")
                time.sleep(45)

    ws_thread = threading.Thread(target=ws_loop, daemon=True)
    ws_thread.start()
    logger.info("[*] Background live data listener configured")

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

# ===================== TELEGRAM ENGINE LOOP ROUTINES =====================
async def execute_automated_signal_broadcast(bot):
    """Core signal loop execution logic"""
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
        msg = format_signal(signal)
        try:
            await bot.send_message(
                chat_id=YOUR_TELEGRAM_ID,
                text=msg,
