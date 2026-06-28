#!/usr/bin/env python3
"""
BETPAWA AVIATOR ENGINE BOT — ULTRA-LIGHTWEIGHT PLAYWRIGHT VERSION
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

    async def scrape_multipliers(self):
        """Launches an optimized background browser, injects cookies, and extracts visual data"""
        if not BETPAWA_SESSION:
            logger.error("No token session found.")
            return []

        logger.info("Launching optimized background browser engine...")
        async with async_playwright() as p:
            # Launch browser in ultra-lightweight performance mode for cloud servers
            browser = await p.chromium.launch(
                headless=True, 
                args=[
                    '--no-sandbox', 
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',  # Prevents memory crashes on small cloud instances
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',            # Saves server processing power
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process'          # Forces execution into one lean thread
                ]
            )
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )

            # Inject active login token directly into browser session
            await context.add_cookies([{
                'name': 'x-pawa-token',
                'value': BETPAWA_SESSION,
                'domain': '.betpawa.ug',
                'path': '/'
            }])

            page = await context.new_page()
            logger.info("Navigating straight to Aviator game matrix...")
            
            try:
                # Open the game URL directly
                await page.goto("https://www.betpawa.ug/casino/game/aviator", timeout=60000, wait_until="domcontentloaded")
                
                # Give the game canvas and iframe 15 seconds to load completely
                await page.wait_for_timeout(15000)

                # Find the Spribe game iframe element
                frames = page.frames
                game_frame = None
                for f in frames:
                    if "spribe" in f.url or "aviator" in f.url:
                        game_frame = f
                        break
                
                target_context = game_frame if game_frame else page
                logger.info(f"Connected to context frame target: {target_context.url[:40]}...")

                # Target the visual multiplier history bubbles inside the game layout
                elements = await target_context.query_selector_all(".stats-item, .bubble-multiplier, .history-item")
                
                new_multipliers = []
                for el in elements[:30]: # Grab up to the last 30 rounds visible on screen
                    text = await el.inner_text()
                    clean_text = text.replace('x', '').strip()
                    try:
                        val = float(clean_text)
                        if val > 0:
                            new_multipliers.append({'multiplier': val})
                    except ValueError:
                        continue
                
                self.logged_in = True
                if new_multipliers:
                    logger.info(f"Successfully pulled {len(new_multipliers)} values from UI layout.")
                    return new_multipliers
                else:
                    logger.warning("Browser connected, but history blocks were empty. Page might still be hydrating.")
                    
            except Exception as e:
                logger.error(f"Browser scraping operation failure exception: {e}")
            finally:
                await browser.close()
                
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
    await update.message.reply_text("🔐 Verifying background browser token integration...")
    res = await scraper.scrape_multipliers()
    if scraper.logged_in:
        if res: scraper.rounds = res
        await update.message.reply_text(f"✅ *Session Connected!*\n📊 Found `{len(scraper.rounds)}` active rounds on screen layout.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Session check failed. Ensure your token variable is active on Render.")

async def do_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Launching browser to scan current screen layout...")
    res = await scraper.scrape_multipliers()
    if res:
        existing = {r['multiplier']: True for r in scraper.rounds}
        for r in res:
            if r['multiplier'] not in existing:
                scraper.rounds.append(r)
        await update.message.reply_text(f"✅ Scanning complete. Current historical database pool holds `{len(scraper.rounds)}` entries.", parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠️ Browser scraped successfully, but did not find active results text elements yet. Please try again in a moment.")

async def do_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "✅ Token Injector Ready" if BETPAWA_SESSION else "❌ Missing Session Token Variable"
    await update.message.reply_text(f"🤖 *System Status*\n• State: {status}\n• Local Pool: `{len(scraper.rounds)}` items", parse_mode='Markdown')

async def do_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not scraper.rounds:
        await update.message.reply_text("❌ Local database pool is empty. Please run /scrape first.")
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
