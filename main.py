"""
Matchmaking Telegram Bot — Production MVP
Features: 18+ gate, registration, preferences, discovery, like/skip,
mutual match, anonymous chat, block, report, anti-spam, admin moderation.
"""

import os
import logging
import asyncio
import threading
import random
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)
from telegram.request import HTTPXRequest
import asyncpg

# ============================================================
# CONFIG (from environment variables)
# ============================================================
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
logger = logging.getLogger("match-bot")

# ============================================================
# FLASK HEALTH CHECK (for Render)
# ============================================================
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "OK", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

# ============================================================
# DATABASE POOL
# ============================================================
db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    # Create tables if not exist (run schema.sql manually or here)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_18_plus BOOLEAN DEFAULT FALSE,
                is_banned BOOLEAN DEFAULT FALSE,
                is_restricted BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP
            );
            -- ... (add other tables as per schema)
        """)
    logger.info("Database pool created.")

async def close_db():
    if db_pool:
        await db_pool.close()

# Helper: get user profile
async def get_profile(user_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM profiles WHERE user_id = $1", user_id)
        return dict(row) if row else None

async def save_profile(user_id: int, **kwargs):
    # Build dynamic UPSERT
    columns = list(kwargs.keys())
    values = list(kwargs.values())
    placeholders = [f"${i+2}" for i in range(len(columns))]
    update_set = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns])
    query = f"""
        INSERT INTO profiles (user_id, {', '.join(columns)})
        VALUES ($1, {', '.join(placeholders)})
        ON CONFLICT (user_id) DO UPDATE SET {update_set}
    """
    async with db_pool.acquire() as conn:
        await conn.execute(query, user_id, *values)

# ============================================================
# RATE LIMITING (in-memory, simple for MVP)
# ============================================================
rate_limit_store = defaultdict(list)  # user_id -> [timestamps]

def is_rate_limited(user_id: int, max_requests: int = 5, window_seconds: int = 60) -> bool:
    now = datetime.now()
    timestamps = rate_limit_store[user_id]
    # Remove old
    timestamps[:] = [t for t in timestamps if (now - t).total_seconds() < window_seconds]
    if len(timestamps) >= max_requests:
        return True
    timestamps.append(now)
    return False

# ============================================================
# MATCHING ENGINE (simple compatibility score)
# ============================================================
def calculate_compatibility(profile_a, prefs_a, profile_b):
    score = 0
    # Interests (40%)
    if profile_a.get('interests') and profile_b.get('interests'):
        common = set(profile_a['interests']) & set(profile_b['interests'])
        score += len(common) * 0.4
    # Languages (20%)
    if profile_a.get('languages') and profile_b.get('languages'):
        common = set(profile_a['languages']) & set(profile_b['languages'])
        score += len(common) * 0.2
    # Location (15%)
    if profile_a.get('country') and profile_b.get('country'):
        if profile_a['country'] == profile_b['country']:
            score += 0.15
    # Intentions (15%)
    if profile_a.get('looking_for') and profile_b.get('looking_for'):
        if profile_a['looking_for'] == profile_b['looking_for']:
            score += 0.15
    # Activity (10%) — placeholder
    score += 0.1
    return score

async def find_candidates(user_id: int, limit: int = 10):
    """Return list of candidate profiles not seen/blocked, ordered by compatibility."""
    async with db_pool.acquire() as conn:
        user_profile = await conn.fetchrow("SELECT * FROM profiles WHERE user_id = $1", user_id)
        if not user_profile:
            return []
        prefs = await conn.fetchrow("SELECT * FROM preferences WHERE user_id = $1", user_id)
        # Exclude already liked/skipped/blocked
        seen = await conn.fetch("""
            SELECT target_id FROM likes WHERE liker_id = $1
            UNION SELECT target_id FROM skips WHERE skipper_id = $1
            UNION SELECT blocked_id FROM blocks WHERE blocker_id = $1
        """, user_id)
        seen_ids = {r['target_id'] for r in seen}
        seen_ids.add(user_id)
        # Fetch all visible profiles except seen
        candidates = await conn.fetch("""
            SELECT * FROM profiles WHERE is_visible = TRUE AND user_id != ALL($1::bigint[])
            LIMIT 100
        """, list(seen_ids))
        # Score and sort
        scored = []
        for c in candidates:
            score = calculate_compatibility(dict(user_profile), dict(prefs) if prefs else {}, dict(c))
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:limit]]

# ============================================================
# HANDLERS
# ============================================================

# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            # Start registration
            context.user_data['reg_step'] = 'age_gate'
            await update.message.reply_text(
                "👋 স্বাগতম! এটি একটি ম্যাচমেকিং বট।\n\n"
                "শুরু করার আগে নিশ্চিত করুন যে আপনার বয়স ১৮+।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ হ্যাঁ, আমি ১৮+", callback_data="age_yes")],
                    [InlineKeyboardButton("❌ না", callback_data="age_no")]
                ])
            )
            return
    # Existing user — show main menu
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔎 Find Someone", callback_data="find_someone")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_profile")],
        [InlineKeyboardButton("❤️ My Matches", callback_data="my_matches")],
        [InlineKeyboardButton("⚙️ Preferences", callback_data="preferences")],
        [InlineKeyboardButton("🛡 Safety", callback_data="safety")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ]
    await update.message.reply_text(
        "🏠 মেইন মেনু — নিচের বাটন থেকে নির্বাচন করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- Age gate callback ---
async def age_gate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "age_yes":
        await query.edit_message_text("✅ ধন্যবাদ! এখন আপনার নাম লিখুন:")
        context.user_data['reg_step'] = 'name'
    else:
        await query.edit_message_text("❌ দুঃখিত, এই বটটি শুধুমাত্র ১৮+ ব্যবহারকারীদের জন্য।")

# --- Registration flow (text handler) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    step = context.user_data.get('reg_step')
    text = update.message.text.strip()

    if step == 'name':
        await save_profile(user_id, display_name=text)
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text("🎂 আপনার বয়স লিখুন (শুধু সংখ্যা):")
    elif step == 'age':
        if not text.isdigit() or int(text) < 18:
            await update.message.reply_text("⚠️ বয়স ১৮ বা তার বেশি হতে হবে। আবার লিখুন:")
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
    elif step == 'country':
        await save_profile(user_id, country=text)
        context.user_data['reg_step'] = 'city'
        await update.message.reply_text("🏙️ আপনার শহর/অঞ্চল লিখুন (সঠিক ঠিকানা নয়):")
    elif step == 'city':
        await save_profile(user_id, city=text)
        context.user_data['reg_step'] = 'languages'
        await update.message.reply_text("🗣️ আপনার ভাষাগুলো কমা দিয়ে লিখুন (যেমন: বাংলা, ইংরেজি):")
    elif step == 'languages':
        langs = [l.strip() for l in text.split(",") if l.strip()]
        await save_profile(user_id, languages=langs)
        context.user_data['reg_step'] = 'interests'
        await update.message.reply_text("🎯 আপনার আগ্রহগুলো কমা দিয়ে লিখুন (যেমন: সংগীত, চলচ্চিত্র, খেলা):")
    elif step == 'interests':
        interests = [i.strip() for i in text.split(",") if i.strip()]
        await save_profile(user_id, interests=interests)
        context.user_data['reg_step'] = 'hobbies'
        await update.message.reply_text("🎨 আপনার শখগুলো কমা দিয়ে লিখুন:")
    elif step == 'hobbies':
        hobbies = [h.strip() for h in text.split(",") if h.strip()]
        await save_profile(user_id, hobbies=hobbies)
        context.user_data['reg_step'] = 'bio'
        await update.message.reply_text("📝 একটি ছোট বায়ো লিখুন (সর্বোচ্চ ২০০ অক্ষর):")
    elif step == 'bio':
        await save_profile(user_id, bio=text[:200])
        context.user_data['reg_step'] = 'looking_for'
        await update.message.reply_text(
            "❤️ আপনি কী খুঁজছেন?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👫 বন্ধুত্ব", callback_data="intent_friendship")],
                [InlineKeyboardButton("💬 কথোপকথন", callback_data="intent_conversation")],
                [InlineKeyboardButton("📚 পড়াশোনার সঙ্গী", callback_data="intent_study")],
                [InlineKeyboardButton("💕 ডেটিং", callback_data="intent_dating")]
            ])
        )
    else:
        # If not in registration, treat as chat message
        await handle_chat_message(update, context)

# --- Gender / Intent callbacks ---
async def gender_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    gender = query.data.split("_")[1]  # male, female, other
    user_id = query.from_user.id
    await save_profile(user_id, gender=gender)
    context.user_data['reg_step'] = 'country'
    await query.edit_message_text("🌍 আপনার দেশ লিখুন:")

async def intent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    intent = query.data.split("_")[1]  # friendship, conversation, etc.
    user_id = query.from_user.id
    await save_profile(user_id, looking_for=intent)
    # Also set default preferences
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO preferences (user_id) VALUES ($1)
            ON CONFLICT (user_id) DO NOTHING
        """, user_id)
    context.user_data['reg_step'] = None
    await query.edit_message_text(
        "✅ রেজিস্ট্রেশন সম্পন্ন! এখন মেইন মেনু:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 মেইন মেনু", callback_data="main_menu")]
        ])
    )

# --- Main menu callback ---
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🏠 মেইন মেনু:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 Find Someone", callback_data="find_someone")],
            [InlineKeyboardButton("👤 My Profile", callback_data="my_profile")],
            [InlineKeyboardButton("❤️ My Matches", callback_data="my_matches")],
            [InlineKeyboardButton("⚙️ Preferences", callback_data="preferences")],
            [InlineKeyboardButton("🛡 Safety", callback_data="safety")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
        ])
    )

# --- Find Someone ---
async def find_someone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if is_rate_limited(user_id, max_requests=3, window_seconds=60):
        await query.edit_message_text("⏳ আপনি খুব দ্রুত রিকোয়েস্ট করছেন। একটু অপেক্ষা করুন।")
        return
    candidates = await find_candidates(user_id, limit=5)
    if not candidates:
        await query.edit_message_text("❌ এখন কোনো নতুন প্রোফাইল নেই। পরে আবার চেষ্টা করুন।")
        return
    # Store candidate list in user_data for navigation
    context.user_data['candidates'] = [dict(c) for c in candidates]
    context.user_data['candidate_index'] = 0
    await show_candidate(query, context)

async def show_candidate(query, context):
    idx = context.user_data.get('candidate_index', 0)
    candidates = context.user_data.get('candidates', [])
    if idx >= len(candidates):
        await query.edit_message_text("✅ সব প্রোফাইল দেখা হয়েছে। পরে আবার চেষ্টা করুন।")
        return
    c = candidates[idx]
    text = (
        f"👤 {c.get('display_name', 'Unknown')}, {c.get('age', '?')}\n"
        f"🌍 {c.get('country', '')} {c.get('city', '')}\n"
        f"🎯 {', '.join(c.get('interests', [])[:3])}\n\n"
        f"💬 \"{c.get('bio', '')[:150]}\""
    )
    keyboard = [
        [InlineKeyboardButton("❤️ Interested", callback_data=f"like_{c['user_id']}")],
        [InlineKeyboardButton("➡️ Skip", callback_data=f"skip_{c['user_id']}")],
        [InlineKeyboardButton("🚫 Report", callback_data=f"report_{c['user_id']}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def like_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    liker_id = query.from_user.id
    target_id = int(query.data.split("_")[1])
    async with db_pool.acquire() as conn:
        # Record like
        await conn.execute(
            "INSERT INTO likes (liker_id, target_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            liker_id, target_id
        )
        # Check for mutual like
        mutual = await conn.fetchrow(
            "SELECT * FROM likes WHERE liker_id = $1 AND target_id = $2",
            target_id, liker_id
        )
        if mutual:
            # Create match
            await conn.execute("""
                INSERT INTO matches (user1_id, user2_id) VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, liker_id, target_id)
            await query.edit_message_text(
                "🎉 It's a Match!\n\nআপনি দুজনেই একে অপরকে পছন্দ করেছেন।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Start Anonymous Chat", callback_data=f"chat_{target_id}")]
                ])
            )
            return
    # No mutual yet — show next candidate
    context.user_data['candidate_index'] += 1
    await show_candidate(query, context)

async def skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    skipper_id = query.from_user.id
    target_id = int(query.data.split("_")[1])
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO skips (skipper_id, target_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            skipper_id, target_id
        )
    context.user_data['candidate_index'] += 1
    await show_candidate(query, context)

# --- Anonymous Chat ---
async def chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    partner_id = int(query.data.split("_")[1])
    # Store active chat in user_data
    context.user_data['chat_partner'] = partner_id
    # Notify both
    await query.edit_message_text(
        "🤫 আপনি এখন অ্যানোনিমাস চ্যাটে আছেন।\n"
        "মেসেজ পাঠান, অন্য পাশে পৌঁছে যাবে।\n"
        "চ্যাট শেষ করতে /stop দিন।",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 End Chat", callback_data="end_chat")],
            [InlineKeyboardButton("🚫 Report", callback_data="report_chat")]
        ])
    )
    try:
        await context.bot.send_message(
            partner_id,
            "🤫 আপনার পার্টনার চ্যাট শুরু করেছেন। মেসেজ পাঠান।",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛑 End Chat", callback_data="end_chat")],
                [InlineKeyboardButton("🚫 Report", callback_data="report_chat")]
            ])
        )
    except Exception as e:
        logger.error(f"Could not notify partner {partner_id}: {e}")

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = context.user_data.get('chat_partner')
    if not partner_id:
        await update.message.reply_text("⚠️ আপনি কোনো চ্যাটে নেই। /start দিন।")
        return
    # Rate limit
    if is_rate_limited(user_id, max_requests=10, window_seconds=10):
        await update.message.reply_text("⏳ খুব দ্রুত মেসেজ পাঠাচ্ছেন। একটু অপেক্ষা করুন।")
        return
    # Copy message anonymously
    try:
        await context.bot.copy_message(
            chat_id=partner_id,
            from_chat_id=user_id,
            message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Copy failed: {e}")
        await update.message.reply_text("❌ মেসেজ পাঠানো যায়নি।")

async def end_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    partner_id = context.user_data.pop('chat_partner', None)
    await query.edit_message_text("🛑 চ্যাট শেষ হয়েছে।")
    if partner_id:
        try:
            await context.bot.send_message(partner_id, "🛑 আপনার পার্টনার চ্যাট শেষ করেছেন।")
        except Exception:
            pass

# --- Block / Report ---
async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    reporter_id = query.from_user.id
    reported_id = int(query.data.split("_")[1])
    # Show reason selection
    reasons = [
        ("Spam", "spam"), ("Harassment", "harassment"), ("Scam", "scam"),
        ("Fake profile", "fake"), ("Inappropriate", "inappropriate"),
        ("Underage", "underage"), ("Other", "other")
    ]
    keyboard = [[InlineKeyboardButton(r[0], callback_data=f"report_reason_{r[1]}_{reported_id}")] for r in reasons]
    await query.edit_message_text("⚠️ রিপোর্টের কারণ নির্বাচন করুন:", reply_markup=InlineKeyboardMarkup(keyboard))

async def report_reason_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        # Auto-block
        await conn.execute(
            "INSERT INTO blocks (blocker_id, blocked_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            reporter_id, reported_id
        )
    await query.edit_message_text("✅ ধন্যবাদ। আপনার রিপোর্ট জমা হয়েছে।")

# --- Admin commands (simple) ---
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ আপনি অ্যাডমিন নন।")
        return
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_matches = await conn.fetchval("SELECT COUNT(*) FROM matches")
        pending_reports = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
    await update.message.reply_text(
        f"📊 Admin Stats\n\n"
        f"👥 Total Users: {total_users}\n"
        f"❤️ Matches: {total_matches}\n"
        f"⚠️ Pending Reports: {pending_reports}"
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
    app.add_handler(CommandHandler("adminstats", admin_stats))

    # Callbacks
    app.add_handler(CallbackQueryHandler(age_gate_callback, pattern="^age_"))
    app.add_handler(CallbackQueryHandler(gender_callback, pattern="^gender_"))
    app.add_handler(CallbackQueryHandler(intent_callback, pattern="^intent_"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(find_someone, pattern="^find_someone$"))
    app.add_handler(CallbackQueryHandler(like_callback, pattern="^like_"))
    app.add_handler(CallbackQueryHandler(skip_callback, pattern="^skip_"))
    app.add_handler(CallbackQueryHandler(chat_callback, pattern="^chat_"))
    app.add_handler(CallbackQueryHandler(end_chat_callback, pattern="^end_chat$"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern="^report_"))
    app.add_handler(CallbackQueryHandler(report_reason_callback, pattern="^report_reason_"))

    # Text & media messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_chat_message))

    logger.info("🤖 Matchmaking Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
