import os

# This forces the code to ONLY use the token from Render's Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
GOOGLE_SHEET_URL = os.getenv("GOOGLE_SHEET_URL")
PORT = int(os.getenv("PORT", 8080))
