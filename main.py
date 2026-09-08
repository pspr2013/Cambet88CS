import asyncio
import logging
import re
import os
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, ADMIN_USER_ID, GOOGLE_SHEET_URL, PORT
from faq_manager import FAQManager
from web_keepalive import start_web_server

# 👇 PASTE YOUR GOOGLE WEB APP URL HERE 👇
GOOGLE_APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbzKtvqmCTVU9J4L2D0_oYyqTINIDilNnKzRh3iNJsqrEmRAYRodKMJpaZRtXOghM56w/exec"


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
faq_manager = FAQManager(GOOGLE_SHEET_URL)

# --- FEATURE: SAVE USER TO GOOGLE SHEETS ---
async def save_user(user_id):
    if GOOGLE_APPS_SCRIPT_URL == "https://script.google.com/macros/s/AKfycbzKtvqmCTVU9J4L2D0_oYyqTINIDilNnKzRh3iNJsqrEmRAYRodKMJpaZRtXOghM56w/exec":
        return 
    try:
        url = f"{GOOGLE_APPS_SCRIPT_URL}?user_id={user_id}&action=save"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.text() 
                logger.info(f"Save User Result: {result}") # This will show in Render Logs!
    except Exception as e:
        logger.error(f"Failed to save user: {e}")

# --- FEATURE: REMOVE BLOCKED USER FROM GOOGLE SHEETS ---
async def remove_user(user_id):
    if GOOGLE_APPS_SCRIPT_URL == "https://script.google.com/macros/s/AKfycbzKtvqmCTVU9J4L2D0_oYyqTINIDilNnKzRh3iNJsqrEmRAYRodKMJpaZRtXOghM56w/exec":
        return 
    try:
        url = f"{GOOGLE_APPS_SCRIPT_URL}?user_id={user_id}&action=delete"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.text()
                logger.info(f"Delete User Result: {result}")
    except Exception as e:
        logger.error(f"Failed to delete user: {e}")


def get_categories_keyboard():
    categories = faq_manager.get_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- FEATURE: WELCOME IMAGE ---
WELCOME_IMAGE_URL = "https://images.unsplash.com/photo-1556761175-5973dc0f32b7?q=80&w=1000&auto=format&fit=crop"

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await save_user(message.from_user.id) # Forced to wait for Google!
    
    welcome_text = (
        "👋 <b>Welcome to our Customer Support Bot!</b>\n\n"
        "How can we help you today? You can type your question below, or use the buttons to browse our FAQ topics."
    )
    try:
        await message.answer_photo(
            photo=WELCOME_IMAGE_URL,
            caption=welcome_text,
            reply_markup=get_categories_keyboard(),
            parse_mode="HTML"
        )
    except:
        await message.answer(welcome_text, reply_markup=get_categories_keyboard(), parse_mode="HTML")


# --- FEATURE: BROADCAST FROM GOOGLE SHEETS ---
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
        
    raw_text = message.text or message.caption or ""
    clean_text = raw_text.replace("/broadcast", "").strip()
    
    if not clean_text and not message.photo and not message.video:
        await message.answer("⚠️ Please provide a message or attach a picture. Example:\n`/broadcast We have a sale today!`", parse_mode="Markdown")
        return

    await message.answer("🔄 Fetching customer list from your Google Sheet...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GOOGLE_APPS_SCRIPT_URL) as response:
                text_data = await response.text()
                
        if not text_data.strip():
            known_users = []
        else:
            known_users = [int(x) for x in text_data.split(",") if x.strip().isdigit()]
    except Exception as e:
        await message.answer(f"❌ Failed to fetch users from Google Sheets: {e}")
        return
        
    if not known_users:
        await message.answer("⚠️ No customers found in the Google Sheet yet!")
        return
        
    await message.answer(f"🚀 Starting broadcast to {len(known_users)} customers...")
    success = 0
    
    for uid in known_users:
        try:
            if message.photo:
                await bot.send_photo(uid, photo=message.photo[-1].file_id, caption=clean_text, parse_mode="HTML")
            elif message.video:
                await bot.send_video(uid, video=message.video.file_id, caption=clean_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, clean_text, parse_mode="HTML")
                
            success += 1
            await asyncio.sleep(0.1)
        except Exception:
            await remove_user(uid)
            
    await message.answer(f"✅ Broadcast finished! Successfully sent to {success} out of {len(known_users)} customers.\n*(Any customers who blocked the bot have been automatically removed from your list).*")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await save_user(message.from_user.id)
    help_text = (
        "Just send me your question and I'll try my best to answer it!\n"
        "Commands:\n"
        "/start - Welcome message\n"
        "/faq - Browse FAQ categories\n"
    )
    if message.from_user.id == ADMIN_USER_ID:
        help_text += "\n<b>Admin Commands:</b>\n/reload - Reload FAQ data\n/broadcast [msg] - Message all users"
    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("faq"))
async def cmd_faq(message: types.Message):
    await save_user(message.from_user.id)
    await message.answer("Please choose a category:", reply_markup=get_categories_keyboard())

@dp.message(Command("reload"))
async def cmd_reload(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    success = faq_manager.load_data()
    if success:
        await message.answer("✅ FAQ data reloaded successfully!")
    else:
        await message.answer("❌ Failed to reload FAQ data. Check logs.")

# --- FEATURE: DIRECT ANSWER ON CATEGORY CLICK ---
@dp.callback_query(F.data.startswith("cat_"))
async def process_category_callback(callback_query: types.CallbackQuery):
    await save_user(callback_query.from_user.id)
    category = callback_query.data[4:]
    
    match_data = faq_manager.find_answer(category)
    
    if match_data:
        answer_text = match_data["answer"]
        image_url = match_data["image_url"]
        try:
            if image_url and image_url.startswith("http"):
                await callback_query.message.answer_photo(photo=image_url, caption=answer_text, parse_mode="HTML")
            else:
                await callback_query.message.answer(answer_text, parse_mode="HTML")
        except Exception:
            await callback_query.message.answer(answer_text, parse_mode="HTML")
    else:
        await callback_query.message.answer("សូមបងរងចាំបន្តិច", parse_mode="HTML")
        
    await callback_query.answer()


@dp.message(F.reply_to_message & (F.from_user.id == ADMIN_USER_ID))
async def admin_reply_handler(message: types.Message):
    replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
    user_match = re.search(r"ID:\s*(\d+)", replied_text)
    msg_match = re.search(r"MsgID:\s*(\d+)", replied_text)
    
    if user_match:
        user_id = int(user_match.group(1))
        reply_to_message_id = None
        if msg_match:
            reply_to_message_id = int(msg_match.group(1))
            
        try:
            await message.copy_to(chat_id=user_id, reply_to_message_id=reply_to_message_id)
            await message.answer("✅ Your reply was successfully sent!")
        except Exception as e:
            await message.answer(f"❌ Failed to send message. Error: {e}")
    else:
        await message.answer("❌ Could not find the User ID. Make sure you are replying to a log message.")


# --- CUSTOMER QUESTION HANDLER ---
@dp.message(F.text)
async def process_question(message: types.Message):
    if message.from_user.id == ADMIN_USER_ID:
        return

    await save_user(message.from_user.id) 
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    await asyncio.sleep(0.5)

    user_text = message.text
    match_data = faq_manager.find_answer(user_text)
    
    if match_data:
        answer_text = match_data["answer"]
        image_url = match_data["image_url"]
        try:
            if image_url and image_url.startswith("http"):
                await message.answer_photo(photo=image_url, caption=answer_text, parse_mode="HTML")
                bot_response_summary = f"✅ Answered with Image:\n💬 {answer_text}"
            else:
                await message.answer(answer_text, parse_mode="HTML")
                bot_response_summary = f"✅ Answered automatically with:\n💬 {answer_text}"
        except Exception:
            await message.answer(answer_text, parse_mode="HTML")
            bot_response_summary = f"✅ Answered automatically (Image failed to load)"
    else:
        await message.answer("សូមបងរងចាំបន្តិច")
        bot_response_summary = "❌ No match (needs human reply)."
        
    username = f"@{message.from_user.username}" if message.from_user.username else "No username"
    admin_log = (
        f"🚨 <b>NEW CUSTOMER QUESTION</b>\n"
        f"👤 <b>User:</b> {message.from_user.full_name} ({username})\n"
        f"🆔 <b>ID:</b> {message.from_user.id}\n"
        f"📝 <b>MsgID:</b> {message.message_id}\n"
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