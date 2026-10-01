import os
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
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
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        """)
    logger.info("Database initialized.")


async def close_db():
    if db_pool:
        await db_pool.close()


async def touch_user(user_id):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = $1",
            user_id
        )


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


rate_limit_store = {}


def is_rate_limited(user_id, max_requests=10, window_seconds=10):
    now = datetime.now()
    timestamps = rate_limit_store.get(user_id, [])
    timestamps = [t for t in timestamps if (now - t).total_seconds() < window_seconds]
    if len(timestamps) >= max_requests:
        rate_limit_store[user_id] = timestamps
        return True
    timestamps.append(now)
    rate_limit_store[user_id] = timestamps
    return False


async def get_active_chat(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM active_chats WHERE user_id = $1", user_id)
        return dict(row) if row else None


async def main_menu_keyboard():
    online = await get_online_count()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Find Partner", callback_data="find_partner")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_profile")],
        [InlineKeyboardButton(f"🟢 Online: {online}", callback_data="refresh_online")],
        [InlineKeyboardButton("🛡 Safety", callback_data="safety")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ])


async def chat_keyboard(partner_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Next Person", callback_data="next_partner")],
        [InlineKeyboardButton("🛑 End Chat", callback_data="end_chat")],
        [InlineKeyboardButton("🚫 Report", callback_data=f"report_{partner_id}")]
    ])


async def queue_timeout_check(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data['user_id']
    async with db_pool.acquire() as conn:
        still_in_queue = await conn.fetchrow(
            "SELECT 1 FROM match_queue WHERE user_id = $1", user_id
        )
        active_chat = await conn.fetchrow(
            "SELECT 1 FROM active_chats WHERE user_id = $1", user_id
        )
    if still_in_queue and not active_chat:
        try:
            await context.bot.send_message(
                user_id,
                "⏰ এখনো কেউ অনলাইনে আসেনি।\n\n"
                "💡 আপনি অপেক্ষা করতে পারেন অথবা সার্চ বাতিল করতে পারেন।\n"
                "🔗 বন্ধুদের ইনভাইট করলে দ্রুত পার্টনার পাবেন।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel Search", callback_data="cancel_search")],
                    [InlineKeyboardButton("🔗 Invite Friends", callback_data="show_link")],
                    [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main_menu")]
                ])
            )
        except Exception as e:
            logger.error(f"Queue timeout notify error: {e}")


async def start(update, context):
    user_id = update.effective_user.id
    await touch_user(user_id)

    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 আপনি এই বট থেকে ব্যান হয়েছেন।")
        return

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            context.user_data.clear()
            context.user_data['reg_step'] = 'age_gate'
            await update.message.reply_text(
                "👋 স্বাগতম! এটি একটি অ্যানোনিমাস চ্যাটিং বট।\n\n"
                "শুরু করার আগে নিশ্চিত করুন যে আপনার বয়স ১৮+।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ হ্যাঁ, আমি ১৮+", callback_data="age_yes")],
                    [InlineKeyboardButton("❌ না", callback_data="age_no")]
                ])
            )
            return

    profile = await get_profile(user_id)
    if not profile or not profile.get('display_name'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'name'
        await update.message.reply_text("✅ ধন্যবাদ! এখন আপনার নাম লিখুন:")
        return
    if not profile.get('age'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text("🎂 আপনার বয়স লিখুন (শুধু সংখ্যা):")
        return
    if not profile.get('gender'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'gender'
        await update.message.reply_text(
            "⚧ আপনার জেন্ডার নির্বাচন করুন:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👦 ছেলে", callback_data="gender_male")],
                [InlineKeyboardButton("👧 মেয়ে", callback_data="gender_female")],
                [InlineKeyboardButton("🌈 অন্যান্য", callback_data="gender_other")]
            ])
        )
        return
    if not profile.get('pref_gender'):
        context.user_data.clear()
        context.user_data['reg_step'] = 'pref_gender'
        await update.message.reply_text(
            "🎯 আপনি কার সাথে চ্যাট করতে চান?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👦 ছেলে", callback_data="pref_male")],
                [InlineKeyboardButton("👧 মেয়ে", callback_data="pref_female")],
                [InlineKeyboardButton("🌍 যে কেউ", callback_data="pref_any")]
            ])
        )
        return

    chat = await get_active_chat(user_id)
    if chat:
        await update.message.reply_text(
            "⚠️ আপনি ইতিমধ্যে একটি চ্যাটে আছেন।",
            reply_markup=await chat_keyboard(chat['partner_id'])
        )
        return

    online = await get_online_count()
    await update.message.reply_text(
        f"🏠 মেইন মেনু — নিচের বাটন থেকে নির্বাচন করুন:\n\n"
        f"🟢 এখন {online} জন অনলাইনে আছেন",
        reply_markup=await main_menu_keyboard()
    )


async def age_gate_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == "age_yes":
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_18_plus = TRUE WHERE user_id = $1", user_id)
        context.user_data['reg_step'] = 'name'
        await query.edit_message_text("✅ ধন্যবাদ! এখন আপনার নাম লিখুন:")
    else:
        await query.edit_message_text("❌ দুঃখিত, এই বটটি শুধুমাত্র ১৮+ ব্যবহারকারীদের জন্য।")


async def handle_text(update, context):
    user_id = update.effective_user.id
    await touch_user(user_id)

    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 আপনি এই বট থেকে ব্যান হয়েছেন।")
        return

    step = context.user_data.get('reg_step')
    text = update.message.text.strip() if update.message.text else ""

    if not step:
        await handle_chat_message(update, context)
        return

    if step == 'name':
        if len(text) < 2 or len(text) > 50:
            await update.message.reply_text("⚠️ নাম ২ থেকে ৫০ অক্ষরের মধ্যে হতে হবে। আবার লিখুন:")
            return
        await save_profile(user_id, display_name=text)
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text("🎂 আপনার বয়স লিখুন (শুধু সংখ্যা):")
        return

    if step == 'age':
        if not text.isdigit() or int(text) < 18 or int(text) > 99:
            await update.message.reply_text("⚠️ বয়স ১৮ থেকে ৯৯ এর মধ্যে হতে হবে। আবার লিখুন:")
            return
        await save_profile(user_id, age=int(text))
        context.user_data['reg_step'] = 'gender'
        await update.message.reply_text(
            "⚧ আপনার জেন্ডার নির্বাচন করুন:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👦 ছেলে", callback_data="gender_male")],
                [InlineKeyboardButton("👧 মেয়ে", callback_data="gender_female")],
                [InlineKeyboardButton("🌈 অন্যান্য", callback_data="gender_other")]
            ])
        )
        return

    if step == 'bio':
        await save_profile(user_id, bio=text[:200])
        context.user_data['reg_step'] = None
        online = await get_online_count()
        await update.message.reply_text(
            f"✅ রেজিস্ট্রেশন সম্পন্ন! 🎉\n\n"
            f"🟢 এখন {online} জন অনলাইনে আছেন\n\n"
            f"নিচের বাটন থেকে পার্টনার খুঁজুন:",
            reply_markup=await main_menu_keyboard()
        )
        return

    if step in ('gender', 'pref_gender'):
        await update.message.reply_text("⚠️ দয়া করে উপরের বাটন থেকে নির্বাচন করুন।")
        return


async def gender_callback(update, context):
    query = update.callback_query
    await query.answer()
    gender = query.data.split("_")[1]
    user_id = query.from_user.id
    await save_profile(user_id, gender=gender)
    context.user_data['reg_step'] = 'pref_gender'
    await query.edit_message_text(
        "🎯 আপনি কার সাথে চ্যাট করতে চান?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👦 ছেলে", callback_data="pref_male")],
            [InlineKeyboardButton("👧 মেয়ে", callback_data="pref_female")],
            [InlineKeyboardButton("🌍 যে কেউ", callback_data="pref_any")]
        ])
    )


async def pref_gender_callback(update, context):
    query = update.callback_query
    await query.answer()
    pref = query.data.split("_")[1]
    user_id = query.from_user.id
    await save_profile(user_id, pref_gender=pref)
    context.user_data['reg_step'] = 'bio'
    await query.edit_message_text("📝 একটি ছোট বায়ো লিখুন (সর্বোচ্চ ২০০ অক্ষর):")


async def main_menu_callback(update, context):
    query = update.callback_query
    await query.answer()
    online = await get_online_count()
    await query.edit_message_text(
        f"🏠 মেইন মেনু — নিচের বাটন থেকে নির্বাচন করুন:\n\n"
        f"🟢 এখন {online} জন অনলাইনে আছেন",
        reply_markup=await main_menu_keyboard()
    )


async def refresh_online(update, context):
    query = update.callback_query
    await query.answer()
    online = await get_online_count()
    await query.answer(f"🟢 এখন {online} জন অনলাইনে আছেন", show_alert=True)


async def find_partner(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await touch_user(user_id)

    profile = await get_profile(user_id)
    if not profile:
        await query.edit_message_text("❌ আগে /start দিন।")
        return

    existing = await get_active_chat(user_id)
    if existing:
        await query.edit_message_text(
            "❌ আপনি ইতিমধ্যে একটি চ্যাটে আছেন।",
            reply_markup=await chat_keyboard(existing['partner_id'])
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

            success_text = (
                "✅ পার্টনার পাওয়া গেছে!\n\n"
                "💬 এখন যেকোনো মেসেজ পাঠান — টেক্সট, ছবি, ভয়েস সবই যাবে।\n"
                "🔒 আপনার পরিচয় সম্পূর্ণ গোপন থাকবে।"
            )

            await query.edit_message_text(success_text, reply_markup=await chat_keyboard(partner_id))
            try:
                await context.bot.send_message(
                    partner_id,
                    success_text,
                    reply_markup=await chat_keyboard(user_id)
                )
            except Exception as e:
                logger.error(f"Notify partner error: {e}")
        else:
            await conn.execute("""
                INSERT INTO match_queue (user_id, gender, pref_gender) VALUES ($1, $2, $3)
                ON CONFLICT (user_id) DO UPDATE SET queued_at = CURRENT_TIMESTAMP
            """, user_id, user_gender, user_pref)

            await query.edit_message_text(
                "⏳ পার্টনার খোঁজা হচ্ছে...\n\n"
                "অনুগ্রহ করে অপেক্ষা করুন। কেউ অনলাইনে এলেই আপনাকে কানেক্ট করা হবে।\n\n"
                "💡 বন্ধুদের ইনভাইট করলে দ্রুত পার্টনার পাবেন।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                    [InlineKeyboardButton("🔗 Invite Friends", callback_data="show_link")],
                    [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main_menu")]
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
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
    job_name = f"queue_timeout_{user_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    await query.edit_message_text(
        "❌ সার্চ বাতিল করা হয়েছে।",
        reply_markup=await main_menu_keyboard()
    )


async def show_link(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{user_id}"
    await query.edit_message_text(
        f"🔗 আপনার ইনভাইট লিংক:\n\n{link}\n\n"
        f"💡 বন্ধুদের এই লিংক শেয়ার করলে তারা সরাসরি বটে যোগ দিতে পারবে এবং আপনি দ্রুত পার্টনার পাবেন।",
        reply_markup=await main_menu_keyboard()
    )


async def handle_chat_message(update, context):
    user_id = update.effective_user.id
    chat = await get_active_chat(user_id)
    if not chat:
        await update.message.reply_text("⚠️ আপনি কোনো চ্যাটে নেই। /start দিন।")
        return
    if is_rate_limited(user_id, max_requests=15, window_seconds=10):
        await update.message.reply_text("⏳ খুব দ্রুত মেসেজ পাঠাচ্ছেন। একটু অপেক্ষা করুন।")
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
        await update.message.reply_text("❌ মেসেজ পাঠানো যায়নি। পার্টনার হয়তো বট ব্লক করেছে।")


async def end_chat_callback(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat = await get_active_chat(user_id)
    if not chat:
        await query.edit_message_text(
            "❌ আপনি কোনো চ্যাটে নেই।",
            reply_markup=await main_menu_keyboard()
        )
        return
    partner_id = chat['partner_id']
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", user_id, partner_id)
    await query.edit_message_text(
        "🛑 চ্যাট শেষ হয়েছে।",
        reply_markup=await main_menu_keyboard()
    )
    try:
        await context.bot.send_message(
            partner_id,
            "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।",
            reply_markup=await main_menu_keyboard()
        )
    except Exception:
        pass


async def next_partner(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    chat = await get_active_chat(user_id)
    if chat:
        partner_id = chat['partner_id']
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", user_id, partner_id)
        try:
            await context.bot.send_message(
                partner_id,
                "🛑 আপনার পার্টনার নতুন পার্টনার খুঁজতে চলে গেছেন।",
                reply_markup=await main_menu_keyboard()
            )
        except Exception:
            pass

    await query.edit_message_text("🔍 নতুন পার্টনার খোঁজা হচ্ছে...")
    await asyncio.sleep(1)
    await find_partner(update, context)


async def report_callback(update, context):
    query = update.callback_query
    await query.answer()
    reported_id = int(query.data.split("_")[1])
    reasons = [
        ("Spam", "spam"), ("Harassment", "harassment"), ("Scam", "scam"),
        ("Fake profile", "fake"), ("Inappropriate", "inappropriate"),
        ("Underage", "underage"), ("Other", "other")
    ]
    keyboard = [[InlineKeyboardButton(r[0], callback_data=f"report_reason_{r[1]}_{reported_id}")] for r in reasons]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="end_chat")])
    await query.edit_message_text(
        "⚠️ রিপোর্টের কারণ নির্বাচন করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def report_reason_callback(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    reason = parts[2]
    reported_id = int(parts[3])
    reporter_id = query.from_user.id

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
            await conn.execute(
                "UPDATE users SET is_banned = TRUE WHERE user_id = $1",
                reported_id
            )
            await conn.execute(
                "UPDATE reports SET status = 'actioned' WHERE reported_id = $1",
                reported_id
            )
            auto_banned = True
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"🚨 Auto-Ban Triggered\n\n"
                        f"👤 User ID: {reported_id}\n"
                        f"📊 Reports: {unique_reporters}\n"
                        f"⚡ Status: Banned"
                    )
                except Exception:
                    pass

    if auto_banned:
        msg = "✅ ধন্যবাদ। আপনার রিপোর্ট জমা হয়েছে।"
    else:
        msg = "✅ ধন্যবাদ। আপনার রিপোর্ট জমা হয়েছে এবং পার্টনারকে ব্লক করা হয়েছে।"

    await query.edit_message_text(msg, reply_markup=await main_menu_keyboard())
    try:
        await context.bot.send_message(
            reported_id,
            "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।",
            reply_markup=await main_menu_keyboard()
        )
    except Exception:
        pass


async def my_profile(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    profile = await get_profile(user_id)
    if not profile:
        await query.edit_message_text("❌ আগে /start দিন।")
        return
    gender_map = {"male": "ছেলে", "female": "মেয়ে", "other": "অন্যান্য"}
    pref_map = {"male": "ছেলে", "female": "মেয়ে", "any": "যে কেউ"}
    text = (
        f"👤 আপনার প্রোফাইল\n\n"
        f"📝 নাম: {profile.get('display_name', 'N/A')}\n"
        f"🎂 বয়স: {profile.get('age', 'N/A')}\n"
        f"⚧ জেন্ডার: {gender_map.get(profile.get('gender'), 'N/A')}\n"
        f"🎯 পছন্দ: {pref_map.get(profile.get('pref_gender'), 'যে কেউ')}\n\n"
        f"💬 বায়ো: {(profile.get('bio') or 'N/A')[:200]}"
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main_menu")]
        ])
    )


async def safety_callback(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🛡 নিরাপত্তা টিপস\n\n"
        "• কখনো পাসওয়ার্ড বা OTP শেয়ার করবেন না\n"
        "• অনলাইনে কাউকে টাকা পাঠাবেন না\n"
        "• বাড়ির ঠিকানা বা GPS লোকেশন শেয়ার করবেন না\n"
        "• সন্দেহজনক লিংকে ক্লিক করবেন না\n"
        "• কোনো খারাপ ব্যবহার হলে সাথে সাথে Report করুন\n"
        "• নিরাপদ থাকতে সবসময় End Chat ব্যবহার করুন\n\n"
        "🚫 ৫টি আলাদা রিপোর্ট পেলে ইউজার অটো-ব্যান হয়।",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main_menu")]
        ])
    )


async def help_callback(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📖 সাহায্য\n\n"
        "🔹 /start — মেইন মেনু\n"
        "🔹 /stop — চলমান চ্যাট শেষ\n"
        "🔹 /reset — প্রোফাইল রিসেট\n"
        "🔹 /stats — বটের পরিসংখ্যান\n\n"
        "🎯 কীভাবে ব্যবহার করবেন:\n"
        "১. Find Partner বাটনে ক্লিক করুন\n"
        "২. কেউ অনলাইনে থাকলে সাথে সাথে কানেক্ট হবেন\n"
        "৩. মেসেজ পাঠান — অ্যানোনিমাসভাবে যাবে\n"
        "৪. চ্যাট শেষ করতে End Chat বাটন বা /stop\n"
        "৫. খারাপ ব্যবহার হলে Report করুন\n\n"
        "🔒 আপনার পরিচয় সম্পূর্ণ গোপন থাকে।",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main_menu")]
        ])
    )


async def stop_chat(update, context):
    user_id = update.effective_user.id
    chat = await get_active_chat(user_id)
    if not chat:
        await update.message.reply_text("❌ আপনি কোনো চ্যাটে নেই।")
        return
    partner_id = chat['partner_id']
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR user_id = $2", user_id, partner_id)
    await update.message.reply_text(
        "🛑 চ্যাট শেষ হয়েছে।",
        reply_markup=await main_menu_keyboard()
    )
    try:
        await context.bot.send_message(
            partner_id,
            "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।",
            reply_markup=await main_menu_keyboard()
        )
    except Exception:
        pass


async def reset_command(update, context):
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM profiles WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM match_queue WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1", user_id)
    context.user_data.clear()
    await update.message.reply_text("🔄 প্রোফাইল রিসেট। আবার /start দিন।")


async def stats_command(update, context):
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        online = await get_online_count()
        in_queue = await conn.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        active_chats = (await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
    await update.message.reply_text(
        f"📊 বটের পরিসংখ্যান\n\n"
        f"👥 মোট ইউজার: {total_users}\n"
        f"🟢 এখন অনলাইনে: {online}\n"
        f"⏳ পার্টনার খুঁজছেন: {in_queue}\n"
        f"💬 চলমান চ্যাট: {active_chats}"
    )


async def admin_stats(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ আপনি অ্যাডমিন নন।")
        return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        online = await get_online_count()
        in_queue = await conn.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        active_chats = (await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
        pending = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'pending'") or 0
        banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE") or 0
        total_blocks = await conn.fetchval("SELECT COUNT(*) FROM blocks") or 0
    await update.message.reply_text(
        f"📊 Admin Dashboard\n\n"
        f"👥 Total Users: {total_users}\n"
        f"🟢 Online Now: {online}\n"
        f"⏳ In Queue: {in_queue}\n"
        f"💬 Active Chats: {active_chats}\n"
        f"⚠️ Pending Reports: {pending}\n"
        f"🚫 Banned Users: {banned}\n"
        f"🛑 Total Blocks: {total_blocks}"
    )


async def link_command(update, context):
    user_id = update.effective_user.id
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{user_id}"
    await update.message.reply_text(
        f"🔗 আপনার ইনভাইট লিংক:\n\n{link}\n\n"
        f"💡 বন্ধুদের এই লিংক শেয়ার করলে তারা সরাসরি বটে যোগ দিতে পারবে।"
    )


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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("adminstats", admin_stats))

    app.add_handler(CallbackQueryHandler(age_gate_callback, pattern="^age_"))
    app.add_handler(CallbackQueryHandler(gender_callback, pattern="^gender_"))
    app.add_handler(CallbackQueryHandler(pref_gender_callback, pattern="^pref_"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(refresh_online, pattern="^refresh_online$"))
    app.add_handler(CallbackQueryHandler(find_partner, pattern="^find_partner$"))
    app.add_handler(CallbackQueryHandler(cancel_search, pattern="^cancel_search$"))
    app.add_handler(CallbackQueryHandler(show_link, pattern="^show_link$"))
    app.add_handler(CallbackQueryHandler(end_chat_callback, pattern="^end_chat$"))
    app.add_handler(CallbackQueryHandler(next_partner, pattern="^next_partner$"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))
    app.add_handler(CallbackQueryHandler(report_reason_callback, pattern="^report_reason_"))
    app.add_handler(CallbackQueryHandler(my_profile, pattern="^my_profile$"))
    app.add_handler(CallbackQueryHandler(safety_callback, pattern="^safety$"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_chat_message))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
