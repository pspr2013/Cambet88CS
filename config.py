import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", 0))
FAQ_FILE_PATH = os.getenv("FAQ_FILE_PATH", "faq.xlsx")
PORT = int(os.getenv("PORT", 8080))
