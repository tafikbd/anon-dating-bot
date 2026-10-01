import os
import logging
import asyncio
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest
import redis.asyncio as aioredis

# ================= LOGGING =================
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("anon-bot")

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("REDIS_URL")

if not BOT_TOKEN or not REDIS_URL:
    raise RuntimeError("BOT_TOKEN and REDIS_URL must be set in Environment Variables.")

# ================= REDIS SETUP =================
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)

# ================= FLASK (HEALTH CHECK) =================
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port, threaded=True)

# ================= BOT HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 Find Partner", callback_data="find_partner")],
        [InlineKeyboardButton("👤 My Profile", callback_data="profile")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "স্বাগতম! 👋\n\nএটি একটি Anonymous Chatting Bot।\n\n"
        "নিচের বাটনে ক্লিক করে পার্টনার খুঁজুন।",
        reply_markup=reply_markup
    )

async def find_partner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    # চেক করা ইউজার আগে থেকেই কোনো চ্যাটে আছে কি না
    partner_id = await redis_client.get(f"chat:{user_id}")
    if partner_id:
        await query.edit_message_text("❌ আপনি ইতিমধ্যে একটি চ্যাটে আছেন। /stop দিয়ে বেরিয়ে আসুন।")
        return

    # কিউতে অপেক্ষারত কেউ আছে কি না চেক করা
    waiting_user = await redis_client.lpop("waiting_queue")
    
    if waiting_user and int(waiting_user) != user_id:
        partner_id = int(waiting_user)
        # দুজনকে কানেক্ট করা
        await redis_client.set(f"chat:{user_id}", partner_id)
        await redis_client.set(f"chat:{partner_id}", user_id)
        
        await query.edit_message_text("✅ পার্টনার পাওয়া গেছে! এখন মেসেজ পাঠান। /stop দিয়ে চ্যাট শেষ করুন।")
        try:
            await context.bot.send_message(chat_id=partner_id, text="✅ পার্টনার পাওয়া গেছে! এখন মেসেজ পাঠান। /stop দিয়ে চ্যাট শেষ করুন।")
        except Exception as e:
            logger.error(f"Error notifying partner: {e}")
    else:
        # কিউতে যোগ করা
        if waiting_user: 
            await redis_client.lpush("waiting_queue", waiting_user)
        
        await redis_client.lpush("waiting_queue", user_id)
        await query.edit_message_text("⏳ পার্টনার খোঁজা হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন।")

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = await redis_client.get(f"chat:{user_id}")
    
    if not partner_id:
        await update.message.reply_text("❌ আপনি বর্তমানে কোনো চ্যাটে নেই।")
        return
        
    partner_id = int(partner_id)
    # কানেকশন মুছে ফেলা
    await redis_client.delete(f"chat:{user_id}")
    await redis_client.delete(f"chat:{partner_id}")
    
    await update.message.reply_text("🛑 চ্যাট শেষ হয়েছে। নতুন পার্টনার খুঁজতে /start দিন।")
    try:
        await context.bot.send_message(chat_id=partner_id, text="🛑 আপনার পার্টনার চ্যাটটি শেষ করেছেন। নতুন পার্টনার খুঁজতে /start দিন।")
    except Exception as e:
        logger.error(f"Error notifying partner: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = await redis_client.get(f"chat:{user_id}")
    
    if not partner_id:
        await update.message.reply_text("⚠️ আপনি কোনো চ্যাটে নেই। পার্টনার খুঁজতে /start দিন।")
        return
        
    partner_id = int(partner_id)
    
    # সিম্পল প্রফানিটি ফিল্টার
    text = update.message.text or ""
    bad_words = ["গালি১", "গালি২", "badword1", "badword2"] 
    if any(word in text.lower() for word in bad_words):
        await update.message.reply_text("🚫 আপনার মেসেজে নিষিদ্ধ শব্দ আছে। মেসেজ পাঠানো হয়নি।")
        return

    # মেসেজ ফরওয়ার্ড করা
    try:
        await update.message.forward(chat_id=partner_id)
    except Exception as e:
        logger.error(f"Failed to forward message: {e}")
        await update.message.reply_text("❌ মেসেজ পাঠানো যায়নি। হয়তো পার্টনার বটটি ব্লক করেছে।")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👤 আপনার প্রোফাইল:\n\nনাম: (আপনার নাম)\nবয়স: সেট করা হয়নি\nজেন্ডার: সেট করা হয়নি\n\n(এই ফিচারটি ডেভেলপমেন্টের অধীনে)")

# ================= MAIN =================
def main():
    # ইভেন্ট লুপ তৈরি করে সেট করা (Python 3.14 এরর সমাধানের জন্য)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Flask থ্রেড চালু করা (Render-এর হেলথ চেকের জন্য)
    threading.Thread(target=run_flask, daemon=True).start()

    request = HTTPXRequest(connection_pool_size=20, connect_timeout=20.0, read_timeout=30.0, write_timeout=30.0)
    app = Application.builder().token(BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CallbackQueryHandler(find_partner, pattern="^find_partner$"))
    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("Starting Anonymous Chatting Bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
