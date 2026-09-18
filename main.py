import asyncio
import logging
import re
import os
import time 
import aiohttp
import html 
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter

from config import BOT_TOKEN, ADMIN_USER_ID, GOOGLE_SHEET_URL, PORT
from faq_manager import FAQManager
from web_keepalive import start_web_server

# 👇 NOW FETCHES FROM RENDER ENVIRONMENT VARIABLES 👇
GOOGLE_APPS_SCRIPT_URL = os.getenv("GOOGLE_APPS_SCRIPT_URL", "")

# --- SUPPORT MULTIPLE ADMINS & GROUP CHATS ---
raw_admins = os.getenv("ADMIN_USER_ID", str(ADMIN_USER_ID))
ADMIN_IDS = [int(x.strip()) for x in str(raw_admins).split(",") if x.strip().lstrip('-').isdigit()]

# --- FEATURE: BANNED USERS ---
raw_banned = os.getenv("BANNED_USERS", "")
BANNED_IDS = [int(x.strip()) for x in str(raw_banned).split(",") if x.strip().lstrip('-').isdigit()]

def is_banned(user_id):
    return user_id in BANNED_IDS

def is_admin(message: types.Message):
    """Checks if the command comes from an Admin DM or the authorized Staff Group"""
    return message.chat.id in ADMIN_IDS or message.from_user.id in ADMIN_IDS

# --- CUSTOMER SPAM SHIELD ---
user_last_message_time = {}
SPAM_COOLDOWN_SECONDS = 1.5  

def is_spam(message: types.Message):
    if is_admin(message): return False
    if message.media_group_id: return False
        
    current_time = time.time()
    user_id = message.from_user.id
    
    if user_id in user_last_message_time:
        if current_time - user_last_message_time[user_id] < SPAM_COOLDOWN_SECONDS:
            user_last_message_time[user_id] = current_time
            return True
            
    user_last_message_time[user_id] = current_time
    return False

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

async def save_user(user_id):
    if not GOOGLE_APPS_SCRIPT_URL: return
    try:
        url = f"{GOOGLE_APPS_SCRIPT_URL}?user_id={user_id}&action=save"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                await response.text() 
    except Exception:
        pass

async def remove_user(user_id):
    if not GOOGLE_APPS_SCRIPT_URL: return
    try:
        url = f"{GOOGLE_APPS_SCRIPT_URL}?user_id={user_id}&action=delete"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                await response.text()
    except Exception:
        pass

def get_categories_keyboard():
    categories = faq_manager.get_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")]])

@dp.callback_query(F.data == "back_to_menu")
async def process_back_menu(callback_query: types.CallbackQuery):
    if callback_query.message.chat.type != "private": return
    if is_banned(callback_query.from_user.id): return
    
    await save_user(callback_query.from_user.id)
    await callback_query.message.answer("សូមជ្រើសរើស:", reply_markup=get_categories_keyboard())
    await callback_query.answer()

WELCOME_IMAGE_URL = "https://images.unsplash.com/photo-1556761175-5973dc0f32b7?q=80&w=1000&auto=format&fit=crop"

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    
    await save_user(message.from_user.id) 
    
    welcome_text = "👋 <b>សូមស្វាគមន៍មកកាន់ ផ្នែកបំរើអតិថិជន! បើបងមានសំណួរអ្វីក្រៅពីចំណុចខាងក្រោម បងអាចផ្ញើសារជាអក្សរក្នុងប្រអប់ខាងក្រោមបាន!</b>"
    try:
        await message.answer_photo(photo=WELCOME_IMAGE_URL, caption=welcome_text, reply_markup=get_categories_keyboard(), parse_mode="HTML")
    except:
        await message.answer(welcome_text, reply_markup=get_categories_keyboard(), parse_mode="HTML")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if not is_admin(message): return
    if not GOOGLE_APPS_SCRIPT_URL:
        await message.answer("⚠️ GOOGLE_APPS_SCRIPT_URL is not set in Render!")
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
        if is_banned(uid): 
            continue
            
        try:
            if message.photo:
                await bot.send_photo(uid, photo=message.photo[-1].file_id, caption=clean_text, parse_mode="HTML")
            elif message.video:
                await bot.send_video(uid, video=message.video.file_id, caption=clean_text, parse_mode="HTML")
            else:
                await bot.send_message(uid, clean_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
                
            success += 1
            await asyncio.sleep(0.1)
            
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            await remove_user(uid)
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if "chat not found" in error_msg or "user is deactivated" in error_msg:
                await remove_user(uid)
        except Exception:
            pass 
            
    await message.answer(f"✅ Broadcast finished! Successfully sent to {success} out of {len(known_users)} customers.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    
    await save_user(message.from_user.id)
    help_text = "Just send me your question and I'll try my best to answer it!\nCommands:\n/start - Welcome message\n/faq - Browse FAQ categories\n"
    if is_admin(message):
        help_text += "\n<b>Admin Commands:</b>\n/reload - Reload FAQ data\n/broadcast [msg] - Message all users"
    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("faq"))
async def cmd_faq(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    
    await save_user(message.from_user.id)
    await message.answer("សូមជ្រើសរើស:", reply_markup=get_categories_keyboard())

@dp.message(Command("reload"))
async def cmd_reload(message: types.Message):
    if not is_admin(message): return
    success = faq_manager.load_data()
    if success:
        await message.answer("✅ FAQ data reloaded successfully!")
    else:
        await message.answer("❌ Failed to reload FAQ data. Check logs.")

@dp.callback_query(F.data.startswith("cat_"))
async def process_category_callback(callback_query: types.CallbackQuery):
    if callback_query.message.chat.type != "private": return
    if is_banned(callback_query.from_user.id): return
    
    await save_user(callback_query.from_user.id)
    category = callback_query.data[4:]
    match_data = faq_manager.find_answer(category)
    
    if match_data:
        answer_text = match_data["answer"]
        image_url = match_data["image_url"]
        try:
            if image_url and image_url.startswith("http"):
                await callback_query.message.answer_photo(photo=image_url, caption=answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML")
            else:
                await callback_query.message.answer(answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
        except Exception:
            await callback_query.message.answer(answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
    else:
        await callback_query.message.answer("សូមបងរងចាំបន្តិច", parse_mode="HTML")
    await callback_query.answer()

@dp.message(F.reply_to_message)
async def admin_reply_handler(message: types.Message):
    if not is_admin(message): return 
    
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
        pass

@dp.message(~F.text)
async def process_media(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    if is_admin(message): return

    await save_user(message.from_user.id) 
    await message.answer("សូមបងរងចាំបន្តិច")
    username = f"@{message.from_user.username}" if message.from_user.username else "No username"
    
    safe_name = html.escape(message.from_user.full_name)
    safe_username = html.escape(username)
    
    admin_log = (
        f"🚨 <b>NEW CUSTOMER ATTACHMENT</b>\n"
        f"👤 <b>User:</b> {safe_name} ({safe_username})\n"
        f"🆔 <b>ID:</b> {message.from_user.id}\n"
        f"📝 <b>MsgID:</b> {message.message_id}\n\n"
        f"<i>(👇 Swipe left on THIS text message to reply to them!)</i>"
    )
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_log, parse_mode="HTML")
            await message.forward(admin_id)
        except Exception:
            pass

@dp.message(F.text)
async def process_question(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    if is_admin(message): return

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
                await message.answer_photo(photo=image_url, caption=answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML")
                bot_response_summary = f"✅ Answered with Image:\n💬 {answer_text}"
            else:
                await message.answer(answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
                bot_response_summary = f"✅ Answered automatically with:\n💬 {answer_text}"
        except Exception:
            await message.answer(answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
            bot_response_summary = f"✅ Answered automatically (Image failed to load)"
    else:
        await message.answer("សូមបងរងចាំបន្តិច")
        bot_response_summary = "❌ No match (needs human reply)."
        
    username = f"@{message.from_user.username}" if message.from_user.username else "No username"
    
    safe_name = html.escape(message.from_user.full_name)
    safe_username = html.escape(username)
    safe_text = html.escape(user_text)
    
    admin_log = (
        f"🚨 <b>NEW CUSTOMER QUESTION</b>\n"
        f"👤 <b>User:</b> {safe_name} ({safe_username})\n"
        f"🆔 <b>ID:</b> {message.from_user.id}\n"
        f"📝 <b>MsgID:</b> {message.message_id}\n"
        f"💬 <b>Asked:</b> {safe_text}\n"
        f"🤖 <b>Bot Action:</b> {bot_response_summary}\n\n"
        f"<i>(Swipe left / Reply directly to this message to answer the customer!)</i>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_log, parse_mode="HTML")
        except Exception:
            pass

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