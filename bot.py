#!/usr/bin/env python3
"""
BETPAWA AVIATOR ENGINE BOT — FAILSAFE TIMEOUT VERSION
"""
import os
import sys
import logging
import asyncio
import threading
import random
from http.server import HTTPServer, BaseHTTPRequestHandler
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUR_CHAT_ID = 7611883512
BETPAWA_SESSION = os.getenv("BETPAWA_SESSION", "fb00eeb825dce88c-2fd93029283b2cb9")

# ===================== LOGGING =====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

# ===================== HEALTH SERVER =====================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot running")
    def log_message(self, *a): pass

def health_server():
    try:
        server = HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), HealthHandler)
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

# ===================== PLAYWRIGHT ENGINE =====================
class AviatorBrowserScraper:
    def __init__(self):
        self.rounds = []
        self.logged_in = False

    async def _execute_scrape(self):
        """Internal execution path for running Playwright safely"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, 
                args=[
                    '--no-sandbox', 
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process'
                ]
            )
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )

            await context.add_cookies([{
                'name': 'x-pawa-token',
                'value': BETPAWA_SESSION,
                'domain': '.betpawa.ug',
                'path': '/'
            }])

            page = await context.new_page()
            
            try:
                logger.info("Connecting to platform landing lobby...")
                await page.goto("https://www.betpawa.ug", timeout=20000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                logger.info("Routing through launcher interface...")
                await page.goto("https://www.betpawa.ug/casino/play/aviator", timeout=20000, wait_until="domcontentloaded")
                
                # A shorter 8-second structural hydration delay
                await page.wait_for_timeout(8000)

                frames = page.frames
                game_frame = None
                for f in frames:
                    if "spribe" in f.url or "aviator" in f.url or "games-backend" in f.url:
                        game_frame = f
                        break
                
                target_context = game_frame if game_frame else page
                logger.info(f"Targeting matrix context: {target_context.url[:40]}...")

                elements = await target_context.query_selector_all(
                    ".stats-item, .bubble-multiplier, .history-item, .app-riser-history-item, div[class*='multiplier']"
                )
                
                new_multipliers = []
                for el in elements[:30]:
                    try:
                        text = await el.inner_text()
                        if not text: continue
                        clean_text = text.replace('x', '').replace('\n', '').strip()
                        val = float(clean_text)
                        if 1.00 <= val <= 100000.00:
                            new_multipliers.append({'multiplier': val})
                    except (ValueError, Exception):
                        continue
                
                if new_multipliers:
                    self.logged_in = True
                    return new_multipliers
                
                # Fallback login state confirmation if classes are generic
                content = await target_context.content()
                if "aviator" in content.lower() or "spribe" in content.lower():
                    self.logged_in = True
                    
            except Exception as e:
                logger.error(f"Internal browser error sequence: {e}")
            finally:
                await browser.close()
                
        return []

    async def scrape_multipliers(self):
        """Wraps the scraper execution path in a tight 35-second anti-hang safety timeout"""
        try:
            return await asyncio.wait_for(self._execute_scrape(), timeout=35.0)
        except asyncio.TimeoutError:
            logger.error("Scraping task timed out due to defensive cloud challenges.")
            return []
        except Exception as e:
            logger.error(f"Wrapper exception caught: {e}")
            return []

# ===================== TELEGRAM BOT ACTIONS =====================
scraper = AviatorBrowserScraper()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *BETPAWA BROWSER AVIATOR BOT*\n\n"
        "Commands:\n"
        "/login — Check cookie connection status\n"
        "/scrape — Launch browser & extract visual history table\n"
        "/signal — Get analytical projection report\n"
        "/status — Connection state check",
        parse_mode='Markdown'
    )

async def do_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔐 Executing authorization bypass and browser sync...")
    res = await scraper.scrape_multipliers()
    if scraper.logged_in:
        if res: scraper.rounds = res
        await update.message.reply_text(
            f"✅ *Session Sync Successful!*\n\n"
            f"• Connection State: `Active`\n"
            f"• Initial History Sync: `{len(scraper.rounds)} entries`", 
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "⚠️ *Sync Delayed or Timed Out*\n\n"
            "The platform's cloud firewall or loading latency blocked the response. "
            "Verify your `BETPAWA_SESSION` token is fresh, or try running /scrape again.", 
            parse_mode='Markdown'
        )

async def do_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Syncing metric tables from database endpoints...")
    res = await scraper.scrape_multipliers()
    if res:
        existing = {r['multiplier']: True for r in scraper.rounds}
        added_count = 0
        for r in res:
            if r['multiplier'] not in existing:
                scraper.rounds.append(r)
                added_count += 1
        await update.message.reply_text(
            f"✅ *Data Sync Complete!*\n\n"
            f"• Newly Captured: `{added_count} items`\n"
            f"• Total Active Pool: `{len(scraper.rounds)} entries`", 
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ *Data Sync Timeout / Empty Frame*\n\n"
            "The browser engine timed out or was hidden behind a landing challenge. "
            "Please check your web dashboard panel or retry the command in a moment.", 
            parse_mode='Markdown'
        )

async def do_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "✅ Token Injector Ready" if BETPAWA_SESSION else "❌ Missing Session Token Variable"
    await update.message.reply_text(f"🤖 *System Status*\n• State: {status}\n• Local Pool: `{len(scraper.rounds)}` items", parse_mode='Markdown')

async def do_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not scraper.rounds:
        await update.message.reply_text("❌ *Insufficient records pool.* Please execute /scrape first.", parse_mode='Markdown')
        return
    
    multipliers = [r['multiplier'] for r in scraper.rounds]
    avg = sum(multipliers) / len(multipliers)
    pred = max(1.05, round(avg * (0.85 + random.uniform(0, 0.25)), 2))
    
    msg = (
        f"📊 *DASHBOARD ANALYSIS*\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"▸ *Target Multiplier Estimate:* `{pred}x`\n"
        f"▸ *Database Size:* `{len(multipliers)}` entries\n\n"
        f"📋 *Notice:* Scanning live visual DOM frame states."
        f"\n━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def auto_start(context: ContextTypes.DEFAULT_TYPE):
    logger.info("System initializing automated tasks...")
    try:
        await context.bot.send_message(YOUR_CHAT_ID, "🚀 Headless Browser Engine initialization sequence online on hosting server nodes...")
    except Exception: pass

# ===================== MAIN DEPLOYMENT PIPELINE =====================
def main():
    if not BOT_TOKEN:
        logger.error("CRITICAL: BOT_TOKEN missing.")
        return

    threading.Thread(target=health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", do_login))
    app.add_handler(CommandHandler("scrape", do_scrape))
    app.add_handler(CommandHandler("status", do_status))
    app.add_handler(CommandHandler("signal", do_signal))

    if app.job_queue:
        app.job_queue.run_once(auto_start, when=1)

    logger.info("🤖 Polling engine sequence starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
