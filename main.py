"""
Anonymous Chatting & Dating Telegram Bot
Complete code with all features: gender filter, referral, coins, VIP, anonymous link.
"""

import os
import logging
import asyncio
import threading
import random
import string
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)
from telegram.request import HTTPXRequest
import redis.asyncio as aioredis

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("anon-bot")

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("REDIS_URL")

if not BOT_TOKEN or not REDIS_URL:
    raise RuntimeError("BOT_TOKEN and REDIS_URL must be set.")

# ============================================================
# REDIS
# ============================================================
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

# ============================================================
# FLASK HEALTH CHECK
# ============================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, threaded=True)

# ============================================================
# CONSTANTS
# ============================================================
BAD_WORDS = ["badword1", "badword2", "গালি১", "গালি২"]
MIN_AGE = 13
MAX_AGE = 99
MIN_NAME_LEN = 2
MAX_NAME_LEN = 30
COINS_PER_REFERRAL = 10
COINS_PER_CHAT = 1
VIP_PRICE_COINS = 100
VIP_DURATION_DAYS = 30

# ============================================================
# HELPER: PROFILE
# ============================================================
async def get_profile(user_id):
    data = await redis_client.hgetall(f"user:{user_id}")
    if not data or not data.get("name"):
        return None
    return data

async def save_profile(user_id, name=None, age=None, gender=None):
    updates = {}
    if name is not None:
        updates["name"] = str(name)
    if age is not None:
        updates["age"] = str(age)
    if gender is not None:
        updates["gender"] = str(gender)
    if updates:
        await redis_client.hset(f"user:{user_id}", mapping=updates)

# ============================================================
# HELPER: COINS & VIP
# ============================================================
async def get_coins(user_id):
    coins = await redis_client.get(f"coins:{user_id}")
    return int(coins) if coins else 0

async def add_coins(user_id, amount):
    await redis_client.incrby(f"coins:{user_id}", amount)

async def deduct_coins(user_id, amount):
    current = await get_coins(user_id)
    if current < amount:
        return False
    await redis_client.decrby(f"coins:{user_id}", amount)
    return True

async def is_vip(user_id):
    vip_until = await redis_client.get(f"vip:{user_id}")
    if not vip_until:
        return False
    try:
        expiry = datetime.fromisoformat(vip_until)
        if datetime.now() < expiry:
            return True
        else:
            await redis_client.delete(f"vip:{user_id}")
            return False
    except Exception:
        return False

async def set_vip(user_id, days=VIP_DURATION_DAYS):
    expiry = datetime.now() + timedelta(days=days)
    await redis_client.set(f"vip:{user_id}", expiry.isoformat())

# ============================================================
# HELPER: REFERRAL
# ============================================================
async def generate_referral_code(user_id):
    code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    await redis_client.set(f"refcode:{code}", str(user_id))
    return code

async def get_referral_code(user_id):
    code = await redis_client.get(f"refcode_of:{user_id}")
    if not code:
        code = await generate_referral_code(user_id)
        await redis_client.set(f"refcode_of:{user_id}", code)
    return code

async def process_referral(new_user_id, code):
    referrer_id = await redis_client.get(f"refcode:{code}")
    if not referrer_id:
        return False
    referrer_id = int(referrer_id)
    if referrer_id == new_user_id:
        return False
    if await redis_client.get(f"referred:{new_user_id}"):
        return False
    await redis_client.set(f"referred:{new_user_id}", str(referrer_id))
    await add_coins(referrer_id, COINS_PER_REFERRAL)
    return True

# ============================================================
# HELPER: MATCHING & BLOCKING
# ============================================================
async def get_partner(user_id):
    pid = await redis_client.get(f"chat:{user_id}")
    return int(pid) if pid else None

async def set_partner(user_a, user_b):
    await redis_client.set(f"chat:{user_a}", user_b)
    await redis_client.set(f"chat:{user_b}", user_a)

async def end_chat(user_id):
    partner_id = await get_partner(user_id)
    if partner_id:
        await redis_client.delete(f"chat:{user_id}")
        await redis_client.delete(f"chat:{partner_id}")
    return partner_id

async def is_blocked(user_id, target_id):
    return await redis_client.sismember(f"blocked:{user_id}", str(target_id))

async def block_user(user_id, target_id):
    await redis_client.sadd(f"blocked:{user_id}", str(target_id))

async def _try_queue(queue_name, user_id):
    while True:
        candidate = await redis_client.lpop(queue_name)
        if not candidate:
            return None
        candidate = int(candidate)
        if candidate == user_id:
            continue
        if await get_partner(candidate):
            continue
        if await is_blocked(user_id, candidate):
            continue
        if await is_blocked(candidate, user_id):
            continue
        return candidate

async def find_match(user_id, user_pref):
    if user_pref == "male":
        queues = ["queue_male", "queue_any"]
    elif user_pref == "female":
        queues = ["queue_female", "queue_any"]
    else:
        queues = ["queue_female", "queue_male", "queue_any"]
    for q in queues:
        found = await _try_queue(q, user_id)
        if found:
            return found
    return None

async def add_to_queue(user_id, user_gender, user_pref):
    await remove_from_queues(user_id)
    if user_pref == "male":
        await redis_client.rpush("queue_male", user_id)
    elif user_pref == "female":
        await redis_client.rpush("queue_female", user_id)
    else:
        if user_gender == "male":
            await redis_client.rpush("queue_male", user_id)
        elif user_gender == "female":
            await redis_client.rpush("queue_female", user_id)
        else:
            await redis_client.rpush("queue_any", user_id)

async def remove_from_queues(user_id):
    for q in ["queue_male", "queue_female", "queue_any"]:
        await redis_client.lrem(q, 0, user_id)

# ============================================================
# HANDLERS: START & REGISTRATION
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    old_partner = await end_chat(user_id)
    if old_partner:
        try:
            await context.bot.send_message(
                old_partner,
                "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।\nনতুন পার্টনার খুঁজতে /start দিন।"
            )
        except Exception:
            pass

    await remove_from_queues(user_id)
    context.user_data.clear()

    # Process referral
    if args and args[0].startswith("ref_"):
        code = args[0][4:]
        await process_referral(user_id, code)

    profile = await get_profile(user_id)
    if not profile:
        context.user_data["state"] = "awaiting_name"
        await update.message.reply_text(
            "👋 স্বাগতম Anonymous Chatting Bot-এ!\n\n"
            "শুরু করার আগে কিছু তথ্য দরকার।\n\n📝 আপনার নাম লিখুন:"
        )
        return

    # Directly find partner on /start
    user_gender = profile.get("gender", "any")
    if user_gender == "male":
        user_pref = "female"
    elif user_gender == "female":
        user_pref = "male"
    else:
        user_pref = "any"

    partner_id = await find_match(user_id, user_pref)
    if partner_id:
        await set_partner(user_id, partner_id)
        success_text = (
            "✅ পার্টনার পাওয়া গেছে!\n\n💬 এখন মেসেজ পাঠান।\n"
            "🛑 চ্যাট শেষ করতে /stop দিন।\n🚨 রিপোর্ট করতে /report দিন।"
        )
        await update.message.reply_text(success_text)
        try:
            await context.bot.send_message(partner_id, success_text)
        except Exception:
            pass
        await add_coins(user_id, COINS_PER_CHAT)
    else:
        await add_to_queue(user_id, user_gender, user_pref)
        await update.message.reply_text(
            "⏳ পার্টনার খোঁজা হচ্ছে...\n\nঅনুগ্রহ করে অপেক্ষা করুন।"
        )

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    if state == "awaiting_name":
        if len(text) < MIN_NAME_LEN or len(text) > MAX_NAME_LEN:
            await update.message.reply_text(f"⚠️ নাম {MIN_NAME_LEN}-{MAX_NAME_LEN} অক্ষরের মধ্যে দিন।")
            return
        context.user_data["temp_name"] = text
        context.user_data["state"] = "awaiting_age"
        await update.message.reply_text(f"✅ নাম সেভ: {text}\n\n🎂 আপনার বয়স কত? (শুধু সংখ্যা লিখুন)")
        return

    if state == "awaiting_age":
        if not text.isdigit():
            await update.message.reply_text("⚠️ শুধু সংখ্যা লিখুন। যেমন: 22")
            return
        age = int(text)
        if not (MIN_AGE <= age <= MAX_AGE):
            await update.message.reply_text(f"⚠️ বয়স {MIN_AGE}-{MAX_AGE} এর মধ্যে দিন।")
            return
        context.user_data["temp_age"] = age
        context.user_data["state"] = "awaiting_gender"
        keyboard = [
            [InlineKeyboardButton("👦 ছেলে", callback_data="gender_male"),
             InlineKeyboardButton("👧 মেয়ে", callback_data="gender_female")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"✅ বয়স সেভ: {age}\n\n⚧ আপনার জেন্ডার সিলেক্ট করুন:",
            reply_markup=reply_markup
        )
        return

async def gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    gender = "male" if query.data == "gender_male" else "female"
    name = context.user_data.get("temp_name")
    age = context.user_data.get("temp_age")

    if not name or not age:
        await query.edit_message_text("❌ কিছু ভুল হয়েছে। আবার /start দিন।")
        return

    await save_profile(user_id, name=name, age=age, gender=gender)
    context.user_data.clear()
    gender_text = "ছেলে" if gender == "male" else "মেয়ে"
    keyboard = [
        [InlineKeyboardButton("🔍 Find Partner", callback_data="find_partner")],
        [InlineKeyboardButton("👤 My Profile", callback_data="profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"✅ রেজিস্ট্রেশন সম্পন্ন!\n\n👤 নাম: {name}\n🎂 বয়স: {age}\n"
        f"⚧ জেন্ডার: {gender_text}\n\nএখন পার্টনার খুঁজতে বাটনে ক্লিক করুন।",
        reply_markup=reply_markup
    )

# ============================================================
# HANDLERS: FIND PARTNER
# ============================================================
async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    existing = await get_partner(user_id)
    if existing:
        await query.edit_message_text(
            "❌ আপনি ইতিমধ্যে একটি চ্যাটে আছেন।\nনতুন পার্টনার খুঁজতে আগে /stop দিন।"
        )
        return

    profile = await get_profile(user_id)
    if not profile:
        await query.edit_message_text("❌ আগে /start দিয়ে রেজিস্ট্রেশন করুন।")
        return

    for q in ["queue_male", "queue_female", "queue_any"]:
        if await redis_client.lpos(q, user_id) is not None:
            await query.edit_message_text(
                "⏳ আপনি ইতিমধ্যে সারিতে আছেন।\nঅনুগ্রহ করে অপেক্ষা করুন।"
            )
            return

    user_gender = profile.get("gender", "any")
    if user_gender == "male":
        user_pref = "female"
    elif user_gender == "female":
        user_pref = "male"
    else:
        user_pref = "any"

    partner_id = await find_match(user_id, user_pref)
    if partner_id:
        await set_partner(user_id, partner_id)
        success_text = (
            "✅ পার্টনার পাওয়া গেছে!\n\n💬 এখন মেসেজ পাঠান।\n"
            "🛑 চ্যাট শেষ করতে /stop দিন।\n🚨 রিপোর্ট করতে /report দিন।"
        )
        await query.edit_message_text(success_text)
        try:
            await context.bot.send_message(partner_id, success_text)
        except Exception:
            pass
        await add_coins(user_id, COINS_PER_CHAT)
    else:
        await add_to_queue(user_id, user_gender, user_pref)
        await query.edit_message_text("⏳ পার্টনার খোঁজা হচ্ছে...\n\nঅনুগ্রহ করে অপেক্ষা করুন।")

# ============================================================
# HANDLERS: STOP & REPORT
# ============================================================
async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await remove_from_queues(user_id)
    partner_id = await end_chat(user_id)
    if not partner_id:
        await update.message.reply_text("❌ আপনি বর্তমানে কোনো চ্যাটে নেই।")
        return
    await update.message.reply_text(
        "🛑 চ্যাট শেষ হয়েছে।\nনতুন পার্টনার খুঁজতে /start দিন।"
    )
    try:
        await context.bot.send_message(
            partner_id,
            "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।\nনতুন পার্টনার খুঁজতে /start দিন।"
        )
    except Exception:
        pass

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = await get_partner(user_id)
    if not partner_id:
        await update.message.reply_text("❌ আপনি কোনো চ্যাটে নেই।")
        return
    await block_user(user_id, partner_id)
    await end_chat(user_id)
    await update.message.reply_text(
        "✅ পার্টনারকে রিপোর্ট ও ব্লক করা হয়েছে।\nনতুন পার্টনার খুঁজতে /start দিন।"
    )
    try:
        await context.bot.send_message(partner_id, "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।")
    except Exception:
        pass

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ বাতিল করা হয়েছে। /start দিন।")

# ============================================================
# HANDLERS: NEW CHAT
# ============================================================
async def newchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await remove_from_queues(user_id)
    partner_id = await end_chat(user_id)
    if partner_id:
        try:
            await context.bot.send_message(
                partner_id,
                "🛑 আপনার পার্টনার নতুন চ্যাট শুরু করেছেন।\nনতুন পার্টনার খুঁজতে /start দিন।"
            )
        except Exception:
            pass
    await update.message.reply_text("🔄 নতুন চ্যাট শুরু হচ্ছে... /start দিন।")

# ============================================================
# HANDLERS: HELP
# ============================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 সাহায্য\n\n"
        "🔹 /start — মেইন মেনু ও পার্টনার খোঁজা\n"
        "🔹 /stop — চলমান চ্যাট শেষ\n"
        "🔹 /report — পার্টনারকে রিপোর্ট ও ব্লক\n"
        "🔹 /cancel — চলমান কাজ বাতিল\n"
        "🔹 /profile — নিজের প্রোফাইল দেখা\n"
        "🔹 /newchat — নতুন চ্যাট শুরু\n"
        "🔹 /link — ইনভাইট লিংক ও কয়েন\n"
        "🔹 /credit — কয়েন ব্যালেন্স\n"
        "🔹 /link_anon — অ্যানোনিমাস লিংক\n"
        "🔹 /vip — VIP আপগ্রেড\n\n"
        "📌 নিয়মাবলি:\n• সবসময় ভদ্র ভাষায় কথা বলুন\n"
        "• অন্যের ব্যক্তিগত তথ্য চাইবেন না\n"
        "• খারাপ ব্যবহার করলে ব্লক করা হবে\n\n"
        "🔒 আপনার পরিচয় সম্পূর্ণ গোপন থাকবে।"
    )

# ============================================================
# HANDLERS: PROFILE & MENUS
# ============================================================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = await get_profile(user_id)
    if not data:
        await query.edit_message_text("❌ আগে /start দিয়ে রেজিস্ট্রেশন করুন।")
        return
    gender_text = {"male": "ছেলে", "female": "মেয়ে"}.get(data.get("gender"), "N/A")
    coins = await get_coins(user_id)
    vip_status = "✅ VIP" if await is_vip(user_id) else "❌ Free"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"👤 আপনার প্রোফাইল\n\n📝 নাম: {data.get('name', 'N/A')}\n"
        f"🎂 বয়স: {data.get('age', 'N/A')}\n⚧ জেন্ডার: {gender_text}\n"
        f"🪙 কয়েন: {coins}\n⭐ স্ট্যাটাস: {vip_status}",
        reply_markup=reply_markup
    )

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📖 সাহায্য\n\n🔹 /start — মেইন মেনু\n🔹 /stop — চ্যাট শেষ\n"
        "🔹 /report — রিপোর্ট ও ব্লক\n\n🔒 আপনার পরিচয় সম্পূর্ণ গোপন।",
        reply_markup=reply_markup
    )

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = await get_profile(user_id)
    if not data:
        await query.edit_message_text("❌ আগে /start দিন।")
        return
    keyboard = [
        [InlineKeyboardButton("🔍 Find Partner", callback_data="find_partner")],
        [InlineKeyboardButton("👤 My Profile", callback_data="profile")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"👋 স্বাগতম, {data['name']}!\n\n🎯 এটি একটি Anonymous Chatting Bot।\n\n"
        f"নিচের বাটনে ক্লিক করুন।",
        reply_markup=reply_markup
    )

# ============================================================
# HANDLERS: COINS & VIP
# ============================================================
async def credit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins = await get_coins(user_id)
    vip_status = "✅ Active" if await is_vip(user_id) else "❌ Inactive"
    await update.message.reply_text(
        f"🪙 আপনার কয়েন ব্যালেন্স: {coins}\n⭐ VIP স্ট্যাটাস: {vip_status}\n\n"
        f"💡 কয়েন আর্ন করতে /link দিন।"
    )

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = await get_referral_code(user_id)
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{code}"
    await update.message.reply_text(
        f"🔗 আপনার ইনভাইট লিংক:\n\n{link}\n\n"
        f"🎁 প্রতি ইনভাইটে {COINS_PER_REFERRAL} কয়েন পাবেন!"
    )

async def link_anon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = await get_referral_code(user_id)
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref_{code}"
    await update.message.reply_text(
        f"👀 আপনার অ্যানোনিমাস চ্যাট লিংক:\n\n{link}\n\n"
        f"এই লিংক শেয়ার করলে কেউ জয়েন করলে আপনি {COINS_PER_REFERRAL} কয়েন পাবেন।"
    )

async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await is_vip(user_id):
        await update.message.reply_text("⭐ আপনি ইতিমধ্যে VIP! আপনার সাবস্ক্রিপশন সক্রিয় আছে।")
        return
    coins = await get_coins(user_id)
    if coins < VIP_PRICE_COINS:
        await update.message.reply_text(
            f"❌ আপনার কাছে যথেষ্ট কয়েন নেই।\n\n"
            f"🪙 প্রয়োজন: {VIP_PRICE_COINS} কয়েন\n🪙 আপনার আছে: {coins} কয়েন\n\n"
            f"💡 কয়েন আর্ন করতে /link দিন।"
        )
        return
    success = await deduct_coins(user_id, VIP_PRICE_COINS)
    if success:
        await set_vip(user_id)
        await update.message.reply_text(
            f"🎉 অভিনন্দন! আপনি VIP হয়েছেন!\n\n"
            f"✅ {VIP_DURATION_DAYS} দিনের জন্য VIP সক্রিয়।"
        )
    else:
        await update.message.reply_text("❌ কয়েন কাটা যায়নি। আবার চেষ্টা করুন।")

# ============================================================
# HANDLERS: MESSAGE (ALL TYPES)
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get("state")

    if state in ("awaiting_name", "awaiting_age"):
        if update.message.text:
            await handle_registration(update, context)
        else:
            await update.message.reply_text("⚠️ দয়া করে টেক্সট লিখুন।")
        return

    if state == "awaiting_gender":
        await update.message.reply_text("⚠️ উপরের বাটন থেকে জেন্ডার সিলেক্ট করুন।")
        return

    partner_id = await get_partner(user_id)
    if not partner_id:
        await update.message.reply_text(
            "⚠️ আপনি কোনো চ্যাটে নেই।\nপার্টনার খুঁজতে /start দিন।"
        )
        return

    if update.message.text:
        text_lower = update.message.text.lower()
        if any(w in text_lower for w in BAD_WORDS):
            await update.message.reply_text("🚫 আপনার মেসেজে নিষিদ্ধ শব্দ আছে। পাঠানো হয়নি।")
            return

    try:
        await context.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=user_id,
            message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Failed to copy message: {e}")
        await update.message.reply_text("❌ মেসেজ পাঠানো যায়নি। পার্টনার হয়তো বটটি ব্লক করেছে।")

# ============================================================
# MAIN
# ============================================================
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    threading.Thread(target=run_flask, daemon=True).start()

    request = HTTPXRequest(
        connection_pool_size=20,
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=30.0
    )
    app = Application.builder().token(BOT_TOKEN).request(request).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("newchat", newchat_command))
    app.add_handler(CommandHandler("credit", credit_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("link_anon", link_anon_command))
    app.add_handler(CommandHandler("vip", vip_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(gender_callback, pattern="^gender_(male|female)$"))
    app.add_handler(CallbackQueryHandler(find_partner, pattern="^find_partner$"))
    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("🤖 Anonymous Chatting Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
