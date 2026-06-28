import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUR_TELEGRAM_ID = 7611883512
BETPAWA_USERNAME = os.getenv("BETPAWA_USERNAME", "")
BETPAWA_PASSWORD = os.getenv("BETPAWA_PASSWORD", "")
CONFIDENCE_THRESHOLD = 0.25
AUTO_SEND_INTERVAL = 60  # seconds

# Betpawa URLs
BETPAWA_BASE_URL = "https://www.betpawa.ug"
BETPAWA_LOGIN_URL = "https://www.betpawa.ug/api/v2/auth/login"
BETPAWA_AVIATOR_URL = "https://www.betpawa.ug/casino/game/aviator"
BETPAWA_GAME_HISTORY_URL = "https://www.betpawa.ug/api/v2/game/aviator/history"
BETPAWA_SEED_INFO_URL = "https://www.betpawa.ug/api/v2/game/aviator/seed-info"
