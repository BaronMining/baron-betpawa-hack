import os

# ===================== TELEGRAM =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Set in Render dashboard
YOUR_TELEGRAM_ID = int(os.getenv("TELEGRAM_ID", "7611883512"))

# ===================== BETPAWA LOGIN =====================
BETPAWA_USERNAME = os.getenv("BETPAWA_USERNAME", "")
BETPAWA_PASSWORD = os.getenv("BETPAWA_PASSWORD", "")

# ===================== BETPAWA DOMAINS =====================
BETPAWA_DOMAINS = [
    "https://www.betpawa.ug",
    "https://www.betpawa.mw",
    "https://www.betpawa.rw",
    "https://www.betpawa.co.ke",
]

GAME_PATHS = [
    "/casino/game/aviator",
    "/games/game/aviator",
    "/aviator-crash-game",
]

# ===================== PREDICTION =====================
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.55"))
AUTO_SEND_INTERVAL = int(os.getenv("AUTO_SEND_INTERVAL", "12"))

# ===================== USER AGENTS =====================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.6422.80 Mobile/15E148 Safari/604.1",
]

BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}
