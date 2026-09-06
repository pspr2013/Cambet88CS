import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, ADMIN_USER_ID, FAQ_FILE_PATH, PORT
from faq_manager import FAQManager
from web_keepalive import start_web_server

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.warning("BOT_TOKEN is missing! Bot will crash if not set in .env")

try:
    bot = Bot(token=BOT_TOKEN or "dummy_token")
except Exception as e:
    logger.error(f"Error initializing bot: {e}")
    bot = None

dp = Dispatcher()
faq_manager = FAQManager(FAQ_FILE_PATH)

def get_categories_keyboard():
    categories = faq_manager.get_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "Welcome to the FAQ Bot! Ask me a question, or use /faq to browse topics.",
        reply_markup=get_categories_keyboard()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "Just send me your question and I'll try my best to answer it!\n"
        "Commands:\n"
        "/start - Welcome message\n"
        "/help - Show this help\n"
        "/faq - Browse FAQ categories\n"
    )
    if message.from_user.id == ADMIN_USER_ID:
        help_text += "/reload - Reload FAQ data from Excel"
    await message.answer(help_text)

@dp.message(Command("faq"))
async def cmd_faq(message: types.Message):
    await message.answer("Please choose a category:", reply_markup=get_categories_keyboard())

@dp.message(Command("reload"))
async def cmd_reload(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("You are not authorized to use this command.")
        return
    
    success = faq_manager.load_data()
    if success:
        await message.answer("FAQ data reloaded successfully!")
    else:
        await message.answer("Failed to reload FAQ data. Check logs.")

@dp.callback_query(F.data.startswith("cat_"))
async def process_category_callback(callback_query: types.CallbackQuery):
    category = callback_query.data[4:]
    questions = faq_manager.get_questions_by_category(category)
    if not questions:
        await callback_query.message.answer("No questions found for this category.")
    else:
        text = f"<b>{category} FAQs:</b>\n\n"
        for i, q in enumerate(questions, 1):
            text += f"{i}. {q}\n"
        await callback_query.message.answer(text, parse_mode="HTML")
    await callback_query.answer()

# --- NEW: ADMIN REPLY HANDLER ---
# This listens for the Admin replying to a forwarded message
@dp.message(F.reply_to_message & (F.from_user.id == ADMIN_USER_ID))
async def admin_reply_handler(message: types.Message):
    replied_text = message.reply_to_message.text or ""
    
    # Extract the User ID from the text the admin replied to
    match = re.search(r"ID:\s*(\d+)", replied_text)
    if match:
        user_id = int(match.group(1))
        try:
            # Send the admin's answer to the customer
            await bot.send_message(
                user_id, 
                f"👨‍💻 <b>Message from Admin:</b>\n\n{message.text}", 
                parse_mode="HTML"
            )
            await message.answer("✅ Your reply was successfully sent to the customer!")
        except Exception as e:
            await message.answer(f"❌ Failed to send message. They might have blocked the bot. Error: {e}")
    else:
        await message.answer("❌ Could not find the User ID. Make sure you are replying to a log message that contains 'ID: 12345678'.")

# --- CUSTOMER QUESTION HANDLER ---
@dp.message(F.text)
async def process_question(message: types.Message):
    # Don't process normal text from the admin as a FAQ question to avoid spamming the admin with their own logs
    if message.from_user.id == ADMIN_USER_ID:
        return

    user_text = message.text
    answer = faq_manager.find_answer(user_text)
    
    if answer:
        await message.answer(str(answer), parse_mode="HTML")
        bot_response_summary = "✅ Answered automatically."
    else:
        await message.answer(
            "I couldn't find an exact match for your question, but I have forwarded it to an admin!\n\nHere are some topics you can explore in the meantime:",
            reply_markup=get_categories_keyboard()
        )
        bot_response_summary = "❌ No match (needs human reply)."
        
    # Send the log to the Admin so they can reply
    username = f"@{message.from_user.username}" if message.from_user.username else "No username"
    admin_log = (
        f"🚨 <b>NEW CUSTOMER QUESTION</b>\n"
        f"👤 <b>User:</b> {message.from_user.full_name} ({username})\n"
        f"🆔 <b>ID:</b> {message.from_user.id}\n"
        f"💬 <b>Asked:</b> {user_text}\n"
        f"🤖 <b>Bot Action:</b> {bot_response_summary}\n\n"
        f"<i>(Swipe left / Reply directly to this message to answer the customer!)</i>"
    )
    try:
        await bot.send_message(ADMIN_USER_ID, admin_log, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Could not send log to admin: {e}")

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing. Cannot start polling.")
        return

    await start_web_server(PORT)
    asyncio.create_task(faq_manager.auto_reload_task())
    
    logger.info("Bot is starting...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if BOT_TOKEN:
        asyncio.run(main())
    else:
        print("Please configure your .env file with a valid BOT_TOKEN")