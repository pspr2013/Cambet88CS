import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

# We removed the 'int()' part so commas won't crash the bot!
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "0") 

GOOGLE_SHEET_URL = os.getenv("GOOGLE_SHEET_URL")
PORT = int(os.getenv("PORT", "8080"))