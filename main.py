import os
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler
)
from telegram.request import HTTPXRequest
import asyncpg

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False

# ============================================================
# CONFIG
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("BOT_TOKEN and DATABASE_URL must be set.")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("anon-chat-bot")

flask_app = Flask(__name__)


@flask_app.route('/')
def health():
    return "OK", 200


def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)


db_pool = None
groq_client = Groq(api_key=GROQ_API_KEY) if (HAS_GROQ and GROQ_API_KEY) else None

# ============================================================
# AI MODELS (with fallback)
# ============================================================
AI_MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
]

# ============================================================
# CONSTANTS
# ============================================================
ONLINE_THRESHOLD_MINUTES = 5
QUEUE_TIMEOUT_SECONDS = 120
CHAT_TIMER_SECONDS = 600
AUTO_BAN_REPORT_COUNT = 5
REFERRAL_COIN_REWARD = 20
CHAT_COIN_REWARD = 1
DAILY_BONUS_COINS = 10
VIP_PRICE_COINS = 500
VIP_STARS_PRICE = 100
VIP_DURATION_DAYS = 30
MAX_DAILY_CHATS_FREE = 20
GROUP_ROOM_MAX = 6
GROUP_ROOM_MIN = 3

BANNED_WORDS = [
    "fuck", "shit", "bitch", "asshole", "dick", "pussy", "bastard",
    "madarchod", "bhadwa", "chutiya", "chod", "harami", "kutta", "kuti",
]

# ============================================================
# LANGUAGE STRINGS
# ============================================================
STRINGS = {
    "welcome": {
        "bn": "👋 স্বাগতম! এটি একটি অ্যানোনিমাস চ্যাটিং বট।\n\nশুরু করার আগে নিশ্চিত করুন যে আপনার বয়স ১৮+।",
        "en": "👋 Welcome! This is an anonymous chat bot.\n\nPlease confirm that you are 18+.",
    },
    "age_yes": {"bn": "✅ হ্যাঁ, আমি ১৮+", "en": "✅ Yes, I am 18+"},
    "age_no": {"bn": "❌ না", "en": "❌ No"},
    "age_denied": {"bn": "❌ দুঃখিত, এই বটটি শুধুমাত্র ১৮+ ব্যবহারকারীদের জন্য।", "en": "❌ Sorry, this bot is only for 18+ users."},
    "ask_name": {"bn": "✅ ধন্যবাদ! এখন আপনার নাম লিখুন:", "en": "✅ Thanks! Now enter your name:"},
    "ask_age": {"bn": "🎂 আপনার বয়স লিখুন (শুধু সংখ্যা):", "en": "🎂 Enter your age (numbers only):"},
    "ask_gender": {"bn": "⚧ আপনার জেন্ডার নির্বাচন করুন:", "en": "⚧ Select your gender:"},
    "ask_pref": {"bn": "🎯 আপনি কার সাথে চ্যাট করতে চান?", "en": "🎯 Who do you want to chat with?"},
    "ask_interest": {"bn": "💡 আপনার আগ্রহ নির্বাচন করুন:", "en": "💡 Select your interest:"},
    "ask_lang_pref": {"bn": "🌐 আপনি কোন ভাষার পার্টনার চান?", "en": "🌐 Which language partner?"},
    "ask_bio": {"bn": "📝 একটি ছোট বায়ো লিখুন (সর্বোচ্চ ২০০ অক্ষর):", "en": "📝 Write a short bio (max 200 chars):"},
    "male": {"bn": "👦 ছেলে", "en": "👦 Male"},
    "female": {"bn": "👧 মেয়ে", "en": "👧 Female"},
    "other": {"bn": "🌈 অন্যান্য", "en": "🌈 Other"},
    "any": {"bn": "🌍 যে কেউ", "en": "🌍 Anyone"},
    "main_menu": {"bn": "🏠 মেইন মেনু — নির্বাচন করুন:", "en": "🏠 Main Menu — Choose:"},
    "find_partner": {"bn": "🔍 Find Partner", "en": "🔍 Find Partner"},
    "group_rooms": {"bn": "👥 Group Rooms", "en": "👥 Group Rooms"},
    "my_profile": {"bn": "👤 My Profile", "en": "👤 My Profile"},
    "edit_profile": {"bn": "✏️ Edit Profile", "en": "✏️ Edit Profile"},
    "safety": {"bn": "🛡 Safety", "en": "🛡 Safety"},
    "help": {"bn": "ℹ️ Help", "en": "ℹ️ Help"},
    "coins": {"bn": "🪙 Coins", "en": "🪙 Coins"},
    "vip": {"bn": "⭐ VIP", "en": "⭐ VIP"},
    "invite": {"bn": "🔗 Invite", "en": "🔗 Invite"},
    "leaderboard": {"bn": "🏆 Leaderboard", "en": "🏆 Leaderboard"},
    "language": {"bn": "🌐 ভাষা", "en": "🌐 Language"},
    "end_chat": {"bn": "🛑 End Chat", "en": "🛑 End Chat"},
    "next_person": {"bn": "➡️ Next Person", "en": "➡️ Next Person"},
    "report": {"bn": "🚫 Report", "en": "🚫 Report"},
    "reg_done": {"bn": "✅ রেজিস্ট্রেশন সম্পন্ন! 🎉", "en": "✅ Registration complete! 🎉"},
    "searching": {"bn": "⏳ পার্টনার খোঁজা হচ্ছে...\n\nঅনুগ্রহ করে অপেক্ষা করুন।", "en": "⏳ Searching for partner...\n\nPlease wait."},
    "partner_found": {"bn": "✅ পার্টনার পাওয়া গেছে!\n\n💬 এখন যেকোনো মেসেজ পাঠান — টেক্সট, ছবি, ভয়েস সবই যাবে।\n🔒 আপনার পরিচয় সম্পূর্ণ গোপন থাকবে।", "en": "✅ Partner found!\n\n💬 Send any message — text, photo, voice all work.\n🔒 Fully anonymous."},
    "chat_ended": {"bn": "🛑 চ্যাট শেষ হয়েছে।", "en": "🛑 Chat ended."},
    "partner_ended": {"bn": "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।", "en": "🛑 Your partner ended the chat."},
    "partner_left": {"bn": "🛑 আপনার পার্টনার নতুন পার্টনার খুঁজতে চলে গেছেন।", "en": "🛑 Your partner left."},
    "partner_disconnected": {"bn": "🔌 পার্টনার সংযোগ হারিয়ে ফেলেছেন।", "en": "🔌 Partner disconnected."},
    "not_in_chat": {"bn": "⚠️ আপনি কোনো চ্যাটে নেই। /start দিন।", "en": "⚠️ You're not in a chat. Send /start."},
    "reg_first": {"bn": "❌ আগে /start দিন।", "en": "❌ Please /start first."},
    "already_in_chat": {"bn": "❌ আপনি ইতিমধ্যে একটি চ্যাটে আছেন।", "en": "❌ You're already in a chat."},
    "search_cancelled": {"bn": "✅ সার্চ বাতিল করা হয়েছে।", "en": "✅ Search cancelled."},
    "online_count": {"bn": "🟢 এখন {n} জন অনলাইনে আছেন", "en": "🟢 {n} users online"},
    "referral_msg": {"bn": "🔗 আপনার ইনভাইট লিংক:\n\n{link}\n\n💡 বন্ধুদের ইনভাইট করলে প্রতি জয়েনে {coins} কয়েন পাবেন!", "en": "🔗 Your invite link:\n\n{link}\n\n💡 Earn {coins} coins per referral!"},
    "coins_balance": {"bn": "🪙 আপনার কয়েন: {coins}\n⭐ VIP: {vip}", "en": "🪙 Coins: {coins}\n⭐ VIP: {vip}"},
    "vip_active": {"bn": "✅ Active", "en": "✅ Active"},
    "vip_inactive": {"bn": "❌ Inactive", "en": "❌ Inactive"},
    "vip_buy_msg": {"bn": "⭐ VIP সাবস্ক্রিপশন\n\n💰 {price} কয়েন বা {stars} Stars দিয়ে {days} দিনের VIP।\n\n🎁 সুবিধা:\n• Priority Matching\n• ডাবল কয়েন\n• Unlimited chats\n• Advanced Filters", "en": "⭐ VIP Subscription\n\n💰 {days}-day VIP for {price} coins or {stars} Stars.\n\n🎁 Benefits:\n• Priority Matching\n• Double coins\n• Unlimited chats\n• Advanced Filters"},
    "vip_bought": {"bn": "🎉 অভিনন্দন! আপনি VIP!\n✅ {days} দিনের জন্য সক্রিয়।", "en": "🎉 Congratulations! VIP!\n✅ Active for {days} days."},
    "not_enough_coins": {"bn": "❌ যথেষ্ট কয়েন নেই।\n🪙 দরকার: {need}\n🪙 আছে: {have}\n\n💡 /link দিয়ে আর্ন করুন।", "en": "❌ Not enough coins.\n🪙 Need: {need}\n🪙 Have: {have}\n\n💡 Earn with /link"},
    "already_vip": {"bn": "⭐ আপনি ইতিমধ্যে VIP!", "en": "⭐ You're already VIP!"},
    "buy_with_coins": {"bn": "💰 কয়েন দিয়ে", "en": "💰 With Coins"},
    "buy_with_stars": {"bn": "⭐ Stars দিয়ে", "en": "⭐ With Stars"},
    "language_select": {"bn": "🌍 ভাষা নির্বাচন করুন:", "en": "🌍 Choose your language:"},
    "language_changed": {"bn": "✅ ভাষা সেট হয়েছে: বাংলা", "en": "✅ Language set: English"},
    "report_thanks": {"bn": "✅ ধন্যবাদ। রিপোর্ট জমা হয়েছে।", "en": "✅ Thanks. Report submitted."},
    "report_blocked": {"bn": "✅ রিপোর্ট জমা + পার্টনার ব্লকড।", "en": "✅ Report submitted + partner blocked."},
    "referral_bonus": {"bn": "🎁 আপনি {coins} কয়েন পেয়েছেন!", "en": "🎁 You earned {coins} coins!"},
    "daily_bonus": {"bn": "🎁 ডেইলি বোনাস: +{coins} কয়েন!", "en": "🎁 Daily bonus: +{coins} coins!"},
    "chat_limit_reached": {"bn": "❌ আজকের ফ্রি চ্যাট লিমিট শেষ ({n})।\n\n⭐ VIP নিন unlimited এর জন্য।", "en": "❌ Daily free chat limit reached ({n}).\n\n⭐ Get VIP for unlimited."},
    "spam_warning": {"bn": "⚠️ অনুগ্রহ করে ভদ্রভাবে কথা বলুন।", "en": "⚠️ Please be respectful."},
    "chat_timer_warning": {"bn": "⏰ চ্যাট ২ মিনিটে শেষ হবে।", "en": "⏰ Chat ends in 2 minutes."},
    "chat_timer_ended": {"bn": "⏰ চ্যাটের সময় শেষ।", "en": "⏰ Chat time ended."},
    "no_partner_ai": {"bn": "🤖 কোনো পার্টনার পাওয়া যায়নি। AI এর সাথে চ্যাট করুন?", "en": "🤖 No partner found. Chat with AI instead?"},
    "ai_mode_on": {"bn": "🤖 AI মোড চালু। এখন আপনি AI এর সাথে কথা বলছেন।\n\n🛑 থামাতে /stop দিন।", "en": "🤖 AI mode ON. You're now chatting with AI.\n\n🛑 Send /stop to stop."},
    "profile_saved": {"bn": "✅ প্রোফাইল সেভ হয়েছে!", "en": "✅ Profile saved!"},
    "leaderboard_title": {"bn": "🏆 টপ চ্যাটার", "en": "🏆 Top Chatters"},
    "leaderboard_empty": {"bn": "এখনো কোনো ডেটা নেই।", "en": "No data yet."},
    "group_room_menu": {"bn": "👥 Group Chat Rooms\n\nএকটি রুমে ৩-৬ জন অ্যানোনিমাস।", "en": "👥 Group Chat Rooms\n\n3-6 anonymous users per room."},
    "group_room_full": {"bn": "❌ রুম ফুল।", "en": "❌ Room full."},
    "group_room_not_found": {"bn": "❌ রুম পাওয়া যায়নি।", "en": "❌ Room not found."},
    "group_room_left": {"bn": "🚪 আপনি রুম থেকে বেরিয়ে গেছেন।", "en": "🚪 Left the room."},
    "wait_moment": {"bn": "⏳ একটু অপেক্ষা করুন।", "en": "⏳ Wait a moment."},
}


def t(key, lang, **kwargs):
    s = STRINGS.get(key, {})
    text = s.get(lang) or s.get("en") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


# ============================================================
# DATABASE
# ============================================================
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as conn:
        # USERS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_18_plus BOOLEAN DEFAULT FALSE,
                is_banned BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                language VARCHAR(5) DEFAULT 'bn',
                coins INTEGER DEFAULT 0,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_until TIMESTAMP,
                referred_by BIGINT
            );
        """)
        user_cols = [
            ("ban_reason", "TEXT"),
            ("chats_today", "INTEGER DEFAULT 0"),
            ("chats_today_date", "DATE DEFAULT CURRENT_DATE"),
            ("daily_bonus_date", "DATE"),
            ("total_chats", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in user_cols:
            try:
                await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            except Exception as e:
                logger.warning(f"users.{col_name} skip: {e}")

        # PROFILES
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id BIGINT PRIMARY KEY,
                display_name VARCHAR(100),
                age INTEGER,
                gender VARCHAR(20),
                pref_gender VARCHAR(20) DEFAULT 'any',
                bio TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        for col_name, col_def in [
            ("pref_language", "VARCHAR(10) DEFAULT 'any'"),
            ("interest", "VARCHAR(30) DEFAULT 'any'"),
        ]:
            try:
                await conn.execute(f"ALTER TABLE profiles ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            except Exception as e:
                logger.warning(f"profiles.{col_name} skip: {e}")

        # MATCH QUEUE
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS match_queue (
                user_id BIGINT PRIMARY KEY,
                gender VARCHAR(20),
                pref_gender VARCHAR(20),
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        for col_name, col_def in [
            ("pref_language", "VARCHAR(10) DEFAULT 'any'"),
            ("interest", "VARCHAR(30) DEFAULT 'any'"),
            ("is_vip", "BOOLEAN DEFAULT FALSE"),
        ]:
            try:
                await conn.execute(f"ALTER TABLE match_queue ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            except Exception as e:
                logger.warning(f"match_queue.{col_name} skip: {e}")

        # ACTIVE CHATS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS active_chats (
                user_id BIGINT PRIMARY KEY,
                partner_id BIGINT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        try:
            await conn.execute("ALTER TABLE active_chats ADD COLUMN IF NOT EXISTS is_ai BOOLEAN DEFAULT FALSE")
        except Exception as e:
            logger.warning(f"active_chats.is_ai skip: {e}")

        # GROUP ROOMS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_rooms (
                room_id SERIAL PRIMARY KEY,
                host_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            );
        """)

        # GROUP MEMBERS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                room_id INTEGER,
                user_id BIGINT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (room_id, user_id)
            );
        """)

        # BLOCKS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                blocker_id BIGINT,
                blocked_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            );
        """)

        # REPORTS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                report_id SERIAL PRIMARY KEY,
                reporter_id BIGINT,
                reported_id BIGINT,
                reason VARCHAR(100),
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    logger.info("Database initialized.")


async def close_db():
    if db_pool:
        await db_pool.close()


# ============================================================
# USER HELPERS
# ============================================================
async def touch_user(user_id):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = $1", user_id)


async def get_user_lang(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT language FROM users WHERE user_id = $1", user_id)
        return row['language'] if row and row['language'] else 'bn'


async def set_user_lang(user_id, lang):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET language = $1 WHERE user_id = $2", lang, user_id)


async def get_online_count():
    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active > NOW() - INTERVAL '5 minutes'")
        return count or 0


async def is_user_banned(user_id):
    async with db_pool.acquire() as conn:
        banned = await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1", user_id)
        return bool(banned)


async def get_profile(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM profiles WHERE user_id = $1", user_id)
        return dict(row) if row else None


async def save_profile(user_id, **kwargs):
    if not kwargs:
        return
    columns = list(kwargs.keys())
    values = list(kwargs.values())
    placeholders = [f"${i + 2}" for i in range(len(columns))]
    update_set = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns])
    query = f"""
        INSERT INTO profiles (user_id, {', '.join(columns)})
        VALUES ($1, {', '.join(placeholders)})
        ON CONFLICT (user_id) DO UPDATE SET {update_set}
    """
    async with db_pool.acquire() as conn:
        await conn.execute(query, user_id, *values)


# ============================================================
# COINS & VIP
# ============================================================
async def get_coins(user_id):
    async with db_pool.acquire() as conn:
        coins = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user_id)
        return coins or 0


async def add_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", amount, user_id)


async def deduct_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        current = await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user_id) or 0
        if current < amount:
            return False
        await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", amount, user_id)
        return True


async def is_vip(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
        if not row or not row['is_vip']:
            return False
        if row['vip_until'] and row['vip_until'] < datetime.now():
            await conn.execute("UPDATE users SET is_vip = FALSE WHERE user_id = $1", user_id)
            return False
        return True


async def set_vip(user_id, days=VIP_DURATION_DAYS):
    until = datetime.now() + timedelta(days=days)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_vip = TRUE, vip_until = $1 WHERE user_id = $2", until, user_id)


# ============================================================
# DAILY LIMIT / BONUS
# ============================================================
async def check_and_increment_chat_limit(user_id):
    if await is_vip(user_id):
        return True
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT chats_today, chats_today_date FROM users WHERE user_id = $1", user_id)
        today = datetime.now().date()
        if not row:
            return False
        if row['chats_today_date'] != today:
            await conn.execute("UPDATE users SET chats_today = 1, chats_today_date = $1 WHERE user_id = $2", today, user_id)
            return True
        if row['chats_today'] >= MAX_DAILY_CHATS_FREE:
            return False
        await conn.execute("UPDATE users SET chats_today = chats_today + 1 WHERE user_id = $1", user_id)
        return True


async def try_daily_bonus(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT daily_bonus_date FROM users WHERE user_id = $1", user_id)
        today = datetime.now().date()
        if row and row['daily_bonus_date'] == today:
            return False
        await conn.execute(
            "UPDATE users SET daily_bonus_date = $1, coins = coins + $2 WHERE user_id = $3",
            today, DAILY_BONUS_COINS, user_id
        )
        return True


# ============================================================
# REFERRAL
# ============================================================
async def process_referral(new_user_id, referrer_id):
    if new_user_id == referrer_id:
        return False
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", referrer_id)
        if not exists:
            return False
        already = await conn.fetchval("SELECT referred_by FROM users WHERE user_id = $1", new_user_id)
        if already is not None:
            return False
        await conn.execute("UPDATE users SET referred_by = $1 WHERE user_id = $2", referrer_id, new_user_id)
        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", REFERRAL_COIN_REWARD, referrer_id)
    return True


# ============================================================
# ANTI-SPAM / RATE LIMIT
# ============================================================
def contains_bad_words(text):
    if not text:
        return False
    lower = text.lower()
    return any(w in lower for w in BANNED_WORDS)


rate_limit_store = {}


def is_rate_limited(user_id, max_requests=20, window_seconds=10):
    now = datetime.now()
    timestamps = rate_limit_store.get(user_id, [])
    timestamps = [ts for ts in timestamps if (now - ts).total_seconds() < window_seconds]
    if len(timestamps) >= max_requests:
        rate_limit_store[user_id] = timestamps
        return True
    timestamps.append(now)
    rate_limit_store[user_id] = timestamps
    return False


# ============================================================
# CHAT HELPERS
# ============================================================
async def get_active_chat(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM active_chats WHERE user_id = $1", user_id)
        return dict(row) if row else None


async def remove_active_chat(user_id, partner_id):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", user_id, partner_id)


async def main_menu_keyboard(lang):
    online = await get_online_count()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("find_partner", lang), callback_data="find_partner"),
         InlineKeyboardButton(t("group_rooms", lang), callback_data="group_menu")],
        [InlineKeyboardButton(t("my_profile", lang), callback_data="my_profile"),
         InlineKeyboardButton(t("edit_profile", lang), callback_data="edit_profile")],
        [InlineKeyboardButton(t("coins", lang), callback_data="show_coins"),
         InlineKeyboardButton(t("vip", lang), callback_data="show_vip")],
        [InlineKeyboardButton(t("invite", lang), callback_data="show_link"),
         InlineKeyboardButton(t("leaderboard", lang), callback_data="leaderboard")],
        [InlineKeyboardButton(t("language", lang), callback_data="change_language"),
         InlineKeyboardButton(f"🟢 {online}", callback_data="refresh_online")],
        [InlineKeyboardButton(t("safety", lang), callback_data="safety"),
         InlineKeyboardButton(t("help", lang), callback_data="help")],
    ])


async def chat_keyboard(partner_id, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("next_person", lang), callback_data="next_partner"),
         InlineKeyboardButton(t("end_chat", lang), callback_data="end_chat")],
        [InlineKeyboardButton(t("report", lang), callback_data=f"report_{partner_id}")],
    ])


# ============================================================
# QUEUE TIMEOUT
# ============================================================
async def queue_timeout_check(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data['user_id']
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        still = await conn.fetchrow("SELECT 1 FROM match_queue WHERE user_id = $1", user_id)
        active = await conn.fetchrow("SELECT 1 FROM active_chats WHERE user_id = $1", user_id)
    if still and not active:
        try:
            await context.bot.send_message(
                user_id,
                t("no_partner_ai", lang),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                    [InlineKeyboardButton("🔗 Invite", callback_data="show_link")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
                ])
            )
        except Exception as e:
            logger.error(f"Timeout notify: {e}")


# ============================================================
# CHAT TIMER
# ============================================================
async def chat_timer_warning(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data['user_id']
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if chat:
        try:
            await context.bot.send_message(user_id, t("chat_timer_warning", lang))
        except Exception:
            pass


async def chat_timer_end(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data['user_id']
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        return
    partner_id = chat['partner_id']
    await remove_active_chat(user_id, partner_id)
    try:
        await context.bot.send_message(user_id, t("chat_timer_ended", lang), reply_markup=await main_menu_keyboard(lang))
        p_lang = await get_user_lang(partner_id)
        await context.bot.send_message(partner_id, t("chat_timer_ended", p_lang), reply_markup=await main_menu_keyboard(p_lang))
    except Exception:
        pass


# ============================================================
# /start
# ============================================================
async def start(update, context):
    user_id = update.effective_user.id
    await touch_user(user_id)

    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned / আপনি ব্যান হয়েছেন।")
        return

    args = context.args or []
    referrer_id = None
    if args and args[0].startswith("ref_"):
        try:
            parsed = int(args[0][4:])
            if parsed != user_id:
                referrer_id = parsed
        except (ValueError, IndexError):
            referrer_id = None

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            if referrer_id:
                try:
                    success = await process_referral(user_id, referrer_id)
                    if success:
                        ref_lang = await get_user_lang(referrer_id)
                        await context.bot.send_message(referrer_id, t("referral_bonus", ref_lang, coins=REFERRAL_COIN_REWARD))
                except Exception as e:
                    logger.error(f"Referral: {e}")
            context.user_data.clear()
            context.user_data['reg_step'] = 'language'
            await update.message.reply_text(
                t("language_select", "bn"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
                    [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
                ])
            )
            return

    lang = user.get('language') or 'bn'

    if referrer_id:
        async with db_pool.acquire() as conn:
            already_ref = await conn.fetchval("SELECT referred_by FROM users WHERE user_id = $1", user_id)
        if already_ref is None:
            success = await process_referral(user_id, referrer_id)
            if success:
                try:
                    ref_lang = await get_user_lang(referrer_id)
                    await context.bot.send_message(referrer_id, t("referral_bonus", ref_lang, coins=REFERRAL_COIN_REWARD))
                except Exception:
                    pass

    if await try_daily_bonus(user_id):
        await update.message.reply_text(t("daily_bonus", lang, coins=DAILY_BONUS_COINS))

    profile = await get_profile(user_id)
    if not profile or not profile.get('display_name'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'name'
        await update.message.reply_text(t("ask_name", lang))
        return
    if not profile.get('age'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text(t("ask_age", lang))
        return
    if not profile.get('gender'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'gender'
        await update.message.reply_text(
            t("ask_gender", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("male", lang), callback_data="gender_male")],
                [InlineKeyboardButton(t("female", lang), callback_data="gender_female")],
                [InlineKeyboardButton(t("other", lang), callback_data="gender_other")]
            ])
        )
        return
    if not profile.get('pref_gender'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'pref_gender'
        await update.message.reply_text(
            t("ask_pref", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("male", lang), callback_data="pref_male")],
                [InlineKeyboardButton(t("female", lang), callback_data="pref_female")],
                [InlineKeyboardButton(t("any", lang), callback_data="pref_any")]
            ])
        )
        return
    if not profile.get('interest'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'interest'
        await update.message.reply_text(
            t("ask_interest", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 Music", callback_data="int_music"),
                 InlineKeyboardButton("🎬 Movie", callback_data="int_movie")],
                [InlineKeyboardButton("📚 Study", callback_data="int_study"),
                 InlineKeyboardButton("🎮 Gaming", callback_data="int_gaming")],
                [InlineKeyboardButton("💕 Love", callback_data="int_love"),
                 InlineKeyboardButton("🌍 Any", callback_data="int_any")],
            ])
        )
        return
    if not profile.get('pref_language'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'pref_language'
        await update.message.reply_text(
            t("ask_lang_pref", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🇧🇩 Bangla", callback_data="plang_bn"),
                 InlineKeyboardButton("🇬🇧 English", callback_data="plang_en")],
                [InlineKeyboardButton("🇮🇳 Hindi", callback_data="plang_hi"),
                 InlineKeyboardButton("🌍 Any", callback_data="plang_any")],
            ])
        )
        return

    chat = await get_active_chat(user_id)
    if chat:
        await update.message.reply_text(t("already_in_chat", lang), reply_markup=await chat_keyboard(chat['partner_id'], lang))
        return

    online = await get_online_count()
    await update.message.reply_text(
        f"{t('main_menu', lang)}\n\n{t('online_count', lang, n=online)}",
        reply_markup=await main_menu_keyboard(lang)
    )


# ============================================================
# LANGUAGE
# ============================================================
async def language_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = "bn" if query.data == "lang_bn" else "en"
    await set_user_lang(user_id, lang)
    
    # If existing user (has profile), just switch and go to menu
    profile = await get_profile(user_id)
    if profile and profile.get('display_name'):
        online = await get_online_count()
        try:
            await query.edit_message_text(
                f"{t('language_changed', lang)}\n\n{t('main_menu', lang)}\n\n{t('online_count', lang, n=online)}",
                reply_markup=await main_menu_keyboard(lang)
            )
        except Exception:
            await query.message.reply_text(
                t("main_menu", lang),
                reply_markup=await main_menu_keyboard(lang)
            )
        return
    
    # New user - continue with age gate
    context.user_data['reg_step'] = 'age_gate'
    await query.edit_message_text(
        t("welcome", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("age_yes", lang), callback_data="age_yes")],
            [InlineKeyboardButton(t("age_no", lang), callback_data="age_no")]
        ])
    )


async def change_language(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        t("language_select", "bn"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ])
    )


async def age_gate_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    if query.data == "age_yes":
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_18_plus = TRUE WHERE user_id = $1", user_id)
        context.user_data['reg_step'] = 'name'
        await query.edit_message_text(t("ask_name", lang))
    else:
        await query.edit_message_text(t("age_denied", lang))


# ============================================================
# TEXT HANDLER
# ============================================================
async def handle_text(update, context):
    user_id = update.effective_user.id
    await touch_user(user_id)

    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned.")
        return

    lang = await get_user_lang(user_id)
    step = context.user_data.get('reg_step')
    text = update.message.text.strip() if update.message.text else ""

    if step == 'name':
        if len(text) < 2 or len(text) > 50:
            await update.message.reply_text("⚠️ Name 2-50 chars")
            return
        await save_profile(user_id, display_name=text)
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text(t("ask_age", lang))
        return

    if step == 'age':
        if not text.isdigit() or int(text) < 18 or int(text) > 99:
            await update.message.reply_text("⚠️ Age 18-99")
            return
        await save_profile(user_id, age=int(text))
        context.user_data['reg_step'] = 'gender'
        await update.message.reply_text(
            t("ask_gender", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("male", lang), callback_data="gender_male")],
                [InlineKeyboardButton(t("female", lang), callback_data="gender_female")],
                [InlineKeyboardButton(t("other", lang), callback_data="gender_other")]
            ])
        )
        return

    if step == 'bio':
        await save_profile(user_id, bio=text[:200])
        context.user_data['reg_step'] = None
        online = await get_online_count()
        await update.message.reply_text(
            f"{t('reg_done', lang)}\n\n{t('online_count', lang, n=online)}",
            reply_markup=await main_menu_keyboard(lang)
        )
        return

    if step in ('gender', 'pref_gender', 'interest', 'pref_language'):
        await update.message.reply_text("⚠️ Use buttons above")
        return

    edit_step = context.user_data.get('edit_step')
    if edit_step:
        if edit_step == 'name':
            await save_profile(user_id, display_name=text[:50])
        elif edit_step == 'bio':
            await save_profile(user_id, bio=text[:200])
        context.user_data.pop('edit_step', None)
        await update.message.reply_text(t("profile_saved", lang))
        return

    await handle_chat_message(update, context)


# ============================================================
# GENDER / PREF / INTEREST / LANG
# ============================================================
async def gender_callback(update, context):
    query = update.callback_query
    await query.answer()
    gender = query.data.split("_")[1]
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await save_profile(user_id, gender=gender)
    context.user_data['reg_step'] = 'pref_gender'
    await query.edit_message_text(
        t("ask_pref", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("male", lang), callback_data="pref_male")],
            [InlineKeyboardButton(t("female", lang), callback_data="pref_female")],
            [InlineKeyboardButton(t("any", lang), callback_data="pref_any")]
        ])
    )


async def pref_gender_callback(update, context):
    query = update.callback_query
    await query.answer()
    pref = query.data.split("_")[1]
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await save_profile(user_id, pref_gender=pref)
    context.user_data['reg_step'] = 'interest'
    await query.edit_message_text(
        t("ask_interest", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Music", callback_data="int_music"),
             InlineKeyboardButton("🎬 Movie", callback_data="int_movie")],
            [InlineKeyboardButton("📚 Study", callback_data="int_study"),
             InlineKeyboardButton("🎮 Gaming", callback_data="int_gaming")],
            [InlineKeyboardButton("💕 Love", callback_data="int_love"),
             InlineKeyboardButton("🌍 Any", callback_data="int_any")],
        ])
    )


async def interest_callback(update, context):
    query = update.callback_query
    await query.answer()
    interest = query.data.split("_")[1]
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await save_profile(user_id, interest=interest)
    context.user_data['reg_step'] = 'pref_language'
    await query.edit_message_text(
        t("ask_lang_pref", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 Bangla", callback_data="plang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="plang_en")],
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="plang_hi"),
             InlineKeyboardButton("🌍 Any", callback_data="plang_any")],
        ])
    )


async def pref_lang_callback(update, context):
    query = update.callback_query
    await query.answer()
    plang = query.data.split("_")[1]
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await save_profile(user_id, pref_language=plang)
    context.user_data['reg_step'] = 'bio'
    await query.edit_message_text(t("ask_bio", lang))


# ============================================================
# MAIN MENU
# ============================================================
async def main_menu_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    online = await get_online_count()
    await query.edit_message_text(
        f"{t('main_menu', lang)}\n\n{t('online_count', lang, n=online)}",
        reply_markup=await main_menu_keyboard(lang)
    )


async def refresh_online(update, context):
    query = update.callback_query
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    online = await get_online_count()
    await query.answer(t("online_count", lang, n=online), show_alert=True)


# ============================================================
# FIND PARTNER
# ============================================================
async def find_partner(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await touch_user(user_id)
    lang = await get_user_lang(user_id)

    profile = await get_profile(user_id)
    if not profile:
        await query.edit_message_text(t("reg_first", lang))
        return

    existing = await get_active_chat(user_id)
    if existing:
        await query.edit_message_text(
            t("already_in_chat", lang),
            reply_markup=await chat_keyboard(existing['partner_id'], lang)
        )
        return

    if not await check_and_increment_chat_limit(user_id):
        await query.edit_message_text(
            t("chat_limit_reached", lang, n=MAX_DAILY_CHATS_FREE),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("vip", lang), callback_data="show_vip")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
            ])
        )
        return

    user_gender = profile.get('gender') or 'any'
    user_pref = profile.get('pref_gender') or 'any'
    user_interest = profile.get('interest') or 'any'
    user_plang = profile.get('pref_language') or 'any'
    user_vip = await is_vip(user_id)

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)

    async with db_pool.acquire() as conn:
        candidates = await conn.fetch("""
            SELECT mq.* FROM match_queue mq
            WHERE mq.user_id != $1
            AND NOT EXISTS (
                SELECT 1 FROM blocks
                WHERE (blocker_id = $1 AND blocked_id = mq.user_id)
                OR (blocker_id = mq.user_id AND blocked_id = $1)
            )
            ORDER BY mq.is_vip DESC, mq.queued_at ASC
            LIMIT 50
        """, user_id)

    def score_candidate(c):
        score = 0
        if user_pref == 'any' or c['gender'] == user_pref:
            score += 10
        else:
            return -1
        if c['pref_gender'] == 'any' or c['pref_gender'] == user_gender:
            score += 10
        else:
            return -1
        if user_interest != 'any' and c['interest'] == user_interest:
            score += 5
        if user_plang != 'any' and c['pref_language'] == user_plang:
            score += 3
        if c['is_vip']:
            score += 2
        return score

    best = None
    best_score = -1
    for c in candidates:
        s = score_candidate(c)
        if s > best_score:
            best = c
            best_score = s

    if best is not None and best_score >= 10:
        partner_id = best['user_id']
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM match_queue WHERE user_id = $1", partner_id)
            await conn.execute("""
                INSERT INTO active_chats (user_id, partner_id) VALUES ($1, $2), ($2, $1)
                ON CONFLICT (user_id) DO UPDATE SET partner_id = EXCLUDED.partner_id, started_at = CURRENT_TIMESTAMP, is_ai = FALSE
            """, user_id, partner_id)
            await conn.execute(
                "UPDATE users SET total_chats = total_chats + 1 WHERE user_id IN ($1, $2)",
                user_id, partner_id
            )

        partner_lang = await get_user_lang(partner_id)

        await query.edit_message_text(t("partner_found", lang), reply_markup=await chat_keyboard(partner_id, lang))
        try:
            await context.bot.send_message(partner_id, t("partner_found", partner_lang), reply_markup=await chat_keyboard(user_id, partner_lang))
        except Exception as e:
            logger.error(f"Notify partner: {e}")

        reward = CHAT_COIN_REWARD * 2 if user_vip else CHAT_COIN_REWARD
        await add_coins(user_id, reward)

        timer_sec = CHAT_TIMER_SECONDS * 2 if user_vip else CHAT_TIMER_SECONDS
        context.job_queue.run_once(chat_timer_warning, timer_sec - 120, data={'user_id': user_id}, name=f"warn1_{user_id}")
        context.job_queue.run_once(chat_timer_warning, timer_sec - 120, data={'user_id': partner_id}, name=f"warn2_{partner_id}")
        context.job_queue.run_once(chat_timer_end, timer_sec, data={'user_id': user_id}, name=f"end1_{user_id}")
        context.job_queue.run_once(chat_timer_end, timer_sec, data={'user_id': partner_id}, name=f"end2_{partner_id}")
    else:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO match_queue (user_id, gender, pref_gender, pref_language, interest, is_vip)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (user_id) DO UPDATE SET
                    queued_at = CURRENT_TIMESTAMP,
                    is_vip = EXCLUDED.is_vip,
                    pref_gender = EXCLUDED.pref_gender,
                    pref_language = EXCLUDED.pref_language,
                    interest = EXCLUDED.interest,
                    gender = EXCLUDED.gender
            """, user_id, user_gender, user_pref, user_plang, user_interest, user_vip)

        await query.edit_message_text(
            t("searching", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
                [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
            ])
        )

        job_name = f"queue_timeout_{user_id}"
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
        context.job_queue.run_once(queue_timeout_check, QUEUE_TIMEOUT_SECONDS, data={'user_id': user_id}, name=job_name)


# ============================================================
# CANCEL SEARCH
# ============================================================
async def cancel_search(update, context):
    query = update.callback_query
    await query.answer("Cancelled")
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)

        job_name = f"queue_timeout_{user_id}"
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()

        context.user_data.pop('searching', None)

        online = await get_online_count()
        await query.edit_message_text(
            f"{t('search_cancelled', lang)}\n\n{t('main_menu', lang)}\n\n{t('online_count', lang, n=online)}",
            reply_markup=await main_menu_keyboard(lang)
        )
    except Exception as e:
        logger.error(f"cancel_search error: {e}")
        try:
            await query.edit_message_text(t("main_menu", lang), reply_markup=await main_menu_keyboard(lang))
        except Exception:
            pass


# ============================================================
# AI CHAT
# ============================================================
async def ai_chat_start(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)

    if not groq_client:
        await query.answer("AI not available", show_alert=True)
        return

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
        await conn.execute("""
            INSERT INTO active_chats (user_id, partner_id, is_ai)
            VALUES ($1, $1, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET partner_id = $1, is_ai = TRUE, started_at = CURRENT_TIMESTAMP
        """, user_id)

    context.user_data['ai_history'] = []
    await query.edit_message_text(
        t("ai_mode_on", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 Stop AI", callback_data="end_chat")],
        ])
    )


# ============================================================
# CHAT MESSAGE
# ============================================================
async def handle_chat_message(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        return

    if is_rate_limited(user_id, max_requests=20, window_seconds=10):
        await update.message.reply_text(t("wait_moment", lang))
        return

    if update.message.text and contains_bad_words(update.message.text):
        await update.message.reply_text(t("spam_warning", lang))
        return

    if chat.get('is_ai'):
        await handle_ai_message(update, context, lang)
        return

    partner_id = chat['partner_id']

    room_id = context.user_data.get('room_id')
    if room_id:
        await handle_group_message(update, context, room_id)
        return

    try:
        await context.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=user_id,
            message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Copy failed: {e}")
        try:
            await update.message.reply_text("❌ Message not sent.")
        except Exception:
            pass


async def handle_ai_message(update, context, lang):
    user_id = update.effective_user.id
    text = update.message.text or ""
    if not text:
        await update.message.reply_text("🤖 Please send text.")
        return
    if contains_bad_words(text):
        await update.message.reply_text(t("spam_warning", lang))
        return

    typing_msg = await update.message.reply_text("🤖 Typing...")
    history = context.user_data.get('ai_history', [])
    history.append({"role": "user", "content": text})

    system = (
        "You are a friendly anonymous chat partner. "
        "Reply in the user's language (Bangla/English/Hindi). "
        "Keep replies short (under 300 chars). Be warm, funny, engaging. "
        "Use emojis. No markdown. No asterisks. Ask follow-up questions."
    )

    answer = None
    last_err = None
    for model_name in AI_MODELS:
        try:
            resp = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=model_name,
                messages=[{"role": "system", "content": system}] + history[-10:],
                temperature=0.8,
                max_tokens=400,
            )
            answer = resp.choices[0].message.content.strip()
            logger.info(f"AI model used: {model_name}")
            break
        except Exception as e:
            last_err = e
            logger.warning(f"AI model {model_name} failed: {e}")
            continue

    if not answer:
        logger.error(f"All AI models failed: {last_err}")
        await typing_msg.edit_text("🤖 AI is having issues. Try again.")
        return

    history.append({"role": "assistant", "content": answer})
    context.user_data['ai_history'] = history[-10:]
    await typing_msg.edit_text(answer)


# ============================================================
# GROUP ROOMS
# ============================================================
async def group_menu(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)

    async with db_pool.acquire() as conn:
        rooms = await conn.fetch("""
            SELECT r.room_id, COUNT(m.user_id) as cnt
            FROM group_rooms r
            LEFT JOIN group_members m ON m.room_id = r.room_id
            WHERE r.is_active = TRUE
            GROUP BY r.room_id
            HAVING COUNT(m.user_id) < $1
            ORDER BY r.room_id DESC
            LIMIT 5
        """, GROUP_ROOM_MAX)

    rows = []
    for r in rooms:
        rows.append([InlineKeyboardButton(
            f"👥 Room {r['room_id']} ({r['cnt']}/{GROUP_ROOM_MAX})",
            callback_data=f"joinroom_{r['room_id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Create New Room", callback_data="create_room")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])

    await query.edit_message_text(t("group_room_menu", lang), reply_markup=InlineKeyboardMarkup(rows))


async def create_room(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)

    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval("INSERT INTO group_rooms (host_id) VALUES ($1) RETURNING room_id", user_id)
        await conn.execute("INSERT INTO group_members (room_id, user_id) VALUES ($1, $2)", room_id, user_id)

    context.user_data['room_id'] = room_id
    await query.edit_message_text(
        f"✅ Room {room_id} created!\n\nID: {room_id}\n\nShare:\n/joinroom {room_id}\n\nSend /leaveroom to leave.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 Leave", callback_data="leave_room")],
        ])
    )


async def join_room_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    room_id = int(query.data.split("_")[1])

    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM group_rooms WHERE room_id = $1 AND is_active = TRUE", room_id)
        if not room:
            await query.edit_message_text(t("group_room_not_found", lang), reply_markup=await main_menu_keyboard(lang))
            return
        cnt = await conn.fetchval("SELECT COUNT(*) FROM group_members WHERE room_id = $1", room_id)
        if cnt >= GROUP_ROOM_MAX:
            await query.edit_message_text(t("group_room_full", lang), reply_markup=await main_menu_keyboard(lang))
            return
        await conn.execute("INSERT INTO group_members (room_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", room_id, user_id)

    context.user_data['room_id'] = room_id
    await query.edit_message_text(
        f"✅ Joined Room {room_id}!\n\nSend any message to the group.\n\n/leaveroom to exit.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 Leave", callback_data="leave_room")],
        ])
    )


async def join_room_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    if not context.args:
        await update.message.reply_text("Usage: /joinroom <id>")
        return
    try:
        room_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid room ID")
        return

    async with db_pool.acquire() as conn:
        room = await conn.fetchrow("SELECT * FROM group_rooms WHERE room_id = $1 AND is_active = TRUE", room_id)
        if not room:
            await update.message.reply_text(t("group_room_not_found", lang))
            return
        cnt = await conn.fetchval("SELECT COUNT(*) FROM group_members WHERE room_id = $1", room_id)
        if cnt >= GROUP_ROOM_MAX:
            await update.message.reply_text(t("group_room_full", lang))
            return
        await conn.execute("INSERT INTO group_members (room_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", room_id, user_id)

    context.user_data['room_id'] = room_id
    await update.message.reply_text(f"✅ Joined Room {room_id}!\n\n/leaveroom to exit.")


async def leave_room_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    room_id = context.user_data.pop('room_id', None)
    if room_id:
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM group_members WHERE room_id = $1 AND user_id = $2", room_id, user_id)
    await query.edit_message_text(t("group_room_left", lang), reply_markup=await main_menu_keyboard(lang))


async def leave_room_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    room_id = context.user_data.pop('room_id', None)
    if not room_id:
        await update.message.reply_text("❌ You're not in a room.")
        return
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM group_members WHERE room_id = $1 AND user_id = $2", room_id, user_id)
    await update.message.reply_text(t("group_room_left", lang))


async def handle_group_message(update, context, room_id):
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        members = await conn.fetch("SELECT user_id FROM group_members WHERE room_id = $1 AND user_id != $2", room_id, user_id)
    for m in members:
        try:
            await context.bot.copy_message(
                chat_id=m['user_id'],
                from_chat_id=user_id,
                message_id=update.message.message_id
            )
        except Exception as e:
            logger.error(f"Group send error: {e}")


# ============================================================
# END / NEXT
# ============================================================
async def end_chat_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        await query.edit_message_text(t("not_in_chat", lang), reply_markup=await main_menu_keyboard(lang))
        return
    partner_id = chat['partner_id']
    is_ai = chat.get('is_ai', False)

    await remove_active_chat(user_id, partner_id)

    for name in [f"warn1_{user_id}", f"warn2_{user_id}", f"end1_{user_id}", f"end2_{user_id}",
                 f"warn1_{partner_id}", f"warn2_{partner_id}", f"end1_{partner_id}", f"end2_{partner_id}"]:
        for job in context.job_queue.get_jobs_by_name(name):
            job.schedule_removal()

    await query.edit_message_text(t("chat_ended", lang), reply_markup=await main_menu_keyboard(lang))
    if not is_ai:
        try:
            p_lang = await get_user_lang(partner_id)
            await context.bot.send_message(partner_id, t("partner_ended", p_lang), reply_markup=await main_menu_keyboard(p_lang))
        except Exception:
            pass


async def next_partner(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)

    chat = await get_active_chat(user_id)
    if chat:
        partner_id = chat['partner_id']
        is_ai = chat.get('is_ai', False)
        await remove_active_chat(user_id, partner_id)

        for name in [f"warn1_{user_id}", f"warn2_{user_id}", f"end1_{user_id}", f"end2_{user_id}",
                     f"warn1_{partner_id}", f"warn2_{partner_id}", f"end1_{partner_id}", f"end2_{partner_id}"]:
            for job in context.job_queue.get_jobs_by_name(name):
                job.schedule_removal()

        if not is_ai:
            try:
                p_lang = await get_user_lang(partner_id)
                await context.bot.send_message(partner_id, t("partner_left", p_lang), reply_markup=await main_menu_keyboard(p_lang))
            except Exception:
                pass

    await query.edit_message_text("🔍...")
    await asyncio.sleep(0.5)
    await find_partner(update, context)


# ============================================================
# REPORT
# ============================================================
async def report_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    reported_id = int(query.data.split("_")[1])
    reasons = [
        ("Spam", "spam"), ("Harassment", "harassment"), ("Scam", "scam"),
        ("Fake profile", "fake"), ("Inappropriate", "inappropriate"),
        ("Underage", "underage"), ("Other", "other")
    ]
    rows = [[InlineKeyboardButton(r[0], callback_data=f"report_reason_{r[1]}_{reported_id}")] for r in reasons]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="end_chat")])
    await query.edit_message_text("⚠️ Report reason:", reply_markup=InlineKeyboardMarkup(rows))


async def report_reason_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    reason = parts[2]
    reported_id = int(parts[3])
    reporter_id = query.from_user.id
    lang = await get_user_lang(reporter_id)

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reports (reporter_id, reported_id, reason) VALUES ($1, $2, $3)", reporter_id, reported_id, reason)
        await conn.execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", reporter_id, reported_id)
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", reporter_id, reported_id)
        unique_reporters = await conn.fetchval(
            "SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE reported_id = $1 AND status = 'pending'",
            reported_id
        )
        if unique_reporters and unique_reporters >= AUTO_BAN_REPORT_COUNT:
            await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1", reported_id)
            await conn.execute("UPDATE reports SET status = 'actioned' WHERE reported_id = $1", reported_id)
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(admin_id, f"🚨 Auto-Ban\n👤 ID: {reported_id}\n📊 Reports: {unique_reporters}")
                except Exception:
                    pass

    await query.edit_message_text(t("report_blocked", lang), reply_markup=await main_menu_keyboard(lang))
    try:
        p_lang = await get_user_lang(reported_id)
        await context.bot.send_message(reported_id, t("partner_ended", p_lang), reply_markup=await main_menu_keyboard(p_lang))
    except Exception:
        pass


# ============================================================
# PROFILE / EDIT
# ============================================================
async def my_profile(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    profile = await get_profile(user_id)
    if not profile:
        await query.edit_message_text(t("reg_first", lang))
        return
    gender_map = {"male": "👦 Male", "female": "👧 Female", "other": "🌈 Other"}
    pref_map = {"male": "👦 Male", "female": "👧 Female", "any": "🌍 Any"}
    coins = await get_coins(user_id)
    vip_status = t("vip_active", lang) if await is_vip(user_id) else t("vip_inactive", lang)
    text = (
        f"👤 {profile.get('display_name', 'N/A')}\n"
        f"🎂 Age: {profile.get('age', 'N/A')}\n"
        f"⚧ Gender: {gender_map.get(profile.get('gender'), 'N/A')}\n"
        f"🎯 Pref: {pref_map.get(profile.get('pref_gender'), 'N/A')}\n"
        f"💡 Interest: {profile.get('interest', 'N/A')}\n"
        f"🌐 Lang Pref: {profile.get('pref_language', 'N/A')}\n"
        f"🪙 Coins: {coins}\n"
        f"⭐ VIP: {vip_status}\n\n"
        f"💬 Bio: {(profile.get('bio') or 'N/A')[:200]}"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("edit_profile", lang), callback_data="edit_profile")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )


async def edit_profile(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await query.edit_message_text(
        "✏️ Edit Profile:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📛 Change Name", callback_data="edit_name")],
            [InlineKeyboardButton("📝 Change Bio", callback_data="edit_bio")],
            [InlineKeyboardButton("🎯 Change Pref Gender", callback_data="edit_pref_gender")],
            [InlineKeyboardButton("💡 Change Interest", callback_data="edit_interest")],
            [InlineKeyboardButton("🌐 Change Lang Pref", callback_data="edit_lang")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
        ])
    )


async def edit_name(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_step'] = 'name'
    await query.edit_message_text("✏️ Send new name:")


async def edit_bio(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_step'] = 'bio'
    await query.edit_message_text("✏️ Send new bio (max 200):")


async def edit_pref_gender(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await query.edit_message_text(
        "🎯 Choose:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("male", lang), callback_data="setpg_male")],
            [InlineKeyboardButton(t("female", lang), callback_data="setpg_female")],
            [InlineKeyboardButton(t("any", lang), callback_data="setpg_any")],
        ])
    )


async def set_pref_gender_edit(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    pref = query.data.split("_")[1]
    await save_profile(user_id, pref_gender=pref)
    await query.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_keyboard(lang))


async def edit_interest(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💡 Choose:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Music", callback_data="setint_music"),
             InlineKeyboardButton("🎬 Movie", callback_data="setint_movie")],
            [InlineKeyboardButton("📚 Study", callback_data="setint_study"),
             InlineKeyboardButton("🎮 Gaming", callback_data="setint_gaming")],
            [InlineKeyboardButton("💕 Love", callback_data="setint_love"),
             InlineKeyboardButton("🌍 Any", callback_data="setint_any")],
        ])
    )


async def set_interest_edit(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    interest = query.data.split("_")[1]
    await save_profile(user_id, interest=interest)
    await query.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_keyboard(lang))


async def edit_lang(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🌐 Choose:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 Bangla", callback_data="setplang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="setplang_en")],
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="setplang_hi"),
             InlineKeyboardButton("🌍 Any", callback_data="setplang_any")],
        ])
    )


async def set_plang_edit(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    plang = query.data.split("_")[1]
    await save_profile(user_id, pref_language=plang)
    await query.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_keyboard(lang))


# ============================================================
# SAFETY / HELP
# ============================================================
async def safety_callback(update, context):
    query = update.callback_query
    await query.answer()
    lang = await get_user_lang(query.from_user.id)
    if lang == 'bn':
        text = ("🛡 নিরাপত্তা টিপস\n\n"
                "• কখনো পাসওয়ার্ড বা OTP শেয়ার করবেন না\n"
                "• অনলাইনে কাউকে টাকা পাঠাবেন না\n"
                "• বাড়ির ঠিকানা/GPS শেয়ার করবেন না\n"
                "• সন্দেহজনক লিংকে ক্লিক করবেন না\n"
                "• খারাপ ব্যবহার হলে Report করুন\n\n"
                "🚫 ৫টি রিপোর্ট = অটো-ব্যান\n"
                "🚫 খারাপ শব্দ স্বয়ংক্রিয় ফিল্টার")
    else:
        text = ("🛡 Safety Tips\n\n"
                "• Never share passwords or OTPs\n"
                "• Never send money online\n"
                "• Don't share home address/GPS\n"
                "• Don't click suspicious links\n"
                "• Report bad behavior\n\n"
                "🚫 5 reports = auto-ban\n"
                "🚫 Bad words auto-filtered")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
    ]))


async def help_callback(update, context):
    query = update.callback_query
    await query.answer()
    lang = await get_user_lang(query.from_user.id)
    if lang == 'bn':
        text = ("📖 সাহায্য\n\n"
                "/start — মেইন মেনু\n/stop — চ্যাট শেষ\n/reset — প্রোফাইল রিসেট\n"
                "/stats — পরিসংখ্যান\n/link — ইনভাইট লিংক\n/coins — কয়েন\n"
                "/vip — VIP কিনুন\n/leaderboard — টপ চ্যাটার\n/language — ভাষা\n"
                "/joinroom — Group room join\n/leaveroom — Group থেকে বের\n\n"
                "🔒 সম্পূর্ণ Anonymous।")
    else:
        text = ("📖 Help\n\n"
                "/start — Main menu\n/stop — End chat\n/reset — Reset profile\n"
                "/stats — Statistics\n/link — Invite link\n/coins — Coins\n"
                "/vip — Buy VIP\n/leaderboard — Top chatters\n/language — Change language\n"
                "/joinroom — Join group room\n/leaveroom — Leave group\n\n"
                "🔒 Fully anonymous.")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
    ]))


# ============================================================
# COINS / VIP
# ============================================================
async def show_coins(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    coins = await get_coins(user_id)
    vip_status = t("vip_active", lang) if await is_vip(user_id) else t("vip_inactive", lang)
    await query.edit_message_text(
        t("coins_balance", lang, coins=coins, vip=vip_status),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
            [InlineKeyboardButton("⭐ VIP", callback_data="show_vip")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )


async def show_vip(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    if await is_vip(user_id):
        await query.edit_message_text(t("already_vip", lang), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ]))
        return
    await query.edit_message_text(
        t("vip_buy_msg", lang, price=VIP_PRICE_COINS, stars=VIP_STARS_PRICE, days=VIP_DURATION_DAYS),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("buy_with_coins", lang), callback_data="vip_coins")],
            [InlineKeyboardButton(t("buy_with_stars", lang), callback_data="vip_stars")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )


async def vip_with_coins(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    if await is_vip(user_id):
        await query.edit_message_text(t("already_vip", lang))
        return
    coins = await get_coins(user_id)
    if coins < VIP_PRICE_COINS:
        await query.edit_message_text(
            t("not_enough_coins", lang, need=VIP_PRICE_COINS, have=coins),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
            ])
        )
        return
    if await deduct_coins(user_id, VIP_PRICE_COINS):
        await set_vip(user_id, VIP_DURATION_DAYS)
        await query.edit_message_text(t("vip_bought", lang, days=VIP_DURATION_DAYS), reply_markup=await main_menu_keyboard(lang))


async def vip_with_stars(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    if await is_vip(user_id):
        await query.edit_message_text(t("already_vip", lang))
        return
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title="⭐ VIP Subscription",
            description=f"{VIP_DURATION_DAYS} days VIP access",
            payload=f"vip_{user_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="VIP", amount=VIP_STARS_PRICE)]
        )
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await query.answer("❌ Payment failed. Try again.", show_alert=True)


async def precheckout_callback(update, context):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    await set_vip(user_id, VIP_DURATION_DAYS)
    await update.message.reply_text(t("vip_bought", lang, days=VIP_DURATION_DAYS), reply_markup=await main_menu_keyboard(lang))


# ============================================================
# LINK / REFERRAL
# ============================================================
async def show_link(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{user_id}"
    await query.edit_message_text(
        t("referral_msg", lang, link=link, coins=REFERRAL_COIN_REWARD),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )


async def link_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{user_id}"
    await update.message.reply_text(t("referral_msg", lang, link=link, coins=REFERRAL_COIN_REWARD))


async def coins_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    coins = await get_coins(user_id)
    vip_status = t("vip_active", lang) if await is_vip(user_id) else t("vip_inactive", lang)
    await update.message.reply_text(t("coins_balance", lang, coins=coins, vip=vip_status))


async def vip_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    if await is_vip(user_id):
        await update.message.reply_text(t("already_vip", lang))
        return
    await update.message.reply_text(
        t("vip_buy_msg", lang, price=VIP_PRICE_COINS, stars=VIP_STARS_PRICE, days=VIP_DURATION_DAYS),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("buy_with_coins", lang), callback_data="vip_coins")],
            [InlineKeyboardButton(t("buy_with_stars", lang), callback_data="vip_stars")]
        ])
    )


async def language_command(update, context):
    await update.message.reply_text(
        t("language_select", "bn"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ])
    )


# ============================================================
# LEADERBOARD
# ============================================================
async def leaderboard(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, p.display_name, u.total_chats
            FROM users u JOIN profiles p ON p.user_id = u.user_id
            WHERE u.total_chats > 0
            ORDER BY u.total_chats DESC LIMIT 10
        """)
    if not rows:
        await query.edit_message_text(t("leaderboard_empty", lang), reply_markup=await main_menu_keyboard(lang))
        return
    text = t("leaderboard_title", lang) + "\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        name = r['display_name'] or f"User{r['user_id']}"
        text += f"{m} {name} — {r['total_chats']} chats\n"
    await query.edit_message_text(text, reply_markup=await main_menu_keyboard(lang))


async def leaderboard_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, p.display_name, u.total_chats
            FROM users u JOIN profiles p ON p.user_id = u.user_id
            WHERE u.total_chats > 0
            ORDER BY u.total_chats DESC LIMIT 10
        """)
    if not rows:
        await update.message.reply_text(t("leaderboard_empty", lang))
        return
    text = t("leaderboard_title", lang) + "\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        name = r['display_name'] or f"User{r['user_id']}"
        text += f"{m} {name} — {r['total_chats']} chats\n"
    await update.message.reply_text(text)


# ============================================================
# STOP / RESET / STATS
# ============================================================
async def stop_chat(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        await update.message.reply_text(t("not_in_chat", lang))
        return
    partner_id = chat['partner_id']
    is_ai = chat.get('is_ai', False)
    await remove_active_chat(user_id, partner_id)
    for name in [f"warn1_{user_id}", f"warn2_{user_id}", f"end1_{user_id}", f"end2_{user_id}",
                 f"warn1_{partner_id}", f"warn2_{partner_id}", f"end1_{partner_id}", f"end2_{partner_id}"]:
        for job in context.job_queue.get_jobs_by_name(name):
            job.schedule_removal()
    await update.message.reply_text(t("chat_ended", lang), reply_markup=await main_menu_keyboard(lang))
    if not is_ai:
        try:
            p_lang = await get_user_lang(partner_id)
            await context.bot.send_message(partner_id, t("partner_ended", p_lang), reply_markup=await main_menu_keyboard(p_lang))
        except Exception:
            pass


async def reset_command(update, context):
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM profiles WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM group_members WHERE user_id = $1", user_id)
    context.user_data.clear()
    await update.message.reply_text("🔄 Reset. /start")


async def stats_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        online = await get_online_count()
        in_queue = await conn.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        active_chats = (await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
    if lang == 'bn':
        text = (f"📊 পরিসংখ্যান\n\n👥 মোট ইউজার: {total_users}\n🟢 অনলাইনে: {online}\n"
                f"⏳ খুঁজছেন: {in_queue}\n💬 চলমান চ্যাট: {active_chats}")
    else:
        text = (f"📊 Statistics\n\n👥 Total: {total_users}\n🟢 Online: {online}\n"
                f"⏳ Searching: {in_queue}\n💬 Active: {active_chats}")
    await update.message.reply_text(text)


# ============================================================
# ADMIN
# ============================================================
async def admin_stats(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Not admin.")
        return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        online = await get_online_count()
        in_queue = await conn.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        active_chats = (await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
        pending = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'pending'") or 0
        banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE") or 0
        vip_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_vip = TRUE") or 0
        total_coins = await conn.fetchval("SELECT SUM(coins) FROM users") or 0
        group_rooms = await conn.fetchval("SELECT COUNT(*) FROM group_rooms WHERE is_active = TRUE") or 0
    await update.message.reply_text(
        f"📊 Admin Dashboard\n\n"
        f"👥 Users: {total_users}\n🟢 Online: {online}\n⏳ Queue: {in_queue}\n"
        f"💬 Chats: {active_chats}\n👥 Group Rooms: {group_rooms}\n"
        f"⚠️ Reports: {pending}\n🚫 Banned: {banned}\n⭐ VIP: {vip_count}\n"
        f"🪙 Total Coins: {total_coins}"
    )


async def ban_command(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID")
        return
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1", target)
    await update.message.reply_text(f"✅ Banned: {target}")


async def unban_command(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID")
        return
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = FALSE WHERE user_id = $1", target)
    await update.message.reply_text(f"✅ Unbanned: {target}")


async def broadcast_command(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE is_banned = FALSE")
    sent, failed = 0, 0
    for u in users:
        try:
            await context.bot.send_message(u['user_id'], f"📢 {msg}")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ Sent: {sent} | ❌ Failed: {failed}")


# ============================================================
# MAIN
# ============================================================
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    threading.Thread(target=run_flask, daemon=True).start()

    async def post_init(app):
        await init_db()

    async def post_shutdown(app):
        await close_db()

    request = HTTPXRequest(connection_pool_size=20)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("coins", coins_command))
    app.add_handler(CommandHandler("vip", vip_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("joinroom", join_room_command))
    app.add_handler(CommandHandler("leaveroom", leave_room_command))
    app.add_handler(CommandHandler("adminstats", admin_stats))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # Callbacks (specific first)
    app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(change_language, pattern="^change_language$"))
    app.add_handler(CallbackQueryHandler(age_gate_callback, pattern="^age_"))
    app.add_handler(CallbackQueryHandler(gender_callback, pattern="^gender_"))
    app.add_handler(CallbackQueryHandler(pref_gender_callback, pattern="^pref_"))
    app.add_handler(CallbackQueryHandler(interest_callback, pattern="^int_"))
    app.add_handler(CallbackQueryHandler(pref_lang_callback, pattern="^plang_"))

    app.add_handler(CallbackQueryHandler(set_pref_gender_edit, pattern="^setpg_"))
    app.add_handler(CallbackQueryHandler(set_interest_edit, pattern="^setint_"))
    app.add_handler(CallbackQueryHandler(set_plang_edit, pattern="^setplang_"))
    app.add_handler(CallbackQueryHandler(edit_name, pattern="^edit_name$"))
    app.add_handler(CallbackQueryHandler(edit_bio, pattern="^edit_bio$"))
    app.add_handler(CallbackQueryHandler(edit_pref_gender, pattern="^edit_pref_gender$"))
    app.add_handler(CallbackQueryHandler(edit_interest, pattern="^edit_interest$"))
    app.add_handler(CallbackQueryHandler(edit_lang, pattern="^edit_lang$"))
    app.add_handler(CallbackQueryHandler(edit_profile, pattern="^edit_profile$"))

    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(refresh_online, pattern="^refresh_online$"))
    app.add_handler(CallbackQueryHandler(find_partner, pattern="^find_partner$"))
    app.add_handler(CallbackQueryHandler(cancel_search, pattern="^cancel_search$"))
    app.add_handler(CallbackQueryHandler(ai_chat_start, pattern="^ai_chat$"))
    app.add_handler(CallbackQueryHandler(show_link, pattern="^show_link$"))
    app.add_handler(CallbackQueryHandler(show_coins, pattern="^show_coins$"))
    app.add_handler(CallbackQueryHandler(show_vip, pattern="^show_vip$"))
    app.add_handler(CallbackQueryHandler(vip_with_coins, pattern="^vip_coins$"))
    app.add_handler(CallbackQueryHandler(vip_with_stars, pattern="^vip_stars$"))
    app.add_handler(CallbackQueryHandler(end_chat_callback, pattern="^end_chat$"))
    app.add_handler(CallbackQueryHandler(next_partner, pattern="^next_partner$"))
    app.add_handler(CallbackQueryHandler(report_reason_callback, pattern="^report_reason_"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))
    app.add_handler(CallbackQueryHandler(my_profile, pattern="^my_profile$"))
    app.add_handler(CallbackQueryHandler(safety_callback, pattern="^safety$"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(leaderboard, pattern="^leaderboard$"))

    app.add_handler(CallbackQueryHandler(group_menu, pattern="^group_menu$"))
    app.add_handler(CallbackQueryHandler(create_room, pattern="^create_room$"))
    app.add_handler(CallbackQueryHandler(join_room_callback, pattern="^joinroom_"))
    app.add_handler(CallbackQueryHandler(leave_room_callback, pattern="^leave_room$"))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    app.add_handler(MessageHandler(~filters.COMMAND, handle_text))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
