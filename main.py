import os, logging, asyncio, threading, random, string
from datetime import datetime, timedelta
from flask import Flask
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, ReplyKeyboardMarkup, KeyboardButton)
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler)
from telegram.request import HTTPXRequest
import asyncpg

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False

# ========== CONFIG ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("BOT_TOKEN and DATABASE_URL required.")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger("mechat")

flask_app = Flask(__name__)

@flask_app.route('/')
def health(): return "OK", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

db_pool = None
groq_client = Groq(api_key=GROQ_API_KEY) if (HAS_GROQ and GROQ_API_KEY) else None
AI_MODELS = ["openai/gpt-oss-120b", "llama-3.1-8b-instant"]

# ========== PAYMENT ==========
BKASH_NUMBER = "01608364088"
ROCKET_NUMBER = "01608364088"
BINANCE_ID = "1076189034"
USDT_BSC20 = "0xb83a03d9ded3ac7a4908aa87cfdfe1df9e05f719"
USDT_TRC20 = "TKeEd3wuTqHse2rdzAg3rqYeRfQD1NC7tq"

# ========== CONSTANTS ==========
QUEUE_TIMEOUT = 120
CHAT_TIMER = 600
AUTO_BAN_COUNT = 5
REFERRAL_REWARD = 15
CHAT_REWARD = 1
DAILY_BONUS = 10
MAX_FREE_CHATS = 20
MSG_DELETE_WINDOW_MIN = 30
COINS_PER_GENDER_MATCH = 2
COINS_TO_STARS = 100
GROUP_ROOM_MAX = 10
LEVELS = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500]

CITIES = ["Dhaka", "Chittagong", "Sylhet", "Rajshahi", "Khulna", "Barisal",
    "Rangpur", "Mymensingh", "Comilla", "Narayanganj", "Gazipur", "Bogura",
    "Jessore", "Cox's Bazar", "Kolkata", "Delhi", "Mumbai", "Karachi",
    "Lahore", "Dubai", "Riyadh", "London", "New York", "Toronto", "Sydney"]

PREMIUM_TIERS = {
    "bronze": {"name": "🥉 Bronze", "price": 49, "stars": 50, "days": 30, "coins": 50,
               "features": "Ads-free • Priority+1 • 50 Coins"},
    "silver": {"name": "🥈 Silver", "price": 99, "stars": 100, "days": 30, "coins": 150,
               "features": "Adv Filters • 2x Coins • Unlimited"},
    "gold": {"name": "🥇 Gold", "price": 199, "stars": 200, "days": 30, "coins": 500,
             "features": "Verified • Secure Chat • Priority Match"},
    "diamond": {"name": "💎 Diamond", "price": 399, "stars": 400, "days": 30, "coins": 1500,
                "features": "ALL + AI Trans + Voice + Priority"},
}

ACHIEVEMENTS = {
    "first_chat": ("🎉", "First Chat"), "chats_10": ("💬", "Chatter"),
    "chats_50": ("🗣️", "Talkative"), "chats_100": ("🏆", "Chat Master"),
    "chats_500": ("👑", "Legend"), "invite_1": ("🎁", "Inviter"),
    "invite_5": ("🔥", "Recruiter"), "invite_25": ("💎", "Influencer"),
    "streak_7": ("🔥", "Week Warrior"), "streak_30": ("💪", "Month Master"),
    "coins_100": ("🪙", "Rich"), "coins_1000": ("💰", "Wealthy"),
    "premium": ("⭐", "Premium"), "level_5": ("📈", "Rising Star"),
    "level_10": ("🌟", "Superstar"), "likes_10": ("❤️", "Loved"),
    "likes_50": ("💝", "Heart Throb"), "views_100": ("👀", "Popular"),
}

MISSIONS = {
    "chat_3": {"text": "3 chats", "reward": 30, "target": 3},
    "msg_20": {"text": "20 messages", "reward": 20, "target": 20},
    "invite_1": {"text": "1 invite", "reward": 50, "target": 1},
    "like_3": {"text": "3 likes", "reward": 15, "target": 3},
}

ICE_BREAKERS = [
    "If you could have dinner with anyone, who?",
    "What's your biggest dream?",
    "Last movie that made you cry?",
    "Secret talent nobody knows?",
    "If you won 1 crore, what would you do?",
    "Most embarrassing moment?",
    "Describe yourself in 3 words?",
    "What's on your bucket list?",
]

TRUTHS = ["Biggest regret?", "Last lie you told?", "Biggest crush?",
    "Most embarrassing thing you've done?", "Deepest secret?",
    "Worst date experience?", "Screen time today?"]

DARES = ["Send a selfie!", "Voice note singing!", "Type with eyes closed!",
    "Send funny sticker!", "Say 'I love you' dramatically!",
    "Reveal your wallpaper!", "Send your last photo!"]

BANNED = ["fuck","shit","bitch","asshole","dick","pussy","bastard",
    "madarchod","bhadwa","chutiya","chod","harami","kutta","kuti"]

# ========== STRINGS (4 LANG) ==========
STRINGS = {
    "welcome": {"bn":"👋 স্বাগতম! অ্যানোনিমাস চ্যাটিং বট।\n\n১৮+ নিশ্চিত করুন।","en":"👋 Welcome! Anonymous chat bot.\n\nConfirm 18+.","hi":"👋 स्वागत! गुमनाम चैट बॉट।\n\n18+ पुष्टि करें।","ru":"👋 Добро пожаловать! Анонимный чат.\n\nПодтвердите 18+."},
    "age_yes": {"bn":"✅ হ্যাঁ, ১৮+","en":"✅ Yes, 18+","hi":"✅ हाँ, 18+","ru":"✅ Да, 18+"},
    "age_no": {"bn":"❌ না","en":"❌ No","hi":"❌ नहीं","ru":"❌ Нет"},
    "age_denied": {"bn":"❌ শুধু ১৮+","en":"❌ Only 18+","hi":"❌ केवल 18+","ru":"❌ Только 18+"},
    "ask_name": {"bn":"✅ নাম:","en":"✅ Your name:","hi":"✅ नाम:","ru":"✅ Имя:"},
    "ask_age": {"bn":"🎂 বয়স (18-99):","en":"🎂 Age (18-99):","hi":"🎂 उम्र:","ru":"🎂 Возраст:"},
    "ask_gender": {"bn":"⚧ জেন্ডার:","en":"⚧ Gender:","hi":"⚧ लिंग:","ru":"⚧ Пол:"},
    "ask_city": {"bn":"🏙️ শহর:","en":"🏙️ Your city:","hi":"🏙️ शहर:","ru":"🏙️ Город:"},
    "ask_pref": {"bn":"🎯 কার সাথে চ্যাট:","en":"🎯 Chat preference:","hi":"🎯 पसंद:","ru":"🎯 Предпочтение:"},
    "ask_interest": {"bn":"💡 আগ্রহ:","en":"💡 Interest:","hi":"💡 रुचि:","ru":"💡 Интерес:"},
    "ask_bio": {"bn":"📝 বায়ো (max 200):","en":"📝 Bio (max 200):","hi":"📝 बायो:","ru":"📝 О себе:"},
    "male": {"bn":"👦 ছেলে","en":"👦 Male","hi":"👦 पुरुष","ru":"👦 Мужской"},
    "female": {"bn":"👧 মেয়ে","en":"👧 Female","hi":"👧 महिला","ru":"👧 Женский"},
    "other": {"bn":"🌈 অন্যান্য","en":"🌈 Other","hi":"🌈 अन्य","ru":"🌈 Другое"},
    "any": {"bn":"🌍 যে কেউ","en":"🌍 Anyone","hi":"🌍 कोई","ru":"🌍 Любой"},
    "main_menu": {"bn":"🏠 মেইন মেনু:","en":"🏠 Main Menu:","hi":"🏠 मुख्य मेनू:","ru":"🏠 Меню:"},
    "new_chat": {"bn":"🌹 নতুন অ্যানোনিমাস চ্যাট!","en":"🌹 New Anonymous Chat!","hi":"🌹 नई चैट!","ru":"🌹 Новый чат!"},
    "browse_people": {"bn":"💥 সবাইকে দেখুন","en":"💥 Browse People","hi":"💥 लोग देखें","ru":"💥 Обзор"},
    "nearby_people": {"bn":"📍 কাছাকাছি","en":"📍 Nearby People","hi":"📍 आसपास","ru":"📍 Рядом"},
    "random_free": {"bn":"🔀 র‍্যান্ডম (ফ্রি)","en":"🔀 Random (Free)","hi":"🔀 रैंडम (फ्री)","ru":"🔀 Случайный (бесплатно)"},
    "chat_guy": {"bn":"👨‍🌾 ছেলের সাথে চ্যাট","en":"👨‍🌾 Chat With Guy","hi":"👨‍🌾 लड़के से","ru":"👨‍🌾 С парнем"},
    "chat_girl": {"bn":"💃 মেয়ের সাথে চ্যাট","en":"💃 Chat With Girl","hi":"💃 लड़की से","ru":"💃 С девушкой"},
    "secure_chat": {"bn":"🔐 সিকিউর চ্যাট","en":"🔐 Secure Chat","hi":"🔐 सुरक्षित","ru":"🔐 Защищённый"},
    "contact_profile": {"bn":"👤 প্রোফাইল","en":"👤 Contact Profile","hi":"👤 प्रोफाइल","ru":"👤 Профиль"},
    "end_chat": {"bn":"🚪 চ্যাট শেষ","en":"🚪 End Chat","hi":"🚪 समाप्त","ru":"🚪 Конец"},
    "delete_msgs": {"bn":"🗑️ মেসেজ ডিলিট","en":"🗑️ Delete Messages","hi":"🗑️ हटाएँ","ru":"🗑️ Удалить"},
    "view_likers": {"bn":"👀 কারা লাইক করেছে","en":"👀 View Likers","hi":"👀 लाइकर्स","ru":"👀 Кто лайкнул"},
    "like_active": {"bn":"💚 লাইক করুন","en":"💚 Like","hi":"💚 लाइक","ru":"💚 Лайк"},
    "contact_list": {"bn":"🗣️ কন্টাক্ট লিস্ট","en":"🗣️ Contact List","hi":"🗣️ संपर्क","ru":"🗣️ Контакты"},
    "blocked_users": {"bn":"🚫 ব্লকড","en":"🚫 Blocked Users","hi":"🚫 ब्लॉक","ru":"🚫 Блок"},
    "advanced_settings": {"bn":"⚙️ সেটিংস","en":"⚙️ Advanced Settings","hi":"⚙️ सेटिंग्स","ru":"⚙️ Настройки"},
    "edit_profile": {"bn":"📝 প্রোফাইল এডিট","en":"📝 Edit Profile Info","hi":"📝 प्रोफाइल","ru":"📝 Профиль"},
    "searching": {"bn":"🔍 খোঁজা হচ্ছে...\n⏳ ২ মিনিট অপেক্ষা করুন।\n⚙️ Same Age Search: {sa}","en":"🔍 Searching...\n⏳ Wait up to 2 min.\n⚙️ Same Age Search: {sa}","hi":"🔍 खोज...\n⏳ 2 मिनट।\n⚙️ समान आयु: {sa}","ru":"🔍 Поиск...\n⏳ До 2 минут.\n⚙️ Поиск по возрасту: {sa}"},
    "partner_found": {"bn":"💗 আপনার জন্য পার্টনার পাওয়া গেছে!\nহ্যালো বলুন 👋","en":"💗 Found partner for you!\nSay hi 👋","hi":"💗 पार्टनर मिला!\nहैलो 👋","ru":"💗 Партнёр найден!\nПоздоровайтесь 👋"},
    "partner_viewed": {"bn":"👀 আপনার পার্টনার প্রোফাইল দেখেছেন!","en":"👀 Your chat partner viewed your profile!","hi":"👀 पार्टनर ने प्रोफाइल देखी!","ru":"👀 Партнёр посмотрел профиль!"},
    "chat_ended": {"bn":"🚪 চ্যাট শেষ।","en":"🚪 Chat ended.","hi":"🚪 समाप्त।","ru":"🚪 Конец."},
    "partner_ended": {"bn":"🚪 পার্টনার চ্যাট শেষ করেছেন।","en":"🚪 Partner ended the chat.","hi":"🚪 पार्टनर ने समाप्त।","ru":"🚪 Партнёр завершил."},
    "msgs_deleted": {"bn":"🗑️ আপনার মেসেজ ডিলিট করা হয়েছে।","en":"🗑️ Your messages were deleted.","hi":"🗑️ संदेश हटा।","ru":"🗑️ Удалено."},
    "not_in_chat": {"bn":"⚠️ চ্যাটে নেই। /start","en":"⚠️ Not in a chat. /start","hi":"⚠️ चैट में नहीं।","ru":"⚠️ Не в чате."},
    "reg_first": {"bn":"❌ আগে /start","en":"❌ /start first","hi":"❌ पहले /start","ru":"❌ Сначала /start"},
    "already_in_chat": {"bn":"❌ ইতিমধ্যে চ্যাটে আছেন।","en":"❌ Already in chat.","hi":"❌ पहले से।","ru":"❌ Уже в чате."},
    "search_cancelled": {"bn":"✅ বাতিল।","en":"✅ Cancelled.","hi":"✅ रद्द।","ru":"✅ Отменено."},
    "online_count": {"bn":"🟢 {n} অনলাইন","en":"🟢 {n} online","hi":"🟢 {n} ऑनलाइन","ru":"🟢 {n} онлайн"},
    "need_coins": {"bn":"💎 এই ফিচারের জন্য {n} কয়েন দরকার।\n🪙 আপনার আছে: {have}\n\n💡 ইনভাইট করে বা কিনে নিন।","en":"💎 Need {n} coins.\n🪙 You have: {have}\n\n💡 Invite or buy more.","hi":"💎 {n} सिक्के चाहिए।\n🪙 आपके पास: {have}","ru":"💎 Нужно {n} монет.\n🪙 У вас: {have}"},
    "coin_deducted": {"bn":"✅ {n} কয়েন কাটা হয়েছে।","en":"✅ {n} coins deducted.","hi":"✅ {n} सिक्के कटे।","ru":"✅ {n} списано."},
    "already_liked": {"bn":"✅ ইতিমধ্যে লাইক করা।","en":"✅ Already liked.","hi":"✅ पहले लाइक।","ru":"✅ Уже лайкнуто."},
    "liked_you": {"bn":"❤️ কেউ আপনার প্রোফাইল লাইক করেছে!","en":"❤️ Someone liked your profile!","hi":"❤️ किसी ने लाइक किया!","ru":"❤️ Кто-то лайкнул!"},
    "no_likers": {"bn":"এখনো কেউ লাইক করেনি।","en":"No likers yet.","hi":"कोई लाइक नहीं।","ru":"Нет лайков."},
    "no_blocked": {"bn":"কোনো blocked নেই।","en":"No blocked users.","hi":"कोई ब्लॉक नहीं।","ru":"Нет блокировок."},
    "unblocked": {"bn":"✅ আনব্লক।","en":"✅ Unblocked.","hi":"✅ अनब्लॉक।","ru":"✅ Разблокировано."},
    "no_contacts": {"bn":"কোনো contact নেই।","en":"No contacts yet.","hi":"कोई संपर्क नहीं।","ru":"Нет контактов."},
    "profile_saved": {"bn":"✅ সেভ!","en":"✅ Saved!","hi":"✅ सेव!","ru":"✅ Сохранено!"},
    "language_select": {"bn":"🌍 ভাষা:","en":"🌍 Language:","hi":"🌍 भाषा:","ru":"🌍 Язык:"},
    "lang_set": {"bn":"✅ বাংলা","en":"✅ English","hi":"✅ हिन्दी","ru":"✅ Русский"},
    "choose_city": {"bn":"🏙️ শহর বাছুন:","en":"🏙️ Choose city:","hi":"🏙️ शहर चुनें:","ru":"🏙️ Город:"},
    "browse_title": {"bn":"💥 অনলাইন ইউজার:","en":"💥 Online Users:","hi":"💥 ऑनलाइन:","ru":"💥 Онлайн:"},
    "nearby_title": {"bn":"📍 {city}-তে অনলাইন:","en":"📍 Online in {city}:","hi":"📍 {city} में:","ru":"📍 В {city}:"},
    "no_users": {"bn":"কোনো ইউজার নেই।","en":"No users found.","hi":"कोई यूज़र नहीं।","ru":"Пользователи не найдены."},
    "no_partner_ai": {"bn":"🤖 পার্টনার নেই। AI চ্যাট?","en":"🤖 No partner. Chat with AI?","hi":"🤖 पार्टनर नहीं। AI चैट?","ru":"🤖 Нет партнёра. Чат с AI?"},
    "ai_mode": {"bn":"🤖 AI মোড। /stop বন্ধ।","en":"🤖 AI mode. /stop to end.","hi":"🤖 AI मोड। /stop","ru":"🤖 AI режим. /stop"},
    "invite_msg": {"bn":"🔗 আপনার লিংক:\n{link}\n\n💡 প্রতি ইনভাইটে {coins} কয়েন!","en":"🔗 Your link:\n{link}\n\n💡 {coins} coins per invite!","hi":"🔗 लिंक:\n{link}\n\n💡 {coins} सिक्के!","ru":"🔗 Ссылка:\n{link}\n\n💡 {coins} монет!"},
    "anon_link_msg": {"bn":"🔗 অ্যানোনিমাস লিংক:\n{link}\n\n💡 ক্লিক করলে সরাসরি আপনার সাথে চ্যাট হবে।","en":"🔗 Anonymous link:\n{link}\n\n💡 Click to chat directly.","hi":"🔗 गुमनाम लिंक:\n{link}","ru":"🔗 Анонимная ссылка:\n{link}"},
    "credit": {"bn":"🪙 কয়েন: {coins}\n💎 Stars: {stars}\n⭐ VIP: {vip}","en":"🪙 Coins: {coins}\n💎 Stars: {stars}\n⭐ VIP: {vip}","hi":"🪙 सिक्के: {coins}\n⭐ VIP: {vip}","ru":"🪙 Монеты: {coins}\n⭐ VIP: {vip}"},
    "vip_active": {"bn":"✅ সক্রিয়","en":"✅ Active","hi":"✅ सक्रिय","ru":"✅ Активен"},
    "vip_inactive": {"bn":"❌ নিষ্ক্রিয়","en":"❌ Inactive","hi":"❌ निष्क्रिय","ru":"❌ Неактивен"},
    "support_sent": {"bn":"✅ পাঠানো হয়েছে।","en":"✅ Sent to admin.","hi":"✅ भेजा गया।","ru":"✅ Отправлено."},
    "report_blocked": {"bn":"✅ রিপোর্ট + ব্লকড।","en":"✅ Reported + blocked.","hi":"✅ रिपोर्ट + ब्लॉक।","ru":"✅ Жалоба + блок."},
    "feedback_thanks": {"bn":"🙏 ধন্যবাদ!","en":"🙏 Thanks!","hi":"🙏 धन्यवाद!","ru":"🙏 Спасибо!"},
    "daily_bonus": {"bn":"🎁 ডেইলি বোনাস: +{n} কয়েন!","en":"🎁 Daily bonus: +{n} coins!","hi":"🎁 बोनस: +{n}","ru":"🎁 Бонус: +{n}"},
    "streak": {"bn":"🔥 Streak: {n} দিন!","en":"🔥 Streak: {n} days!","hi":"🔥 स्ट्रीक: {n}","ru":"🔥 Серия: {n}"},
    "level_up": {"bn":"🎉 Level Up! Lv{level}!","en":"🎉 Level Up! Lv{level}!","hi":"🎉 लेवल अप! Lv{level}!","ru":"🎉 Уровень! Ур{level}!"},
    "chat_limit": {"bn":"❌ আজকের লিমিট শেষ। VIP নিন।","en":"❌ Daily limit reached. Get VIP.","hi":"❌ दैनिक सीमा।","ru":"❌ Лимит. Купите VIP."},
    "spam_warn": {"bn":"⚠️ ভদ্রভাবে বলুন।","en":"⚠️ Be respectful.","hi":"⚠️ सम्मान।","ru":"⚠️ Вежливо."},
    "same_age_on": {"bn":"✅ Same Age Search চালু","en":"✅ Same Age Search ON","hi":"✅ समान आयु ON","ru":"✅ Поиск по возрасту ВКЛ"},
    "same_age_off": {"bn":"⚪ Same Age Search বন্ধ","en":"⚪ Same Age Search OFF","hi":"⚪ समान आयु OFF","ru":"⚪ Поиск по возрасту ВЫКЛ"},
    "liked_success": {"bn":"❤️ লাইক সফল!","en":"❤️ Liked!","hi":"❤️ लाइक!","ru":"❤️ Лайкнуто!"},
    "verify_ok": {"bn":"✅ Verified!","en":"✅ Verified!","hi":"✅ Verified!","ru":"✅ Verified!"},
}

def t(key, lang="bn", **kw):
    s = STRINGS.get(key, {})
    txt = s.get(lang) or s.get("en") or s.get("bn") or key
    if kw:
        try: return txt.format(**kw)
        except: return txt
    return txt

# ========== DATABASE ==========
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as c:
        # USERS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_18_plus BOOLEAN DEFAULT FALSE,
                is_banned BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                language VARCHAR(5) DEFAULT 'en',
                coins INTEGER DEFAULT 0,
                stars_balance INTEGER DEFAULT 0,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                streak INTEGER DEFAULT 0,
                last_streak_date DATE,
                is_vip BOOLEAN DEFAULT FALSE,
                vip_tier VARCHAR(20),
                vip_until TIMESTAMP,
                referred_by BIGINT,
                total_chats INTEGER DEFAULT 0,
                chats_today INTEGER DEFAULT 0,
                chats_today_date DATE DEFAULT CURRENT_DATE,
                daily_bonus_date DATE,
                is_verified BOOLEAN DEFAULT FALSE,
                birthday DATE,
                anon_id VARCHAR(20),
                city VARCHAR(50),
                likes_received INTEGER DEFAULT 0,
                profile_views INTEGER DEFAULT 0,
                same_age_search BOOLEAN DEFAULT FALSE,
                secure_chat BOOLEAN DEFAULT FALSE,
                status VARCHAR(20) DEFAULT 'idle'
            );
        """)
        # PROFILES
        await c.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id BIGINT PRIMARY KEY,
                display_name VARCHAR(100), age INTEGER,
                gender VARCHAR(20), pref_gender VARCHAR(20) DEFAULT 'any',
                bio TEXT, pref_language VARCHAR(10) DEFAULT 'any',
                interest VARCHAR(30) DEFAULT 'any',
                min_age INTEGER DEFAULT 18, max_age INTEGER DEFAULT 99,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # MATCH QUEUE
        await c.execute("""
            CREATE TABLE IF NOT EXISTS match_queue (
                user_id BIGINT PRIMARY KEY,
                gender VARCHAR(20), pref_gender VARCHAR(20),
                pref_language VARCHAR(10), interest VARCHAR(30),
                is_vip BOOLEAN DEFAULT FALSE, age INTEGER DEFAULT 18,
                min_age INTEGER DEFAULT 18, max_age INTEGER DEFAULT 99,
                same_age BOOLEAN DEFAULT FALSE,
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # ACTIVE CHATS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS active_chats (
                user_id BIGINT PRIMARY KEY, partner_id BIGINT,
                is_ai BOOLEAN DEFAULT FALSE,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # CHAT LOG (for delete window)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS chat_log (
                id SERIAL PRIMARY KEY, user_id BIGINT, partner_id BIGINT,
                message_id BIGINT, messages INTEGER DEFAULT 0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP
            );
        """)
        # GROUP ROOMS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS group_rooms (
                room_id SERIAL PRIMARY KEY, host_id BIGINT,
                name VARCHAR(100), is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                room_id INTEGER, user_id BIGINT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (room_id, user_id)
            );
        """)
        # VOICE ROOMS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS voice_rooms (
                room_id SERIAL PRIMARY KEY, host_id BIGINT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await c.execute("""
            CREATE TABLE IF NOT EXISTS voice_members (
                room_id INTEGER, user_id BIGINT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (room_id, user_id)
            );
        """)
        # BLOCKS / REPORTS / FRIENDS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                blocker_id BIGINT, blocked_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (blocker_id, blocked_id)
            );
            CREATE TABLE IF NOT EXISTS reports (
                report_id SERIAL PRIMARY KEY, reporter_id BIGINT,
                reported_id BIGINT, reason VARCHAR(100),
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS friends (
                user_id BIGINT, friend_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, friend_id)
            );
        """)
        # ACHIEVEMENTS / MISSIONS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                user_id BIGINT, achievement_key VARCHAR(50),
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, achievement_key)
            );
            CREATE TABLE IF NOT EXISTS daily_missions (
                user_id BIGINT, mission_key VARCHAR(50), date DATE,
                progress INTEGER DEFAULT 0, completed BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (user_id, mission_key, date)
            );
        """)
        # PAYMENTS / STATUSES / TICKETS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id SERIAL PRIMARY KEY, user_id BIGINT,
                tier VARCHAR(20), method VARCHAR(30), amount_bdt INTEGER,
                transaction_id TEXT, status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP, approved_by BIGINT
            );
            CREATE TABLE IF NOT EXISTS statuses (
                status_id SERIAL PRIMARY KEY, user_id BIGINT,
                content TEXT, expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS support_tickets (
                ticket_id SERIAL PRIMARY KEY, user_id BIGINT,
                message TEXT, status VARCHAR(20) DEFAULT 'open',
                admin_reply TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                replied_at TIMESTAMP
            );
        """)
        # LIKES / VIEWS / ANON LINKS
        await c.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                liker_id BIGINT, liked_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (liker_id, liked_id)
            );
            CREATE TABLE IF NOT EXISTS profile_views (
                viewer_id BIGINT, viewed_id BIGINT,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (viewer_id, viewed_id)
            );
            CREATE TABLE IF NOT EXISTS anon_links (
                link_code VARCHAR(20) PRIMARY KEY,
                user_id BIGINT UNIQUE,
                clicks INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # MIGRATIONS for old DBs
        migrations = [
            ("users", "xp", "INTEGER DEFAULT 0"),
            ("users", "level", "INTEGER DEFAULT 1"),
            ("users", "streak", "INTEGER DEFAULT 0"),
            ("users", "last_streak_date", "DATE"),
            ("users", "vip_tier", "VARCHAR(20)"),
            ("users", "total_chats", "INTEGER DEFAULT 0"),
            ("users", "chats_today", "INTEGER DEFAULT 0"),
            ("users", "chats_today_date", "DATE DEFAULT CURRENT_DATE"),
            ("users", "daily_bonus_date", "DATE"),
            ("users", "is_verified", "BOOLEAN DEFAULT FALSE"),
            ("users", "birthday", "DATE"),
            ("users", "anon_id", "VARCHAR(20)"),
            ("users", "city", "VARCHAR(50)"),
            ("users", "likes_received", "INTEGER DEFAULT 0"),
            ("users", "profile_views", "INTEGER DEFAULT 0"),
            ("users", "same_age_search", "BOOLEAN DEFAULT FALSE"),
            ("users", "secure_chat", "BOOLEAN DEFAULT FALSE"),
            ("users", "stars_balance", "INTEGER DEFAULT 0"),
            ("users", "status", "VARCHAR(20) DEFAULT 'idle'"),
            ("profiles", "pref_language", "VARCHAR(10) DEFAULT 'any'"),
            ("profiles", "interest", "VARCHAR(30) DEFAULT 'any'"),
            ("profiles", "min_age", "INTEGER DEFAULT 18"),
            ("profiles", "max_age", "INTEGER DEFAULT 99"),
            ("match_queue", "pref_language", "VARCHAR(10) DEFAULT 'any'"),
            ("match_queue", "interest", "VARCHAR(30) DEFAULT 'any'"),
            ("match_queue", "is_vip", "BOOLEAN DEFAULT FALSE"),
            ("match_queue", "age", "INTEGER DEFAULT 18"),
            ("match_queue", "min_age", "INTEGER DEFAULT 18"),
            ("match_queue", "max_age", "INTEGER DEFAULT 99"),
            ("match_queue", "same_age", "BOOLEAN DEFAULT FALSE"),
            ("active_chats", "is_ai", "BOOLEAN DEFAULT FALSE"),
            ("group_rooms", "name", "VARCHAR(100)"),
            ("chat_log", "message_id", "BIGINT"),
        ]
        for tbl, col, typ in migrations:
            try:
                await c.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception as e:
                logger.warning(f"Migration {tbl}.{col}: {e}")
    logger.info("DB ready.")


async def close_db():
    if db_pool: await db_pool.close()


# ========== HELPERS ==========
def gen_id(): 
    return ''.join(random.choice(string.ascii_letters+string.digits) for _ in range(4))

async def touch(uid):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET last_active=NOW() WHERE user_id=$1", uid)

async def get_lang(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT language FROM users WHERE user_id=$1", uid)
        return (r['language'] if r and r['language'] else 'en')

async def set_lang(uid, l):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET language=$1 WHERE user_id=$2", l, uid)

async def online_count():
    async with db_pool.acquire() as c:
        return (await c.fetchval("SELECT COUNT(*) FROM users WHERE last_active > NOW() - INTERVAL '5 min'")) or 0

async def is_banned(uid):
    async with db_pool.acquire() as c:
        return bool(await c.fetchval("SELECT is_banned FROM users WHERE user_id=$1", uid))

async def get_profile(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM profiles WHERE user_id=$1", uid)
        return dict(r) if r else None

async def save_profile(uid, **kw):
    if not kw: return
    cols = list(kw.keys()); vals = list(kw.values())
    ph = [f"${i+2}" for i in range(len(cols))]
    upd = ", ".join([f"{c}=EXCLUDED.{c}" for c in cols])
    q = f"INSERT INTO profiles (user_id,{','.join(cols)}) VALUES ($1,{','.join(ph)}) ON CONFLICT (user_id) DO UPDATE SET {upd}"
    async with db_pool.acquire() as c:
        await c.execute(q, uid, *vals)

async def get_stats(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("""SELECT coins,stars_balance,xp,level,streak,total_chats,
            is_vip,vip_tier,vip_until,is_verified,anon_id,city,likes_received,
            profile_views,same_age_search,secure_chat FROM users WHERE user_id=$1""", uid)
        return dict(r) if r else None

async def get_anon_id(uid):
    async with db_pool.acquire() as c:
        aid = await c.fetchval("SELECT anon_id FROM users WHERE user_id=$1", uid)
        if aid: return aid
        for _ in range(10):
            nid = gen_id()
            try:
                await c.execute("UPDATE users SET anon_id=$1 WHERE user_id=$2 AND anon_id IS NULL", nid, uid)
                aid2 = await c.fetchval("SELECT anon_id FROM users WHERE user_id=$1", uid)
                if aid2: return aid2
            except: continue
        return "user"

async def set_city(uid, city):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET city=$1 WHERE user_id=$2", city, uid)

async def get_coins(uid):
    async with db_pool.acquire() as c:
        return (await c.fetchval("SELECT coins FROM users WHERE user_id=$1", uid)) or 0

async def add_coins(uid, n):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET coins=coins+$1 WHERE user_id=$2", n, uid)

async def deduct_coins(uid, n):
    async with db_pool.acquire() as c:
        cur = (await c.fetchval("SELECT coins FROM users WHERE user_id=$1", uid)) or 0
        if cur < n: return False
        await c.execute("UPDATE users SET coins=coins-$1 WHERE user_id=$2", n, uid)
        return True

async def add_xp(uid, n):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT xp,level FROM users WHERE user_id=$1", uid)
        if not r: return None
        new_xp = (r['xp'] or 0) + n
        new_lvl = 1
        for i, th in enumerate(LEVELS):
            if new_xp >= th: new_lvl = i+1
        await c.execute("UPDATE users SET xp=$1,level=$2 WHERE user_id=$3", new_xp, new_lvl, uid)
        return new_lvl if new_lvl > (r['level'] or 1) else None

async def is_vip(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT is_vip,vip_until FROM users WHERE user_id=$1", uid)
        if not r or not r['is_vip']: return False
        if r['vip_until'] and r['vip_until'] < datetime.now():
            await c.execute("UPDATE users SET is_vip=FALSE WHERE user_id=$1", uid)
            return False
        return True

async def get_tier(uid):
    async with db_pool.acquire() as c:
        return await c.fetchval("SELECT vip_tier FROM users WHERE user_id=$1", uid)

async def set_vip(uid, tier, days=30):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET is_vip=TRUE,vip_tier=$1,vip_until=$2 WHERE user_id=$3",
                        tier, datetime.now()+timedelta(days=days), uid)

async def update_streak(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT streak,last_streak_date FROM users WHERE user_id=$1", uid)
        if not r: return 0, False
        today = datetime.now().date()
        if r['last_streak_date'] == today: return r['streak'] or 0, False
        streak = r['streak'] or 0
        if r['last_streak_date'] and (today - r['last_streak_date']).days == 1: streak += 1
        else: streak = 1
        await c.execute("UPDATE users SET streak=$1,last_streak_date=$2 WHERE user_id=$3", streak, today, uid)
        if streak == 7: await c.execute("UPDATE users SET coins=coins+100 WHERE user_id=$1", uid)
        elif streak == 30: await c.execute("UPDATE users SET coins=coins+500 WHERE user_id=$1", uid)
        return streak, True

async def daily_bonus(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT daily_bonus_date FROM users WHERE user_id=$1", uid)
        today = datetime.now().date()
        if r and r['daily_bonus_date'] == today: return False
        await c.execute("UPDATE users SET daily_bonus_date=$1,coins=coins+$2 WHERE user_id=$3",
                        today, DAILY_BONUS, uid)
        return True

async def toggle_same_age(uid):
    async with db_pool.acquire() as c:
        cur = await c.fetchval("SELECT same_age_search FROM users WHERE user_id=$1", uid)
        new = not cur
        await c.execute("UPDATE users SET same_age_search=$1 WHERE user_id=$2", new, uid)
        return new

async def get_same_age(uid):
    async with db_pool.acquire() as c:
        return bool(await c.fetchval("SELECT same_age_search FROM users WHERE user_id=$1", uid))

# LIKES
async def add_like(liker, liked):
    if liker == liked: return False
    async with db_pool.acquire() as c:
        if await c.fetchval("SELECT 1 FROM likes WHERE liker_id=$1 AND liked_id=$2", liker, liked):
            return False
        await c.execute("INSERT INTO likes (liker_id,liked_id) VALUES ($1,$2)", liker, liked)
        await c.execute("UPDATE users SET likes_received=likes_received+1 WHERE user_id=$1", liked)
        return True

async def get_likers(uid, limit=20):
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT l.liker_id, p.display_name, u.anon_id
            FROM likes l LEFT JOIN profiles p ON p.user_id=l.liker_id
            LEFT JOIN users u ON u.user_id=l.liker_id
            WHERE l.liked_id=$1 ORDER BY l.created_at DESC LIMIT $2""", uid, limit)
        return [dict(r) for r in rows]

async def record_view(viewer, viewed):
    if viewer == viewed: return
    async with db_pool.acquire() as c:
        if await c.fetchval("SELECT 1 FROM profile_views WHERE viewer_id=$1 AND viewed_id=$2", viewer, viewed):
            await c.execute("UPDATE profile_views SET viewed_at=NOW() WHERE viewer_id=$1 AND viewed_id=$2", viewer, viewed)
        else:
            await c.execute("INSERT INTO profile_views (viewer_id,viewed_id) VALUES ($1,$2)", viewer, viewed)
            await c.execute("UPDATE users SET profile_views=profile_views+1 WHERE user_id=$1", viewed)

async def get_blocked(uid):
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT b.blocked_id, p.display_name, u.anon_id
            FROM blocks b LEFT JOIN profiles p ON p.user_id=b.blocked_id
            LEFT JOIN users u ON u.user_id=b.blocked_id
            WHERE b.blocker_id=$1""", uid)
        return [dict(r) for r in rows]

async def unblock_user(uid, target):
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM blocks WHERE blocker_id=$1 AND blocked_id=$2", uid, target)

async def browse_people(uid, limit=10):
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT u.user_id, u.anon_id, u.city, u.is_verified,
            p.display_name, p.age, p.gender
            FROM users u LEFT JOIN profiles p ON p.user_id=u.user_id
            WHERE u.user_id!=$1 AND u.is_banned=FALSE AND p.display_name IS NOT NULL
            AND u.last_active > NOW() - INTERVAL '1 hour'
            ORDER BY u.last_active DESC LIMIT $2""", uid, limit)
        return [dict(r) for r in rows]

async def nearby_people(uid, limit=10):
    async with db_pool.acquire() as c:
        city = await c.fetchval("SELECT city FROM users WHERE user_id=$1", uid)
        if not city: return []
        rows = await c.fetch("""SELECT u.user_id, u.anon_id, u.city, u.is_verified,
            p.display_name, p.age FROM users u LEFT JOIN profiles p ON p.user_id=u.user_id
            WHERE u.user_id!=$1 AND u.city=$2 AND u.is_banned=FALSE
            AND u.last_active > NOW() - INTERVAL '1 hour' AND p.display_name IS NOT NULL
            ORDER BY u.last_active DESC LIMIT $3""", uid, city, limit)
        return [dict(r) for r in rows]

async def get_anon_link(uid):
    async with db_pool.acquire() as c:
        code = await c.fetchval("SELECT link_code FROM anon_links WHERE user_id=$1", uid)
        if code: return code
        for _ in range(10):
            ncode = gen_id() + gen_id()
            try:
                await c.execute("INSERT INTO anon_links (link_code,user_id) VALUES ($1,$2)", ncode, uid)
                return ncode
            except: continue
        return None

async def resolve_anon(code):
    async with db_pool.acquire() as c:
        uid = await c.fetchval("SELECT user_id FROM anon_links WHERE link_code=$1", code)
        if uid:
            await c.execute("UPDATE anon_links SET clicks=clicks+1 WHERE link_code=$1", code)
        return uid

# CHAT
async def get_chat(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM active_chats WHERE user_id=$1", uid)
        return dict(r) if r else None

async def remove_chat(uid, pid):
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM active_chats WHERE user_id=$1 OR user_id=$2", uid, pid)

def bad_words(text):
    if not text: return False
    return any(w in text.lower() for w in BANNED)

rate_store = {}
def rate_limited(uid, mx=20, win=10):
    now = datetime.now()
    ts = [x for x in rate_store.get(uid, []) if (now-x).total_seconds() < win]
    if len(ts) >= mx:
        rate_store[uid] = ts; return True
    ts.append(now); rate_store[uid] = ts; return False

async def ref_process(new_uid, ref_uid):
    if new_uid == ref_uid: return False
    async with db_pool.acquire() as c:
        if not await c.fetchval("SELECT 1 FROM users WHERE user_id=$1", ref_uid): return False
        if await c.fetchval("SELECT referred_by FROM users WHERE user_id=$1", new_uid) is not None: return False
        await c.execute("UPDATE users SET referred_by=$1 WHERE user_id=$2", ref_uid, new_uid)
        await c.execute("UPDATE users SET coins=coins+$1 WHERE user_id=$2", REFERRAL_REWARD, ref_uid)
    return True

# ACHIEVEMENTS
async def user_ach(uid):
    async with db_pool.acquire() as c:
        rows = await c.fetch("SELECT achievement_key FROM user_achievements WHERE user_id=$1", uid)
        return {r['achievement_key'] for r in rows}

async def unlock_ach(uid, key):
    async with db_pool.acquire() as c:
        if await c.fetchval("SELECT 1 FROM user_achievements WHERE user_id=$1 AND achievement_key=$2", uid, key):
            return False
        await c.execute("INSERT INTO user_achievements (user_id,achievement_key) VALUES ($1,$2)", uid, key)
        return True

async def check_ach(uid, context):
    s = await get_stats(uid)
    if not s: return []
    earned = await user_ach(uid)
    new = []
    checks = {
        "chats_10": (s['total_chats'] or 0) >= 10,
        "chats_50": (s['total_chats'] or 0) >= 50,
        "chats_100": (s['total_chats'] or 0) >= 100,
        "chats_500": (s['total_chats'] or 0) >= 500,
        "streak_7": (s['streak'] or 0) >= 7,
        "streak_30": (s['streak'] or 0) >= 30,
        "coins_100": (s['coins'] or 0) >= 100,
        "coins_1000": (s['coins'] or 0) >= 1000,
        "premium": s['is_vip'],
        "level_5": (s['level'] or 1) >= 5,
        "level_10": (s['level'] or 1) >= 10,
        "likes_10": (s['likes_received'] or 0) >= 10,
        "likes_50": (s['likes_received'] or 0) >= 50,
        "views_100": (s['profile_views'] or 0) >= 100,
    }
    async with db_pool.acquire() as c:
        inv = await c.fetchval("SELECT COUNT(*) FROM users WHERE referred_by=$1", uid) or 0
    checks["invite_1"] = inv >= 1
    checks["invite_5"] = inv >= 5
    checks["invite_25"] = inv >= 25
    for k, ok in checks.items():
        if ok and k not in earned:
            if await unlock_ach(uid, k):
                new.append(k)
                e, title = ACHIEVEMENTS.get(k, ("🏅", k))
                try: await context.bot.send_message(uid, f"🎉 {e} {title}")
                except: pass
    return new

async def mission_prog(uid, key, amt=1):
    m = MISSIONS.get(key)
    if not m: return
    today = datetime.now().date()
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT progress,completed FROM daily_missions WHERE user_id=$1 AND mission_key=$2 AND date=$3", uid, key, today)
        if r and r['completed']: return
        prog = (r['progress'] if r else 0) + amt
        done = prog >= m['target']
        if done:
            await c.execute("UPDATE users SET coins=coins+$1 WHERE user_id=$2", m['reward'], uid)
        await c.execute("""INSERT INTO daily_missions (user_id,mission_key,date,progress,completed)
            VALUES ($1,$2,$3,$4,$5) ON CONFLICT (user_id,mission_key,date)
            DO UPDATE SET progress=$4,completed=$5""", uid, key, today, prog, done)

async def missions_status(uid):
    today = datetime.now().date()
    async with db_pool.acquire() as c:
        rows = await c.fetch("SELECT mission_key,progress,completed FROM daily_missions WHERE user_id=$1 AND date=$2", uid, today)
    out = {}
    for k, m in MISSIONS.items():
        r = next((x for x in rows if x['mission_key'] == k), None)
        out[k] = {"progress": r['progress'] if r else 0, "completed": r['completed'] if r else False,
                  "target": m['target'], "reward": m['reward'], "text": m['text']}
    return out

# ========== KEYBOARDS ==========
def bottom_kb(lang):
    """MeChat-style persistent bottom keyboard."""
    return ReplyKeyboardMarkup([
        [KeyboardButton(t("new_chat", lang))],
        [KeyboardButton(t("browse_people", lang)),
         KeyboardButton(t("nearby_people", lang))],
    ], resize_keyboard=True, is_persistent=True)

async def main_menu_kb(lang):
    on = await online_count()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("new_chat", lang), callback_data="newchat")],
        [InlineKeyboardButton("👤 Profile", callback_data="my_profile"),
         InlineKeyboardButton("🎯 Missions", callback_data="show_missions")],
        [InlineKeyboardButton("🏅 Achievements", callback_data="show_achievements"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("🎁 Invite", callback_data="show_link"),
         InlineKeyboardButton("🔗 Anon Link", callback_data="show_anon_link")],
        [InlineKeyboardButton("⭐ Premium", callback_data="show_vip"),
         InlineKeyboardButton("🪙 Credit", callback_data="show_credit")],
        [InlineKeyboardButton("🌐 Language", callback_data="change_language"),
         InlineKeyboardButton("🎫 Support", callback_data="support_ticket")],
        [InlineKeyboardButton(f"🟢 {on} online", callback_data="refresh_online")],
    ])

def newchat_kb(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("random_free", lang), callback_data="search_random")],
        [InlineKeyboardButton(t("chat_guy", lang), callback_data="search_guy"),
         InlineKeyboardButton(t("chat_girl", lang), callback_data="search_girl")],
        [InlineKeyboardButton("🌐 Language", callback_data="change_language")],
    ])

def active_chat_kb(pid, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("secure_chat", lang), callback_data="secure_chat"),
         InlineKeyboardButton(t("contact_profile", lang), callback_data=f"viewprof_{pid}")],
        [InlineKeyboardButton(t("end_chat", lang), callback_data="end_chat"),
         InlineKeyboardButton(t("delete_msgs", lang), callback_data="delete_msgs")],
        [InlineKeyboardButton("🎲 Truth/Dare", callback_data="tod_start"),
         InlineKeyboardButton("🧊 Ice-Breaker", callback_data="ice_breaker")],
        [InlineKeyboardButton("💯 Compat", callback_data="compat"),
         InlineKeyboardButton("📝 Summary", callback_data="chat_summary")],
        [InlineKeyboardButton("❤️ Like", callback_data=f"like_{pid}"),
         InlineKeyboardButton("👫 Friend", callback_data=f"addfriend_{pid}")],
        [InlineKeyboardButton("🚫 Report", callback_data=f"report_{pid}")],
    ])

def profile_kb(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("view_likers", lang), callback_data="view_likers"),
         InlineKeyboardButton(t("like_active", lang), callback_data="my_likes")],
        [InlineKeyboardButton(t("contact_list", lang), callback_data="contact_list"),
         InlineKeyboardButton(t("blocked_users", lang), callback_data="show_blocked")],
        [InlineKeyboardButton(t("advanced_settings", lang), callback_data="advanced_settings")],
        [InlineKeyboardButton(t("edit_profile", lang), callback_data="edit_profile")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")],
    ])

def city_kb(lang):
    rows = []; row = []
    for i, city in enumerate(CITIES):
        row.append(InlineKeyboardButton(city, callback_data=f"setcity_{city}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Custom", callback_data="custom_city")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

# ========== /START ==========
async def start(update, context):
    uid = update.effective_user.id
    await touch(uid)
    if await is_banned(uid):
        await update.message.reply_text("🚫 Banned."); return

    args = context.args or []
    ref_id = None
    anon_target = None
    
    if args and args[0].startswith("ref_"):
        try:
            p = int(args[0][4:])
            if p != uid: ref_id = p
        except: pass
    elif args and args[0].startswith("anon_"):
        try:
            code = args[0][5:]
            anon_target = await resolve_anon(code)
            if anon_target == uid: anon_target = None
        except Exception as e:
            logger.error(f"Anon link: {e}")

    async with db_pool.acquire() as c:
        u = await c.fetchrow("SELECT * FROM users WHERE user_id=$1", uid)
        if not u:
            await c.execute("INSERT INTO users (user_id) VALUES ($1)", uid)
            await get_anon_id(uid)
            if ref_id:
                try:
                    if await ref_process(uid, ref_id):
                        rl = await get_lang(ref_id)
                        await context.bot.send_message(ref_id, t("invite_msg", rl, link="", coins=REFERRAL_REWARD))
                except: pass
            context.user_data.clear()
            context.user_data['reg_step'] = 'language'
            if anon_target: context.user_data['anon_target'] = anon_target
            await update.message.reply_text(t("language_select", "en"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
                     InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
                    [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
                     InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]]))
            return

    lang = u.get('language') or 'en'
    await get_anon_id(uid)

    if ref_id:
        async with db_pool.acquire() as c:
            alr = await c.fetchval("SELECT referred_by FROM users WHERE user_id=$1", uid)
        if alr is None:
            if await ref_process(uid, ref_id):
                try:
                    rl = await get_lang(ref_id)
                    await context.bot.send_message(ref_id, f"🎁 You earned {REFERRAL_REWARD} coins!")
                except: pass

    if await daily_bonus(uid):
        await update.message.reply_text(t("daily_bonus", lang, n=DAILY_BONUS))

    streak, is_new = await update_streak(uid)
    if is_new and streak > 1:
        await update.message.reply_text(t("streak", lang, n=streak))

    prof = await get_profile(uid)
    if not prof or not prof.get('display_name'):
        context.user_data.clear()
        if anon_target: context.user_data['anon_target'] = anon_target
        context.user_data['reg_step'] = 'name'
        await update.message.reply_text(t("ask_name", lang)); return
    if not prof.get('age'):
        context.user_data.clear()
        if anon_target: context.user_data['anon_target'] = anon_target
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text(t("ask_age", lang)); return
    if not prof.get('gender'):
        context.user_data.clear()
        if anon_target: context.user_data['anon_target'] = anon_target
        context.user_data['reg_step'] = 'gender'
        await update.message.reply_text(t("ask_gender", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("male", lang), callback_data="gender_male"),
                 InlineKeyboardButton(t("female", lang), callback_data="gender_female")],
                [InlineKeyboardButton(t("other", lang), callback_data="gender_other")]]))
        return
    if not prof.get('pref_gender'):
        context.user_data.clear()
        if anon_target: context.user_data['anon_target'] = anon_target
        context.user_data['reg_step'] = 'pref_gender'
        await update.message.reply_text(t("ask_pref", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("male", lang), callback_data="pref_male"),
                 InlineKeyboardButton(t("female", lang), callback_data="pref_female")],
                [InlineKeyboardButton(t("any", lang), callback_data="pref_any")]]))
        return
    if not prof.get('interest'):
        context.user_data.clear()
        if anon_target: context.user_data['anon_target'] = anon_target
        context.user_data['reg_step'] = 'interest'
        await update.message.reply_text(t("ask_interest", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 Music", callback_data="int_music"),
                 InlineKeyboardButton("🎬 Movie", callback_data="int_movie")],
                [InlineKeyboardButton("📚 Study", callback_data="int_study"),
                 InlineKeyboardButton("🎮 Gaming", callback_data="int_gaming")],
                [InlineKeyboardButton("💕 Love", callback_data="int_love"),
                 InlineKeyboardButton("🌍 Any", callback_data="int_any")]]))
        return
    if not prof.get('pref_language'):
        context.user_data.clear()
        if anon_target: context.user_data['anon_target'] = anon_target
        context.user_data['reg_step'] = 'pref_language'
        await update.message.reply_text(t("ask_pref", lang) + " (Language)",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🇧🇩 Bangla", callback_data="plang_bn"),
                 InlineKeyboardButton("🇬🇧 English", callback_data="plang_en")],
                [InlineKeyboardButton("🇮🇳 Hindi", callback_data="plang_hi"),
                 InlineKeyboardButton("🌍 Any", callback_data="plang_any")]]))
        return

    # Auto-connect from anon link
    if anon_target:
        try:
            await connect_users(uid, anon_target, context, lang); return
        except Exception as e:
            logger.error(f"Anon connect: {e}")

    chat = await get_chat(uid)
    if chat:
        await update.message.reply_text(t("partner_found", lang), reply_markup=active_chat_kb(chat['partner_id'], lang)); return

    # Send bottom keyboard
    await update.message.reply_text(
        f"{t('main_menu', lang)}\n\n{t('online_count', lang, n=await online_count())}",
        reply_markup=bottom_kb(lang))
    await update.message.reply_text("👇", reply_markup=await main_menu_kb(lang))


async def connect_users(uid, target, context, lang):
    if uid == target:
        await context.bot.send_message(uid, "❌ Cannot connect to self."); return
    async with db_pool.acquire() as c:
        t_u = await c.fetchrow("SELECT user_id FROM users WHERE user_id=$1 AND is_banned=FALSE", target)
        if not t_u:
            await context.bot.send_message(uid, "❌ User not found."); return
        blocked = await c.fetchrow("""SELECT 1 FROM blocks WHERE
            (blocker_id=$1 AND blocked_id=$2) OR (blocker_id=$2 AND blocked_id=$1)""", uid, target)
        if blocked:
            await context.bot.send_message(uid, "❌ Cannot connect."); return
        await c.execute("""INSERT INTO active_chats (user_id,partner_id) VALUES ($1,$2),($2,$1)
            ON CONFLICT (user_id) DO UPDATE SET partner_id=EXCLUDED.partner_id, started_at=NOW(), is_ai=FALSE""", uid, target)
        await c.execute("UPDATE users SET total_chats=total_chats+1 WHERE user_id IN ($1,$2)", uid, target)
        await c.execute("INSERT INTO chat_log (user_id,partner_id) VALUES ($1,$2)", uid, target)
    
    pl = await get_lang(target)
    try: await context.bot.send_message(uid, t("partner_found", lang), reply_markup=active_chat_kb(target, lang))
    except: pass
    try: await context.bot.send_message(target, t("partner_found", pl), reply_markup=active_chat_kb(uid, pl))
    except: pass
    
    context.job_queue.run_once(timer_end, CHAT_TIMER, data={'user_id': uid}, name=f"end1_{uid}")
    context.job_queue.run_once(timer_end, CHAT_TIMER, data={'user_id': target}, name=f"end2_{target}")


# ========== LANGUAGE ==========
async def language_callback(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    lang = q.data.replace("lang_", "")
    if lang not in ("bn","en","hi","ru"): lang = "en"
    await set_lang(uid, lang)
    prof = await get_profile(uid)
    if prof and prof.get('display_name'):
        # Already registered — go to menu
        anon_t = context.user_data.pop('anon_target', None)
        if anon_t:
            try: await connect_users(uid, anon_t, context, lang); return
            except: pass
        try:
            await q.edit_message_text(t("lang_set", lang),
                reply_markup=await main_menu_kb(lang))
        except:
            try: await q.message.reply_text(t("lang_set", lang), reply_markup=await main_menu_kb(lang))
            except: pass
        return
    context.user_data['reg_step'] = 'age_gate'
    await q.edit_message_text(t("welcome", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("age_yes", lang), callback_data="age_yes")],
            [InlineKeyboardButton(t("age_no", lang), callback_data="age_no")]]))


async def change_language(update, context):
    q = update.callback_query; await q.answer()
    try:
        await q.edit_message_text(t("language_select", "en"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
                 InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
                [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
                 InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]]))
    except:
        try: await q.message.reply_text(t("language_select", "en"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
                 InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
                [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
                 InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]]))
        except: pass


async def age_gate_callback(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    if q.data == "age_yes":
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET is_18_plus=TRUE WHERE user_id=$1", uid)
        context.user_data['reg_step'] = 'name'
        await q.edit_message_text(t("ask_name", lang))
    else:
        await q.edit_message_text(t("age_denied", lang))


# ========== REG CALLBACKS ==========
async def gender_cb(update, context):
    q = update.callback_query; await q.answer()
    g = q.data.split("_")[1]; uid = q.from_user.id; lang = await get_lang(uid)
    await save_profile(uid, gender=g)
    context.user_data['reg_step'] = 'pref_gender'
    await q.edit_message_text(t("ask_pref", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("male", lang), callback_data="pref_male"),
             InlineKeyboardButton(t("female", lang), callback_data="pref_female")],
            [InlineKeyboardButton(t("any", lang), callback_data="pref_any")]]))


async def pref_gender_cb(update, context):
    q = update.callback_query; await q.answer()
    p = q.data.split("_")[1]; uid = q.from_user.id; lang = await get_lang(uid)
    await save_profile(uid, pref_gender=p)
    context.user_data['reg_step'] = 'interest'
    await q.edit_message_text(t("ask_interest", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Music", callback_data="int_music"),
             InlineKeyboardButton("🎬 Movie", callback_data="int_movie")],
            [InlineKeyboardButton("📚 Study", callback_data="int_study"),
             InlineKeyboardButton("🎮 Gaming", callback_data="int_gaming")],
            [InlineKeyboardButton("💕 Love", callback_data="int_love"),
             InlineKeyboardButton("🌍 Any", callback_data="int_any")]]))


async def interest_cb(update, context):
    q = update.callback_query; await q.answer()
    i = q.data.split("_")[1]; uid = q.from_user.id; lang = await get_lang(uid)
    await save_profile(uid, interest=i)
    context.user_data['reg_step'] = 'pref_language'
    await q.edit_message_text(t("ask_pref", lang) + " (Language)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 Bangla", callback_data="plang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="plang_en")],
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="plang_hi"),
             InlineKeyboardButton("🌍 Any", callback_data="plang_any")]]))


async def pref_lang_cb(update, context):
    q = update.callback_query; await q.answer()
    pl = q.data.split("_")[1]; uid = q.from_user.id; lang = await get_lang(uid)
    await save_profile(uid, pref_language=pl)
    context.user_data['reg_step'] = 'bio'
    await q.edit_message_text(t("ask_bio", lang))


# ========== TEXT HANDLER ==========
async def handle_text(update, context):
    uid = update.effective_user.id
    await touch(uid)
    if await is_banned(uid):
        await update.message.reply_text("🚫 Banned."); return
    lang = await get_lang(uid)
    step = context.user_data.get('reg_step')
    text = update.message.text.strip() if update.message.text else ""

    # Payment proof
    if context.user_data.get('awaiting_payment'):
        tier = context.user_data.get('payment_tier', 'bronze')
        method = context.user_data.get('payment_method', 'unknown')
        for aid in ADMIN_IDS:
            try:
                await context.bot.forward_message(chat_id=aid, from_chat_id=uid, message_id=update.message.message_id)
                await context.bot.send_message(aid,
                    f"💰 Payment\n👤 {update.effective_user.full_name}\n🆔 `{uid}`\n📦 {tier}\n💳 {method}\n\n"
                    f"Approve: `/approve {uid} {tier}`")
            except: pass
        async with db_pool.acquire() as c:
            await c.execute("INSERT INTO payments (user_id,tier,method,transaction_id,status) VALUES ($1,$2,$3,$4,'pending')",
                            uid, tier, method, text[:200])
        await update.message.reply_text("✅ Sent to admin. Verify in 5-10 min.")
        for k in ['awaiting_payment','payment_tier','payment_method']: context.user_data.pop(k, None)
        return

    # Support
    if context.user_data.get('awaiting_support'):
        async with db_pool.acquire() as c:
            await c.execute("INSERT INTO support_tickets (user_id,message) VALUES ($1,$2)", uid, text)
        for aid in ADMIN_IDS:
            try: await context.bot.send_message(aid, f"🎫 Ticket\n👤 `{uid}`\n📝 {text[:400]}\n\nReply: `/reply_ticket <id> <msg>`")
            except: pass
        await update.message.reply_text(t("support_sent", lang))
        context.user_data.pop('awaiting_support', None); return

    # Custom city input
    if context.user_data.get('awaiting_city'):
        await set_city(uid, text[:50])
        await update.message.reply_text(f"✅ City: {text[:50]}")
        context.user_data.pop('awaiting_city', None); return

    # Registration
    if step == 'name':
        if len(text) < 2 or len(text) > 50:
            await update.message.reply_text("⚠️ 2-50 chars"); return
        await save_profile(uid, display_name=text)
        context.user_data['reg_step'] = 'age'
        await update.message.reply_text(t("ask_age", lang)); return

    if step == 'age':
        if not text.isdigit() or int(text) < 18 or int(text) > 99:
            await update.message.reply_text("⚠️ 18-99"); return
        await save_profile(uid, age=int(text))
        context.user_data['reg_step'] = 'gender'
        await update.message.reply_text(t("ask_gender", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("male", lang), callback_data="gender_male"),
                 InlineKeyboardButton(t("female", lang), callback_data="gender_female")],
                [InlineKeyboardButton(t("other", lang), callback_data="gender_other")]]))
        return

    if step == 'bio':
        await save_profile(uid, bio=text[:200])
        context.user_data['reg_step'] = 'city'
        await update.message.reply_text(t("ask_city", lang)); return

    if step == 'city':
        await set_city(uid, text[:50])
        context.user_data['reg_step'] = None
        anon_t = context.user_data.pop('anon_target', None)
        if anon_t:
            try: await connect_users(uid, anon_t, context, lang); return
            except: pass
        await update.message.reply_text("✅ Registration complete! 🎉", reply_markup=bottom_kb(lang))
        await update.message.reply_text(t("main_menu", lang), reply_markup=await main_menu_kb(lang))
        return

    if step in ('gender','pref_gender','interest','pref_language'):
        await update.message.reply_text("⚠️ Use buttons"); return

    # Edit profile
    es = context.user_data.get('edit_step')
    if es:
        if es == 'name': await save_profile(uid, display_name=text[:50])
        elif es == 'bio': await save_profile(uid, bio=text[:200])
        elif es == 'birthday':
            try:
                bd = datetime.strptime(text, "%d-%m-%Y").date()
                async with db_pool.acquire() as c:
                    await c.execute("UPDATE users SET birthday=$1 WHERE user_id=$2", bd, uid)
                await update.message.reply_text("✅ Birthday saved!")
            except: await update.message.reply_text("❌ Use DD-MM-YYYY")
        context.user_data.pop('edit_step', None)
        await update.message.reply_text(t("profile_saved", lang))
        return

    # Bottom keyboard buttons
    if text == t("new_chat", lang) or text == "🌹 New Anonymous Chat!":
        await newchat_cmd(update, context); return
    if text == t("browse_people", lang) or text == "💥 Browse People":
        await browse_people(update, context); return
    if text == t("nearby_people", lang) or text == "📍 Nearby People":
        await nearby_people(update, context); return

    # Chat
    await chat_relay(update, context)


# ========== /NEWCHAT ==========
async def newchat_cmd(update, context):
    """MeChat-style /newchat — show Random/Guy/Girl choices."""
    if update.callback_query:
        uid = update.callback_query.from_user.id
        try: await update.callback_query.answer()
        except: pass
        q = update.callback_query
    else:
        uid = update.message.from_user.id
        q = None
    lang = await get_lang(uid)
    prof = await get_profile(uid)
    if not prof:
        text = t("reg_first", lang)
        if q: await q.message.reply_text(text)
        else: await update.message.reply_text(text)
        return
    ex = await get_chat(uid)
    if ex:
        text = t("already_in_chat", lang)
        kb = active_chat_kb(ex['partner_id'], lang)
        if q: await q.message.reply_text(text, reply_markup=kb)
        else: await update.message.reply_text(text, reply_markup=kb)
        return
    
    text = "💗 Choose who you want to chat with 👇"
    kb = newchat_kb(lang)
    try:
        if q: await q.edit_message_text(text, reply_markup=kb)
        else: await update.message.reply_text(text, reply_markup=kb)
    except:
        if q: await q.message.reply_text(text, reply_markup=kb)
        else: await update.message.reply_text(text, reply_markup=kb)


# ========== SEARCH (with coin deduction) ==========
async def search_random(update, context):
    await do_search(update, context, "random")

async def search_guy(update, context):
    await do_search(update, context, "male")

async def search_girl(update, context):
    await do_search(update, context, "female")


async def do_search(update, context, mode):
    """mode: 'random', 'male', 'female'"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    await touch(uid)
    lang = await get_lang(uid)
    
    prof = await get_profile(uid)
    if not prof:
        await safe_edit(q, t("reg_first", lang)); return
    
    ex = await get_chat(uid)
    if ex:
        await safe_edit(q, t("already_in_chat", lang), active_chat_kb(ex['partner_id'], lang)); return

    # Coin check for gender-specific
    if mode in ("male", "female"):
        coins = await get_coins(uid)
        if coins < COINS_PER_GENDER_MATCH:
            await safe_edit(q,
                t("need_coins", lang, n=COINS_PER_GENDER_MATCH, have=coins),
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 Invite", callback_data="show_link")],
                    [InlineKeyboardButton("💰 Top-Up", callback_data="coins_topup")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
            return

    # Daily limit
    if not await is_vip(uid):
        async with db_pool.acquire() as c:
            r = await c.fetchrow("SELECT chats_today,chats_today_date FROM users WHERE user_id=$1", uid)
            today = datetime.now().date()
            if r and r['chats_today_date'] == today and (r['chats_today'] or 0) >= MAX_FREE_CHATS:
                await safe_edit(q, t("chat_limit", lang),
                    InlineKeyboardMarkup([[InlineKeyboardButton("⭐ VIP", callback_data="show_vip")]]))
                return
            if not r or r['chats_today_date'] != today:
                await c.execute("UPDATE users SET chats_today=1,chats_today_date=$1 WHERE user_id=$2", today, uid)
            else:
                await c.execute("UPDATE users SET chats_today=chats_today+1 WHERE user_id=$1", uid)

    # Deduct coins for gender-specific
    if mode in ("male", "female"):
        ok = await deduct_coins(uid, COINS_PER_GENDER_MATCH)
        if not ok:
            await safe_edit(q, t("need_coins", lang, n=COINS_PER_GENDER_MATCH, have=0)); return

    g = prof.get('gender') or 'any'
    pg = mode if mode in ("male","female") else (prof.get('pref_gender') or 'any')
    it = prof.get('interest') or 'any'
    pl = prof.get('pref_language') or 'any'
    ag = prof.get('age') or 18
    mi = prof.get('min_age') or 18
    ma = prof.get('max_age') or 99
    vip = await is_vip(uid)
    same_age = await get_same_age(uid)

    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM match_queue WHERE user_id=$1", uid)
        rows = await c.fetch("""SELECT mq.* FROM match_queue mq WHERE mq.user_id!=$1
            AND NOT EXISTS (SELECT 1 FROM blocks WHERE (blocker_id=$1 AND blocked_id=mq.user_id)
            OR (blocker_id=mq.user_id AND blocked_id=$1))
            ORDER BY mq.is_vip DESC, mq.queued_at ASC LIMIT 50""", uid)
        cands = [dict(r) for r in rows]

    def score(c):
        s = 0
        if pg != 'any' and c['gender'] != pg: return -1
        if c['pref_gender'] != 'any' and c['pref_gender'] != g: return -1
        s += 15
        ca = c['age'] or 18
        if ca < mi or ca > ma: return -1
        cmi = c['min_age'] or 18
        cma = c['max_age'] or 99
        if ag < cmi or ag > cma: return -1
        if same_age and abs(ca - ag) > 2: return -1
        if same_age: s += 10
        if it != 'any' and c['interest'] == it: s += 5
        if pl != 'any' and c['pref_language'] == pl: s += 3
        if c['is_vip']: s += 2
        return s

    best, bs = None, -1
    for c in cands:
        sc = score(c)
        if sc > bs: best, bs = c, sc

    if best and bs >= 10:
        pid = best['user_id']
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM match_queue WHERE user_id=$1", pid)
            await c.execute("""INSERT INTO active_chats (user_id,partner_id) VALUES ($1,$2),($2,$1)
                ON CONFLICT (user_id) DO UPDATE SET partner_id=EXCLUDED.partner_id, started_at=NOW(), is_ai=FALSE""", uid, pid)
            await c.execute("UPDATE users SET total_chats=total_chats+1 WHERE user_id IN ($1,$2)", uid, pid)
            await c.execute("INSERT INTO chat_log (user_id,partner_id) VALUES ($1,$2)", uid, pid)

        lvl = await add_xp(uid, 10)
        await mission_prog(uid, "chat_3", 1)
        if lvl:
            try: await q.message.reply_text(t("level_up", lang, level=lvl))
            except: pass
        await check_ach(uid, context)

        pl2 = await get_lang(pid)
        await safe_edit(q, t("partner_found", lang), active_chat_kb(pid, lang))
        try: await context.bot.send_message(pid, t("partner_found", pl2), reply_markup=active_chat_kb(uid, pl2))
        except: pass

        reward = 2 if vip else 1
        await add_coins(uid, reward)
        timer = CHAT_TIMER*2 if vip else CHAT_TIMER
        context.job_queue.run_once(timer_end, timer, data={'user_id': uid}, name=f"end1_{uid}")
        context.job_queue.run_once(timer_end, timer, data={'user_id': pid}, name=f"end2_{pid}")
    else:
        async with db_pool.acquire() as c:
            await c.execute("""INSERT INTO match_queue (user_id,gender,pref_gender,pref_language,interest,is_vip,age,min_age,max_age,same_age)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (user_id) DO UPDATE SET
                queued_at=NOW(), is_vip=EXCLUDED.is_vip, pref_gender=EXCLUDED.pref_gender,
                pref_language=EXCLUDED.pref_language, interest=EXCLUDED.interest,
                gender=EXCLUDED.gender, age=EXCLUDED.age, min_age=EXCLUDED.min_age,
                max_age=EXCLUDED.max_age, same_age=EXCLUDED.same_age""",
                uid, g, pg, pl, it, vip, ag, mi, ma, same_age)
        sa = "🟢 ON" if same_age else "⚪ OFF"
        text = t("searching", lang, sa=sa)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⚙️ Same Age: {sa}", callback_data="toggle_sa")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
            [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]])
        await safe_edit(q, text, kb)
        jn = f"queue_timeout_{uid}"
        for j in context.job_queue.get_jobs_by_name(jn): j.schedule_removal()
        context.job_queue.run_once(queue_timeout, QUEUE_TIMEOUT, data={'user_id': uid}, name=jn)


async def safe_edit(q, text, reply_markup=None):
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except:
        try:
            if q.message:
                await q.message.reply_text(text, reply_markup=reply_markup)
        except: pass


async def toggle_sa(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    new = await toggle_same_age(uid)
    sa = "🟢 ON" if new else "⚪ OFF"
    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⚙️ Same Age: {sa}", callback_data="toggle_sa")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
            [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    except: pass
    await q.answer(t("same_age_on", lang) if new else t("same_age_off", lang), show_alert=False)


async def cancel_search(update, context):
    q = update.callback_query; await q.answer("Cancelled")
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM match_queue WHERE user_id=$1", uid)
    for j in context.job_queue.get_jobs_by_name(f"queue_timeout_{uid}"): j.schedule_removal()
    try:
        await q.edit_message_text(f"{t('search_cancelled', lang)}\n\n{t('online_count', lang, n=await online_count())}",
                                  reply_markup=await main_menu_kb(lang))
    except: pass


async def queue_timeout(ctx):
    uid = ctx.job.data['user_id']
    lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        still = await c.fetchrow("SELECT 1 FROM match_queue WHERE user_id=$1", uid)
        active = await c.fetchrow("SELECT 1 FROM active_chats WHERE user_id=$1", uid)
    if still and not active:
        try:
            await ctx.bot.send_message(uid, t("no_partner_ai", lang),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
        except: pass


async def timer_end(ctx):
    uid = ctx.job.data['user_id']
    lang = await get_lang(uid)
    chat = await get_chat(uid)
    if not chat: return
    pid = chat['partner_id']; is_ai = chat.get('is_ai', False)
    await remove_chat(uid, pid)
    try:
        await ctx.bot.send_message(uid, t("chat_ended", lang), reply_markup=await main_menu_kb(lang))
        if not is_ai:
            pl = await get_lang(pid)
            await ctx.bot.send_message(pid, t("chat_ended", pl), reply_markup=await main_menu_kb(pl))
    except: pass


# ========== AI CHAT ==========
async def ai_chat_start(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    if not groq_client:
        await q.answer("AI off", show_alert=True); return
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM match_queue WHERE user_id=$1", uid)
        await c.execute("""INSERT INTO active_chats (user_id,partner_id,is_ai) VALUES ($1,$1,TRUE)
            ON CONFLICT (user_id) DO UPDATE SET partner_id=$1, is_ai=TRUE, started_at=NOW()""", uid)
    context.user_data['ai_history'] = []
    await safe_edit(q, t("ai_mode", lang),
        InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="end_chat")]]))


# ========== CHAT RELAY ==========
async def chat_relay(update, context):
    uid = update.effective_user.id
    lang = await get_lang(uid)
    chat = await get_chat(uid)
    if not chat: return
    if rate_limited(uid, 20, 10):
        await update.message.reply_text("⏳ Wait."); return
    if update.message.text and bad_words(update.message.text):
        await update.message.reply_text(t("spam_warn", lang)); return
    await add_xp(uid, 1)
    await mission_prog(uid, "msg_20", 1)
    if chat.get('is_ai'):
        await handle_ai_msg(update, context, lang); return
    pid = chat['partner_id']
    rid = context.user_data.get('room_id')
    if rid:
        await relay_group(update, context, rid); return
    vrid = context.user_data.get('voice_room_id')
    if vrid:
        await relay_voice(update, context, vrid); return
    try:
        await context.bot.copy_message(chat_id=pid, from_chat_id=uid,
            message_id=update.message.message_id)
    except Exception as e: logger.error(f"copy: {e}")


async def handle_ai_msg(update, context, lang):
    uid = update.effective_user.id
    text = update.message.text or ""
    if not text or bad_words(text): return
    typing = await update.message.reply_text("🤖...")
    hist = context.user_data.get('ai_history', [])
    hist.append({"role": "user", "content": text})
    sys = "You are a friendly anonymous chat partner. Reply in user's language. Short replies under 300 chars. Warm, funny. Use emojis."
    ans = None
    for m in AI_MODELS:
        try:
            r = await asyncio.to_thread(groq_client.chat.completions.create,
                model=m, messages=[{"role":"system","content":sys}] + hist[-10:],
                temperature=0.8, max_tokens=400)
            ans = r.choices[0].message.content.strip(); break
        except: continue
    if not ans:
        await typing.edit_text("🤖 Busy, try later."); return
    hist.append({"role": "assistant", "content": ans})
    context.user_data['ai_history'] = hist[-10:]
    await typing.edit_text(ans)


# ========== END CHAT / NEXT ==========
async def end_chat_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    chat = await get_chat(uid)
    if not chat:
        await safe_edit(q, t("not_in_chat", lang), await main_menu_kb(lang)); return
    pid = chat['partner_id']; is_ai = chat.get('is_ai', False)
    await remove_chat(uid, pid)
    async with db_pool.acquire() as c:
        await c.execute("UPDATE chat_log SET ended_at=NOW() WHERE user_id=$1 AND ended_at IS NULL", uid)
    for n in [f"end1_{uid}", f"end2_{uid}", f"end1_{pid}", f"end2_{pid}"]:
        for j in context.job_queue.get_jobs_by_name(n): j.schedule_removal()
    await safe_edit(q, t("chat_ended", lang), await main_menu_kb(lang))
    if not is_ai:
        try:
            pl = await get_lang(pid)
            await context.bot.send_message(pid, t("partner_ended", pl), reply_markup=await main_menu_kb(pl))
        except: pass


async def delete_msgs_cb(update, context):
    q = update.callback_query; await q.answer()
    lang = await get_lang(q.from_user.id)
    await q.answer(t("msgs_deleted", lang), show_alert=True)


async def secure_chat_cb(update, context):
    q = update.callback_query; await q.answer()
    lang = await get_lang(q.from_user.id)
    await q.answer("🔐 Secure mode active", show_alert=False)


# ========== PROFILE ==========
async def my_profile(update, context):
    q = update.callback_query
    try: await q.answer()
    except: pass
    try:
        uid = q.from_user.id
        lang = await get_lang(uid)
        prof = await get_profile(uid)
        if not prof:
            await q.message.reply_text(t("reg_first", lang)); return
        st = await get_stats(uid) or {}
        gm = {"male":"👦","female":"👧","other":"🌈"}
        vip = await is_vip(uid); tier = await get_tier(uid) if vip else None
        lvl = st.get('level') or 1
        if lvl < 1: lvl = 1
        nx = LEVELS[lvl] if lvl < len(LEVELS) else 0
        aid = st.get('anon_id') or await get_anon_id(uid)
        text = (
            f"👤 {prof.get('display_name', 'N/A')}\n"
            f"🆔 /{aid}\n"
            f"🎂 Age: {prof.get('age', '?')} {gm.get(prof.get('gender'), '?')}\n"
            f"🏙️ City: {st.get('city') or 'N/A'}\n"
            f"• Number of likes: {st.get('likes_received') or 0}\n"
            f"👀 Profile views: {st.get('profile_views') or 0}\n"
            f"💡 Interest: {prof.get('interest', 'any')}\n"
            f"📈 Lv{lvl} • XP {st.get('xp') or 0}/{nx}\n"
            f"🪙 Coins: {st.get('coins') or 0}\n"
            f"🔥 Streak: {st.get('streak') or 0}\n"
            f"💬 Chats: {st.get('total_chats') or 0}\n"
            f"⭐ {tier or 'Free'}\n\n"
            f"💬 {(prof.get('bio') or 'N/A')[:150]}"
        )
        try:
            await q.edit_message_text(text, reply_markup=profile_kb(lang))
        except:
            await q.message.reply_text(text, reply_markup=profile_kb(lang))
    except Exception as e:
        logger.error(f"my_profile: {e}")


async def view_likers(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    likers = await get_likers(uid, 20)
    if not likers:
        await safe_edit(q, t("no_likers", lang), await main_menu_kb(lang)); return
    text = f"👀 {t('view_likers', lang)}\n\n"
    for l in likers:
        aid = l.get('anon_id') or f"user_{l['liker_id']}"
        nm = l.get('display_name') or "Anonymous"
        text += f"• {nm} (@{aid})\n"
    await safe_edit(q, text[:4000], await main_menu_kb(lang))


async def show_blocked(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    blocked = await get_blocked(uid)
    if not blocked:
        await safe_edit(q, t("no_blocked", lang), await main_menu_kb(lang)); return
    rows = []
    for b in blocked[:10]:
        nm = b.get('display_name') or f"User {b['blocked_id']}"
        rows.append([InlineKeyboardButton(f"🔓 Unblock {nm[:20]}", callback_data=f"unblock_{b['blocked_id']}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    await safe_edit(q, t("blocked_users", lang), InlineKeyboardMarkup(rows))


async def unblock_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[1])
    except: return
    await unblock_user(uid, pid)
    await q.answer(t("unblocked", lang), show_alert=True)
    await show_blocked(update, context)


async def contact_list_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT f.friend_id,p.display_name,u.anon_id
            FROM friends f LEFT JOIN profiles p ON p.user_id=f.friend_id
            LEFT JOIN users u ON u.user_id=f.friend_id WHERE f.user_id=$1 LIMIT 20""", uid)
    if not rows:
        await safe_edit(q, t("no_contacts", lang), await main_menu_kb(lang)); return
    text = f"🗣️ {t('contact_list', lang)}\n\n"
    for r in rows:
        text += f"• {r['display_name'] or 'Anon'} (@{r['anon_id'] or ''})\n"
    await safe_edit(q, text[:4000], await main_menu_kb(lang))


async def advanced_settings(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    sa = await get_same_age(uid)
    sa_lbl = "🟢 ON" if sa else "⚪ OFF"
    rows = [
        [InlineKeyboardButton(f"⚙️ Same Age: {sa_lbl}", callback_data="toggle_sa_setting")],
        [InlineKeyboardButton("🏙️ Change City", callback_data="choose_city")],
        [InlineKeyboardButton("🎂 Birthday", callback_data="edit_birthday")],
        [InlineKeyboardButton("💎 Coins→Stars", callback_data="coins_to_stars")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
    await safe_edit(q, t("advanced_settings", lang), InlineKeyboardMarkup(rows))


async def toggle_sa_setting(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    new = await toggle_same_age(uid)
    await q.answer(t("same_age_on", lang) if new else t("same_age_off", lang), show_alert=False)
    await advanced_settings(update, context)


async def coins_to_stars_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    coins = await get_coins(uid)
    if coins < COINS_TO_STARS:
        await q.answer(f"Need {COINS_TO_STARS} coins", show_alert=True); return
    stars = coins // COINS_TO_STARS
    ok = await deduct_coins(uid, stars*COINS_TO_STARS)
    if ok:
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET stars_balance=stars_balance+$1 WHERE user_id=$2", stars, uid)
        await q.answer(f"✅ {stars} stars added!", show_alert=True)


async def edit_profile(update, context):
    q = update.callback_query; await q.answer()
    rows = [
        [InlineKeyboardButton("📛 Name", callback_data="edit_name"),
         InlineKeyboardButton("📝 Bio", callback_data="edit_bio")],
        [InlineKeyboardButton("🎯 Pref", callback_data="edit_pref_gender"),
         InlineKeyboardButton("💡 Interest", callback_data="edit_interest")],
        [InlineKeyboardButton("🌐 Lang", callback_data="edit_lang"),
         InlineKeyboardButton("📅 Age Range", callback_data="edit_age_range")],
        [InlineKeyboardButton("🏙️ City", callback_data="choose_city"),
         InlineKeyboardButton("🎂 Birthday", callback_data="edit_birthday")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
    await safe_edit(q, "✏️ Edit Profile:", InlineKeyboardMarkup(rows))


async def edit_name(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['edit_step'] = 'name'
    await safe_edit(q, "✏️ Send new name:")


async def edit_bio(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['edit_step'] = 'bio'
    await safe_edit(q, "✏️ Send new bio:")


async def edit_birthday(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['edit_step'] = 'birthday'
    await safe_edit(q, "🎂 DD-MM-YYYY format:")


async def edit_pref_gender(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    await safe_edit(q, t("ask_pref", lang), InlineKeyboardMarkup([
        [InlineKeyboardButton(t("male", lang), callback_data="setpg_male"),
         InlineKeyboardButton(t("female", lang), callback_data="setpg_female")],
        [InlineKeyboardButton(t("any", lang), callback_data="setpg_any")]]))


async def set_pref_gender(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    p = q.data.split("_")[1]
    await save_profile(uid, pref_gender=p)
    await safe_edit(q, t("profile_saved", lang), await main_menu_kb(lang))


async def edit_interest(update, context):
    q = update.callback_query; await q.answer()
    await safe_edit(q, t("ask_interest", "en"), InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 Music", callback_data="setint_music"),
         InlineKeyboardButton("🎬 Movie", callback_data="setint_movie")],
        [InlineKeyboardButton("📚 Study", callback_data="setint_study"),
         InlineKeyboardButton("🎮 Gaming", callback_data="setint_gaming")],
        [InlineKeyboardButton("💕 Love", callback_data="setint_love"),
         InlineKeyboardButton("🌍 Any", callback_data="setint_any")]]))


async def set_interest(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    i = q.data.split("_")[1]
    await save_profile(uid, interest=i)
    await safe_edit(q, t("profile_saved", lang), await main_menu_kb(lang))


async def edit_lang(update, context):
    q = update.callback_query; await q.answer()
    await safe_edit(q, t("ask_pref", "en") + " (Language)", InlineKeyboardMarkup([
        [InlineKeyboardButton("🇧🇩 Bangla", callback_data="setplang_bn"),
         InlineKeyboardButton("🇬🇧 English", callback_data="setplang_en")],
        [InlineKeyboardButton("🇮🇳 Hindi", callback_data="setplang_hi"),
         InlineKeyboardButton("🌍 Any", callback_data="setplang_any")]]))


async def set_plang(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    pl = q.data.split("_")[1]
    await save_profile(uid, pref_language=pl)
    await safe_edit(q, t("profile_saved", lang), await main_menu_kb(lang))


async def edit_age_range(update, context):
    q = update.callback_query; await q.answer()
    await safe_edit(q, "📅 Age Range:", InlineKeyboardMarkup([
        [InlineKeyboardButton("18-25", callback_data="setage_18_25"),
         InlineKeyboardButton("25-35", callback_data="setage_25_35")],
        [InlineKeyboardButton("35-50", callback_data="setage_35_50"),
         InlineKeyboardButton("18-99", callback_data="setage_18_99")]]))


async def set_age(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    parts = q.data.replace("setage_", "").split("_")
    await save_profile(uid, min_age=int(parts[0]), max_age=int(parts[1]))
    await safe_edit(q, t("profile_saved", lang), await main_menu_kb(lang))


# ========== CITY ==========
async def choose_city_cb(update, context):
    q = update.callback_query; await q.answer()
    lang = await get_lang(q.from_user.id)
    await safe_edit(q, t("choose_city", lang), city_kb(lang))


async def set_city_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: city = q.data.replace("setcity_", "")[:50]
    except: return
    await set_city(uid, city)
    await q.answer(f"✅ {city}", show_alert=True)


async def custom_city_cb(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['awaiting_city'] = True
    await safe_edit(q, "✏️ Type your city name:")


# ========== VIEW PROFILE ==========
async def view_profile_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[1])
    except: return
    await record_view(uid, pid)
    try:
        pl = await get_lang(pid)
        await context.bot.send_message(pid, t("partner_viewed", pl))
    except: pass
    prof = await get_profile(pid)
    st = await get_stats(pid)
    if not prof:
        await q.answer("Profile not found", show_alert=True); return
    gm = {"male":"👦","female":"👧","other":"🌈"}
    aid = (st or {}).get('anon_id') or f"user_{pid}"
    text = (
        f"👤 {prof.get('display_name', 'Anon')}\n"
        f"🆔 /{aid}\n"
        f"🎂 {prof.get('age', '?')} {gm.get(prof.get('gender'), '?')}\n"
        f"🏙️ {(st or {}).get('city') or 'N/A'}\n"
        f"💡 {prof.get('interest', 'any')}\n"
        f"❤️ Likes: {(st or {}).get('likes_received', 0)}\n"
        f"👀 Views: {(st or {}).get('profile_views', 0)}\n"
        f"⭐ {'Premium' if (st or {}).get('is_vip') else 'Free'}\n\n"
        f"💬 {(prof.get('bio') or 'N/A')[:200]}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Like", callback_data=f"like_{pid}"),
         InlineKeyboardButton("💬 Message", callback_data=f"msg_{pid}")],
        [InlineKeyboardButton("🚫 Block", callback_data=f"block_{pid}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]])
    try: await q.edit_message_text(text, reply_markup=kb)
    except: await q.message.reply_text(text, reply_markup=kb)


async def like_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[1])
    except: return
    ok = await add_like(uid, pid)
    if ok:
        await q.answer(t("liked_success", lang), show_alert=False)
        await mission_prog(uid, "like_3", 1)
        try:
            pl = await get_lang(pid)
            await context.bot.send_message(pid, t("liked_you", pl))
        except: pass
    else:
        await q.answer(t("already_liked", lang), show_alert=False)


async def msg_user_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[1])
    except: return
    await connect_users(uid, pid, context, lang)


async def block_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[1])
    except: return
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO blocks (blocker_id,blocked_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, pid)
        await c.execute("DELETE FROM active_chats WHERE user_id=$1 OR user_id=$2", uid, pid)
    await q.answer("✅ Blocked", show_alert=True)


async def add_friend_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; fid = int(q.data.split("_")[1])
    if uid == fid:
        await q.answer("Cannot add self", show_alert=True); return
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO friends (user_id,friend_id) VALUES ($1,$2),($2,$1) ON CONFLICT DO NOTHING", uid, fid)
    await q.answer("✅ Friend added!", show_alert=True)


# ========== BROWSE / NEARBY ==========
async def browse_people(update, context):
    if update.callback_query:
        q = update.callback_query
        try: await q.answer()
        except: pass
        uid = q.from_user.id
    else:
        uid = update.message.from_user.id
        q = None
    lang = await get_lang(uid)
    users = await browse_people_db(uid, 10)
    if not users:
        text = t("no_users", lang)
        kb = await main_menu_kb(lang)
        if q: await safe_edit(q, text, kb)
        else: await update.message.reply_text(text, reply_markup=kb)
        return
    rows = []
    for u in users:
        aid = u.get('anon_id') or f"user_{u['user_id']}"
        nm = u.get('display_name') or "Anon"
        v = "✅" if u.get('is_verified') else ""
        rows.append([InlineKeyboardButton(f"{v} {nm} (@{aid})", callback_data=f"viewprof_{u['user_id']}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    text = t("browse_title", lang)
    if q: await safe_edit(q, text, InlineKeyboardMarkup(rows))
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def browse_people_db(uid, limit=10):
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT u.user_id, u.anon_id, u.city, u.is_verified,
            p.display_name, p.age, p.gender FROM users u
            LEFT JOIN profiles p ON p.user_id=u.user_id
            WHERE u.user_id!=$1 AND u.is_banned=FALSE AND p.display_name IS NOT NULL
            AND u.last_active > NOW() - INTERVAL '1 hour'
            ORDER BY u.last_active DESC LIMIT $2""", uid, limit)
        return [dict(r) for r in rows]


async def nearby_people(update, context):
    if update.callback_query:
        q = update.callback_query
        try: await q.answer()
        except: pass
        uid = q.from_user.id
    else:
        uid = update.message.from_user.id
        q = None
    lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        city = await c.fetchval("SELECT city FROM users WHERE user_id=$1", uid)
    if not city:
        text = t("choose_city", lang)
        kb = city_kb(lang)
        if q: await safe_edit(q, text, kb)
        else: await update.message.reply_text(text, reply_markup=kb)
        return
    users = await nearby_people_db(uid, 10)
    if not users:
        text = t("no_users", lang)
        kb = await main_menu_kb(lang)
        if q: await safe_edit(q, text, kb)
        else: await update.message.reply_text(text, reply_markup=kb)
        return
    rows = []
    for u in users:
        aid = u.get('anon_id') or f"user_{u['user_id']}"
        nm = u.get('display_name') or "Anon"
        rows.append([InlineKeyboardButton(f"📍 {nm} ({u.get('city', '')})", callback_data=f"viewprof_{u['user_id']}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    text = t("nearby_title", lang, city=city)
    if q: await safe_edit(q, text, InlineKeyboardMarkup(rows))
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def nearby_people_db(uid, limit=10):
    async with db_pool.acquire() as c:
        city = await c.fetchval("SELECT city FROM users WHERE user_id=$1", uid)
        if not city: return []
        rows = await c.fetch("""SELECT u.user_id, u.anon_id, u.city, u.is_verified,
            p.display_name, p.age FROM users u
            LEFT JOIN profiles p ON p.user_id=u.user_id
            WHERE u.user_id!=$1 AND u.city=$2 AND u.is_banned=FALSE
            AND u.last_active > NOW() - INTERVAL '1 hour' AND p.display_name IS NOT NULL
            ORDER BY u.last_active DESC LIMIT $3""", uid, city, limit)
        return [dict(r) for r in rows]


# ========== ANON LINK ==========
async def show_anon_link(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    code = await get_anon_link(uid)
    if not code:
        await q.answer("Error", show_alert=True); return
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=anon_{code}"
    await safe_edit(q, t("anon_link_msg", lang, link=link),
        InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def link_anon_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    code = await get_anon_link(uid)
    if not code:
        await update.message.reply_text("Error"); return
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=anon_{code}"
    await update.message.reply_text(t("anon_link_msg", lang, link=link))


# ========== GAMES ==========
async def tod_start(update, context):
    q = update.callback_query; await q.answer()
    await safe_edit(q, "🎲 Truth or Dare:",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Truth", callback_data="tod_truth"),
             InlineKeyboardButton("🔥 Dare", callback_data="tod_dare")],
            [InlineKeyboardButton("🎲 Random", callback_data="tod_random")]]))


async def tod_truth_cb(update, context):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(f"🎯 Truth:\n\n{random.choice(TRUTHS)}")


async def tod_dare_cb(update, context):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(f"🔥 Dare:\n\n{random.choice(DARES)}")


async def tod_random_cb(update, context):
    q = update.callback_query; await q.answer()
    if random.random() > 0.5: await tod_truth_cb(update, context)
    else: await tod_dare_cb(update, context)


async def ice_breaker(update, context):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(f"🧊 {random.choice(ICE_BREAKERS)}")


async def compat(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    chat = await get_chat(uid)
    if not chat or chat.get('is_ai'):
        await q.answer("No partner", show_alert=True); return
    pid = chat['partner_id']
    p1 = await get_profile(uid); p2 = await get_profile(pid)
    if not p1 or not p2:
        await q.answer("No data", show_alert=True); return
    s = 0
    if p1.get('interest') == p2.get('interest') and p1.get('interest') != 'any': s += 40
    if p1.get('pref_language') == p2.get('pref_language'): s += 20
    if abs((p1.get('age') or 25) - (p2.get('age') or 25)) <= 5: s += 20
    if p1.get('gender') == p2.get('pref_gender') or p2.get('pref_gender') == 'any': s += 20
    s = min(s, 100)
    bar = "🟩"*(s//10) + "⬜"*(10-s//10)
    await q.message.reply_text(f"💯 Compatibility: {s}%\n\n{bar}")


async def chat_summary(update, context):
    q = update.callback_query; await q.answer()
    if not groq_client:
        await q.answer("AI off", show_alert=True); return
    await q.message.reply_text("📝 Chat Summary:\n\nFriendly chat session ended. Nice talking!")


# ========== REPORT ==========
async def report_cb(update, context):
    q = update.callback_query; await q.answer()
    try: pid = int(q.data.split("_")[1])
    except: return
    reasons = [("Spam","spam"),("Harass","harass"),("Scam","scam"),
               ("Fake","fake"),("18-","under"),("Other","other")]
    rows = [[InlineKeyboardButton(r[0], callback_data=f"rpr_{r[1]}_{pid}")] for r in reasons]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="end_chat")])
    await safe_edit(q, "⚠️ Report reason:", InlineKeyboardMarkup(rows))


async def report_reason_cb(update, context):
    q = update.callback_query; await q.answer()
    parts = q.data.split("_")
    reason = parts[1]; rid = int(parts[2])
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO reports (reporter_id,reported_id,reason) VALUES ($1,$2,$3)", uid, rid, reason)
        await c.execute("INSERT INTO blocks (blocker_id,blocked_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, rid)
        await c.execute("DELETE FROM active_chats WHERE user_id=$1 OR user_id=$2", uid, rid)
        uniq = await c.fetchval("SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE reported_id=$1 AND status='pending'", rid)
        if uniq and uniq >= AUTO_BAN_COUNT:
            await c.execute("UPDATE users SET is_banned=TRUE WHERE user_id=$1", rid)
            await c.execute("UPDATE reports SET status='actioned' WHERE reported_id=$1", rid)
            for aid in ADMIN_IDS:
                try: await context.bot.send_message(aid, f"🚨 Auto-Ban {rid}")
                except: pass
    await safe_edit(q, t("report_blocked", lang), await main_menu_kb(lang))


# ========== ACH / MISSIONS / LEADERBOARD ==========
async def show_achievements(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    unlocked = await user_ach(uid)
    text = f"🏅 {t('achievements_title', lang) if 'achievements_title' in STRINGS else 'Achievements'}\n\n"
    for k, (e, title) in ACHIEVEMENTS.items():
        text += f"{'✅' if k in unlocked else '🔒'} {e} {title}\n"
    await safe_edit(q, text[:4000], await main_menu_kb(lang))


async def show_missions(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    st = await missions_status(uid)
    text = "🎯 Daily Missions\n\n"
    for k, m in st.items():
        if m['completed']: text += f"✅ {m['text']} — +{m['reward']}\n"
        else: text += f"⏳ {m['text']} ({m['progress']}/{m['target']}) — +{m['reward']}\n"
    await safe_edit(q, text, await main_menu_kb(lang))


async def leaderboard(update, context):
    q = update.callback_query; await q.answer()
    lang = await get_lang(q.from_user.id)
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT u.user_id,p.display_name,u.total_chats,u.xp,u.level
            FROM users u JOIN profiles p ON p.user_id=u.user_id WHERE u.total_chats>0
            ORDER BY u.xp DESC LIMIT 10""")
    if not rows:
        await safe_edit(q, "No data yet.", await main_menu_kb(lang)); return
    text = "🏆 Top Chatters\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        text += f"{m} {r['display_name'] or 'Anon'} — Lv{r['level']} • {r['total_chats']} chats\n"
    await safe_edit(q, text, await main_menu_kb(lang))


# ========== CREDIT / VIP ==========
async def show_credit(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    st = await get_stats(uid) or {}
    vip = await is_vip(uid); tier = await get_tier(uid) if vip else None
    text = t("credit", lang, coins=st.get('coins') or 0,
             stars=st.get('stars_balance') or 0,
             vip=(f"✅ {tier}" if vip else "❌"))
    await safe_edit(q, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Top-Up", callback_data="coins_topup")],
        [InlineKeyboardButton("🎁 Invite", callback_data="show_link")],
        [InlineKeyboardButton("💎 Coins→Stars", callback_data="coins_to_stars")],
        [InlineKeyboardButton("⭐ VIP", callback_data="show_vip")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def coins_topup(update, context):
    q = update.callback_query; await q.answer()
    rows = [
        [InlineKeyboardButton("100 coins — 50৳", callback_data="topup_100")],
        [InlineKeyboardButton("500 coins — 200৳", callback_data="topup_500")],
        [InlineKeyboardButton("2000 coins — 700৳", callback_data="topup_2000")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
    await safe_edit(q, "💰 Coins Top-Up:\n\nSend bKash/Rocket. Admin approves.", InlineKeyboardMarkup(rows))


async def topup_select(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    coins = q.data.split("_")[1]
    price_map = {"100": 50, "500": 200, "2000": 700}
    price = price_map.get(coins, 50)
    context.user_data['awaiting_payment'] = True
    context.user_data['payment_method'] = f"Topup {coins} coins"
    context.user_data['payment_tier'] = f"topup_{coins}"
    await safe_edit(q,
        f"💰 Top-Up {coins} coins = {price}৳\n\n"
        f"Send to:\n`{BKASH_NUMBER}` (bKash)\n`{ROCKET_NUMBER}` (Rocket)\n\n"
        f"Then send TrxID/Screenshot.",
        InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")]]))


async def show_vip(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    if await is_vip(uid):
        tier = await get_tier(uid)
        await safe_edit(q, f"⭐ You're Premium! Tier: {tier}",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
        return
    rows = []
    for k, info in PREMIUM_TIERS.items():
        rows.append([InlineKeyboardButton(f"{info['name']} — {info['price']}৳", callback_data=f"tier_{k}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    text = "💎 Premium Packages:\n\n"
    for k, info in PREMIUM_TIERS.items():
        text += f"{info['name']} — {info['price']}৳ / {info['stars']}⭐\n{info['features']}\n\n"
    await safe_edit(q, text[:4000], InlineKeyboardMarkup(rows))


async def tier_select(update, context):
    q = update.callback_query; await q.answer()
    tier = q.data.replace("tier_", "")
    info = PREMIUM_TIERS.get(tier)
    if not info: return
    context.user_data['payment_tier'] = tier
    text = (f"{info['name']}\n💰 {info['price']}৳ — {info['days']} days\n"
            f"🎁 {info['coins']} coins\n✨ {info['features']}")
    await safe_edit(q, text, InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⭐ {info['stars']} Stars", callback_data=f"stars_{tier}")],
        [InlineKeyboardButton("📱 bKash", callback_data=f"pay_bkash_{tier}"),
         InlineKeyboardButton("📱 Rocket", callback_data=f"pay_rocket_{tier}")],
        [InlineKeyboardButton("💎 Binance", callback_data=f"pay_binance_{tier}")],
        [InlineKeyboardButton("🪙 USDT BSC20", callback_data=f"pay_bsc20_{tier}"),
         InlineKeyboardButton("🪙 USDT TRC20", callback_data=f"pay_trc20_{tier}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def stars_payment(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    tier = q.data.replace("stars_", "")
    info = PREMIUM_TIERS.get(tier)
    if not info: return
    try:
        await context.bot.send_invoice(
            chat_id=uid, title=f"⭐ {info['name']} Premium",
            description=f"{info['days']} days premium",
            payload=f"premium_{tier}_{uid}",
            provider_token="", currency="XTR",
            prices=[LabeledPrice(label=info['name'], amount=info['stars'])])
    except Exception as e:
        logger.error(f"Invoice: {e}")
        await q.answer("❌ Failed", show_alert=True)


async def payment_method(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    parts = q.data.split("_")
    method = parts[1]; tier = parts[2] if len(parts) > 2 else "bronze"
    info = PREMIUM_TIERS.get(tier, PREMIUM_TIERS["bronze"])
    m = {"bkash": (BKASH_NUMBER, "bKash"), "rocket": (ROCKET_NUMBER, "Rocket"),
         "binance": (BINANCE_ID, "Binance Pay"), "bsc20": (USDT_BSC20, "USDT BSC20"),
         "trc20": (USDT_TRC20, "USDT TRC20")}
    if method not in m: return
    num, mname = m[method]
    context.user_data['awaiting_payment'] = True
    context.user_data['payment_method'] = mname
    text = (f"💳 {mname} Payment\n\n📦 {info['name']}\n💰 {info['price']}৳ ({info['days']} days)\n\n"
            f"Send to:\n`{num}`\n\n✅ After sending, send TrxID/Screenshot here.\n\n⏱️ Verify in 5-10 min.")
    await safe_edit(q, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy", callback_data=f"copy_{method}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def copy_num(update, context):
    q = update.callback_query; await q.answer()
    m = q.data.replace("copy_", "")
    nums = {"bkash": BKASH_NUMBER, "rocket": ROCKET_NUMBER, "binance": BINANCE_ID,
            "bsc20": USDT_BSC20, "trc20": USDT_TRC20}
    await q.message.reply_text(f"`{nums.get(m, 'N/A')}`\n\n👇 Tap to copy")


async def cancel_payment(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    for k in ['awaiting_payment','payment_tier','payment_method']: context.user_data.pop(k, None)
    await safe_edit(q, "✅ Cancelled.", await main_menu_kb(lang))


async def precheckout(update, context):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update, context):
    uid = update.effective_user.id
    lang = await get_lang(uid)
    payload = update.message.successful_payment.invoice_payload
    try:
        parts = payload.split("_")
        tier = parts[1] if len(parts) > 1 else "bronze"
        info = PREMIUM_TIERS.get(tier, PREMIUM_TIERS["bronze"])
    except:
        tier = "bronze"; info = PREMIUM_TIERS["bronze"]
    await set_vip(uid, tier, info['days'])
    await add_coins(uid, info['coins'])
    async with db_pool.acquire() as c:
        await c.execute("""INSERT INTO payments (user_id,tier,method,amount_bdt,status,approved_at)
            VALUES ($1,$2,'Telegram Stars',$3,'approved',NOW())""", uid, tier, info['price'])
    await update.message.reply_text(
        f"🎉 Premium activated!\n🌟 {info['name']}\n📅 {info['days']} days\n🪙 +{info['coins']} coins",
        reply_markup=await main_menu_kb(lang))


# ========== INVITE / LINK ==========
async def show_link(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{uid}"
    await safe_edit(q, t("invite_msg", lang, link=link, coins=REFERRAL_REWARD),
        InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def link_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{uid}"
    await update.message.reply_text(t("invite_msg", lang, link=link, coins=REFERRAL_REWARD))


# ========== MENU ==========
async def main_menu_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    context.user_data.pop('roleplay', None)
    await safe_edit(q,
        f"{t('main_menu', lang)}\n\n{t('online_count', lang, n=await online_count())}",
        await main_menu_kb(lang))


async def refresh_online(update, context):
    q = update.callback_query
    lang = await get_lang(q.from_user.id)
    await q.answer(t("online_count", lang, n=await online_count()), show_alert=True)


# ========== SUPPORT ==========
async def support_ticket(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['awaiting_support'] = True
    await safe_edit(q, "🎫 Send your support message:")


async def reply_ticket_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /reply_ticket <id> <msg>"); return
    try:
        tid = int(context.args[0]); msg = " ".join(context.args[1:])
        async with db_pool.acquire() as c:
            r = await c.fetchrow("SELECT user_id FROM support_tickets WHERE ticket_id=$1", tid)
            if not r:
                await update.message.reply_text("❌ Not found"); return
            await c.execute("UPDATE support_tickets SET admin_reply=$1,status='closed' WHERE ticket_id=$2", msg, tid)
        try: await context.bot.send_message(r['user_id'], f"📩 Support Reply:\n\n{msg}")
        except: pass
        await update.message.reply_text("✅ Sent")
    except Exception as e: await update.message.reply_text(f"❌ {e}")


# ========== GROUP ROOMS ==========
async def group_menu(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        rooms = await c.fetch("""SELECT r.room_id,r.name,COUNT(m.user_id) cnt
            FROM group_rooms r LEFT JOIN group_members m ON m.room_id=r.room_id
            WHERE r.is_active=TRUE GROUP BY r.room_id,r.name
            HAVING COUNT(m.user_id) < $1 ORDER BY r.room_id DESC LIMIT 5""", GROUP_ROOM_MAX)
    rows = []
    for r in rooms:
        nm = r['name'] or f"Room {r['room_id']}"
        rows.append([InlineKeyboardButton(f"👥 {nm} ({r['cnt']}/{GROUP_ROOM_MAX})", callback_data=f"joinroom_{r['room_id']}")])
    rows.append([InlineKeyboardButton("➕ Create Room", callback_data="create_room")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    await safe_edit(q, "👥 Group Rooms (3-10):", InlineKeyboardMarkup(rows))


async def create_room(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    async with db_pool.acquire() as c:
        rid = await c.fetchval("INSERT INTO group_rooms (host_id) VALUES ($1) RETURNING room_id", uid)
        await c.execute("INSERT INTO group_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['room_id'] = rid
    await safe_edit(q, f"✅ Room {rid} created!\n\nShare ID: `{rid}`\nOr: /joinroom {rid}",
        InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_room")]]))


async def join_room_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    rid = int(q.data.split("_")[1])
    async with db_pool.acquire() as c:
        room = await c.fetchrow("SELECT * FROM group_rooms WHERE room_id=$1 AND is_active=TRUE", rid)
        if not room:
            await safe_edit(q, "❌ Room not found", await main_menu_kb(lang)); return
        cnt = await c.fetchval("SELECT COUNT(*) FROM group_members WHERE room_id=$1", rid)
        if cnt >= GROUP_ROOM_MAX:
            await safe_edit(q, "❌ Room full", await main_menu_kb(lang)); return
        await c.execute("INSERT INTO group_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['room_id'] = rid
    await safe_edit(q, f"✅ Joined Room {rid}!\n\nSend messages.\n/leaveroom to exit.",
        InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_room")]]))


async def join_room_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    if not context.args:
        await update.message.reply_text("Usage: /joinroom <id>"); return
    try: rid = int(context.args[0])
    except: await update.message.reply_text("❌ Invalid"); return
    async with db_pool.acquire() as c:
        room = await c.fetchrow("SELECT * FROM group_rooms WHERE room_id=$1 AND is_active=TRUE", rid)
        if not room:
            await update.message.reply_text("❌ Not found"); return
        cnt = await c.fetchval("SELECT COUNT(*) FROM group_members WHERE room_id=$1", rid)
        if cnt >= GROUP_ROOM_MAX:
            await update.message.reply_text("❌ Full"); return
        await c.execute("INSERT INTO group_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['room_id'] = rid
    await update.message.reply_text(f"✅ Joined Room {rid}!")


async def leave_room(update, context):
    q = update.callback_query
    try: await q.answer()
    except: pass
    uid = q.from_user.id if q else update.effective_user.id
    lang = await get_lang(uid)
    rid = context.user_data.pop('room_id', None)
    if rid:
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM group_members WHERE room_id=$1 AND user_id=$2", rid, uid)
    if q:
        try: await safe_edit(q, "🚪 Left.", await main_menu_kb(lang))
        except: pass
    else:
        await update.message.reply_text("🚪 Left.")


async def relay_group(update, context, rid):
    uid = update.effective_user.id
    async with db_pool.acquire() as c:
        mem = await c.fetch("SELECT user_id FROM group_members WHERE room_id=$1 AND user_id!=$2", rid, uid)
    for m in mem:
        try: await context.bot.copy_message(chat_id=m['user_id'], from_chat_id=uid,
            message_id=update.message.message_id)
        except: pass


# ========== VOICE ROOMS ==========
async def voice_menu(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not await is_vip(uid):
        await safe_edit(q, "⭐ Voice Room is Premium only!\n\nUpgrade to Diamond.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Premium", callback_data="show_vip")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
        return
    async with db_pool.acquire() as c:
        rooms = await c.fetch("""SELECT r.room_id,COUNT(m.user_id) cnt FROM voice_rooms r
            LEFT JOIN voice_members m ON m.room_id=r.room_id WHERE r.is_active=TRUE
            GROUP BY r.room_id HAVING COUNT(m.user_id) < 6 ORDER BY r.room_id DESC LIMIT 5""")
    rows = []
    for r in rooms:
        rows.append([InlineKeyboardButton(f"🎤 Room {r['room_id']} ({r['cnt']}/6)", callback_data=f"jvr_{r['room_id']}")])
    rows.append([InlineKeyboardButton("➕ Create", callback_data="create_vr")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    await safe_edit(q, "🎤 Voice Rooms", InlineKeyboardMarkup(rows))


async def create_vr(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not await is_vip(uid):
        await q.answer("Premium only", show_alert=True); return
    async with db_pool.acquire() as c:
        rid = await c.fetchval("INSERT INTO voice_rooms (host_id) VALUES ($1) RETURNING room_id", uid)
        await c.execute("INSERT INTO voice_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['voice_room_id'] = rid
    await safe_edit(q, f"🎤 Voice Room {rid}!\n\nSend voice notes.\n/leavevoice to exit.",
        InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_vr")]]))


async def join_vr(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not await is_vip(uid):
        await q.answer("Premium only", show_alert=True); return
    rid = int(q.data.replace("jvr_", ""))
    async with db_pool.acquire() as c:
        cnt = await c.fetchval("SELECT COUNT(*) FROM voice_members WHERE room_id=$1", rid)
        if cnt >= 6:
            await q.answer("Full", show_alert=True); return
        await c.execute("INSERT INTO voice_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['voice_room_id'] = rid
    await safe_edit(q, f"🎤 Joined Room {rid}!\n\nSend voice notes.",
        InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_vr")]]))


async def leave_voice(update, context):
    q = update.callback_query
    try: await q.answer()
    except: pass
    uid = q.from_user.id if q else update.effective_user.id
    lang = await get_lang(uid)
    rid = context.user_data.pop('voice_room_id', None)
    if rid:
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM voice_members WHERE room_id=$1 AND user_id=$2", rid, uid)
    if q:
        try: await safe_edit(q, "🎤 Left.", await main_menu_kb(lang))
        except: pass
    else:
        await update.message.reply_text("🎤 Left.")


async def relay_voice(update, context, rid):
    uid = update.effective_user.id
    if not (update.message.voice or update.message.audio): return
    async with db_pool.acquire() as c:
        mem = await c.fetch("SELECT user_id FROM voice_members WHERE room_id=$1 AND user_id!=$2", rid, uid)
    for m in mem:
        try: await context.bot.copy_message(chat_id=m['user_id'], from_chat_id=uid,
            message_id=update.message.message_id)
        except: pass


# ========== COMMANDS ==========
async def stop_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    chat = await get_chat(uid)
    if not chat:
        await update.message.reply_text(t("not_in_chat", lang)); return
    pid = chat['partner_id']; is_ai = chat.get('is_ai', False)
    await remove_chat(uid, pid)
    for n in [f"end1_{uid}", f"end2_{uid}", f"end1_{pid}", f"end2_{pid}"]:
        for j in context.job_queue.get_jobs_by_name(n): j.schedule_removal()
    await update.message.reply_text(t("chat_ended", lang), reply_markup=await main_menu_kb(lang))
    if not is_ai:
        try:
            pl = await get_lang(pid)
            await context.bot.send_message(pid, t("partner_ended", pl), reply_markup=await main_menu_kb(pl))
        except: pass


async def reset_cmd(update, context):
    uid = update.effective_user.id
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM profiles WHERE user_id=$1", uid)
        await c.execute("DELETE FROM match_queue WHERE user_id=$1", uid)
        await c.execute("DELETE FROM active_chats WHERE user_id=$1", uid)
        await c.execute("DELETE FROM group_members WHERE user_id=$1", uid)
        await c.execute("DELETE FROM voice_members WHERE user_id=$1", uid)
    context.user_data.clear()
    await update.message.reply_text("🔄 Reset. /start")


async def stats_cmd(update, context):
    async with db_pool.acquire() as c:
        tu = await c.fetchval("SELECT COUNT(*) FROM users") or 0
        iq = await c.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        ch = (await c.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
    await update.message.reply_text(f"📊\n👥 {tu}\n🟢 {await online_count()}\n⏳ {iq}\n💬 {ch}")


async def profile_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    prof = await get_profile(uid)
    if not prof:
        await update.message.reply_text(t("reg_first", lang)); return
    st = await get_stats(uid) or {}
    lvl = st.get('level') or 1
    nx = LEVELS[lvl] if lvl < len(LEVELS) else 0
    aid = st.get('anon_id') or await get_anon_id(uid)
    await update.message.reply_text(
        f"👤 {prof.get('display_name')}\n🆔 /{aid}\n"
        f"🎂 {prof.get('age')} • {st.get('city') or 'N/A'}\n"
        f"❤️ Likes: {st.get('likes_received') or 0}\n"
        f"👀 Views: {st.get('profile_views') or 0}\n"
        f"📈 Lv{lvl} • XP {st.get('xp') or 0}/{nx}\n"
        f"🪙 {st.get('coins') or 0}\n💬 {st.get('total_chats') or 0}",
        reply_markup=profile_kb(lang))


async def help_cmd(update, context):
    lang = await get_lang(update.effective_user.id)
    text = (
        "📖 Help\n\n"
        "/start — Main menu\n"
        "/newchat — Start new chat\n"
        "/profile — Your profile\n"
        "/credit — Coins & Stars\n"
        "/vip — Premium plans\n"
        "/link — Invite & earn\n"
        "/link_anon — Anonymous link\n"
        "/leaderboard — Top chatters\n"
        "/language — Change language\n"
        "/joinroom /leaveroom — Group rooms\n"
        "/stop — End chat\n"
        "/reset — Reset profile\n\n"
        "🔒 Anonymous. 18+ only."
    )
    await update.message.reply_text(text)


async def vip_cmd(update, context):
    uid = update.effective_user.id
    rows = [[InlineKeyboardButton(f"{info['name']} — {info['price']}৳", callback_data=f"tier_{k}")] for k, info in PREMIUM_TIERS.items()]
    await update.message.reply_text("💎 Premium:", reply_markup=InlineKeyboardMarkup(rows))


async def coins_cmd(update, context):
    uid = update.effective_user.id
    c = await get_coins(uid)
    vip = await is_vip(uid); tier = await get_tier(uid) if vip else None
    await update.message.reply_text(f"🪙 Coins: {c}\n⭐ {'✅ ' + (tier or '') if vip else '❌'}")


async def language_cmd(update, context):
    await update.message.reply_text(t("language_select", "en"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
             InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]]))


async def leaderboard_cmd(update, context):
    lang = await get_lang(update.effective_user.id)
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT p.display_name,u.total_chats,u.xp,u.level
            FROM users u JOIN profiles p ON p.user_id=u.user_id
            WHERE u.total_chats>0 ORDER BY u.xp DESC LIMIT 10""")
    if not rows:
        await update.message.reply_text("No data."); return
    text = "🏆 Top Chatters\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        text += f"{m} {r['display_name'] or 'Anon'} — Lv{r['level']} • {r['total_chats']}\n"
    await update.message.reply_text(text)


# ========== ADMIN ==========
async def admin_stats(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    async with db_pool.acquire() as c:
        tu = await c.fetchval("SELECT COUNT(*) FROM users") or 0
        q = await c.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        ch = (await c.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
        pend = await c.fetchval("SELECT COUNT(*) FROM reports WHERE status='pending'") or 0
        bn = await c.fetchval("SELECT COUNT(*) FROM users WHERE is_banned=TRUE") or 0
        vp = await c.fetchval("SELECT COUNT(*) FROM users WHERE is_vip=TRUE") or 0
        co = await c.fetchval("SELECT SUM(coins) FROM users") or 0
        pp = await c.fetchval("SELECT COUNT(*) FROM payments WHERE status='pending'") or 0
        rev = await c.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved'") or 0
    await update.message.reply_text(
        f"📊 Dashboard\n\n👥 {tu}\n🟢 {await online_count()}\n⏳ {q}\n💬 {ch}\n"
        f"⚠️ Reports: {pend}\n🚫 Banned: {bn}\n⭐ VIP: {vp}\n🪙 Coins: {co}\n\n"
        f"💳 Pending: {pp}\n💰 Revenue: {rev}৳")


async def ban_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /ban <id>"); return
    try:
        tid = int(context.args[0])
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET is_banned=TRUE WHERE user_id=$1", tid)
        await update.message.reply_text(f"✅ Banned {tid}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")


async def unban_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /unban <id>"); return
    try:
        tid = int(context.args[0])
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET is_banned=FALSE WHERE user_id=$1", tid)
        await update.message.reply_text(f"✅ Unbanned {tid}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")


async def approve_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /approve <uid> <tier|topup_XXX>"); return
    try:
        tid = int(context.args[0]); key = context.args[1]
        if key.startswith("topup_"):
            coins = int(key.replace("topup_", ""))
            await add_coins(tid, coins)
            await update.message.reply_text(f"✅ +{coins} coins to {tid}")
        else:
            info = PREMIUM_TIERS.get(key)
            if not info:
                await update.message.reply_text("❌ Invalid tier"); return
            await set_vip(tid, key, info['days'])
            await add_coins(tid, info['coins'])
            try:
                tl = await get_lang(tid)
                await context.bot.send_message(tid,
                    f"🎉 Premium activated!\n🌟 {info['name']}\n📅 {info['days']} days\n🪙 +{info['coins']}")
            except: pass
            await update.message.reply_text(f"✅ Premium for {tid} ({key})")
        async with db_pool.acquire() as c:
            await c.execute("UPDATE payments SET status='approved',approved_at=NOW() WHERE user_id=$1 AND status='pending'", tid)
    except Exception as e: await update.message.reply_text(f"❌ {e}")


async def verify_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /verify <uid>"); return
    try:
        tid = int(context.args[0])
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET is_verified=TRUE WHERE user_id=$1", tid)
        await context.bot.send_message(tid, "✅ You're now Verified!")
        await update.message.reply_text("✅ Verified")
    except Exception as e: await update.message.reply_text(f"❌ {e}")


async def broadcast_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <msg>"); return
    msg = " ".join(context.args)
    async with db_pool.acquire() as c:
        users = await c.fetch("SELECT user_id FROM users WHERE is_banned=FALSE")
    sent, failed = 0, 0
    for u in users:
        try:
            await context.bot.send_message(u['user_id'], f"📢 {msg}")
            sent += 1; await asyncio.sleep(0.05)
        except: failed += 1
    await update.message.reply_text(f"✅ {sent} | ❌ {failed}")


async def pending_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    async with db_pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM payments WHERE status='pending' ORDER BY created_at DESC LIMIT 20")
    if not rows:
        await update.message.reply_text("✅ None"); return
    text = "💳 Pending:\n\n"
    for r in rows:
        text += f"🆔 #{r['payment_id']} 👤 `{r['user_id']}`\n📦 {r['tier']} • {r['method']}\n➡️ /approve {r['user_id']} {r['tier']}\n\n"
    await update.message.reply_text(text[:4000])


# ========== MAIN ==========
def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    threading.Thread(target=run_flask, daemon=True).start()

    async def post_init(app):
        await init_db()

    async def post_shutdown(app):
        await close_db()

    req = HTTPXRequest(connection_pool_size=20)
    app = (Application.builder()
           .token(BOT_TOKEN).request(req)
           .post_init(post_init).post_shutdown(post_shutdown).build())

    cmds = [
        ("start", start), ("stop", stop_cmd), ("reset", reset_cmd),
        ("stats", stats_cmd), ("link", link_cmd), ("coins", coins_cmd),
        ("credit", show_credit), ("vip", vip_cmd), ("language", language_cmd),
        ("profile", profile_cmd), ("help", help_cmd), ("newchat", newchat_cmd),
        ("link_anon", link_anon_cmd), ("leaderboard", leaderboard_cmd),
        ("joinroom", join_room_cmd), ("leaveroom", leave_room),
        ("leavevoice", leave_voice),
        ("adminstats", admin_stats), ("ban", ban_cmd), ("unban", unban_cmd),
        ("approve", approve_cmd), ("verify", verify_cmd),
        ("broadcast", broadcast_cmd), ("pending", pending_cmd),
        ("reply_ticket", reply_ticket_cmd),
    ]
    for n, f in cmds: app.add_handler(CommandHandler(n, f))

    callbacks = [
        ("^lang_", language_callback), ("^change_language$", change_language),
        ("^age_", age_gate_callback),
        ("^gender_", gender_cb), ("^pref_", pref_gender_cb),
        ("^int_", interest_cb), ("^plang_", pref_lang_cb),
        ("^setpg_", set_pref_gender), ("^setint_", set_interest),
        ("^setplang_", set_plang), ("^setage_", set_age),
        ("^setcity_", set_city_cb), ("^custom_city$", custom_city_cb),
        ("^choose_city$", choose_city_cb),
        ("^edit_name$", edit_name), ("^edit_bio$", edit_bio),
        ("^edit_birthday$", edit_birthday),
        ("^edit_pref_gender$", edit_pref_gender),
        ("^edit_interest$", edit_interest),
        ("^edit_lang$", edit_lang), ("^edit_age_range$", edit_age_range),
        ("^edit_profile$", edit_profile),
        ("^advanced_settings$", advanced_settings),
        ("^toggle_sa$", toggle_sa), ("^toggle_sa_setting$", toggle_sa_setting),
        ("^coins_to_stars$", coins_to_stars_cb),
        ("^main_menu$", main_menu_cb), ("^refresh_online$", refresh_online),
        ("^newchat$", newchat_cmd),
        ("^search_random$", search_random),
        ("^search_guy$", search_guy), ("^search_girl$", search_girl),
        ("^cancel_search$", cancel_search),
        ("^ai_chat$", ai_chat_start),
        ("^show_link$", show_link), ("^show_anon_link$", show_anon_link),
        ("^show_credit$", show_credit), ("^show_vip$", show_vip),
        ("^coins_topup$", coins_topup), ("^topup_", topup_select),
        ("^show_achievements$", show_achievements),
        ("^show_missions$", show_missions),
        ("^show_blocked$", show_blocked),
        ("^unblock_", unblock_cb),
        ("^contact_list$", contact_list_cb),
        ("^view_likers$", view_likers),
        ("^my_likes$", view_likers),
        ("^browse_people$", browse_people), ("^nearby_people$", nearby_people),
        ("^tier_", tier_select), ("^stars_", stars_payment),
        ("^pay_", payment_method),
        ("^copy_", copy_num), ("^cancel_payment$", cancel_payment),
        ("^end_chat$", end_chat_cb),
        ("^delete_msgs$", delete_msgs_cb),
        ("^secure_chat$", secure_chat_cb),
        ("^addfriend_", add_friend_cb),
        ("^like_", like_cb), ("^msg_", msg_user_cb), ("^block_", block_cb),
        ("^viewprof_", view_profile_cb),
        ("^rpr_", report_reason_cb), ("^report_", report_cb),
        ("^my_profile$", my_profile),
        ("^leaderboard$", leaderboard),
        ("^support_ticket$", support_ticket),
        ("^group_menu$", group_menu), ("^create_room$", create_room),
        ("^joinroom_", join_room_cb), ("^leave_room$", leave_room),
        ("^voice_menu$", voice_menu), ("^create_vr$", create_vr),
        ("^jvr_", join_vr), ("^leave_vr$", leave_voice),
        ("^tod_start$", tod_start), ("^tod_truth$", tod_truth_cb),
        ("^tod_dare$", tod_dare_cb), ("^tod_random$", tod_random_cb),
        ("^ice_breaker$", ice_breaker), ("^compat$", compat),
        ("^chat_summary$", chat_summary),
    ]
    for p, f in callbacks: app.add_handler(CallbackQueryHandler(f, pattern=p))

    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_text))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
