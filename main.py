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

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
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

ONLINE_THRESHOLD_MINUTES = 5
QUEUE_TIMEOUT_SECONDS = 120
AUTO_BAN_REPORT_COUNT = 5
REFERRAL_COIN_REWARD = 20
CHAT_COIN_REWARD = 1
VIP_PRICE_COINS = 500
VIP_STARS_PRICE = 100
VIP_DURATION_DAYS = 30

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
    "age_denied": {
        "bn": "❌ দুঃখিত, এই বটটি শুধুমাত্র ১৮+ ব্যবহারকারীদের জন্য।",
        "en": "❌ Sorry, this bot is only for 18+ users.",
    },
    "ask_name": {"bn": "✅ ধন্যবাদ! এখন আপনার নাম লিখুন:", "en": "✅ Thanks! Now enter your name:"},
    "ask_age": {"bn": "🎂 আপনার বয়স লিখুন (শুধু সংখ্যা):", "en": "🎂 Enter your age (numbers only):"},
    "ask_gender": {"bn": "⚧ আপনার জেন্ডার নির্বাচন করুন:", "en": "⚧ Select your gender:"},
    "ask_pref": {"bn": "🎯 আপনি কার সাথে চ্যাট করতে চান?", "en": "🎯 Who do you want to chat with?"},
    "ask_bio": {"bn": "📝 একটি ছোট বায়ো লিখুন (সর্বোচ্চ ২০০ অক্ষর):", "en": "📝 Write a short bio (max 200 chars):"},
    "male": {"bn": "👦 ছেলে", "en": "👦 Male"},
    "female": {"bn": "👧 মেয়ে", "en": "👧 Female"},
    "other": {"bn": "🌈 অন্যান্য", "en": "🌈 Other"},
    "any": {"bn": "🌍 যে কেউ", "en": "🌍 Anyone"},
    "main_menu": {"bn": "🏠 মেইন মেনু — নিচের বাটন থেকে নির্বাচন করুন:", "en": "🏠 Main Menu — Choose from below:"},
    "find_partner": {"bn": "🔍 Find Partner", "en": "🔍 Find Partner"},
    "my_profile": {"bn": "👤 My Profile", "en": "👤 My Profile"},
    "safety": {"bn": "🛡 Safety", "en": "🛡 Safety"},
    "help": {"bn": "ℹ️ Help", "en": "ℹ️ Help"},
    "coins": {"bn": "🪙 কয়েন", "en": "🪙 Coins"},
    "vip": {"bn": "⭐ VIP", "en": "⭐ VIP"},
    "invite": {"bn": "🔗 Invite", "en": "🔗 Invite"},
    "end_chat": {"bn": "🛑 End Chat", "en": "🛑 End Chat"},
    "next_person": {"bn": "➡️ Next Person", "en": "➡️ Next Person"},
    "report": {"bn": "🚫 Report", "en": "🚫 Report"},
    "reg_done": {
        "bn": "✅ রেজিস্ট্রেশন সম্পন্ন! 🎉",
        "en": "✅ Registration complete! 🎉",
    },
    "searching": {
        "bn": "⏳ পার্টনার খোঁজা হচ্ছে...\n\nঅনুগ্রহ করে অপেক্ষা করুন। কেউ অনলাইনে এলেই আপনাকে কানেক্ট করা হবে।",
        "en": "⏳ Searching for partner...\n\nPlease wait. You'll be connected as soon as someone comes online.",
    },
    "partner_found": {
        "bn": "✅ পার্টনার পাওয়া গেছে!\n\n💬 এখন যেকোনো মেসেজ পাঠান — টেক্সট, ছবি, ভয়েস সবই যাবে।\n🔒 আপনার পরিচয় সম্পূর্ণ গোপন থাকবে।",
        "en": "✅ Partner found!\n\n💬 Send any message — text, photo, voice all work.\n🔒 Your identity is completely anonymous.",
    },
    "chat_ended": {"bn": "🛑 চ্যাট শেষ হয়েছে।", "en": "🛑 Chat ended."},
    "partner_ended": {
        "bn": "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।",
        "en": "🛑 Your partner ended the chat.",
    },
    "partner_left": {
        "bn": "🛑 আপনার পার্টনার নতুন পার্টনার খুঁজতে চলে গেছেন।",
        "en": "🛑 Your partner left to find someone new.",
    },
    "not_in_chat": {"bn": "⚠️ আপনি কোনো চ্যাটে নেই। /start দিন।", "en": "⚠️ You're not in a chat. Send /start."},
    "reg_first": {"bn": "❌ আগে /start দিন।", "en": "❌ Please /start first."},
    "already_in_chat": {
        "bn": "❌ আপনি ইতিমধ্যে একটি চ্যাটে আছেন।",
        "en": "❌ You're already in a chat.",
    },
    "search_cancelled": {"bn": "❌ সার্চ বাতিল করা হয়েছে।", "en": "❌ Search cancelled."},
    "online_count": {"bn": "🟢 এখন {n} জন অনলাইনে আছেন", "en": "🟢 {n} users online now"},
    "referral_msg": {
        "bn": "🔗 আপনার ইনভাইট লিংক:\n\n{link}\n\n💡 বন্ধুদের ইনভাইট করলে প্রতি জয়েনে {coins} কয়েন পাবেন!",
        "en": "🔗 Your invite link:\n\n{link}\n\n💡 Earn {coins} coins per friend who joins!",
    },
    "coins_balance": {
        "bn": "🪙 আপনার কয়েন: {coins}\n⭐ VIP: {vip}",
        "en": "🪙 Your coins: {coins}\n⭐ VIP: {vip}",
    },
    "vip_active": {"bn": "✅ Active", "en": "✅ Active"},
    "vip_inactive": {"bn": "❌ Inactive", "en": "❌ Inactive"},
    "vip_buy_msg": {
        "bn": "⭐ VIP সাবস্ক্রিপশন\n\n💰 {price} কয়েন অথবা {stars} Telegram Stars দিয়ে {days} দিনের জন্য VIP কিনুন।\n\n🎁 VIP সুবিধা:\n• আনলিমিটেড চ্যাট\n• প্রায়োরিটি ম্যাচিং\n• বিজ্ঞাপনমুক্ত",
        "en": "⭐ VIP Subscription\n\n💰 Get {days}-day VIP for {price} coins or {stars} Telegram Stars.\n\n🎁 VIP Benefits:\n• Unlimited chats\n• Priority matching\n• No ads",
    },
    "vip_bought": {
        "bn": "🎉 অভিনন্দন! আপনি VIP হয়েছেন!\n\n✅ {days} দিনের জন্য VIP সক্রিয়।",
        "en": "🎉 Congratulations! You're now VIP!\n\n✅ VIP active for {days} days.",
    },
    "not_enough_coins": {
        "bn": "❌ আপনার যথেষ্ট কয়েন নেই।\n\n🪙 প্রয়োজন: {need}\n🪙 আপনার আছে: {have}\n\n💡 কয়েন আর্ন করতে /link ব্যবহার করুন।",
        "en": "❌ Not enough coins.\n\n🪙 Need: {need}\n🪙 You have: {have}\n\n💡 Use /link to earn coins.",
    },
    "already_vip": {"bn": "⭐ আপনি ইতিমধ্যে VIP!", "en": "⭐ You're already VIP!"},
    "buy_with_coins": {"bn": "💰 কয়েন দিয়ে কিনুন", "en": "💰 Buy with Coins"},
    "buy_with_stars": {"bn": "⭐ Stars দিয়ে কিনুন", "en": "⭐ Buy with Stars"},
    "back": {"bn": "🔙 Back", "en": "🔙 Back"},
    "language_select": {
        "bn": "🌍 ভাষা নির্বাচন করুন:\n\nSelect your language:",
        "en": "🌍 Choose your language:\n\nআপনার ভাষা নির্বাচন করুন:",
    },
    "banned": {"bn": "🚫 আপনি এই বট থেকে ব্যান হয়েছেন।", "en": "🚫 You are banned from this bot."},
    "rate_limited": {"bn": "⏳ একটু অপেক্ষা করুন।", "en": "⏳ Please wait a moment."},
    "report_thanks": {"bn": "✅ ধন্যবাদ। আপনার রিপোর্ট জমা হয়েছে।", "en": "✅ Thank you. Your report has been submitted."},
    "report_blocked": {
        "bn": "✅ ধন্যবাদ। রিপোর্ট জমা হয়েছে এবং পার্টনারকে ব্লক করা হয়েছে।",
        "en": "✅ Thank you. Report submitted and partner blocked.",
    },
    "referral_bonus": {
        "bn": "🎁 আপনি {coins} কয়েন পেয়েছেন বন্ধু ইনভাইটের জন্য!",
        "en": "🎁 You earned {coins} coins for referring a friend!",
    },
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
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
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
            CREATE TABLE IF NOT EXISTS profiles (
                user_id BIGINT PRIMARY KEY,
                display_name VARCHAR(100),
                age INTEGER,
                gender VARCHAR(20),
                pref_gender VARCHAR(20) DEFAULT 'any',
                bio TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS match_queue (
                user_id BIGINT PRIMARY KEY,
                gender VARCHAR(20),
                pref_gender VARCHAR(20),
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS active_chats (
                user_id BIGINT PRIMARY KEY,
                partner_id BIGINT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS blocks (
                blocker_id BIGINT,
                blocked_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            );
            CREATE TABLE IF NOT EXISTS reports (
                report_id SERIAL PRIMARY KEY,
                reporter_id BIGINT,
                reported_id BIGINT,
                reason VARCHAR(100),
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(5) DEFAULT 'bn';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS coins INTEGER DEFAULT 0;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_vip BOOLEAN DEFAULT FALSE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_until TIMESTAMP;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;
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
        await conn.execute(
            "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = $1",
            user_id
        )


async def get_user_lang(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT language FROM users WHERE user_id = $1", user_id)
        return row['language'] if row and row['language'] else 'bn'


async def set_user_lang(user_id, lang):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET language = $1 WHERE user_id = $2", lang, user_id)


async def get_online_count():
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE last_active > NOW() - INTERVAL '5 minutes'"
        )
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
        await conn.execute(
            "UPDATE users SET is_vip = TRUE, vip_until = $1 WHERE user_id = $2",
            until, user_id
        )


# ============================================================
# REFERRAL
# ============================================================
async def process_referral(new_user_id, referrer_id):
    if new_user_id == referrer_id:
        return False
    async with db_pool.acquire() as conn:
        already = await conn.fetchval("SELECT referred_by FROM users WHERE user_id = $1", new_user_id)
        if already:
            return False
        await conn.execute("UPDATE users SET referred_by = $1 WHERE user_id = $2", referrer_id, new_user_id)
    await add_coins(referrer_id, REFERRAL_COIN_REWARD)
    return True


# ============================================================
# RATE LIMIT
# ============================================================
rate_limit_store = {}


def is_rate_limited(user_id, max_requests=10, window_seconds=10):
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


async def main_menu_keyboard(lang):
    online = await get_online_count()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("find_partner", lang), callback_data="find_partner")],
        [InlineKeyboardButton(t("my_profile", lang), callback_data="my_profile")],
        [InlineKeyboardButton(t("coins", lang), callback_data="show_coins"),
         InlineKeyboardButton(t("vip", lang), callback_data="show_vip")],
        [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
        [InlineKeyboardButton(f"🟢 {online}", callback_data="refresh_online"),
         InlineKeyboardButton(t("safety", lang), callback_data="safety"),
         InlineKeyboardButton(t("help", lang), callback_data="help")]
    ])


async def chat_keyboard(partner_id, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("next_person", lang), callback_data="next_partner")],
        [InlineKeyboardButton(t("end_chat", lang), callback_data="end_chat")],
        [InlineKeyboardButton(t("report", lang), callback_data=f"report_{partner_id}")]
    ])


# ============================================================
# QUEUE TIMEOUT
# ============================================================
async def queue_timeout_check(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data['user_id']
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        still_in_queue = await conn.fetchrow(
            "SELECT 1 FROM match_queue WHERE user_id = $1", user_id
        )
        active_chat = await conn.fetchrow(
            "SELECT 1 FROM active_chats WHERE user_id = $1", user_id
        )
    if still_in_queue and not active_chat:
        try:
            text = (
                "⏰ এখনো কেউ অনলাইনে আসেনি।\n\n"
                "💡 আপনি অপেক্ষা করতে পারেন অথবা সার্চ বাতিল করতে পারেন।"
                if lang == 'bn' else
                "⏰ No one has come online yet.\n\n"
                "💡 You can keep waiting or cancel the search."
            )
            await context.bot.send_message(
                user_id,
                text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                    [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"Queue timeout notify error: {e}")


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

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            context.user_data.clear()
            context.user_data['reg_step'] = 'language'
            await update.message.reply_text(
                "🌍 ভাষা নির্বাচন করুন:\n\nSelect your language:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
                    [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
                ])
            )
            return

    lang = user.get('language') or 'bn'

    # Referral
    if args and args[0].startswith("ref_"):
        try:
            referrer_id = int(args[0][4:])
            if referrer_id != user_id:
                success = await process_referral(user_id, referrer_id)
                if success:
                    await update.message.reply_text(t("referral_bonus", lang, coins=REFERRAL_COIN_REWARD))
        except (ValueError, IndexError):
            pass

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

    chat = await get_active_chat(user_id)
    if chat:
        await update.message.reply_text(
            t("already_in_chat", lang),
            reply_markup=await chat_keyboard(chat['partner_id'], lang)
        )
        return

    online = await get_online_count()
    await update.message.reply_text(
        f"{t('main_menu', lang)}\n\n{t('online_count', lang, n=online)}",
        reply_markup=await main_menu_keyboard(lang)
    )


# ============================================================
# LANGUAGE SELECT
# ============================================================
async def language_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = "bn" if query.data == "lang_bn" else "en"
    await set_user_lang(user_id, lang)
    context.user_data['reg_step'] = 'age_gate'
    await query.edit_message_text(
        t("welcome", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("age_yes", lang), callback_data="age_yes")],
            [InlineKeyboardButton(t("age_no", lang), callback_data="age_no")]
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

    if not step:
        await handle_chat_message(update, context)
        return

    if step == 'name':
        if len(text) < 2 or len(text) > 50:
            await update.message.reply_text(
                "⚠️ নাম ২-৫০ অক্ষর / Name 2-50 chars"
            )
            return
        await save_profile(user_id, display_name=text)
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text(t("ask_age", lang))
        return

    if step == 'age':
        if not text.isdigit() or int(text) < 18 or int(text) > 99:
            await update.message.reply_text("⚠️ বয়স ১৮-৯৯ / Age 18-99")
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

    if step in ('gender', 'pref_gender'):
        await update.message.reply_text("⚠️ উপরের বাটন ব্যবহার করুন / Use buttons above")
        return


# ============================================================
# GENDER / PREF CALLBACKS
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

    user_gender = profile.get('gender') or 'any'
    user_pref = profile.get('pref_gender') or 'any'

    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)

        if user_pref == 'any':
            candidate = await conn.fetchrow("""
                SELECT mq.* FROM match_queue mq
                WHERE mq.user_id != $1
                AND (mq.pref_gender = 'any' OR mq.pref_gender = $2)
                AND NOT EXISTS (
                    SELECT 1 FROM blocks
                    WHERE (blocker_id = $1 AND blocked_id = mq.user_id)
                    OR (blocker_id = mq.user_id AND blocked_id = $1)
                )
                ORDER BY mq.queued_at ASC
                LIMIT 1
            """, user_id, user_gender)
        else:
            candidate = await conn.fetchrow("""
                SELECT mq.* FROM match_queue mq
                WHERE mq.user_id != $1
                AND mq.gender = $2
                AND (mq.pref_gender = 'any' OR mq.pref_gender = $3)
                AND NOT EXISTS (
                    SELECT 1 FROM blocks
                    WHERE (blocker_id = $1 AND blocked_id = mq.user_id)
                    OR (blocker_id = mq.user_id AND blocked_id = $1)
                )
                ORDER BY mq.queued_at ASC
                LIMIT 1
            """, user_id, user_pref, user_gender)

        if candidate:
            partner_id = candidate['user_id']
            await conn.execute("DELETE FROM match_queue WHERE user_id = $1", partner_id)

            await conn.execute("""
                INSERT INTO active_chats (user_id, partner_id) VALUES ($1, $2), ($2, $1)
                ON CONFLICT (user_id) DO UPDATE SET partner_id = EXCLUDED.partner_id, started_at = CURRENT_TIMESTAMP
            """, user_id, partner_id)

            partner_lang = await get_user_lang(partner_id)

            await query.edit_message_text(
                t("partner_found", lang),
                reply_markup=await chat_keyboard(partner_id, lang)
            )
            try:
                await context.bot.send_message(
                    partner_id,
                    t("partner_found", partner_lang),
                    reply_markup=await chat_keyboard(user_id, partner_lang)
                )
            except Exception as e:
                logger.error(f"Notify partner error: {e}")

            # কয়েন রিওয়ার্ড (VIP হলে দ্বিগুণ)
            reward = CHAT_COIN_REWARD * 2 if await is_vip(user_id) else CHAT_COIN_REWARD
            await add_coins(user_id, reward)
        else:
            await conn.execute("""
                INSERT INTO match_queue (user_id, gender, pref_gender) VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET queued_at = CURRENT_TIMESTAMP
            """, user_id, user_gender, user_pref)

            await query.edit_message_text(
                t("searching", lang),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                    [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
                ])
            )

            job_name = f"queue_timeout_{user_id}"
            for job in context.job_queue.get_jobs_by_name(job_name):
                job.schedule_removal()
            context.job_queue.run_once(
                queue_timeout_check,
                QUEUE_TIMEOUT_SECONDS,
                data={'user_id': user_id},
                name=job_name
            )


async def cancel_search(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
    job_name = f"queue_timeout_{user_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    await query.edit_message_text(
        t("search_cancelled", lang),
        reply_markup=await main_menu_keyboard(lang)
    )


# ============================================================
# CHAT MESSAGE
# ============================================================
async def handle_chat_message(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        await update.message.reply_text(t("not_in_chat", lang))
        return
    if is_rate_limited(user_id, max_requests=15, window_seconds=10):
        await update.message.reply_text(t("rate_limited", lang))
        return
    partner_id = chat['partner_id']
    try:
        await context.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=user_id,
            message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Copy failed: {e}")
        await update.message.reply_text("❌ Message not sent.")


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
        await query.edit_message_text(
            t("not_in_chat", lang),
            reply_markup=await main_menu_keyboard(lang)
        )
        return
    partner_id = chat['partner_id']
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", user_id, partner_id)
    await query.edit_message_text(
        t("chat_ended", lang),
        reply_markup=await main_menu_keyboard(lang)
    )
    try:
        partner_lang = await get_user_lang(partner_id)
        await context.bot.send_message(
            partner_id,
            t("partner_ended", partner_lang),
            reply_markup=await main_menu_keyboard(partner_lang)
        )
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
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", user_id, partner_id)
        try:
            partner_lang = await get_user_lang(partner_id)
            await context.bot.send_message(
                partner_id,
                t("partner_left", partner_lang),
                reply_markup=await main_menu_keyboard(partner_lang)
            )
        except Exception:
            pass

    await query.edit_message_text("🔍...")
    await asyncio.sleep(1)
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
    keyboard = [[InlineKeyboardButton(r[0], callback_data=f"report_reason_{r[1]}_{reported_id}")] for r in reasons]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="end_chat")])
    await query.edit_message_text(
        "⚠️ Report reason:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def report_reason_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    reason = parts[2]
    reported_id = int(parts[3])
    reporter_id = query.from_user.id
    lang = await get_user_lang(reporter_id)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reports (reporter_id, reported_id, reason) VALUES ($1, $2, $3)",
            reporter_id, reported_id, reason
        )
        await conn.execute(
            "INSERT INTO blocks (blocker_id, blocked_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            reporter_id, reported_id
        )
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", reporter_id, reported_id)

        unique_reporters = await conn.fetchval(
            "SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE reported_id = $1 AND status = 'pending'",
            reported_id
        )

        auto_banned = False
        if unique_reporters and unique_reporters >= AUTO_BAN_REPORT_COUNT:
            await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1", reported_id)
            await conn.execute("UPDATE reports SET status = 'actioned' WHERE reported_id = $1", reported_id)
            auto_banned = True
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"🚨 Auto-Ban\n👤 ID: {reported_id}\n📊 Reports: {unique_reporters}"
                    )
                except Exception:
                    pass

    await query.edit_message_text(
        t("report_thanks" if auto_banned else "report_blocked", lang),
        reply_markup=await main_menu_keyboard(lang)
    )
    try:
        p_lang = await get_user_lang(reported_id)
        await context.bot.send_message(
            reported_id,
            t("partner_ended", p_lang),
            reply_markup=await main_menu_keyboard(p_lang)
        )
    except Exception:
        pass


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
    gender_map = {"male": "ছেলে/Male", "female": "মেয়ে/Female", "other": "অন্যান্য/Other"}
    pref_map = {"male": "ছেলে/Male", "female": "মেয়ে/Female", "any": "যে কেউ/Anyone"}
    coins = await get_coins(user_id)
    vip_status = t("vip_active", lang) if await is_vip(user_id) else t("vip_inactive", lang)
    text = (
        f"👤 {profile.get('display_name', 'N/A')}\n"
        f"🎂 Age: {profile.get('age', 'N/A')}\n"
        f"⚧ Gender: {gender_map.get(profile.get('gender'), 'N/A')}\n"
        f"🎯 Pref: {pref_map.get(profile.get('pref_gender'), 'N/A')}\n"
        f"🪙 Coins: {coins}\n"
        f"⭐ VIP: {vip_status}\n\n"
        f"💬 Bio: {(profile.get('bio') or 'N/A')[:200]}"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )


# ============================================================
# SAFETY / HELP
# ============================================================
async def safety_callback(update, context):
    query = update.callback_query
    await query.answer()
    lang = await get_user_lang(query.from_user.id)
    if lang == 'bn':
        text = (
            "🛡 নিরাপত্তা টিপস\n\n"
            "• কখনো পাসওয়ার্ড বা OTP শেয়ার করবেন না\n"
            "• অনলাইনে কাউকে টাকা পাঠাবেন না\n"
            "• বাড়ির ঠিকানা বা GPS শেয়ার করবেন না\n"
            "• সন্দেহজনক লিংকে ক্লিক করবেন না\n"
            "• খারাপ ব্যবহার হলে Report করুন\n\n"
            "🚫 ৫টি রিপোর্ট পেলে ইউজার অটো-ব্যান।"
        )
    else:
        text = (
            "🛡 Safety Tips\n\n"
            "• Never share passwords or OTPs\n"
            "• Never send money online\n"
            "• Don't share home address or GPS\n"
            "• Don't click suspicious links\n"
            "• Report bad behavior\n\n"
            "🚫 5 reports = auto-ban."
        )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )


async def help_callback(update, context):
    query = update.callback_query
    await query.answer()
    lang = await get_user_lang(query.from_user.id)
    if lang == 'bn':
        text = (
            "📖 সাহায্য\n\n"
            "/start — মেইন মেনু\n"
            "/stop — চ্যাট শেষ\n"
            "/reset — প্রোফাইল রিসেট\n"
            "/stats — পরিসংখ্যান\n"
            "/link — ইনভাইট লিংক\n"
            "/coins — কয়েন ব্যালেন্স\n"
            "/vip — VIP কিনুন\n"
            "/language — ভাষা পরিবর্তন\n\n"
            "🎯 Find Partner → সরাসরি কানেক্ট।\n"
            "🔒 সম্পূর্ণ অ্যানোনিমাস।"
        )
    else:
        text = (
            "📖 Help\n\n"
            "/start — Main Menu\n"
            "/stop — End chat\n"
            "/reset — Reset profile\n"
            "/stats — Bot stats\n"
            "/link — Invite link\n"
            "/coins — Coin balance\n"
            "/vip — Buy VIP\n"
            "/language — Change language\n\n"
            "🎯 Find Partner → direct connect.\n"
            "🔒 Fully anonymous."
        )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
        ])
    )


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
        await query.edit_message_text(
            t("already_vip", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
            ])
        )
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
        await query.edit_message_text(
            t("already_vip", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
            ])
        )
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
    success = await deduct_coins(user_id, VIP_PRICE_COINS)
    if success:
        await set_vip(user_id, VIP_DURATION_DAYS)
        await query.edit_message_text(
            t("vip_bought", lang, days=VIP_DURATION_DAYS),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
            ])
        )


async def vip_with_stars(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = await get_user_lang(user_id)
    if await is_vip(user_id):
        await query.edit_message_text(
            t("already_vip", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]
            ])
        )
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
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    await set_vip(user_id, VIP_DURATION_DAYS)
    await update.message.reply_text(
        t("vip_bought", lang, days=VIP_DURATION_DAYS),
        reply_markup=await main_menu_keyboard(lang)
    )


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
    await update.message.reply_text(
        t("referral_msg", lang, link=link, coins=REFERRAL_COIN_REWARD)
    )


async def coins_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    coins = await get_coins(user_id)
    vip_status = t("vip_active", lang) if await is_vip(user_id) else t("vip_inactive", lang)
    await update.message.reply_text(
        t("coins_balance", lang, coins=coins, vip=vip_status)
    )


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
        "🌍 ভাষা / Language:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
        ])
    )


# ============================================================
# STOP / RESET / STATS / ADMIN
# ============================================================
async def stop_chat(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    chat = await get_active_chat(user_id)
    if not chat:
        await update.message.reply_text(t("not_in_chat", lang))
        return
    partner_id = chat['partner_id']
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", user_id, partner_id)
    await update.message.reply_text(
        t("chat_ended", lang),
        reply_markup=await main_menu_keyboard(lang)
    )
    try:
        p_lang = await get_user_lang(partner_id)
        await context.bot.send_message(
            partner_id,
            t("partner_ended", p_lang),
            reply_markup=await main_menu_keyboard(p_lang)
        )
    except Exception:
        pass


async def reset_command(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM profiles WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1", user_id)
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
        await update.message.reply_text(
            f"📊 পরিসংখ্যান\n\n"
            f"👥 মোট ইউজার: {total_users}\n"
            f"🟢 অনলাইনে: {online}\n"
            f"⏳ খুঁজছেন: {in_queue}\n"
            f"💬 চলমান চ্যাট: {active_chats}"
        )
    else:
        await update.message.reply_text(
            f"📊 Statistics\n\n"
            f"👥 Total Users: {total_users}\n"
            f"🟢 Online: {online}\n"
            f"⏳ Searching: {in_queue}\n"
            f"💬 Active Chats: {active_chats}"
        )


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
    await update.message.reply_text(
        f"📊 Admin Dashboard\n\n"
        f"👥 Users: {total_users}\n"
        f"🟢 Online: {online}\n"
        f"⏳ Queue: {in_queue}\n"
        f"💬 Chats: {active_chats}\n"
        f"⚠️ Reports: {pending}\n"
        f"🚫 Banned: {banned}\n"
        f"⭐ VIP: {vip_count}"
    )


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
    app.add_handler(CommandHandler("adminstats", admin_stats))

    # Callbacks
    app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(age_gate_callback, pattern="^age_"))
    app.add_handler(CallbackQueryHandler(gender_callback, pattern="^gender_"))
    app.add_handler(CallbackQueryHandler(pref_gender_callback, pattern="^pref_"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(refresh_online, pattern="^refresh_online$"))
    app.add_handler(CallbackQueryHandler(find_partner, pattern="^find_partner$"))
    app.add_handler(CallbackQueryHandler(cancel_search, pattern="^cancel_search$"))
    app.add_handler(CallbackQueryHandler(show_link, pattern="^show_link$"))
    app.add_handler(CallbackQueryHandler(show_coins, pattern="^show_coins$"))
    app.add_handler(CallbackQueryHandler(show_vip, pattern="^show_vip$"))
    app.add_handler(CallbackQueryHandler(vip_with_coins, pattern="^vip_coins$"))
    app.add_handler(CallbackQueryHandler(vip_with_stars, pattern="^vip_stars$"))
    app.add_handler(CallbackQueryHandler(end_chat_callback, pattern="^end_chat$"))
    app.add_handler(CallbackQueryHandler(next_partner, pattern="^next_partner$"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))
    app.add_handler(CallbackQueryHandler(report_reason_callback, pattern="^report_reason_"))
    app.add_handler(CallbackQueryHandler(my_profile, pattern="^my_profile$"))
    app.add_handler(CallbackQueryHandler(safety_callback, pattern="^safety$"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))

    # Payment
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_chat_message))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
