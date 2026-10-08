import os
import logging
import asyncio
import threading
import random
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
    raise RuntimeError("BOT_TOKEN and DATABASE_URL required.")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("anon-chat-bot")

flask_app = Flask(__name__)


@flask_app.route('/')
def health():
    return "OK", 200


def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)


db_pool = None
groq_client = Groq(api_key=GROQ_API_KEY) if (HAS_GROQ and GROQ_API_KEY) else None

AI_MODELS = ["openai/gpt-oss-120b", "llama-3.1-8b-instant", "llama3-8b-8192"]

# ============================================================
# PAYMENT INFO
# ============================================================
BKASH_NUMBER = "01608364088"
ROCKET_NUMBER = "01608364088"
BINANCE_ID = "1076189034"
USDT_BSC20 = "0xb83a03d9ded3ac7a4908aa87cfdfe1df9e05f719"
USDT_TRC20 = "TKeEd3wuTqHse2rdzAg3rqYeRfQD1NC7tq"

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
MAX_DAILY_CHATS_FREE = 20
GROUP_ROOM_MAX = 10
GROUP_ROOM_MIN = 3

# Premium Tiers
PREMIUM_TIERS = {
    "bronze": {"name": "🥉 Bronze", "price_bdt": 99, "days": 30, "coins": 50, "emoji": "🥉",
               "features": "Ads-free • 50 Coins • Priority +1"},
    "silver": {"name": "🥈 Silver", "price_bdt": 199, "days": 30, "coins": 150, "emoji": "🥈",
               "features": "Bronze + Advanced Filters + 2x Coins + Unlimited Chats"},
    "gold": {"name": "🥇 Gold", "price_bdt": 499, "days": 30, "coins": 500, "emoji": "🥇",
             "features": "Silver + Verified Badge + Super Chat + Friends List + Priority"},
    "diamond": {"name": "💎 Diamond", "price_bdt": 999, "days": 30, "coins": 1500, "emoji": "💎",
                "features": "Gold + AI Translation + Voice Notes + Public Rooms"},
}

# XP Levels
XP_PER_CHAT = 10
XP_PER_MESSAGE = 1
LEVEL_THRESHOLDS = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500, 5500, 6600, 7800, 9100, 10500]

# Achievements
ACHIEVEMENTS = {
    "first_chat": ("🎉", "First Chat", "Complete your first chat"),
    "chats_10": ("💬", "Chatter", "Complete 10 chats"),
    "chats_50": ("🗣️", "Talkative", "Complete 50 chats"),
    "chats_100": ("🏆", "Chat Master", "Complete 100 chats"),
    "chats_500": ("👑", "Legend", "Complete 500 chats"),
    "invite_1": ("🎁", "Inviter", "Invite 1 friend"),
    "invite_5": ("🔥", "Recruiter", "Invite 5 friends"),
    "invite_25": ("💎", "Influencer", "Invite 25 friends"),
    "streak_7": ("🔥", "Week Warrior", "7-day streak"),
    "streak_30": ("💪", "Month Master", "30-day streak"),
    "coins_100": ("🪙", "Rich", "Earn 100 coins"),
    "coins_1000": ("💰", "Wealthy", "Earn 1000 coins"),
    "premium": ("⭐", "Premium", "Become a premium member"),
    "level_5": ("📈", "Rising Star", "Reach level 5"),
    "level_10": ("🌟", "Superstar", "Reach level 10"),
}

# Daily Missions
DAILY_MISSIONS = {
    "chat_3": {"text": "Complete 3 chats", "reward": 30, "target": 3},
    "msg_20": {"text": "Send 20 messages", "reward": 20, "target": 20},
    "invite_1": {"text": "Invite 1 friend", "reward": 50, "target": 1},
}

BANNED_WORDS = ["fuck", "shit", "bitch", "asshole", "dick", "pussy", "bastard",
                "madarchod", "bhadwa", "chutiya", "chod", "harami", "kutta", "kuti"]

# ============================================================
# LANGUAGE STRINGS
# ============================================================
STRINGS = {
    "welcome": {"bn": "👋 স্বাগতম! এটি একটি অ্যানোনিমাস চ্যাটিং বট।\n\nশুরু করার আগে নিশ্চিত করুন যে আপনার বয়স ১৮+।", "en": "👋 Welcome! This is an anonymous chat bot.\n\nPlease confirm that you are 18+."},
    "age_yes": {"bn": "✅ হ্যাঁ, আমি ১৮+", "en": "✅ Yes, I am 18+"},
    "age_no": {"bn": "❌ না", "en": "❌ No"},
    "age_denied": {"bn": "❌ এই বট শুধুমাত্র ১৮+ ব্যবহারকারীদের জন্য।", "en": "❌ This bot is only for 18+ users."},
    "ask_name": {"bn": "✅ ধন্যবাদ! এখন আপনার নাম লিখুন:", "en": "✅ Thanks! Now enter your name:"},
    "ask_age": {"bn": "🎂 আপনার বয়স লিখুন (শুধু সংখ্যা):", "en": "🎂 Enter your age (numbers only):"},
    "ask_gender": {"bn": "⚧ জেন্ডার নির্বাচন করুন:", "en": "⚧ Select your gender:"},
    "ask_pref": {"bn": "🎯 কার সাথে চ্যাট করতে চান?", "en": "🎯 Who do you want to chat with?"},
    "ask_interest": {"bn": "💡 আগ্রহ নির্বাচন করুন:", "en": "💡 Select your interest:"},
    "ask_lang_pref": {"bn": "🌐 কোন ভাষার পার্টনার চান?", "en": "🌐 Which language partner?"},
    "ask_bio": {"bn": "📝 ছোট বায়ো লিখুন (max 200):", "en": "📝 Write a short bio (max 200):"},
    "male": {"bn": "👦 ছেলে", "en": "👦 Male"},
    "female": {"bn": "👧 মেয়ে", "en": "👧 Female"},
    "other": {"bn": "🌈 অন্যান্য", "en": "🌈 Other"},
    "any": {"bn": "🌍 যে কেউ", "en": "🌍 Anyone"},
    "main_menu": {"bn": "🏠 মেইন মেনু:", "en": "🏠 Main Menu:"},
    "find_partner": {"bn": "🔍 Find Partner", "en": "🔍 Find Partner"},
    "group_rooms": {"bn": "👥 Group Rooms", "en": "👥 Group Rooms"},
    "my_profile": {"bn": "👤 My Profile", "en": "👤 My Profile"},
    "edit_profile": {"bn": "✏️ Edit Profile", "en": "✏️ Edit Profile"},
    "safety": {"bn": "🛡 Safety", "en": "🛡 Safety"},
    "help": {"bn": "ℹ️ Help", "en": "ℹ️ Help"},
    "coins": {"bn": "🪙 Coins", "en": "🪙 Coins"},
    "vip": {"bn": "⭐ Premium", "en": "⭐ Premium"},
    "invite": {"bn": "🔗 Invite", "en": "🔗 Invite"},
    "leaderboard": {"bn": "🏆 Leaderboard", "en": "🏆 Leaderboard"},
    "language": {"bn": "🌐 ভাষা", "en": "🌐 Language"},
    "achievements": {"bn": "🏅 Achievements", "en": "🏅 Achievements"},
    "missions": {"bn": "🎯 Daily Missions", "en": "🎯 Daily Missions"},
    "friends": {"bn": "👫 Friends", "en": "👫 Friends"},
    "end_chat": {"bn": "🛑 End Chat", "en": "🛑 End Chat"},
    "next_person": {"bn": "➡️ Next Person", "en": "➡️ Next Person"},
    "report": {"bn": "🚫 Report", "en": "🚫 Report"},
    "reg_done": {"bn": "✅ রেজিস্ট্রেশন সম্পন্ন! 🎉", "en": "✅ Registration complete! 🎉"},
    "searching": {"bn": "⏳ পার্টনার খোঁজা হচ্ছে...", "en": "⏳ Searching for partner..."},
    "partner_found": {"bn": "✅ পার্টনার পাওয়া গেছে!\n\n💬 এখন যেকোনো মেসেজ পাঠান।\n🔒 সম্পূর্ণ গোপন।", "en": "✅ Partner found!\n\n💬 Send any message.\n🔒 Fully anonymous."},
    "chat_ended": {"bn": "🛑 চ্যাট শেষ।", "en": "🛑 Chat ended."},
    "partner_ended": {"bn": "🛑 পার্টনার চ্যাট শেষ করেছেন।", "en": "🛑 Partner ended the chat."},
    "partner_left": {"bn": "🛑 পার্টনার নতুন পার্টনার খুঁজতে গেছেন।", "en": "🛑 Partner left."},
    "not_in_chat": {"bn": "⚠️ আপনি কোনো চ্যাটে নেই। /start দিন।", "en": "⚠️ Not in a chat. Send /start."},
    "reg_first": {"bn": "❌ আগে /start দিন।", "en": "❌ Please /start first."},
    "already_in_chat": {"bn": "❌ আপনি ইতিমধ্যে চ্যাটে আছেন।", "en": "❌ Already in a chat."},
    "search_cancelled": {"bn": "✅ সার্চ বাতিল।", "en": "✅ Search cancelled."},
    "online_count": {"bn": "🟢 {n} জন অনলাইনে", "en": "🟢 {n} users online"},
    "referral_msg": {"bn": "🔗 আপনার ইনভাইট লিংক:\n\n{link}\n\n💡 প্রতি ইনভাইটে {coins} কয়েন!", "en": "🔗 Your invite link:\n\n{link}\n\n💡 {coins} coins per referral!"},
    "coins_balance": {"bn": "🪙 কয়েন: {coins}\n⭐ Premium: {vip}", "en": "🪙 Coins: {coins}\n⭐ Premium: {vip}"},
    "vip_active": {"bn": "✅ Active", "en": "✅ Active"},
    "vip_inactive": {"bn": "❌ Inactive", "en": "❌ Inactive"},
    "language_select": {"bn": "🌍 ভাষা নির্বাচন করুন:", "en": "🌍 Choose your language:"},
    "language_changed": {"bn": "✅ ভাষা: বাংলা", "en": "✅ Language: English"},
    "report_thanks": {"bn": "✅ ধন্যবাদ। রিপোর্ট জমা।", "en": "✅ Thanks. Report submitted."},
    "report_blocked": {"bn": "✅ রিপোর্ট + পার্টনার ব্লকড।", "en": "✅ Report submitted + partner blocked."},
    "referral_bonus": {"bn": "🎁 {coins} কয়েন পেয়েছেন!", "en": "🎁 You earned {coins} coins!"},
    "daily_bonus": {"bn": "🎁 ডেইলি বোনাস: +{coins} কয়েন!", "en": "🎁 Daily bonus: +{coins} coins!"},
    "streak_msg": {"bn": "🔥 Streak: {n} দিন!", "en": "🔥 Streak: {n} days!"},
    "chat_limit_reached": {"bn": "❌ আজকের ফ্রি চ্যাট লিমিট শেষ।\n⭐ Premium নিন unlimited এর জন্য।", "en": "❌ Daily free limit reached.\n⭐ Get Premium for unlimited."},
    "spam_warning": {"bn": "⚠️ ভদ্রভাবে কথা বলুন।", "en": "⚠️ Please be respectful."},
    "no_partner_ai": {"bn": "🤖 পার্টনার পাওয়া যায়নি। AI এর সাথে চ্যাট?", "en": "🤖 No partner found. Chat with AI?"},
    "ai_mode_on": {"bn": "🤖 AI মোড চালু। /stop দিয়ে থামান।", "en": "🤖 AI mode ON. /stop to stop."},
    "profile_saved": {"bn": "✅ সেভ হয়েছে!", "en": "✅ Saved!"},
    "leaderboard_title": {"bn": "🏆 টপ চ্যাটার", "en": "🏆 Top Chatters"},
    "leaderboard_empty": {"bn": "কোনো ডেটা নেই।", "en": "No data yet."},
    "group_room_menu": {"bn": "👥 Group Rooms\n\n৩-১০ জন।", "en": "👥 Group Rooms\n\n3-10 users."},
    "group_room_full": {"bn": "❌ রুম ফুল।", "en": "❌ Room full."},
    "group_room_not_found": {"bn": "❌ রুম নেই।", "en": "❌ Room not found."},
    "group_room_left": {"bn": "🚪 বেরিয়ে গেছেন।", "en": "🚪 Left the room."},
    "wait_moment": {"bn": "⏳ অপেক্ষা করুন।", "en": "⏳ Wait."},
    "choose_tier": {"bn": "💎 প্রিমিয়াম প্যাকেজ নির্বাচন করুন:", "en": "💎 Choose your premium package:"},
    "choose_payment": {"bn": "💳 পেমেন্ট পদ্ধতি নির্বাচন করুন:", "en": "💳 Choose payment method:"},
    "payment_sent": {"bn": "✅ আপনার পেমেন্ট ইনফো পাঠানো হয়েছে।\n\nঅ্যাডমিন ৫-১০ মিনিটে ভেরিফাই করে Premium চালু করবে।", "en": "✅ Payment info sent.\n\nAdmin will verify within 5-10 min."},
    "premium_activated": {"bn": "🎉 Premium চালু হয়েছে!\n\n🌟 Tier: {tier}\n📅 মেয়াদ: {days} দিন\n🪙 +{coins} কয়েন", "en": "🎉 Premium activated!\n\n🌟 Tier: {tier}\n📅 Duration: {days} days\n🪙 +{coins} coins"},
    "achievements_title": {"bn": "🏅 Achievements", "en": "🏅 Achievements"},
    "missions_title": {"bn": "🎯 Daily Missions", "en": "🎯 Daily Missions"},
    "mission_done": {"bn": "✅ {text} — +{reward} কয়েন", "en": "✅ {text} — +{reward} coins"},
    "mission_pending": {"bn": "⏳ {text} ({current}/{target}) — +{reward} কয়েন", "en": "⏳ {text} ({current}/{target}) — +{reward} coins"},
    "xp_level": {"bn": "📈 Level {level} • XP: {xp}/{next_xp}", "en": "📈 Level {level} • XP: {xp}/{next_xp}"},
    "level_up": {"bn": "🎉 Level Up! এখন Level {level}!", "en": "🎉 Level Up! You're Level {level}!"},
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
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                streak INTEGER DEFAULT 0,
                last_streak_date DATE,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_tier VARCHAR(20),
                vip_until TIMESTAMP,
                referred_by BIGINT,
                total_chats INTEGER DEFAULT 0
            );
        """)
        for col, typ in [
            ("ban_reason", "TEXT"), ("chats_today", "INTEGER DEFAULT 0"),
            ("chats_today_date", "DATE DEFAULT CURRENT_DATE"),
            ("daily_bonus_date", "DATE"), ("total_chats", "INTEGER DEFAULT 0"),
            ("xp", "INTEGER DEFAULT 0"), ("level", "INTEGER DEFAULT 1"),
            ("streak", "INTEGER DEFAULT 0"), ("last_streak_date", "DATE"),
            ("vip_tier", "VARCHAR(20)"),
        ]:
            try:
                await conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception as e:
                logger.warning(f"users.{col}: {e}")

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
        for col, typ in [("pref_language", "VARCHAR(10) DEFAULT 'any'"),
                         ("interest", "VARCHAR(30) DEFAULT 'any'"),
                         ("min_age", "INTEGER DEFAULT 18"), ("max_age", "INTEGER DEFAULT 99")]:
            try:
                await conn.execute(f"ALTER TABLE profiles ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception as e:
                logger.warning(f"profiles.{col}: {e}")

        # MATCH QUEUE
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS match_queue (
                user_id BIGINT PRIMARY KEY,
                gender VARCHAR(20),
                pref_gender VARCHAR(20),
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        for col, typ in [("pref_language", "VARCHAR(10) DEFAULT 'any'"),
                         ("interest", "VARCHAR(30) DEFAULT 'any'"),
                         ("is_vip", "BOOLEAN DEFAULT FALSE"),
                         ("age", "INTEGER DEFAULT 18"),
                         ("min_age", "INTEGER DEFAULT 18"), ("max_age", "INTEGER DEFAULT 99")]:
            try:
                await conn.execute(f"ALTER TABLE match_queue ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception as e:
                logger.warning(f"match_queue.{col}: {e}")

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
            logger.warning(f"active_chats.is_ai: {e}")

        # GROUP ROOMS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_rooms (
                room_id SERIAL PRIMARY KEY,
                host_id BIGINT,
                name VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            );
        """)
        try:
            await conn.execute("ALTER TABLE group_rooms ADD COLUMN IF NOT EXISTS name VARCHAR(100)")
        except Exception:
            pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                room_id INTEGER, user_id BIGINT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (room_id, user_id)
            );
        """)

        # BLOCKS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                blocker_id BIGINT, blocked_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            );
        """)

        # REPORTS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                report_id SERIAL PRIMARY KEY,
                reporter_id BIGINT, reported_id BIGINT,
                reason VARCHAR(100), status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # FRIENDS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                user_id BIGINT, friend_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, friend_id)
            );
        """)

        # USER ACHIEVEMENTS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                user_id BIGINT, achievement_key VARCHAR(50),
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, achievement_key)
            );
        """)

        # DAILY MISSIONS PROGRESS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_missions (
                user_id BIGINT, mission_key VARCHAR(50), date DATE,
                progress INTEGER DEFAULT 0, completed BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, mission_key, date)
            );
        """)

        # PAYMENTS
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id SERIAL PRIMARY KEY,
                user_id BIGINT, tier VARCHAR(20), method VARCHAR(30),
                amount_bdt INTEGER, transaction_id TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP, approved_by BIGINT
            );
        """)

        # CHAT LOG (for stats)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_log (
                id SERIAL PRIMARY KEY,
                user_id BIGINT, partner_id BIGINT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP, messages INTEGER DEFAULT 0
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
    cols = list(kwargs.keys())
    vals = list(kwargs.values())
    ph = [f"${i+2}" for i in range(len(cols))]
    update_set = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols])
    query = f"INSERT INTO profiles (user_id, {', '.join(cols)}) VALUES ($1, {', '.join(ph)}) ON CONFLICT (user_id) DO UPDATE SET {update_set}"
    async with db_pool.acquire() as conn:
        await conn.execute(query, user_id, *vals)


async def get_user_stats(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins, xp, level, streak, total_chats, is_vip, vip_tier, vip_until FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None


# ============================================================
# COINS / XP / LEVEL
# ============================================================
async def get_coins(user_id):
    async with db_pool.acquire() as conn:
        return (await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user_id)) or 0


async def add_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", amount, user_id)


async def deduct_coins(user_id, amount):
    async with db_pool.acquire() as conn:
        cur = (await conn.fetchval("SELECT coins FROM users WHERE user_id = $1", user_id)) or 0
        if cur < amount:
            return False
        await conn.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", amount, user_id)
        return True


async def add_xp(user_id, amount):
    """Add XP and check level up. Returns new level if leveled up, else None."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT xp, level FROM users WHERE user_id = $1", user_id)
        if not row:
            return None
        old_xp = row['xp'] or 0
        old_level = row['level'] or 1
        new_xp = old_xp + amount
        new_level = 1
        for i, threshold in enumerate(LEVEL_THRESHOLDS):
            if new_xp >= threshold:
                new_level = i + 1
        await conn.execute("UPDATE users SET xp = $1, level = $2 WHERE user_id = $3", new_xp, new_level, user_id)
        if new_level > old_level:
            return new_level
        return None


# ============================================================
# VIP / PREMIUM
# ============================================================
async def is_vip(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_vip, vip_until FROM users WHERE user_id = $1", user_id)
        if not row or not row['is_vip']:
            return False
        if row['vip_until'] and row['vip_until'] < datetime.now():
            await conn.execute("UPDATE users SET is_vip = FALSE WHERE user_id = $1", user_id)
            return False
        return True


async def get_vip_tier(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT vip_tier FROM users WHERE user_id = $1", user_id)


async def set_vip(user_id, tier="bronze", days=30):
    until = datetime.now() + timedelta(days=days)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_vip = TRUE, vip_tier = $1, vip_until = $2 WHERE user_id = $3", tier, until, user_id)


# ============================================================
# STREAK
# ============================================================
async def update_streak(user_id):
    """Update daily streak. Returns (streak, is_new_day)."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT streak, last_streak_date FROM users WHERE user_id = $1", user_id)
        if not row:
            return 0, False
        today = datetime.now().date()
        last = row['last_streak_date']
        streak = row['streak'] or 0
        if last == today:
            return streak, False
        if last and (today - last).days == 1:
            streak += 1
        else:
            streak = 1
        await conn.execute("UPDATE users SET streak = $1, last_streak_date = $2 WHERE user_id = $3", streak, today, user_id)
        # Streak rewards
        if streak == 7:
            await conn.execute("UPDATE users SET coins = coins + 100 WHERE user_id = $1", user_id)
        elif streak == 30:
            await conn.execute("UPDATE users SET coins = coins + 500 WHERE user_id = $1", user_id)
        return streak, True


# ============================================================
# DAILY BONUS
# ============================================================
async def try_daily_bonus(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT daily_bonus_date FROM users WHERE user_id = $1", user_id)
        today = datetime.now().date()
        if row and row['daily_bonus_date'] == today:
            return False
        await conn.execute("UPDATE users SET daily_bonus_date = $1, coins = coins + $2 WHERE user_id = $3", today, DAILY_BONUS_COINS, user_id)
        return True


# ============================================================
# ACHIEVEMENTS
# ============================================================
async def get_user_achievements(user_id):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT achievement_key FROM user_achievements WHERE user_id = $1", user_id)
        return {r['achievement_key'] for r in rows}


async def unlock_achievement(user_id, key):
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM user_achievements WHERE user_id = $1 AND achievement_key = $2", user_id, key)
        if exists:
            return False
        await conn.execute("INSERT INTO user_achievements (user_id, achievement_key) VALUES ($1, $2)", user_id, key)
        return True


async def check_achievements(user_id, context, lang):
    """Check all achievements and unlock new ones."""
    stats = await get_user_stats(user_id)
    if not stats:
        return []
    unlocked = await get_user_achievements(user_id)
    newly = []
    checks = {
        "chats_10": (stats['total_chats'] or 0) >= 10,
        "chats_50": (stats['total_chats'] or 0) >= 50,
        "chats_100": (stats['total_chats'] or 0) >= 100,
        "chats_500": (stats['total_chats'] or 0) >= 500,
        "streak_7": (stats['streak'] or 0) >= 7,
        "streak_30": (stats['streak'] or 0) >= 30,
        "coins_100": (stats['coins'] or 0) >= 100,
        "coins_1000": (stats['coins'] or 0) >= 1000,
        "premium": stats['is_vip'],
        "level_5": (stats['level'] or 1) >= 5,
        "level_10": (stats['level'] or 1) >= 10,
    }
    async with db_pool.acquire() as conn:
        invites = await conn.fetchval("SELECT COUNT(*) FROM users WHERE referred_by = $1", user_id) or 0
    checks["invite_1"] = invites >= 1
    checks["invite_5"] = invites >= 5
    checks["invite_25"] = invites >= 25

    for key, ok in checks.items():
        if ok and key not in unlocked:
            if await unlock_achievement(user_id, key):
                newly.append(key)
                emoji, title, _ = ACHIEVEMENTS.get(key, ("🏅", key, ""))
                try:
                    await context.bot.send_message(user_id, f"🎉 Achievement Unlocked!\n\n{emoji} {title}")
                except Exception:
                    pass
    return newly


# ============================================================
# MISSIONS
# ============================================================
async def update_mission_progress(user_id, mission_key, amount=1):
    """Update mission progress. Returns (progress, target, completed, reward)."""
    m = DAILY_MISSIONS.get(mission_key)
    if not m:
        return None
    today = datetime.now().date()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT progress, completed FROM daily_missions WHERE user_id = $1 AND mission_key = $2 AND date = $3",
            user_id, mission_key, today
        )
        if row and row['completed']:
            return (row['progress'], m['target'], True, m['reward'])
        progress = (row['progress'] if row else 0) + amount
        completed = progress >= m['target']
        if completed:
            await conn.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", m['reward'], user_id)
        await conn.execute("""
            INSERT INTO daily_missions (user_id, mission_key, date, progress, completed)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, mission_key, date) DO UPDATE SET progress = $4, completed = $5
        """, user_id, mission_key, today, progress, completed)
        return (progress, m['target'], completed, m['reward'])


async def get_missions_status(user_id):
    today = datetime.now().date()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT mission_key, progress, completed FROM daily_missions WHERE user_id = $1 AND date = $2",
            user_id, today
        )
    status = {}
    for k, m in DAILY_MISSIONS.items():
        row = next((r for r in rows if r['mission_key'] == k), None)
        status[k] = {
            "progress": row['progress'] if row else 0,
            "completed": row['completed'] if row else False,
            "target": m['target'],
            "reward": m['reward'],
            "text": m['text'],
        }
    return status


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
    ts = rate_limit_store.get(user_id, [])
    ts = [x for x in ts if (now - x).total_seconds() < window_seconds]
    if len(ts) >= max_requests:
        rate_limit_store[user_id] = ts
        return True
    ts.append(now)
    rate_limit_store[user_id] = ts
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
        [InlineKeyboardButton(t("achievements", lang), callback_data="show_achievements"),
         InlineKeyboardButton(t("missions", lang), callback_data="show_missions")],
        [InlineKeyboardButton(t("friends", lang), callback_data="show_friends"),
         InlineKeyboardButton(t("leaderboard", lang), callback_data="leaderboard")],
        [InlineKeyboardButton(t("invite", lang), callback_data="show_link"),
         InlineKeyboardButton(t("language", lang), callback_data="change_language")],
        [InlineKeyboardButton(f"🟢 {online}", callback_data="refresh_online"),
         InlineKeyboardButton(t("safety", lang), callback_data="safety"),
         InlineKeyboardButton(t("help", lang), callback_data="help")],
    ])


async def chat_keyboard(partner_id, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("next_person", lang), callback_data="next_partner"),
         InlineKeyboardButton(t("end_chat", lang), callback_data="end_chat")],
        [InlineKeyboardButton(t("report", lang), callback_data=f"report_{partner_id}"),
         InlineKeyboardButton("👫 Add Friend", callback_data=f"addfriend_{partner_id}")],
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
                user_id, t("no_partner_ai", lang),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
                ])
            )
        except Exception as e:
            logger.error(f"Timeout: {e}")


# ============================================================
# CHAT TIMER
# ============================================================
async def chat_timer_end(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data['user_id']
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        return
    partner_id = chat['partner_id']
    await remove_active_chat(user_id, partner_id)
    try:
        await context.bot.send_message(user_id, t("chat_ended", lang), reply_markup=await main_menu_keyboard(lang))
        p_lang = await get_user_lang(partner_id)
        await context.bot.send_message(partner_id, t("chat_ended", p_lang), reply_markup=await main_menu_keyboard(p_lang))
    except Exception:
        pass


# ============================================================
# /start
# ============================================================
async def start(update, context):
    user_id = update.effective_user.id
    await touch_user(user_id)

    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 You are banned.")
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
                    if await process_referral(user_id, referrer_id):
                        ref_lang = await get_user_lang(referrer_id)
                        await context.bot.send_message(referrer_id, t("referral_bonus", ref_lang, coins=REFERRAL_COIN_REWARD))
                except Exception as e:
                    logger.error(f"Ref: {e}")
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

    # Existing referral
    if referrer_id:
        async with db_pool.acquire() as conn:
            already = await conn.fetchval("SELECT referred_by FROM users WHERE user_id = $1", user_id)
        if already is None:
            if await process_referral(user_id, referrer_id):
                try:
                    ref_lang = await get_user_lang(referrer_id)
                    await context.bot.send_message(referrer_id, t("referral_bonus", ref_lang, coins=REFERRAL_COIN_REWARD))
                except Exception:
                    pass

    # Daily bonus
    if await try_daily_bonus(user_id):
        await update.message.reply_text(t("daily_bonus", lang, coins=DAILY_BONUS_COINS))

    # Streak
    streak, is_new = await update_streak(user_id)
    if is_new and streak > 1:
        await update.message.reply_text(t("streak_msg", lang, n=streak))

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
            ]))
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
            ]))
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
            ]))
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
            ]))
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

    profile = await get_profile(user_id)
    if profile and profile.get('display_name'):
        online = await get_online_count()
        try:
            await query.edit_message_text(
                f"{t('language_changed', lang)}\n\n{t('main_menu', lang)}\n\n{t('online_count', lang, n=online)}",
                reply_markup=await main_menu_keyboard(lang)
            )
        except Exception:
            pass
        return

    context.user_data['reg_step'] = 'age_gate'
    await query.edit_message_text(
        t("welcome", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("age_yes", lang), callback_data="age_yes")],
            [InlineKeyboardButton(t("age_no", lang), callback_data="age_no")]
        ]))


async def change_language(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        t("language_select", "bn"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ]))


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
        await update.message.reply_text("🚫 Banned.")
        return

    lang = await get_user_lang(user_id)
    step = context.user_data.get('reg_step')
    text = update.message.text.strip() if update.message.text else ""

    # Payment proof mode
    if context.user_data.get('awaiting_payment'):
        tier = context.user_data.get('payment_tier', 'bronze')
        method = context.user_data.get('payment_method', 'unknown')
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.forward_message(chat_id=admin_id, from_chat_id=user_id, message_id=update.message.message_id)
                await context.bot.send_message(
                    admin_id,
                    f"💰 Payment Info\n\n👤 {update.effective_user.full_name}\n🆔 `{user_id}`\n"
                    f"📦 Tier: {tier}\n💳 Method: {method}\n\n"
                    f"Approve: `/approve {user_id} {tier}`"
                )
            except Exception as e:
                logger.error(f"Admin fwd: {e}")
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO payments (user_id, tier, method, transaction_id, status) VALUES ($1, $2, $3, $4, 'pending')",
                user_id, tier, method, text[:200]
            )
        await update.message.reply_text(t("payment_sent", lang))
        context.user_data.pop('awaiting_payment', None)
        context.user_data.pop('payment_tier', None)
        context.user_data.pop('payment_method', None)
        return

    if step == 'name':
        if len(text) < 2 or len(text) > 50:
            await update.message.reply_text("⚠️ 2-50 chars")
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
            ]))
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
        await update.message.reply_text("⚠️ Use buttons")
        return

    # Edit profile
    edit_step = context.user_data.get('edit_step')
    if edit_step:
        if edit_step == 'name':
            await save_profile(user_id, display_name=text[:50])
        elif edit_step == 'bio':
            await save_profile(user_id, bio=text[:200])
        elif edit_step == 'min_age':
            if text.isdigit():
                await save_profile(user_id, min_age=int(text))
        elif edit_step == 'max_age':
            if text.isdigit():
                await save_profile(user_id, max_age=int(text))
        context.user_data.pop('edit_step', None)
        await update.message.reply_text(t("profile_saved", lang))
        return

    # Chat message
    await handle_chat_message(update, context)


# ============================================================
# REGISTRATION CALLBACKS
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
        ]))


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
        ]))


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
        ]))


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
        reply_markup=await main_menu_keyboard(lang))


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
        await query.edit_message_text(t("already_in_chat", lang), reply_markup=await chat_keyboard(existing['partner_id'], lang))
        return

    # Chat limit check
    if not await is_vip(user_id):
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT chats_today, chats_today_date FROM users WHERE user_id = $1", user_id)
            today = datetime.now().date()
            if row and row['chats_today_date'] == today and (row['chats_today'] or 0) >= MAX_DAILY_CHATS_FREE:
                await query.edit_message_text(
                    t("chat_limit_reached", lang),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t("vip", lang), callback_data="show_vip")],
                        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
                    ]))
                return
            if not row or row['chats_today_date'] != today:
                await conn.execute("UPDATE users SET chats_today = 1, chats_today_date = $1 WHERE user_id = $2", today, user_id)
            else:
                await conn.execute("UPDATE users SET chats_today = chats_today + 1 WHERE user_id = $1", user_id)

    user_gender = profile.get('gender') or 'any'
    user_pref = profile.get('pref_gender') or 'any'
    user_interest = profile.get('interest') or 'any'
    user_plang = profile.get('pref_language') or 'any'
    user_age = profile.get('age') or 18
    user_min_age = profile.get('min_age') or 18
    user_max_age = profile.get('max_age') or 99
    user_vip = await is_vip(user_id)

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
        candidates = await conn.fetch("""
            SELECT mq.* FROM match_queue mq
            WHERE mq.user_id != $1
            AND NOT EXISTS (
                SELECT 1 FROM blocks
                WHERE (blocker_id = $1 AND blocked_id = mq.user_id)
                OR (blocker_id = mq.user_id AND blocked_id = $1)
            )
            ORDER BY mq.is_vip DESC, mq.queued_at ASC LIMIT 50
        """, user_id)

    def score(c):
        s = 0
        if user_pref == 'any' or c['gender'] == user_pref:
            s += 10
        else:
            return -1
        if c['pref_gender'] == 'any' or c['pref_gender'] == user_gender:
            s += 10
        else:
            return -1
        # Age filter
        c_age = c.get('age') or 18
        if c_age < user_min_age or c_age > user_max_age:
            return -1
        c_min = c.get('min_age') or 18
        c_max = c.get('max_age') or 99
        if user_age < c_min or user_age > c_max:
            return -1
        if user_interest != 'any' and c['interest'] == user_interest:
            s += 5
        if user_plang != 'any' and c['pref_language'] == user_plang:
            s += 3
        if c['is_vip']:
            s += 2
        return s

    best = None
    best_score = -1
    for c in candidates:
        sc = score(c)
        if sc > best_score:
            best = c
            best_score = sc

    if best is not None and best_score >= 10:
        partner_id = best['user_id']
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM match_queue WHERE user_id = $1", partner_id)
            await conn.execute("""
                INSERT INTO active_chats (user_id, partner_id) VALUES ($1, $2), ($2, $1)
                ON CONFLICT (user_id) DO UPDATE SET partner_id = EXCLUDED.partner_id, started_at = CURRENT_TIMESTAMP, is_ai = FALSE
            """, user_id, partner_id)
            await conn.execute("UPDATE users SET total_chats = total_chats + 1 WHERE user_id IN ($1, $2)", user_id, partner_id)

        # XP + Mission
        lvl = await add_xp(user_id, XP_PER_CHAT)
        await update_mission_progress(user_id, "chat_3", 1)
        if lvl:
            await query.message.reply_text(t("level_up", lang, level=lvl))

        # Achievement check
        await check_achievements(user_id, context, lang)

        partner_lang = await get_user_lang(partner_id)
        await query.edit_message_text(t("partner_found", lang), reply_markup=await chat_keyboard(partner_id, lang))
        try:
            await context.bot.send_message(partner_id, t("partner_found", partner_lang), reply_markup=await chat_keyboard(user_id, partner_lang))
        except Exception as e:
            logger.error(f"Notify: {e}")

        reward = CHAT_COIN_REWARD * 2 if user_vip else CHAT_COIN_REWARD
        await add_coins(user_id, reward)

        timer = CHAT_TIMER_SECONDS * 2 if user_vip else CHAT_TIMER_SECONDS
        context.job_queue.run_once(chat_timer_end, timer, data={'user_id': user_id}, name=f"end1_{user_id}")
        context.job_queue.run_once(chat_timer_end, timer, data={'user_id': partner_id}, name=f"end2_{partner_id}")
    else:
        async with db_pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO match_queue (user_id, gender, pref_gender, pref_language, interest, is_vip, age, min_age, max_age)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (user_id) DO UPDATE SET
                    queued_at = CURRENT_TIMESTAMP, is_vip = EXCLUDED.is_vip,
                    pref_gender = EXCLUDED.pref_gender, pref_language = EXCLUDED.pref_language,
                    interest = EXCLUDED.interest, gender = EXCLUDED.gender,
                    age = EXCLUDED.age, min_age = EXCLUDED.min_age, max_age = EXCLUDED.max_age
            """, user_id, user_gender, user_pref, user_plang, user_interest, user_vip, user_age, user_min_age, user_max_age)

        await query.edit_message_text(
            t("searching", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
                [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
            ]))

        job_name = f"queue_timeout_{user_id}"
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
        context.job_queue.run_once(queue_timeout_check, QUEUE_TIMEOUT_SECONDS, data={'user_id': user_id}, name=job_name)


async def cancel_search(update, context):
    query = update.callback_query
    await query.answer("Cancelled")
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
        for job in context.job_queue.get_jobs_by_name(f"queue_timeout_{user_id}"):
            job.schedule_removal()
        context.user_data.pop('searching', None)
        online = await get_online_count()
        await query.edit_message_text(
            f"{t('search_cancelled', lang)}\n\n{t('main_menu', lang)}\n\n{t('online_count', lang, n=online)}",
            reply_markup=await main_menu_keyboard(lang))
    except Exception as e:
        logger.error(f"cancel: {e}")


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
            INSERT INTO active_chats (user_id, partner_id, is_ai) VALUES ($1, $1, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET partner_id = $1, is_ai = TRUE, started_at = CURRENT_TIMESTAMP
        """, user_id)

    context.user_data['ai_history'] = []
    await query.edit_message_text(
        t("ai_mode_on", lang),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop AI", callback_data="end_chat")]]))


# ============================================================
# CHAT MESSAGE
# ============================================================
async def handle_chat_message(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        return

    if is_rate_limited(user_id, 20, 10):
        await update.message.reply_text(t("wait_moment", lang))
        return

    if update.message.text and contains_bad_words(update.message.text):
        await update.message.reply_text(t("spam_warning", lang))
        return

    # XP and missions for messages
    await add_xp(user_id, XP_PER_MESSAGE)
    await update_mission_progress(user_id, "msg_20", 1)

    if chat.get('is_ai'):
        await handle_ai_message(update, context, lang)
        return

    partner_id = chat['partner_id']
    room_id = context.user_data.get('room_id')
    if room_id:
        await handle_group_message(update, context, room_id)
        return

    try:
        await context.bot.copy_message(chat_id=partner_id, from_chat_id=user_id, message_id=update.message.message_id)
    except Exception as e:
        logger.error(f"Copy: {e}")


async def handle_ai_message(update, context, lang):
    user_id = update.effective_user.id
    text = update.message.text or ""
    if not text:
        await update.message.reply_text("🤖 Send text.")
        return
    if contains_bad_words(text):
        await update.message.reply_text(t("spam_warning", lang))
        return

    typing = await update.message.reply_text("🤖 Typing...")
    history = context.user_data.get('ai_history', [])
    history.append({"role": "user", "content": text})

    system = ("You are a friendly anonymous chat partner. Reply in user's language (Bangla/English/Hindi). "
              "Keep replies short (under 300 chars). Be warm, funny, engaging. Use emojis. No markdown.")

    answer = None
    for model in AI_MODELS:
        try:
            resp = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=model,
                messages=[{"role": "system", "content": system}] + history[-10:],
                temperature=0.8, max_tokens=400)
            answer = resp.choices[0].message.content.strip()
            break
        except Exception as e:
            logger.warning(f"AI {model}: {e}")
            continue

    if not answer:
        await typing.edit_text("🤖 AI busy. Try again.")
        return

    history.append({"role": "assistant", "content": answer})
    context.user_data['ai_history'] = history[-10:]
    await typing.edit_text(answer)


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
            SELECT r.room_id, r.name, COUNT(m.user_id) as cnt
            FROM group_rooms r
            LEFT JOIN group_members m ON m.room_id = r.room_id
            WHERE r.is_active = TRUE
            GROUP BY r.room_id, r.name
            HAVING COUNT(m.user_id) < $1
            ORDER BY r.room_id DESC LIMIT 5
        """, GROUP_ROOM_MAX)

    rows = []
    for r in rooms:
        name = r['name'] or f"Room {r['room_id']}"
        rows.append([InlineKeyboardButton(f"👥 {name} ({r['cnt']}/{GROUP_ROOM_MAX})", callback_data=f"joinroom_{r['room_id']}")])
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
        await conn.execute("INSERT INTO group_members (room_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", room_id, user_id)

    context.user_data['room_id'] = room_id
    await query.edit_message_text(
        f"✅ Room {room_id} created!\n\nID: `{room_id}`\n\nShare: /joinroom {room_id}\n\n/leaveroom to leave.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_room")]]))


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
        f"✅ Joined Room {room_id}!\n\n/leaveroom to exit.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_room")]]))


async def join_room_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    if not context.args:
        await update.message.reply_text("Usage: /joinroom <id>")
        return
    try:
        room_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID")
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
    await update.message.reply_text(f"✅ Joined Room {room_id}!")


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
        await update.message.reply_text("❌ Not in a room.")
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
            await context.bot.copy_message(chat_id=m['user_id'], from_chat_id=user_id, message_id=update.message.message_id)
        except Exception as e:
            logger.error(f"Group: {e}")


# ============================================================
# END / NEXT / FRIEND
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
    for n in [f"end1_{user_id}", f"end2_{user_id}", f"end1_{partner_id}", f"end2_{partner_id}"]:
        for job in context.job_queue.get_jobs_by_name(n):
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
        for n in [f"end1_{user_id}", f"end2_{user_id}", f"end1_{partner_id}", f"end2_{partner_id}"]:
            for job in context.job_queue.get_jobs_by_name(n):
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


async def add_friend_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    friend_id = int(query.data.split("_")[1])
    if user_id == friend_id:
        await query.answer("Cannot add yourself", show_alert=True)
        return
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO friends (user_id, friend_id) VALUES ($1, $2), ($2, $1) ON CONFLICT DO NOTHING", user_id, friend_id)
    await query.answer("✅ Friend added!", show_alert=True)


# ============================================================
# REPORT
# ============================================================
async def report_callback(update, context):
    query = update.callback_query
    await query.answer()
    reported_id = int(query.data.split("_")[1])
    reasons = [("Spam", "spam"), ("Harassment", "harassment"), ("Scam", "scam"),
               ("Fake", "fake"), ("18-", "underage"), ("Other", "other")]
    rows = [[InlineKeyboardButton(r[0], callback_data=f"rpr_{r[1]}_{reported_id}")] for r in reasons]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="end_chat")])
    await query.edit_message_text("⚠️ Reason:", reply_markup=InlineKeyboardMarkup(rows))


async def report_reason_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    reason = parts[1]
    reported_id = int(parts[2])
    reporter_id = query.from_user.id
    lang = await get_user_lang(reporter_id)

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO reports (reporter_id, reported_id, reason) VALUES ($1, $2, $3)", reporter_id, reported_id, reason)
        await conn.execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", reporter_id, reported_id)
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", reporter_id, reported_id)
        unique = await conn.fetchval("SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE reported_id = $1 AND status = 'pending'", reported_id)
        if unique and unique >= AUTO_BAN_REPORT_COUNT:
            await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1", reported_id)
            await conn.execute("UPDATE reports SET status = 'actioned' WHERE reported_id = $1", reported_id)
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(aid, f"🚨 Auto-Ban\n👤 {reported_id}\n📊 {unique} reports")
                except Exception:
                    pass

    await query.edit_message_text(t("report_blocked", lang), reply_markup=await main_menu_keyboard(lang))


# ============================================================
# PROFILE
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
    stats = await get_user_stats(user_id) or {}
    gender_map = {"male": "👦", "female": "👧", "other": "🌈"}
    vip = await is_vip(user_id)
    tier = await get_vip_tier(user_id) if vip else None
    # XP next level
    xp = stats.get('xp', 0) or 0
    level = stats.get('level', 1) or 1
    next_xp = LEVEL_THRESHOLDS[level] if level < len(LEVEL_THRESHOLDS) else 0
    text = (
        f"👤 {profile.get('display_name', 'N/A')}\n"
        f"🎂 Age: {profile.get('age', 'N/A')} | {gender_map.get(profile.get('gender'), '?')}\n"
        f"💡 Interest: {profile.get('interest', 'N/A')}\n"
        f"🎯 Pref: {profile.get('pref_gender', 'any')} • {profile.get('pref_language', 'any')}\n\n"
        f"{t('xp_level', lang, level=level, xp=xp, next_xp=next_xp)}\n"
        f"🪙 Coins: {stats.get('coins', 0)}\n"
        f"🔥 Streak: {stats.get('streak', 0)}\n"
        f"💬 Total Chats: {stats.get('total_chats', 0)}\n"
        f"⭐ Premium: {'✅ ' + (tier or 'Active') if vip else '❌ Inactive'}\n\n"
        f"💬 Bio: {(profile.get('bio') or 'N/A')[:150]}"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(t("edit_profile", lang), callback_data="edit_profile")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def edit_profile(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await query.edit_message_text(
        "✏️ Edit Profile:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📛 Name", callback_data="edit_name"),
             InlineKeyboardButton("📝 Bio", callback_data="edit_bio")],
            [InlineKeyboardButton("🎯 Pref Gender", callback_data="edit_pref_gender"),
             InlineKeyboardButton("💡 Interest", callback_data="edit_interest")],
            [InlineKeyboardButton("🌐 Lang Pref", callback_data="edit_lang"),
             InlineKeyboardButton("📅 Age Range", callback_data="edit_age_range")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def edit_name(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_step'] = 'name'
    await query.edit_message_text("✏️ Send new name:")


async def edit_bio(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['edit_step'] = 'bio'
    await query.edit_message_text("✏️ Send new bio:")


async def edit_pref_gender(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    await query.edit_message_text(
        "🎯 Choose:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("male", lang), callback_data="setpg_male"),
             InlineKeyboardButton(t("female", lang), callback_data="setpg_female")],
            [InlineKeyboardButton(t("any", lang), callback_data="setpg_any")]]))


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
             InlineKeyboardButton("🌍 Any", callback_data="setint_any")]]))


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
             InlineKeyboardButton("🌍 Any", callback_data="setplang_any")]]))


async def set_plang_edit(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    plang = query.data.split("_")[1]
    await save_profile(user_id, pref_language=plang)
    await query.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_keyboard(lang))


async def edit_age_range(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📅 Age Range:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("18-25", callback_data="setage_18_25"),
             InlineKeyboardButton("25-35", callback_data="setage_25_35")],
            [InlineKeyboardButton("35-50", callback_data="setage_35_50"),
             InlineKeyboardButton("18-99 (Any)", callback_data="setage_18_99")]]))


async def set_age_range(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    parts = query.data.replace("setage_", "").split("_")
    await save_profile(user_id, min_age=int(parts[0]), max_age=int(parts[1]))
    await query.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_keyboard(lang))


# ============================================================
# ACHIEVEMENTS / MISSIONS / FRIENDS
# ============================================================
async def show_achievements(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    unlocked = await get_user_achievements(user_id)
    text = f"{t('achievements_title', lang)}\n\n"
    for key, (emoji, title, desc) in ACHIEVEMENTS.items():
        mark = "✅" if key in unlocked else "🔒"
        text += f"{mark} {emoji} {title}\n"
    await query.edit_message_text(text[:4000], reply_markup=await main_menu_keyboard(lang))


async def show_missions(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    status = await get_missions_status(user_id)
    text = f"{t('missions_title', lang)}\n\n"
    for k, m in status.items():
        if m['completed']:
            text += t("mission_done", lang, text=m['text'], reward=m['reward']) + "\n"
        else:
            text += t("mission_pending", lang, text=m['text'], current=m['progress'], target=m['target'], reward=m['reward']) + "\n"
    await query.edit_message_text(text, reply_markup=await main_menu_keyboard(lang))


async def show_friends(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT f.friend_id, p.display_name
            FROM friends f LEFT JOIN profiles p ON p.user_id = f.friend_id
            WHERE f.user_id = $1 LIMIT 20
        """, user_id)
    if not rows:
        text = "👫 Friends\n\nNo friends yet. Add from chat!"
    else:
        text = "👫 Friends\n\n"
        for r in rows:
            text += f"• {r['display_name'] or 'Anonymous'}\n"
    await query.edit_message_text(text, reply_markup=await main_menu_keyboard(lang))


# ============================================================
# SAFETY / HELP
# ============================================================
async def safety_callback(update, context):
    query = update.callback_query
    await query.answer()
    lang = await get_user_lang(query.from_user.id)
    if lang == 'bn':
        text = ("🛡 নিরাপত্তা টিপস\n\n"
                "• পাসওয়ার্ড/OTP শেয়ার করবেন না\n"
                "• টাকা পাঠাবেন না\n"
                "• ঠিকানা/GPS শেয়ার করবেন না\n"
                "• Report করুন\n\n"
                "🚫 ৫টি রিপোর্ট = অটো-ব্যান")
    else:
        text = ("🛡 Safety Tips\n\n"
                "• Never share passwords/OTPs\n"
                "• Never send money\n"
                "• Don't share address/GPS\n"
                "• Report bad behavior\n\n"
                "🚫 5 reports = auto-ban")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def help_callback(update, context):
    query = update.callback_query
    await query.answer()
    lang = await get_user_lang(query.from_user.id)
    if lang == 'bn':
        text = ("📖 সাহায্য\n\n/start মেইন মেনু\n/stop চ্যাট শেষ\n/profile প্রোফাইল\n"
                "/coins কয়েন\n/vip প্রিমিয়াম\n/link ইনভাইট\n/leaderboard টপ\n"
                "/language ভাষা\n/joinroom /leaveroom\n/missions /achievements\n\n🔒 Anonymous")
    else:
        text = ("📖 Help\n\n/start Main\n/stop End chat\n/profile Profile\n"
                "/coins Coins\n/vip Premium\n/link Invite\n/leaderboard Top\n"
                "/language Language\n/joinroom /leaveroom\n/missions /achievements\n\n🔒 Anonymous")
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


# ============================================================
# COINS / PREMIUM
# ============================================================
async def show_coins(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    coins = await get_coins(user_id)
    vip = await is_vip(user_id)
    tier = await get_vip_tier(user_id) if vip else None
    text = f"🪙 Coins: {coins}\n⭐ Premium: {'✅ ' + (tier or 'Active') if vip else '❌ Inactive'}"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
        [InlineKeyboardButton("⭐ Premium", callback_data="show_vip")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def show_vip(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    if await is_vip(user_id):
        tier = await get_vip_tier(user_id)
        await query.edit_message_text(
            f"⭐ You're Premium!\nTier: {tier}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
        return
    rows = []
    for key, info in PREMIUM_TIERS.items():
        rows.append([InlineKeyboardButton(
            f"{info['emoji']} {info['name']} — {info['price_bdt']}৳",
            callback_data=f"tier_{key}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    text = t("choose_tier", lang) + "\n\n"
    for key, info in PREMIUM_TIERS.items():
        text += f"{info['emoji']} {info['name']} — {info['price_bdt']}৳\n{info['features']}\n\n"
    await query.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(rows))


async def tier_select(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    tier = query.data.replace("tier_", "")
    info = PREMIUM_TIERS.get(tier)
    if not info:
        await query.answer("Invalid tier")
        return
    context.user_data['payment_tier'] = tier
    text = (
        f"{info['emoji']} {info['name']}\n"
        f"💰 {info['price_bdt']}৳ — {info['days']} days\n"
        f"🎁 {info['coins']} coins bonus\n"
        f"✨ {info['features']}\n\n"
        f"{t('choose_payment', lang)}"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 bKash", callback_data=f"pay_bkash_{tier}"),
         InlineKeyboardButton("📱 Rocket", callback_data=f"pay_rocket_{tier}")],
        [InlineKeyboardButton("💎 Binance Pay", callback_data=f"pay_binance_{tier}")],
        [InlineKeyboardButton("🪙 USDT (BSC20)", callback_data=f"pay_bsc20_{tier}"),
         InlineKeyboardButton("🪙 USDT (TRC20)", callback_data=f"pay_trc20_{tier}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def payment_method(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    parts = query.data.split("_")
    method = parts[1]
    tier = parts[2] if len(parts) > 2 else "bronze"
    info = PREMIUM_TIERS.get(tier, PREMIUM_TIERS["bronze"])

    if method == "bkash":
        num, mname = BKASH_NUMBER, "bKash (Personal)"
    elif method == "rocket":
        num, mname = ROCKET_NUMBER, "Rocket"
    elif method == "binance":
        num, mname = BINANCE_ID, "Binance Pay ID"
    elif method == "bsc20":
        num, mname = USDT_BSC20, "USDT BSC20 Address"
    elif method == "trc20":
        num, mname = USDT_TRC20, "USDT TRC20 Address"
    else:
        await query.answer("Unknown method")
        return

    context.user_data['awaiting_payment'] = True
    context.user_data['payment_method'] = mname

    text = (
        f"💳 {mname}\n\n"
        f"📦 Package: {info['emoji']} {info['name']}\n"
        f"💰 Amount: {info['price_bdt']}৳ ({info['days']} days)\n\n"
        f"📍 Send to:\n`{num}`\n\n"
        f"✅ After sending, send the Transaction ID or Screenshot here.\n"
        f"⏱️ Admin will verify within 5-10 minutes."
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Number", callback_data=f"copy_{method}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def copy_number(update, context):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("copy_", "")
    nums = {"bkash": BKASH_NUMBER, "rocket": ROCKET_NUMBER, "binance": BINANCE_ID,
            "bsc20": USDT_BSC20, "trc20": USDT_TRC20}
    num = nums.get(method, "N/A")
    await query.message.reply_text(f"`{num}`\n\n👇 Tap to copy")


async def cancel_payment(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    for k in ['awaiting_payment', 'payment_tier', 'payment_method']:
        context.user_data.pop(k, None)
    await query.edit_message_text("✅ Cancelled.", reply_markup=await main_menu_keyboard(lang))


async def precheckout_callback(update, context):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    await set_vip(user_id, "bronze", 30)
    await add_coins(user_id, 50)
    await update.message.reply_text(f"🎉 Premium activated!\nTier: 🥉 Bronze\nDuration: 30 days\n🪙 +50 coins",
                                    reply_markup=await main_menu_keyboard(lang))


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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


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
    vip = await is_vip(user_id)
    tier = await get_vip_tier(user_id) if vip else None
    await update.message.reply_text(f"🪙 Coins: {coins}\n⭐ Premium: {'✅ ' + (tier or 'Active') if vip else '❌ Inactive'}")


async def vip_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    rows = []
    for key, info in PREMIUM_TIERS.items():
        rows.append([InlineKeyboardButton(f"{info['emoji']} {info['name']} — {info['price_bdt']}৳", callback_data=f"tier_{key}")])
    await update.message.reply_text(t("choose_tier", lang), reply_markup=InlineKeyboardMarkup(rows))


async def language_command(update, context):
    await update.message.reply_text(
        t("language_select", "bn"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]]))


async def profile_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    profile = await get_profile(user_id)
    if not profile:
        await update.message.reply_text(t("reg_first", lang))
        return
    stats = await get_user_stats(user_id) or {}
    xp = stats.get('xp', 0) or 0
    level = stats.get('level', 1) or 1
    next_xp = LEVEL_THRESHOLDS[level] if level < len(LEVEL_THRESHOLDS) else 0
    await update.message.reply_text(
        f"👤 {profile.get('display_name')}\n"
        f"📈 Level {level} • XP {xp}/{next_xp}\n"
        f"🪙 Coins: {stats.get('coins', 0)}\n"
        f"🔥 Streak: {stats.get('streak', 0)}\n"
        f"💬 Chats: {stats.get('total_chats', 0)}")


async def missions_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    status = await get_missions_status(user_id)
    text = f"{t('missions_title', lang)}\n\n"
    for k, m in status.items():
        if m['completed']:
            text += t("mission_done", lang, text=m['text'], reward=m['reward']) + "\n"
        else:
            text += t("mission_pending", lang, text=m['text'], current=m['progress'], target=m['target'], reward=m['reward']) + "\n"
    await update.message.reply_text(text)


async def achievements_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    unlocked = await get_user_achievements(user_id)
    text = f"{t('achievements_title', lang)}\n\n"
    for key, (emoji, title, desc) in ACHIEVEMENTS.items():
        mark = "✅" if key in unlocked else "🔒"
        text += f"{mark} {emoji} {title}\n"
    await update.message.reply_text(text[:4000])


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
            SELECT u.user_id, p.display_name, u.total_chats, u.xp, u.level
            FROM users u JOIN profiles p ON p.user_id = u.user_id
            WHERE u.total_chats > 0
            ORDER BY u.xp DESC, u.total_chats DESC LIMIT 10
        """)
    if not rows:
        await query.edit_message_text(t("leaderboard_empty", lang), reply_markup=await main_menu_keyboard(lang))
        return
    text = t("leaderboard_title", lang) + "\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        text += f"{m} {r['display_name'] or 'Anon'} — Lv{r['level']} • {r['total_chats']} chats\n"
    await query.edit_message_text(text, reply_markup=await main_menu_keyboard(lang))


async def leaderboard_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, p.display_name, u.total_chats, u.xp, u.level
            FROM users u JOIN profiles p ON p.user_id = u.user_id
            WHERE u.total_chats > 0
            ORDER BY u.xp DESC LIMIT 10
        """)
    if not rows:
        await update.message.reply_text(t("leaderboard_empty", lang))
        return
    text = t("leaderboard_title", lang) + "\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        text += f"{m} {r['display_name'] or 'Anon'} — Lv{r['level']} • {r['total_chats']} chats\n"
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
    for n in [f"end1_{user_id}", f"end2_{user_id}", f"end1_{partner_id}", f"end2_{partner_id}"]:
        for job in context.job_queue.get_jobs_by_name(n):
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
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        online = await get_online_count()
        in_q = await conn.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        chats = (await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
    await update.message.reply_text(f"📊 Stats\n👥 Users: {total}\n🟢 Online: {online}\n⏳ Queue: {in_q}\n💬 Chats: {chats}")


# ============================================================
# ADMIN
# ============================================================
async def admin_stats(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Not admin.")
        return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        online = await get_online_count()
        queue = await conn.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        chats = (await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
        pending = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'pending'") or 0
        banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE") or 0
        vip = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_vip = TRUE") or 0
        coins = await conn.fetchval("SELECT SUM(coins) FROM users") or 0
        rooms = await conn.fetchval("SELECT COUNT(*) FROM group_rooms WHERE is_active = TRUE") or 0
        pending_pay = await conn.fetchval("SELECT COUNT(*) FROM payments WHERE status = 'pending'") or 0
        revenue = await conn.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status = 'approved'") or 0
    await update.message.reply_text(
        f"📊 Admin Dashboard\n\n"
        f"👥 Users: {total}\n🟢 Online: {online}\n⏳ Queue: {queue}\n"
        f"💬 Chats: {chats}\n👥 Rooms: {rooms}\n"
        f"⚠️ Reports: {pending}\n🚫 Banned: {banned}\n⭐ Premium: {vip}\n"
        f"🪙 Coins: {coins}\n\n"
        f"💳 Pending Payments: {pending_pay}\n💰 Revenue: {revenue}৳"
    )


async def ban_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    try:
        target = int(context.args[0])
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1", target)
        await update.message.reply_text(f"✅ Banned: {target}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def unban_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        target = int(context.args[0])
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_banned = FALSE WHERE user_id = $1", target)
        await update.message.reply_text(f"✅ Unbanned: {target}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def approve_command(update, context):
    """Usage: /approve <user_id> <tier>"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /approve <user_id> <tier>\nTiers: bronze/silver/gold/diamond")
        return
    try:
        target = int(context.args[0])
        tier = context.args[1].lower()
        info = PREMIUM_TIERS.get(tier)
        if not info:
            await update.message.reply_text("❌ Invalid tier")
            return
        await set_vip(target, tier, info['days'])
        await add_coins(target, info['coins'])
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE payments SET status='approved', approved_at=NOW(), approved_by=$1 WHERE user_id=$2 AND status='pending'",
                               update.effective_user.id, target)
        try:
            t_lang = await get_user_lang(target)
            await context.bot.send_message(
                target,
                t("premium_activated", t_lang, tier=info['name'], days=info['days'], coins=info['coins'])
            )
        except Exception:
            pass
        await update.message.reply_text(f"✅ Premium activated for {target} ({tier})")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def broadcast_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
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


async def pending_payments_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM payments WHERE status = 'pending' ORDER BY created_at DESC LIMIT 20")
    if not rows:
        await update.message.reply_text("✅ No pending payments.")
        return
    text = "💳 Pending Payments:\n\n"
    for r in rows:
        text += f"🆔 #{r['payment_id']}\n👤 `{r['user_id']}`\n📦 {r['tier']} • {r['method']}\n📝 {r['transaction_id'][:60]}\n➡️ /approve {r['user_id']} {r['tier']}\n\n"
    await update.message.reply_text(text[:4000])


async def revenue_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    async with db_pool.acquire() as conn:
        approved = await conn.fetchval("SELECT COUNT(*) FROM payments WHERE status='approved'") or 0
        pending = await conn.fetchval("SELECT COUNT(*) FROM payments WHERE status='pending'") or 0
        total = await conn.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved'") or 0
        today_total = await conn.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved' AND approved_at > NOW() - INTERVAL '1 day'") or 0
        month_total = await conn.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved' AND approved_at > NOW() - INTERVAL '30 days'") or 0
    await update.message.reply_text(
        f"💰 Revenue Tracker\n\n"
        f"✅ Approved: {approved}\n⏳ Pending: {pending}\n\n"
        f"💵 Total: {total}৳\n📅 Today: {today_total}৳\n📆 Last 30d: {month_total}৳"
    )


async def user_info_command(update, context):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /userinfo <user_id>")
        return
    try:
        target = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID")
        return
    profile = await get_profile(target)
    stats = await get_user_stats(target)
    if not stats:
        await update.message.reply_text("User not found.")
        return
    text = (
        f"👤 User: `{target}`\n"
        f"📛 Name: {(profile or {}).get('display_name', 'N/A')}\n"
        f"📈 Level: {stats.get('level', 1)} • XP: {stats.get('xp', 0)}\n"
        f"🪙 Coins: {stats.get('coins', 0)}\n"
        f"🔥 Streak: {stats.get('streak', 0)}\n"
        f"💬 Chats: {stats.get('total_chats', 0)}\n"
        f"⭐ VIP: {'Yes (' + (stats.get('vip_tier') or '?') + ')' if stats.get('is_vip') else 'No'}"
    )
    await update.message.reply_text(text)


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
    app = (Application.builder()
           .token(BOT_TOKEN)
           .request(request)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .build())

    # Commands
    cmds = [
        ("start", start), ("stop", stop_chat), ("reset", reset_command),
        ("stats", stats_command), ("link", link_command), ("coins", coins_command),
        ("vip", vip_command), ("language", language_command),
        ("leaderboard", leaderboard_command), ("profile", profile_command),
        ("missions", missions_command), ("achievements", achievements_command),
        ("joinroom", join_room_command), ("leaveroom", leave_room_command),
        ("adminstats", admin_stats), ("ban", ban_command), ("unban", unban_command),
        ("approve", approve_command), ("broadcast", broadcast_command),
        ("pending", pending_payments_command), ("revenue", revenue_command),
        ("userinfo", user_info_command),
    ]
    for name, fn in cmds:
        app.add_handler(CommandHandler(name, fn))

    # Callbacks (specific first)
    for pattern, fn in [
        ("^lang_", language_callback), ("^change_language$", change_language),
        ("^age_", age_gate_callback), ("^gender_", gender_callback),
        ("^pref_", pref_gender_callback), ("^int_", interest_callback),
        ("^plang_", pref_lang_callback),
        ("^setpg_", set_pref_gender_edit), ("^setint_", set_interest_edit),
        ("^setplang_", set_plang_edit), ("^setage_", set_age_range),
        ("^edit_name$", edit_name), ("^edit_bio$", edit_bio),
        ("^edit_pref_gender$", edit_pref_gender), ("^edit_interest$", edit_interest),
        ("^edit_lang$", edit_lang), ("^edit_age_range$", edit_age_range),
        ("^edit_profile$", edit_profile),
        ("^main_menu$", main_menu_callback), ("^refresh_online$", refresh_online),
        ("^find_partner$", find_partner), ("^cancel_search$", cancel_search),
        ("^ai_chat$", ai_chat_start), ("^show_link$", show_link),
        ("^show_coins$", show_coins), ("^show_vip$", show_vip),
        ("^show_achievements$", show_achievements), ("^show_missions$", show_missions),
        ("^show_friends$", show_friends),
        ("^tier_", tier_select),
        ("^pay_", payment_method), ("^copy_", copy_number),
        ("^cancel_payment$", cancel_payment),
        ("^end_chat$", end_chat_callback), ("^next_partner$", next_partner),
        ("^addfriend_", add_friend_callback),
        ("^rpr_", report_reason_callback), ("^report_", report_callback),
        ("^my_profile$", my_profile), ("^safety$", safety_callback),
        ("^help$", help_callback), ("^leaderboard$", leaderboard),
        ("^group_menu$", group_menu), ("^create_room$", create_room),
        ("^joinroom_", join_room_callback), ("^leave_room$", leave_room_callback),
    ]:
        app.add_handler(CallbackQueryHandler(fn, pattern=pattern))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_text))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
