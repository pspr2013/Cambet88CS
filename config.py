import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))
# Replaced local file with Google Sheet URL:
GOOGLE_SHEET_URL = os.getenv("GOOGLE_SHEET_URL", "")
PORT = int(os.getenv("PORT", 8080))