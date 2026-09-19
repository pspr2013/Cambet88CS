import asyncio
import logging
import re
import os
import time 
import aiohttp
import html 
import pandas as pd
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
import google.generativeai as genai

from config import BOT_TOKEN, ADMIN_USER_ID, GOOGLE_SHEET_URL, PORT
from faq_manager import FAQManager
from web_keepalive import start_web_server

# --- GEMINI AI SETUP ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
WEBSITE_URL = os.getenv("WEBSITE_URL", "")
AI_SHEET_URL = os.getenv("AI_SHEET_URL", "")

ai_model = None
user_ai_chats = {}

async def update_ai_brain():
    global ai_model, user_ai_chats
    user_ai_chats.clear() # Clear old memory so it learns the new rules
    
    training_text = ""
    
    if AI_SHEET_URL:
        try:
            # Safely extract the Google Sheet ID to download as text
            match = re.search(r'/d/([a-zA-Z0-9-_]+)', AI_SHEET_URL)
            if match:
                sheet_id = match.group(1)
                csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(csv_url) as response:
                        if response.status == 200:
                            csv_data = await response.text()
                            df = pd.read_csv(io.StringIO(csv_data))
                            # Convert the entire Excel sheet into a text format for the AI to read
                            training_text = df.to_string(index=False)
                            logging.info("✅ AI successfully memorized the Google Sheet!")
        except Exception as e:
            logging.error(f"Failed to load AI Sheet: {e}")

    # Fallback to the old variable if the sheet fails
    if not training_text.strip():
        training_text = os.getenv("AI_TRAINING_DATA", "We are a premium online casino.")

    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        ai_model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            system_instruction=(
                f"You are a helpful customer support assistant for a website/casino. "
                f"Here is the official information and training data about our website:\n{training_text}\n\n"
                f"Our official website link is: {WEBSITE_URL}\n\n"
                "Answer the user's questions politely in Khmer or English based ONLY on the training data provided above. "
                "CRITICAL RULE: If the user asks for specific account help (like resetting passwords, deposits missing), "
                "or if they ask a question that is NOT covered in your training data, you MUST reply with EXACTLY the word 'HUMAN_FALLBACK'. "
                "Do not guess. Do not say anything else. Just HUMAN_FALLBACK."
            )
        )

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
    await callback_query.message.answer("Please choose a category:", reply_markup=get_categories_keyboard())
    await callback_query.answer()

WELCOME_IMAGE_URL = "https://images.unsplash.com/photo-1556761175-5973dc0f32b7?q=80&w=1000&auto=format&fit=crop"

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    
    await save_user(message.from_user.id) 
    
    welcome_text = "👋 <b>សូមស្វាគមន៍មកកាន់ ផ្នែកបំរើអតិថិជន តើមានអ្វីខ្ញុំអាចជួយបាន?</b>"
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
        await message.answer("⚠️ Please provide a message or attach a picture.")
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
        await message.answer(f"❌ Failed to fetch users: {e}")
        return
        
    if not known_users:
        await message.answer("⚠️ No customers found!")
        return
        
    await message.answer(f"🚀 Starting broadcast to {len(known_users)} customers...")
    success = 0
    
    for uid in known_users:
        if is_banned(uid): continue
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
        except Exception:
            pass 
            
    await message.answer(f"✅ Broadcast finished! Sent to {success}/{len(known_users)} customers.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    
    await save_user(message.from_user.id)
    help_text = "Just send me your question and I'll try my best to answer it!\n/start - Welcome menu\n/faq - Browse FAQs"
    if is_admin(message):
        help_text += "\n<b>Admin Commands:</b>\n/reload - Reload FAQ & AI data\n/broadcast [msg] - Message all users"
    await message.answer(help_text, parse_mode="HTML")

@dp.message(Command("faq"))
async def cmd_faq(message: types.Message):
    if message.chat.type != "private": return
    if is_banned(message.from_user.id): return
    if is_spam(message): return
    
    await save_user(message.from_user.id)
    await message.answer("Please choose a category:", reply_markup=get_categories_keyboard())

@dp.message(Command("reload"))
async def cmd_reload(message: types.Message):
    if not is_admin(message): return
    
    await message.answer("🔄 Downloading new data from Google Sheets...")
    success = faq_manager.load_data()
    await update_ai_brain()
    
    if success:
        await message.answer("✅ FAQ and AI Brain reloaded successfully!")
    else:
        await message.answer("⚠️ AI Brain updated, but FAQ had an error. Check logs.")

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
                bot_response_summary = f"✅ Answered with Excel Image:\n💬 {answer_text}"
            else:
                await message.answer(answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
                bot_response_summary = f"✅ Answered automatically from Excel:\n💬 {answer_text}"
        except Exception:
            await message.answer(answer_text, reply_markup=get_back_keyboard(), parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
            bot_response_summary = f"✅ Answered automatically from Excel"
            
    elif ai_model:
        try:
            uid = message.from_user.id
            if uid not in user_ai_chats:
                user_ai_chats[uid] = ai_model.start_chat(history=[])
                
            ai_response = await user_ai_chats[uid].send_message_async(user_text)
            ai_text = ai_response.text.strip()
            
            if "HUMAN_FALLBACK" in ai_text:
                await message.answer("សូមបងរងចាំបន្តិច", parse_mode="HTML")
                bot_response_summary = "🚨 <b>AI could not answer. HUMAN NEEDED!</b>"
            else:
                await message.answer(ai_text, link_preview_options=LinkPreviewOptions(is_disabled=True))
                bot_response_summary = f"🤖 <b>AI Answered:</b>\n💬 {ai_text}"
                
        except Exception as e:
            logger.error(f"AI Error: {e}")
            await message.answer("សូមបងរងចាំបន្តិច", parse_mode="HTML")
            bot_response_summary = "🚨 <b>AI crashed/failed. HUMAN NEEDED!</b>"
    else:
        await message.answer("សូមបងរងចាំបន្តិច", parse_mode="HTML")
        bot_response_summary = "🚨 <b>No match. HUMAN NEEDED!</b>"
        
    username = f"@{message.from_user.username}" if message.from_user.username else "No username"
    safe_name = html.escape(message.from_user.full_name)
    safe_username = html.escape(username)
    safe_text = html.escape(user_text)
    
    admin_log = (
        f"🔔 <b>NEW CUSTOMER QUESTION</b>\n"
        f"👤 <b>User:</b> {safe_name} ({safe_username})\n"
        f"🆔 <b>ID:</b> {message.from_user.id}\n"
        f"📝 <b>MsgID:</b> {message.message_id}\n"
        f"💬 <b>Asked:</b> {safe_text}\n"
        f"------------------\n"
        f"{bot_response_summary}\n\n"
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

    await update_ai_brain() # Download the AI brain on startup!
    await start_web_server(PORT)
    asyncio.create_task(faq_manager.auto_reload_task())
    
    logger.info("Bot is starting...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    if BOT_TOKEN:
        asyncio.run(main())
