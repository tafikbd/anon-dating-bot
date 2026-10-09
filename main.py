import os, logging, asyncio, threading, random, string
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler)
from telegram.request import HTTPXRequest
import asyncpg

try:
    from groq import Groq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False

# ============ CONFIG ============
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("BOT_TOKEN and DATABASE_URL required.")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger("anon-bot")

flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "OK", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True)

db_pool = None
groq_client = Groq(api_key=GROQ_API_KEY) if (HAS_GROQ and GROQ_API_KEY) else None
AI_MODELS = ["openai/gpt-oss-120b", "llama-3.1-8b-instant", "llama3-8b-8192"]

# ============ PAYMENT INFO ============
BKASH_NUMBER = "01608364088"
ROCKET_NUMBER = "01608364088"
BINANCE_ID = "1076189034"
USDT_BSC20 = "0xb83a03d9ded3ac7a4908aa87cfdfe1df9e05f719"
USDT_TRC20 = "TKeEd3wuTqHse2rdzAg3rqYeRfQD1NC7tq"

# ============ CONSTANTS ============
QUEUE_TIMEOUT_SECONDS = 120
CHAT_TIMER_SECONDS = 600
AUTO_BAN_REPORT_COUNT = 5
REFERRAL_COIN_REWARD = 20
CHAT_COIN_REWARD = 1
DAILY_BONUS_COINS = 10
MAX_DAILY_CHATS_FREE = 20
GROUP_ROOM_MAX = 10
XP_PER_CHAT = 10
XP_PER_MESSAGE = 1
MSG_DELETE_WINDOW_MIN = 30
COINS_TO_STARS_RATE = 100  # 100 coins = 1 star
LEVEL_THRESHOLDS = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500, 5500, 6600, 7800, 9100, 10500]

# Popular cities for Nearby
CITIES = [
    "Dhaka", "Chittagong", "Sylhet", "Rajshahi", "Khulna",
    "Barisal", "Rangpur", "Mymensingh", "Comilla", "Narayanganj",
    "Gazipur", "Sakhhipur", "Bogura", "Jessore", "Cox's Bazar",
    "Kolkata", "Delhi", "Mumbai", "Chennai", "Bangalore",
    "Karachi", "Lahore", "Dubai", "Abu Dhabi", "Riyadh",
    "London", "New York", "Toronto", "Sydney", "Singapore",
]

PREMIUM_TIERS = {
    "bronze": {"name": "🥉 Bronze", "price": 49, "stars": 50, "days": 30, "coins": 50,
               "features": "Ads-free • Priority+1 • 50 Coins"},
    "silver": {"name": "🥈 Silver", "price": 99, "stars": 100, "days": 30, "coins": 150,
               "features": "Adv Filters • 2x Coins • Unlimited Chats"},
    "gold": {"name": "🥇 Gold", "price": 199, "stars": 200, "days": 30, "coins": 500,
             "features": "Verified • Super Chat • Friends • Secure Chat"},
    "diamond": {"name": "💎 Diamond", "price": 399, "stars": 400, "days": 30, "coins": 1500,
                "features": "ALL + AI Trans + Voice Rooms + Priority Match"},
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

DAILY_MISSIONS = {
    "chat_3": {"text": "3 chats complete", "reward": 30, "target": 3},
    "msg_20": {"text": "20 messages send", "reward": 20, "target": 20},
    "invite_1": {"text": "1 friend invite", "reward": 50, "target": 1},
    "like_3": {"text": "3 profiles like", "reward": 15, "target": 3},
}

ICE_BREAKERS = [
    "If you could have dinner with anyone, who?",
    "What's your biggest dream?",
    "Last movie that made you cry?",
    "Secret talent nobody knows?",
    "If you won 1 crore, what would you do?",
    "Most embarrassing moment?",
    "Your favorite childhood memory?",
    "Describe yourself in 3 words?",
    "What's on your bucket list?",
    "Biggest fear and why?",
]

TRUTH_QUESTIONS = [
    "What's your biggest regret?", "Last lie you told?",
    "Biggest crush's name?", "Most embarrassing thing you've done?",
    "Ever cheated on a test?", "Deepest secret?",
    "Who do you secretly dislike?", "Worst date experience?",
    "Do you stalk your ex?", "Screen time today?",
]

DARE_TASKS = [
    "Send a selfie!", "Voice note singing!", "Type with eyes closed!",
    "Send a funny sticker!", "Voice: say 'I love you' dramatically!",
    "Reveal your phone wallpaper!", "Send your last photo!",
]

BANNED_WORDS = ["fuck","shit","bitch","asshole","dick","pussy","bastard",
    "madarchod","bhadwa","chutiya","chod","harami","kutta","kuti"]

# ============ LANGUAGE STRINGS ============
STRINGS = {
    "welcome": {"bn":"👋 স্বাগতম! এটি অ্যানোনিমাস চ্যাটিং বট।\n\n১৮+ নিশ্চিত করুন।","en":"👋 Welcome! Anonymous chat bot.\n\nConfirm you are 18+.","hi":"👋 स्वागत! गुमनाम चैट बॉट।\n\n18+ पुष्टि करें।","ru":"👋 Добро пожаловать! Анонимный чат-бот.\n\nПодтвердите 18+."},
    "age_yes": {"bn":"✅ হ্যাঁ, ১৮+","en":"✅ Yes, 18+","hi":"✅ हाँ, 18+","ru":"✅ Да, 18+"},
    "age_no": {"bn":"❌ না","en":"❌ No","hi":"❌ नहीं","ru":"❌ Нет"},
    "age_denied": {"bn":"❌ শুধু ১৮+","en":"❌ Only 18+","hi":"❌ केवल 18+","ru":"❌ Только 18+"},
    "ask_name": {"bn":"✅ নাম লিখুন:","en":"✅ Enter your name:","hi":"✅ नाम लिखें:","ru":"✅ Введите имя:"},
    "ask_age": {"bn":"🎂 বয়স (18-99):","en":"🎂 Age (18-99):","hi":"🎂 उम्र (18-99):","ru":"🎂 Возраст (18-99):"},
    "ask_gender": {"bn":"⚧ জেন্ডার:","en":"⚧ Gender:","hi":"⚧ लिंग:","ru":"⚧ Пол:"},
    "ask_city": {"bn":"🏙️ আপনার শহর:","en":"🏙️ Your city:","hi":"🏙️ आपका शहर:","ru":"🏙️ Ваш город:"},
    "ask_pref": {"bn":"🎯 কার সাথে চ্যাট:","en":"🎯 Chat preference:","hi":"🎯 चैट वरीयता:","ru":"🎯 Предпочтение:"},
    "ask_interest": {"bn":"💡 আগ্রহ:","en":"💡 Interest:","hi":"💡 रुचि:","ru":"💡 Интерес:"},
    "ask_lang_pref": {"bn":"🌐 ভাষা:","en":"🌐 Language:","hi":"🌐 भाषा:","ru":"🌐 Язык:"},
    "ask_bio": {"bn":"📝 বায়ো (max 200):","en":"📝 Bio (max 200):","hi":"📝 बायो (max 200):","ru":"📝 О себе (max 200):"},
    "male": {"bn":"👦 ছেলে","en":"👦 Male","hi":"👦 पुरुष","ru":"👦 Мужской"},
    "female": {"bn":"👧 মেয়ে","en":"👧 Female","hi":"👧 महिला","ru":"👧 Женский"},
    "other": {"bn":"🌈 অন্যান্য","en":"🌈 Other","hi":"🌈 अन्य","ru":"🌈 Другое"},
    "any": {"bn":"🌍 যে কেউ","en":"🌍 Anyone","hi":"🌍 कोई भी","ru":"🌍 Любой"},
    "main_menu": {"bn":"🏠 মেইন মেনু:","en":"🏠 Main Menu:","hi":"🏠 मुख्य मेनू:","ru":"🏠 Главное меню:"},
    "find_partner": {"bn":"🔍 পার্টনার খুঁজুন","en":"🔍 Find Partner","hi":"🔍 पार्टनर खोजें","ru":"🔍 Найти партнёра"},
    "chat_with_guy": {"bn":"👦 ছেলের সাথে চ্যাট","en":"👦 Chat With Guy","hi":"👦 लड़के से चैट","ru":"👦 Чат с парнем"},
    "chat_with_girl": {"bn":"👧 মেয়ের সাথে চ্যাট","en":"👧 Chat With Girl","hi":"👧 लड़की से चैट","ru":"👧 Чат с девушкой"},
    "random_free": {"bn":"🎲 র‍্যান্ডম (ফ্রি)","en":"🎲 Random (Free)","hi":"🎲 रैंडम (फ्री)","ru":"🎲 Случайный (бесплатно)"},
    "same_age": {"bn":"⚙️ একই বয়সের খোঁজ","en":"⚙️ Same Age Search","hi":"⚙️ समान आयु खोज","ru":"⚙️ Поиск по возрасту"},
    "group_rooms": {"bn":"👥 গ্রুপ রুম","en":"👥 Group Rooms","hi":"👥 ग्रुप रूम","ru":"👥 Группы"},
    "voice_room": {"bn":"🎤 ভয়েস রুম","en":"🎤 Voice Room","hi":"🎤 वॉइस रूम","ru":"🎤 Голосовая"},
    "status": {"bn":"📸 স্ট্যাটাস","en":"📸 Status","hi":"📸 स्टेटस","ru":"📸 Статус"},
    "browse_people": {"bn":"👥 সবাইকে দেখুন","en":"👥 Browse People","hi":"👥 लोगों को देखें","ru":"👥 Обзор людей"},
    "nearby_people": {"bn":"📍 কাছাকাছি","en":"📍 Nearby People","hi":"📍 आसपास के लोग","ru":"📍 Рядом"},
    "my_profile": {"bn":"👤 আমার প্রোফাইল","en":"👤 My Profile","hi":"👤 मेरी प्रोफाइल","ru":"👤 Профиль"},
    "edit_profile": {"bn":"✏️ প্রোফাইল এডিট","en":"✏️ Edit Profile","hi":"✏️ प्रोफाइल संपादित","ru":"✏️ Редактировать"},
    "view_likers": {"bn":"❤️ কারা লাইক করেছে","en":"❤️ View Likers","hi":"❤️ लाइकर्स देखें","ru":"❤️ Кто лайкнул"},
    "liked_you": {"bn":"❤️ আপনার প্রোফাইল লাইক করেছে","en":"❤️ liked your profile","hi":"❤️ ने आपकी प्रोफाइल लाइक की","ru":"❤️ лайкнул ваш профиль"},
    "contact_list": {"bn":"📋 কন্টাক্ট লিস্ট","en":"📋 Contact List","hi":"📋 संपर्क सूची","ru":"📋 Контакты"},
    "blocked_users": {"bn":"🚫 ব্লকড ইউজার","en":"🚫 Blocked Users","hi":"🚫 ब्लॉक किए गए","ru":"🚫 Заблокированные"},
    "advanced_settings": {"bn":"⚙️ অ্যাডভান্সড সেটিংস","en":"⚙️ Advanced Settings","hi":"⚙️ उन्नत सेटिंग्स","ru":"⚙️ Настройки"},
    "edit_info": {"bn":"📝 প্রোফাইল তথ্য এডিট","en":"📝 Edit Profile Info","hi":"📝 प्रोफाइल जानकारी","ru":"📝 Изменить профиль"},
    "safe_chat": {"bn":"🔒 সিকিউর চ্যাট","en":"🔒 Secure Chat","hi":"🔒 सुरक्षित चैट","ru":"🔒 Безопасный чат"},
    "profile_views": {"bn":"👀 প্রোফাইল ভিউ","en":"👀 Profile Views","hi":"👀 प्रोफाइल व्यू","ru":"👀 Просмотры"},
    "secure_chat": {"bn":"🔒 শুধু verified","en":"🔒 Verified only","hi":"🔒 केवल verified","ru":"🔒 Только подтверждённые"},
    "coins": {"bn":"🪙 কয়েন","en":"🪙 Coins","hi":"🪙 सिक्के","ru":"🪙 Монеты"},
    "premium": {"bn":"⭐ প্রিমিয়াম","en":"⭐ Premium","hi":"⭐ प्रीमियम","ru":"⭐ Премиум"},
    "invite": {"bn":"🔗 ইনভাইট","en":"🔗 Invite","hi":"🔗 आमंत्रित","ru":"🔗 Пригласить"},
    "anon_link": {"bn":"🔗 অ্যানোনিমাস লিংক","en":"🔗 Anonymous Link","hi":"🔗 गुमनाम लिंक","ru":"🔗 Анонимная ссылка"},
    "leaderboard": {"bn":"🏆 লিডারবোর্ড","en":"🏆 Leaderboard","hi":"🏆 लीडरबोर्ड","ru":"🏆 Рейтинг"},
    "language": {"bn":"🌐 ভাষা","en":"🌐 Language","hi":"🌐 भाषा","ru":"🌐 Язык"},
    "achievements": {"bn":"🏅 অ্যাচিভমেন্ট","en":"🏅 Achievements","hi":"🏅 उपलब्धियाँ","ru":"🏅 Достижения"},
    "missions": {"bn":"🎯 ডেইলি মিশন","en":"🎯 Daily Missions","hi":"🎯 दैनिक मिशन","ru":"🎯 Миссии"},
    "friends": {"bn":"👫 বন্ধু","en":"👫 Friends","hi":"👫 दोस्त","ru":"👫 Друзья"},
    "end_chat": {"bn":"🛑 শেষ","en":"🛑 End","hi":"🛑 समाप्त","ru":"🛑 Конец"},
    "next_person": {"bn":"➡️ পরবর্তী","en":"➡️ Next","hi":"➡️ अगला","ru":"➡️ Следующий"},
    "report": {"bn":"🚫 রিপোর্ট","en":"🚫 Report","hi":"🚫 रिपोर्ट","ru":"🚫 Жалоба"},
    "delete_msgs": {"bn":"🗑️ মেসেজ ডিলিট","en":"🗑️ Delete Messages","hi":"🗑️ संदेश हटाएँ","ru":"🗑️ Удалить"},
    "contact_profile": {"bn":"👤 প্রোফাইল দেখুন","en":"👤 Contact Profile","hi":"👤 प्रोफाइल देखें","ru":"👤 Профиль"},
    "reg_done": {"bn":"✅ রেজিস্ট্রেশন সম্পন্ন! 🎉","en":"✅ Registration complete! 🎉","hi":"✅ पंजीकरण पूरा! 🎉","ru":"✅ Регистрация завершена! 🎉"},
    "searching": {"bn":"⏳ খোঁজা হচ্ছে...\nঅনুগ্রহ করে ২ মিনিট অপেক্ষা করুন।","en":"⏳ Searching...\nPlease wait up to 2 minutes.","hi":"⏳ खोज रहे हैं...\n2 मिनट तक प्रतीक्षा करें।","ru":"⏳ Поиск...\nПодождите до 2 минут."},
    "partner_found": {"bn":"💗 আপনার জন্য পার্টনার পাওয়া গেছে!\nহ্যালো বলুন 👋","en":"💗 Found partner for you!\nSay hi 👋","hi":"💗 आपके लिए पार्टनर मिला!\nहैलो कहें 👋","ru":"💗 Партнёр найден!\nПоздоровайтесь 👋"},
    "partner_viewed": {"bn":"👀 আপনার চ্যাট পার্টনার আপনার প্রোফাইল দেখেছেন!","en":"👀 Your chat partner viewed your profile!","hi":"👀 आपके पार्टनर ने प्रोफाइल देखी!","ru":"👀 Партнёр посмотрел ваш профиль!"},
    "chat_ended": {"bn":"🛑 চ্যাট শেষ।","en":"🛑 Chat ended.","hi":"🛑 चैट समाप्त।","ru":"🛑 Чат завершён."},
    "partner_ended": {"bn":"🛑 পার্টনার চ্যাট শেষ করেছেন।","en":"🛑 Partner ended the chat.","hi":"🛑 पार्टनर ने चैट समाप्त की।","ru":"🛑 Партнёр завершил чат."},
    "msgs_deleted": {"bn":"🗑️ আপনার মেসেজ ডিলিট করা হয়েছে।","en":"🗑️ Your messages deleted.","hi":"🗑️ संदेश हटा दिए गए।","ru":"🗑️ Сообщения удалены."},
    "not_in_chat": {"bn":"⚠️ চ্যাটে নেই। /start","en":"⚠️ Not in a chat. /start","hi":"⚠️ चैट में नहीं। /start","ru":"⚠️ Не в чате. /start"},
    "reg_first": {"bn":"❌ আগে /start","en":"❌ /start first","hi":"❌ पहले /start","ru":"❌ Сначала /start"},
    "already_in_chat": {"bn":"❌ ইতিমধ্যে চ্যাটে আছেন।","en":"❌ Already in chat.","hi":"❌ पहले से चैट में।","ru":"❌ Уже в чате."},
    "search_cancelled": {"bn":"✅ বাতিল।","en":"✅ Cancelled.","hi":"✅ रद्द।","ru":"✅ Отменено."},
    "online_count": {"bn":"🟢 {n} জন অনলাইনে","en":"🟢 {n} online","hi":"🟢 {n} ऑनलाइन","ru":"🟢 {n} онлайн"},
    "referral_msg": {"bn":"🔗 লিংক:\n\n{link}\n\n💡 প্রতি ইনভাইটে {coins} কয়েন!","en":"🔗 Link:\n\n{link}\n\n💡 {coins} coins per invite!","hi":"🔗 लिंक:\n\n{link}\n\n💡 {coins} सिक्के!","ru":"🔗 Ссылка:\n\n{link}\n\n💡 {coins} монет!"},
    "anon_link_msg": {"bn":"🔗 আপনার অ্যানোনিমাস লিংক:\n\n{link}\n\n💡 এই লিংকে ক্লিক করলে সরাসরি আপনার সাথে চ্যাট শুরু হবে।","en":"🔗 Your anonymous link:\n\n{link}\n\n💡 Anyone clicking this will chat directly with you.","hi":"🔗 आपका गुमनाम लिंक:\n\n{link}\n\n💡 इसे क्लिक करने पर सीधे आपसे चैट होगी।","ru":"🔗 Анонимная ссылка:\n\n{link}\n\n💡 Любой кликнувший будет чатить с вами."},
    "coins_balance": {"bn":"🪙 কয়েন: {coins}\n⭐ প্রিমিয়াম: {vip}","en":"🪙 Coins: {coins}\n⭐ Premium: {vip}","hi":"🪙 सिक्के: {coins}\n⭐ प्रीमियम: {vip}","ru":"🪙 Монеты: {coins}\n⭐ Премиум: {vip}"},
    "vip_active": {"bn":"✅ সক্রিয়","en":"✅ Active","hi":"✅ सक्रिय","ru":"✅ Активен"},
    "vip_inactive": {"bn":"❌ নিষ্ক্রিয়","en":"❌ Inactive","hi":"❌ निष्क्रिय","ru":"❌ Неактивен"},
    "language_select": {"bn":"🌍 ভাষা:","en":"🌍 Language:","hi":"🌍 भाषा:","ru":"🌍 Язык:"},
    "language_changed": {"bn":"✅ ভাষা: বাংলা","en":"✅ Language: English","hi":"✅ भाषा: हिन्दी","ru":"✅ Язык: Русский"},
    "report_blocked": {"bn":"✅ রিপোর্ট + ব্লকড।","en":"✅ Reported + blocked.","hi":"✅ रिपोर्ट + ब्लॉक।","ru":"✅ Жалоба + блок."},
    "referral_bonus": {"bn":"🎁 {coins} কয়েন!","en":"🎁 {coins} coins!","hi":"🎁 {coins} सिक्के!","ru":"🎁 {coins} монет!"},
    "daily_bonus": {"bn":"🎁 ডেইলি বোনাস: +{coins} কয়েন!","en":"🎁 Daily bonus: +{coins} coins!","hi":"🎁 दैनिक बोनस: +{coins} सिक्के!","ru":"🎁 Бонус: +{coins} монет!"},
    "streak_msg": {"bn":"🔥 Streak: {n} দিন!","en":"🔥 Streak: {n} days!","hi":"🔥 स्ट्रीक: {n} दिन!","ru":"🔥 Серия: {n} дней!"},
    "chat_limit_reached": {"bn":"❌ আজকের লিমিট শেষ। প্রিমিয়াম নিন।","en":"❌ Daily limit reached. Get Premium.","hi":"❌ दैनिक सीमा। प्रीमियम लें।","ru":"❌ Лимит. Купите Премиум."},
    "spam_warning": {"bn":"⚠️ ভদ্রভাবে বলুন।","en":"⚠️ Be respectful.","hi":"⚠️ सम्मान से बोलें।","ru":"⚠️ Будьте вежливы."},
    "no_partner_ai": {"bn":"🤖 পার্টনার নেই। AI চ্যাট?","en":"🤖 No partner. Chat with AI?","hi":"🤖 पार्टनर नहीं। AI चैट?","ru":"🤖 Нет партнёра. Чат с AI?"},
    "ai_mode_on": {"bn":"🤖 AI মোড চালু। /stop বন্ধ।","en":"🤖 AI mode ON. /stop to end.","hi":"🤖 AI मोड चालू। /stop बंद।","ru":"🤖 AI режим. /stop конец."},
    "profile_saved": {"bn":"✅ সেভ!","en":"✅ Saved!","hi":"✅ सेव!","ru":"✅ Сохранено!"},
    "leaderboard_title": {"bn":"🏆 টপ চ্যাটার","en":"🏆 Top Chatters","hi":"🏆 टॉप चैटर","ru":"🏆 Топ"},
    "leaderboard_empty": {"bn":"ডেটা নেই।","en":"No data.","hi":"डेटा नहीं।","ru":"Нет данных."},
    "group_room_menu": {"bn":"👥 গ্রুপ রুম (3-10):","en":"👥 Group Rooms (3-10):","hi":"👥 ग्रुप रूम (3-10):","ru":"👥 Группы (3-10):"},
    "group_room_full": {"bn":"❌ রুম ফুল।","en":"❌ Room full.","hi":"❌ रूम भरा।","ru":"❌ Полна."},
    "group_room_not_found": {"bn":"❌ রুম নেই।","en":"❌ Room not found.","hi":"❌ रूम नहीं।","ru":"❌ Не найдена."},
    "group_room_left": {"bn":"🚪 বেরিয়ে গেছেন।","en":"🚪 Left.","hi":"🚪 निकल गए।","ru":"🚪 Выйдено."},
    "wait_moment": {"bn":"⏳ অপেক্ষা।","en":"⏳ Wait.","hi":"⏳ इंतज़ार।","ru":"⏳ Подождите."},
    "choose_tier": {"bn":"💎 প্রিমিয়াম প্যাকেজ:","en":"💎 Premium Package:","hi":"💎 प्रीमियम पैकेज:","ru":"💎 Премиум пакет:"},
    "choose_payment": {"bn":"💳 পেমেন্ট পদ্ধতি:","en":"💳 Payment Method:","hi":"💳 भुगतान विधि:","ru":"💳 Способ оплаты:"},
    "payment_sent": {"bn":"✅ পাঠানো হয়েছে। ৫-১০ মিনিটে verify।","en":"✅ Sent. Verify in 5-10 min.","hi":"✅ भेजा गया। 5-10 मिनट।","ru":"✅ Отправлено. 5-10 мин."},
    "premium_activated": {"bn":"🎉 প্রিমিয়াম চালু!\n🌟 {tier}\n📅 {days} দিন\n🪙 +{coins}","en":"🎉 Premium activated!\n🌟 {tier}\n📅 {days} days\n🪙 +{coins}","hi":"🎉 प्रीमियम सक्रिय!\n🌟 {tier}\n📅 {days} दिन\n🪙 +{coins}","ru":"🎉 Премиум активен!\n🌟 {tier}\n📅 {days} дней\n🪙 +{coins}"},
    "achievements_title": {"bn":"🏅 অ্যাচিভমেন্ট","en":"🏅 Achievements","hi":"🏅 उपलब्धियाँ","ru":"🏅 Достижения"},
    "missions_title": {"bn":"🎯 ডেইলি মিশন","en":"🎯 Daily Missions","hi":"🎯 दैनिक मिशन","ru":"🎯 Миссии"},
    "level_up": {"bn":"🎉 Level Up! Lv{level}!","en":"🎉 Level Up! Lv{level}!","hi":"🎉 लेवल अप! Lv{level}!","ru":"🎉 Уровень! Ур{level}!"},
    "truth_or_dare": {"bn":"🎲 সত্য না সাহস","en":"🎲 Truth or Dare","hi":"🎲 सच या साहस","ru":"🎲 Правда или действие"},
    "chat_summary": {"bn":"📝 চ্যাট সারাংশ","en":"📝 Chat Summary","hi":"📝 चैट सारांश","ru":"📝 Резюме"},
    "compatibility": {"bn":"💯 মিল","en":"💯 Compatibility","hi":"💯 अनुकूलता","ru":"💯 Совместимость"},
    "ice_breaker": {"bn":"🧊 আইস-ব্রেকার","en":"🧊 Ice-Breaker","hi":"🧊 आइस-ब्रेकर","ru":"🧊 Лёд растопить"},
    "chat_extend": {"bn":"⏱️ +১০ মিনিট (২০ কয়েন)","en":"⏱️ +10 Min (20 coins)","hi":"⏱️ +10 मिनट (20)","ru":"⏱️ +10 мин (20)"},
    "support": {"bn":"🎫 সাপোর্ট","en":"🎫 Support","hi":"🎫 सहायता","ru":"🎫 Поддержка"},
    "stars_btn": {"bn":"⭐ {n} Stars","en":"⭐ {n} Stars","hi":"⭐ {n} Stars","ru":"⭐ {n} Stars"},
    "same_age_on": {"bn":"✅ Same Age Search চালু","en":"✅ Same Age Search ON","hi":"✅ समान आयु ON","ru":"✅ Поиск по возрасту ВКЛ"},
    "same_age_off": {"bn":"❌ Same Age Search বন্ধ","en":"❌ Same Age Search OFF","hi":"❌ समान आयु OFF","ru":"❌ Поиск по возрасту ВЫКЛ"},
    "no_likers": {"bn":"এখনো কেউ লাইক করেনি।","en":"No likes yet.","hi":"अभी कोई लाइक नहीं।","ru":"Пока нет лайков."},
    "liked_success": {"bn":"❤️ লাইক করা হয়েছে!","en":"❤️ Liked!","hi":"❤️ लाइक किया!","ru":"❤️ Лайкнуто!"},
    "no_blocked": {"bn":"কোনো blocked user নেই।","en":"No blocked users.","hi":"कोई ब्लॉक नहीं।","ru":"Нет заблокированных."},
    "unblocked": {"bn":"✅ আনব্লক করা হয়েছে।","en":"✅ Unblocked.","hi":"✅ अनब्लॉक।","ru":"✅ Разблокировано."},
    "choose_city": {"bn":"🏙️ আপনার শহর নির্বাচন করুন:","en":"🏙️ Choose your city:","hi":"🏙️ अपना शहर चुनें:","ru":"🏙️ Выберите город:"},
    "browse_title": {"bn":"👥 অনলাইন ইউজার:","en":"👥 Online Users:","hi":"👥 ऑनलाइन यूज़र्स:","ru":"👥 Пользователи:"},
    "nearby_title": {"bn":"📍 আপনার শহরে অনলাইন:","en":"📍 Online in your city:","hi":"📍 आपके शहर में ऑनलाइन:","ru":"📍 В вашем городе:"},
    "no_users": {"bn":"কোনো ইউজার নেই।","en":"No users.","hi":"कोई यूज़र नहीं।","ru":"Нет пользователей."},
    "contact_list_empty": {"bn":"কোনো contact নেই।","en":"No contacts.","hi":"कोई संपर्क नहीं।","ru":"Нет контактов."},
    "converted": {"bn":"💎 {coins} কয়েন = {stars} Stars","en":"💎 {coins} coins = {stars} Stars","hi":"💎 {coins} सिक्के = {stars} Stars","ru":"💎 {coins} монет = {stars} Stars"},
    "not_enough_coins_convert": {"bn":"❌ কমপক্ষে ১০০ কয়েন দরকার।","en":"❌ Need at least 100 coins.","hi":"❌ कम से कम 100 चाहिए।","ru":"❌ Минимум 100 монет."},
}

def t(key, lang="bn", **kw):
    s = STRINGS.get(key, {})
    txt = s.get(lang) or s.get("en") or s.get("bn") or key
    if kw:
        try: return txt.format(**kw)
        except: return txt
    return txt


# ============ DATABASE ============
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as c:
        await c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_18_plus BOOLEAN DEFAULT FALSE,
                is_banned BOOLEAN DEFAULT FALSE,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                language VARCHAR(5) DEFAULT 'en',
                coins INTEGER DEFAULT 0,
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
                truth_count INTEGER DEFAULT 0,
                anon_id VARCHAR(20) UNIQUE,
                city VARCHAR(50),
                likes_received INTEGER DEFAULT 0,
                profile_views INTEGER DEFAULT 0,
                same_age_search BOOLEAN DEFAULT FALSE,
                secure_chat BOOLEAN DEFAULT FALSE,
                stars_balance INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS profiles (
                user_id BIGINT PRIMARY KEY,
                display_name VARCHAR(100), age INTEGER,
                gender VARCHAR(20), pref_gender VARCHAR(20) DEFAULT 'any',
                bio TEXT, pref_language VARCHAR(10) DEFAULT 'any',
                interest VARCHAR(30) DEFAULT 'any',
                min_age INTEGER DEFAULT 18, max_age INTEGER DEFAULT 99,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS match_queue (
                user_id BIGINT PRIMARY KEY, gender VARCHAR(20),
                pref_gender VARCHAR(20), pref_language VARCHAR(10),
                interest VARCHAR(30), is_vip BOOLEAN DEFAULT FALSE,
                age INTEGER DEFAULT 18, min_age INTEGER DEFAULT 18,
                max_age INTEGER DEFAULT 99, same_age BOOLEAN DEFAULT FALSE,
                queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS active_chats (
                user_id BIGINT PRIMARY KEY, partner_id BIGINT,
                is_ai BOOLEAN DEFAULT FALSE,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS group_rooms (
                room_id SERIAL PRIMARY KEY, host_id BIGINT,
                name VARCHAR(100), is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS group_members (
                room_id INTEGER, user_id BIGINT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (room_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS voice_rooms (
                room_id SERIAL PRIMARY KEY, host_id BIGINT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS voice_members (
                room_id INTEGER, user_id BIGINT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (room_id, user_id)
            );
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
            CREATE TABLE IF NOT EXISTS chat_log (
                id SERIAL PRIMARY KEY, user_id BIGINT, partner_id BIGINT,
                messages INTEGER DEFAULT 0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP
            );
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
            ("users", "truth_count", "INTEGER DEFAULT 0"),
            ("users", "anon_id", "VARCHAR(20)"),
            ("users", "city", "VARCHAR(50)"),
            ("users", "likes_received", "INTEGER DEFAULT 0"),
            ("users", "profile_views", "INTEGER DEFAULT 0"),
            ("users", "same_age_search", "BOOLEAN DEFAULT FALSE"),
            ("users", "secure_chat", "BOOLEAN DEFAULT FALSE"),
            ("users", "stars_balance", "INTEGER DEFAULT 0"),
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
        ]
        for tbl, col, typ in migrations:
            try:
                await c.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception as e:
                logger.warning(f"Migration {tbl}.{col}: {e}")

    logger.info("DB initialized + migrations applied.")


async def close_db():
    if db_pool: await db_pool.close()


# ============ HELPERS ============
def gen_anon_id():
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(4))

async def touch_user(uid):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET last_active = NOW() WHERE user_id = $1", uid)

async def get_lang(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT language FROM users WHERE user_id = $1", uid)
        return (r['language'] if r and r['language'] else 'en')

async def set_lang(uid, lang):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET language = $1 WHERE user_id = $2", lang, uid)

async def online_count():
    async with db_pool.acquire() as c:
        return (await c.fetchval("SELECT COUNT(*) FROM users WHERE last_active > NOW() - INTERVAL '5 min'")) or 0

async def is_banned(uid):
    async with db_pool.acquire() as c:
        return bool(await c.fetchval("SELECT is_banned FROM users WHERE user_id = $1", uid))

async def get_profile(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM profiles WHERE user_id = $1", uid)
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
        r = await c.fetchrow("SELECT coins,xp,level,streak,total_chats,is_vip,vip_tier,vip_until,is_verified,anon_id,city,likes_received,profile_views,same_age_search,secure_chat,stars_balance FROM users WHERE user_id = $1", uid)
        return dict(r) if r else None

async def get_anon_id(uid):
    async with db_pool.acquire() as c:
        aid = await c.fetchval("SELECT anon_id FROM users WHERE user_id = $1", uid)
        if aid: return aid
        for _ in range(10):
            new_id = gen_anon_id()
            try:
                await c.execute("UPDATE users SET anon_id=$1 WHERE user_id=$2 AND anon_id IS NULL", new_id, uid)
                return new_id
            except: continue
        return "user"

async def set_city(uid, city):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET city=$1 WHERE user_id=$2", city, uid)

async def get_coins(uid):
    async with db_pool.acquire() as c:
        return (await c.fetchval("SELECT coins FROM users WHERE user_id = $1", uid)) or 0

async def add_coins(uid, amt):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET coins = coins + $1 WHERE user_id = $2", amt, uid)

async def deduct_coins(uid, amt):
    async with db_pool.acquire() as c:
        cur = (await c.fetchval("SELECT coins FROM users WHERE user_id = $1", uid)) or 0
        if cur < amt: return False
        await c.execute("UPDATE users SET coins = coins - $1 WHERE user_id = $2", amt, uid)
        return True

async def add_xp(uid, amt):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT xp,level FROM users WHERE user_id = $1", uid)
        if not r: return None
        old_xp = r['xp'] or 0; old_lvl = r['level'] or 1
        new_xp = old_xp + amt
        new_lvl = 1
        for i, th in enumerate(LEVEL_THRESHOLDS):
            if new_xp >= th: new_lvl = i + 1
        await c.execute("UPDATE users SET xp=$1,level=$2 WHERE user_id=$3", new_xp, new_lvl, uid)
        return new_lvl if new_lvl > old_lvl else None

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

async def set_vip(uid, tier="bronze", days=30):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET is_vip=TRUE,vip_tier=$1,vip_until=$2 WHERE user_id=$3",
                        tier, datetime.now() + timedelta(days=days), uid)

async def update_streak(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT streak,last_streak_date FROM users WHERE user_id=$1", uid)
        if not r: return 0, False
        today = datetime.now().date()
        if r['last_streak_date'] == today: return r['streak'] or 0, False
        streak = r['streak'] or 0
        if r['last_streak_date'] and (today - r['last_streak_date']).days == 1:
            streak += 1
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
        await c.execute("UPDATE users SET daily_bonus_date=$1,coins=coins+$2 WHERE user_id=$3", today, DAILY_BONUS_COINS, uid)
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

# Likes
async def add_like(liker_id, liked_id):
    if liker_id == liked_id: return False
    async with db_pool.acquire() as c:
        exists = await c.fetchval("SELECT 1 FROM likes WHERE liker_id=$1 AND liked_id=$2", liker_id, liked_id)
        if exists: return False
        await c.execute("INSERT INTO likes (liker_id,liked_id) VALUES ($1,$2)", liker_id, liked_id)
        await c.execute("UPDATE users SET likes_received=likes_received+1 WHERE user_id=$1", liked_id)
        return True

async def get_likers(uid, limit=20):
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT l.liker_id, p.display_name, u.anon_id FROM likes l
            LEFT JOIN profiles p ON p.user_id=l.liker_id
            LEFT JOIN users u ON u.user_id=l.liker_id
            WHERE l.liked_id=$1 ORDER BY l.created_at DESC LIMIT $2""", uid, limit)
        return [dict(r) for r in rows]

# Profile views
async def record_view(viewer_id, viewed_id):
    if viewer_id == viewed_id: return
    async with db_pool.acquire() as c:
        exists = await c.fetchval("SELECT 1 FROM profile_views WHERE viewer_id=$1 AND viewed_id=$2", viewer_id, viewed_id)
        if exists:
            await c.execute("UPDATE profile_views SET viewed_at=NOW() WHERE viewer_id=$1 AND viewed_id=$2", viewer_id, viewed_id)
        else:
            await c.execute("INSERT INTO profile_views (viewer_id,viewed_id) VALUES ($1,$2)", viewer_id, viewed_id)
            await c.execute("UPDATE users SET profile_views=profile_views+1 WHERE user_id=$1", viewed_id)

# Blocked users list
async def get_blocked(uid):
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT b.blocked_id, p.display_name, u.anon_id FROM blocks b
            LEFT JOIN profiles p ON p.user_id=b.blocked_id
            LEFT JOIN users u ON u.user_id=b.blocked_id
            WHERE b.blocker_id=$1""", uid)
        return [dict(r) for r in rows]

async def unblock_user(uid, target):
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM blocks WHERE blocker_id=$1 AND blocked_id=$2", uid, target)

# Browse
async def browse_people(uid, limit=10):
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT u.user_id, u.anon_id, u.city, u.is_verified, p.display_name, p.age, p.gender
            FROM users u LEFT JOIN profiles p ON p.user_id=u.user_id
            WHERE u.user_id != $1 AND u.is_banned=FALSE AND u.last_active > NOW() - INTERVAL '1 hour'
            AND p.display_name IS NOT NULL
            ORDER BY u.last_active DESC LIMIT $2""", uid, limit)
        return [dict(r) for r in rows]

async def nearby_people(uid, limit=10):
    async with db_pool.acquire() as c:
        city = await c.fetchval("SELECT city FROM users WHERE user_id=$1", uid)
        if not city: return []
        rows = await c.fetch("""SELECT u.user_id, u.anon_id, u.city, u.is_verified, p.display_name, p.age, p.gender
            FROM users u LEFT JOIN profiles p ON p.user_id=u.user_id
            WHERE u.user_id != $1 AND u.city=$2 AND u.is_banned=FALSE
            AND u.last_active > NOW() - INTERVAL '1 hour' AND p.display_name IS NOT NULL
            ORDER BY u.last_active DESC LIMIT $3""", uid, city, limit)
        return [dict(r) for r in rows]

# Anon link
async def get_or_create_anon_link(uid):
    async with db_pool.acquire() as c:
        code = await c.fetchval("SELECT link_code FROM anon_links WHERE user_id=$1", uid)
        if code: return code
        for _ in range(10):
            new_code = gen_anon_id() + gen_anon_id()
            try:
                await c.execute("INSERT INTO anon_links (link_code,user_id) VALUES ($1,$2)", new_code, uid)
                return new_code
            except: continue
        return None

async def resolve_anon_link(code):
    async with db_pool.acquire() as c:
        uid = await c.fetchval("SELECT user_id FROM anon_links WHERE link_code=$1", code)
        if uid:
            await c.execute("UPDATE anon_links SET clicks=clicks+1 WHERE link_code=$1", code)
        return uid

# Coins to Stars
async def convert_coins_to_stars(uid, coins_amount):
    rate = coins_amount // COINS_TO_STARS_RATE
    if rate < 1: return 0
    ok = await deduct_coins(uid, rate * COINS_TO_STARS_RATE)
    if not ok: return 0
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET stars_balance=stars_balance+$1 WHERE user_id=$2", rate, uid)
    return rate

# ============ CHAT HELPERS ============
async def get_chat(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM active_chats WHERE user_id=$1", uid)
        return dict(r) if r else None

async def remove_chat(uid, pid):
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM active_chats WHERE user_id=$1 OR user_id=$2", uid, pid)

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

async def chat_timer_end(ctx):
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

def has_bad_words(text):
    if not text: return False
    low = text.lower()
    return any(w in low for w in BANNED_WORDS)

rate_store = {}
def rate_limited(uid, max_r=20, win=10):
    now = datetime.now()
    ts = rate_store.get(uid, [])
    ts = [x for x in ts if (now - x).total_seconds() < win]
    if len(ts) >= max_r:
        rate_store[uid] = ts
        return True
    ts.append(now)
    rate_store[uid] = ts
    return False

# ============ ACHIEVEMENTS ============
async def user_achievements(uid):
    async with db_pool.acquire() as c:
        rows = await c.fetch("SELECT achievement_key FROM user_achievements WHERE user_id=$1", uid)
        return {r['achievement_key'] for r in rows}

async def unlock_achievement(uid, key):
    async with db_pool.acquire() as c:
        exists = await c.fetchval("SELECT 1 FROM user_achievements WHERE user_id=$1 AND achievement_key=$2", uid, key)
        if exists: return False
        await c.execute("INSERT INTO user_achievements (user_id,achievement_key) VALUES ($1,$2)", uid, key)
        return True

async def check_achievements(uid, context):
    stats = await get_stats(uid)
    if not stats: return []
    unlocked = await user_achievements(uid)
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
        "likes_10": (stats['likes_received'] or 0) >= 10,
        "likes_50": (stats['likes_received'] or 0) >= 50,
        "views_100": (stats['profile_views'] or 0) >= 100,
    }
    async with db_pool.acquire() as c:
        invites = await c.fetchval("SELECT COUNT(*) FROM users WHERE referred_by=$1", uid) or 0
    checks["invite_1"] = invites >= 1
    checks["invite_5"] = invites >= 5
    checks["invite_25"] = invites >= 25
    for k, ok in checks.items():
        if ok and k not in unlocked:
            if await unlock_achievement(uid, k):
                newly.append(k)
                e, title = ACHIEVEMENTS.get(k, ("🏅", k))
                try: await context.bot.send_message(uid, f"🎉 Achievement!\n\n{e} {title}")
                except: pass
    return newly

# ============ MISSIONS ============
async def mission_progress(uid, key, amt=1):
    m = DAILY_MISSIONS.get(key)
    if not m: return None
    today = datetime.now().date()
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT progress,completed FROM daily_missions WHERE user_id=$1 AND mission_key=$2 AND date=$3", uid, key, today)
        if r and r['completed']: return (r['progress'], m['target'], True, m['reward'])
        prog = (r['progress'] if r else 0) + amt
        done = prog >= m['target']
        if done:
            await c.execute("UPDATE users SET coins=coins+$1 WHERE user_id=$2", m['reward'], uid)
        await c.execute("""INSERT INTO daily_missions (user_id,mission_key,date,progress,completed)
            VALUES ($1,$2,$3,$4,$5) ON CONFLICT (user_id,mission_key,date) DO UPDATE SET progress=$4,completed=$5""",
            uid, key, today, prog, done)
        return (prog, m['target'], done, m['reward'])

async def missions_status(uid):
    today = datetime.now().date()
    async with db_pool.acquire() as c:
        rows = await c.fetch("SELECT mission_key,progress,completed FROM daily_missions WHERE user_id=$1 AND date=$2", uid, today)
    out = {}
    for k, m in DAILY_MISSIONS.items():
        r = next((x for x in rows if x['mission_key'] == k), None)
        out[k] = {"progress": r['progress'] if r else 0, "completed": r['completed'] if r else False,
                  "target": m['target'], "reward": m['reward'], "text": m['text']}
    return out

# ============ REFERRAL ============
async def process_ref(new_uid, ref_id):
    if new_uid == ref_id: return False
    async with db_pool.acquire() as c:
        if not await c.fetchval("SELECT 1 FROM users WHERE user_id=$1", ref_id): return False
        if await c.fetchval("SELECT referred_by FROM users WHERE user_id=$1", new_uid) is not None: return False
        await c.execute("UPDATE users SET referred_by=$1 WHERE user_id=$2", ref_id, new_uid)
        await c.execute("UPDATE users SET coins=coins+$1 WHERE user_id=$2", REFERRAL_COIN_REWARD, ref_id)
    return True

# ============ KEYBOARDS ============
async def main_menu_kb(lang):
    on = await online_count()
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("find_partner", lang), callback_data="find_partner"),
         InlineKeyboardButton(t("chat_with_guy", lang), callback_data="chat_guy"),
         InlineKeyboardButton(t("chat_with_girl", lang), callback_data="chat_girl")],
        [InlineKeyboardButton(t("group_rooms", lang), callback_data="group_menu"),
         InlineKeyboardButton(t("voice_room", lang), callback_data="voice_menu")],
        [InlineKeyboardButton(t("browse_people", lang), callback_data="browse_people"),
         InlineKeyboardButton(t("nearby_people", lang), callback_data="nearby_people")],
        [InlineKeyboardButton(t("my_profile", lang), callback_data="my_profile"),
         InlineKeyboardButton(t("edit_profile", lang), callback_data="edit_profile")],
        [InlineKeyboardButton(t("coins", lang), callback_data="show_coins"),
         InlineKeyboardButton(t("premium", lang), callback_data="show_vip")],
        [InlineKeyboardButton(t("achievements", lang), callback_data="show_achievements"),
         InlineKeyboardButton(t("missions", lang), callback_data="show_missions")],
        [InlineKeyboardButton(t("friends", lang), callback_data="show_friends"),
         InlineKeyboardButton(t("leaderboard", lang), callback_data="leaderboard")],
        [InlineKeyboardButton(t("invite", lang), callback_data="show_link"),
         InlineKeyboardButton(t("anon_link", lang), callback_data="show_anon_link"),
         InlineKeyboardButton(t("language", lang), callback_data="change_language")],
        [InlineKeyboardButton(t("status", lang), callback_data="status_menu"),
         InlineKeyboardButton(t("support", lang), callback_data="support_ticket")],
        [InlineKeyboardButton(f"🟢 {on}", callback_data="refresh_online"),
         InlineKeyboardButton(t("safety", lang), callback_data="safety"),
         InlineKeyboardButton(t("help", lang), callback_data="help")],
    ])

def chat_kb(pid, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("next_person", lang), callback_data="next_partner"),
         InlineKeyboardButton(t("end_chat", lang), callback_data="end_chat")],
        [InlineKeyboardButton(t("truth_or_dare", lang), callback_data="tod_start"),
         InlineKeyboardButton(t("ice_breaker", lang), callback_data="ice_breaker")],
        [InlineKeyboardButton(t("compatibility", lang), callback_data="compat"),
         InlineKeyboardButton(t("chat_summary", lang), callback_data="chat_summary")],
        [InlineKeyboardButton(t("chat_extend", lang), callback_data="extend_chat")],
        [InlineKeyboardButton(t("contact_profile", lang), callback_data=f"viewprof_{pid}"),
         InlineKeyboardButton(t("like"), callback_data=f"like_{pid}")],
        [InlineKeyboardButton(t("delete_msgs", lang), callback_data="delete_msgs")],
        [InlineKeyboardButton(t("report", lang), callback_data=f"report_{pid}"),
         InlineKeyboardButton("👫 Friend", callback_data=f"addfriend_{pid}")],
    ])

# Fix: like label
STRINGS["like"] = {"bn":"❤️ লাইক","en":"❤️ Like","hi":"❤️ लाइक","ru":"❤️ Лайк"}

# ============ /START ============
async def start(update, context):
    uid = update.effective_user.id
    await touch_user(uid)
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
            anon_target = await resolve_anon_link(code)
            if anon_target == uid: anon_target = None
        except Exception as e:
            logger.error(f"Anon link error: {e}")

    async with db_pool.acquire() as c:
        u = await c.fetchrow("SELECT * FROM users WHERE user_id=$1", uid)
        if not u:
            await c.execute("INSERT INTO users (user_id) VALUES ($1)", uid)
            await get_anon_id(uid)
            if ref_id:
                try:
                    if await process_ref(uid, ref_id):
                        rl = await get_lang(ref_id)
                        await context.bot.send_message(ref_id, t("referral_bonus", rl, coins=REFERRAL_COIN_REWARD))
                except: pass
            context.user_data.clear()
            context.user_data['reg_step'] = 'language'
            if anon_target:
                context.user_data['anon_target'] = anon_target
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
            if await process_ref(uid, ref_id):
                try:
                    rl = await get_lang(ref_id)
                    await context.bot.send_message(ref_id, t("referral_bonus", rl, coins=REFERRAL_COIN_REWARD))
                except: pass

    if await daily_bonus(uid):
        await update.message.reply_text(t("daily_bonus", lang, coins=DAILY_BONUS_COINS))

    streak, is_new = await update_streak(uid)
    if is_new and streak > 1:
        await update.message.reply_text(t("streak_msg", lang, n=streak))

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
        await update.message.reply_text(t("ask_lang_pref", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🇧🇩 Bangla", callback_data="plang_bn"),
                 InlineKeyboardButton("🇬🇧 English", callback_data="plang_en")],
                [InlineKeyboardButton("🇮🇳 Hindi", callback_data="plang_hi"),
                 InlineKeyboardButton("🌍 Any", callback_data="plang_any")]]))
        return

    # If anon target present, connect
    if anon_target:
        try:
            await connect_anon(uid, anon_target, context, lang)
            return
        except Exception as e:
            logger.error(f"Anon connect fail: {e}")

    chat = await get_chat(uid)
    if chat:
        await update.message.reply_text(t("partner_found", lang), reply_markup=chat_kb(chat['partner_id'], lang))
        return

    on = await online_count()
    await update.message.reply_text(f"{t('main_menu', lang)}\n\n{t('online_count', lang, n=on)}",
                                    reply_markup=await main_menu_kb(lang))


async def connect_anon(uid, target_uid, context, lang):
    """Connect user directly with anon link owner."""
    if uid == target_uid:
        await context.bot.send_message(uid, "❌ Cannot connect to self.")
        return
    # Check target exists
    async with db_pool.acquire() as c:
        target = await c.fetchrow("SELECT user_id FROM users WHERE user_id=$1 AND is_banned=FALSE", target_uid)
        if not target:
            await context.bot.send_message(uid, "❌ User not found.")
            return
        # Check blocks
        blocked = await c.fetchrow("""SELECT 1 FROM blocks WHERE
            (blocker_id=$1 AND blocked_id=$2) OR (blocker_id=$2 AND blocked_id=$1)""", uid, target_uid)
        if blocked:
            await context.bot.send_message(uid, "❌ Cannot connect.")
            return
        # Create chat
        await c.execute("""INSERT INTO active_chats (user_id,partner_id) VALUES ($1,$2),($2,$1)
            ON CONFLICT (user_id) DO UPDATE SET partner_id=EXCLUDED.partner_id, started_at=NOW(), is_ai=FALSE""", uid, target_uid)
        await c.execute("UPDATE users SET total_chats=total_chats+1 WHERE user_id IN ($1,$2)", uid, target_uid)
    
    my_lang = lang
    my_tg = await context.bot.get_me()
    pl = await get_lang(target_uid)
    
    await context.bot.send_message(uid, t("partner_found", my_lang), reply_markup=chat_kb(target_uid, my_lang))
    try:
        await context.bot.send_message(target_uid, t("partner_found", pl), reply_markup=chat_kb(uid, pl))
    except: pass
    
    # Timers
    context.job_queue.run_once(chat_timer_end, CHAT_TIMER_SECONDS, data={'user_id': uid}, name=f"end1_{uid}")
    context.job_queue.run_once(chat_timer_end, CHAT_TIMER_SECONDS, data={'user_id': target_uid}, name=f"end2_{target_uid}")


# ============ LANGUAGE ============
async def language_callback(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    lang = q.data.replace("lang_", "")
    if lang not in ("bn", "en", "hi", "ru"): lang = "en"
    await set_lang(uid, lang)
    prof = await get_profile(uid)
    if prof and prof.get('display_name'):
        on = await online_count()
        try:
            await q.edit_message_text(f"{t('language_changed', lang)}\n\n{t('main_menu', lang)}\n\n{t('online_count', lang, n=on)}",
                                      reply_markup=await main_menu_kb(lang))
        except:
            try: await q.message.reply_text(t("main_menu", lang), reply_markup=await main_menu_kb(lang))
            except: pass
        return
    context.user_data['reg_step'] = 'age_gate'
    await q.edit_message_text(t("welcome", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("age_yes", lang), callback_data="age_yes")],
            [InlineKeyboardButton(t("age_no", lang), callback_data="age_no")]]))


async def change_language(update, context):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(t("language_select", "en"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
             InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]]))


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


# ============ TEXT HANDLER ============
async def handle_text(update, context):
    uid = update.effective_user.id
    await touch_user(uid)
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
                    f"💰 Payment Proof\n\n👤 {update.effective_user.full_name}\n🆔 `{uid}`\n📦 {tier}\n💳 {method}\n\n"
                    f"Approve: `/approve {uid} {tier}`")
            except: pass
        async with db_pool.acquire() as c:
            await c.execute("INSERT INTO payments (user_id,tier,method,transaction_id,status) VALUES ($1,$2,$3,$4,'pending')",
                            uid, tier, method, text[:200])
        await update.message.reply_text(t("payment_sent", lang))
        for k in ['awaiting_payment','payment_tier','payment_method']: context.user_data.pop(k, None)
        return

    # Support ticket
    if context.user_data.get('awaiting_support'):
        async with db_pool.acquire() as c:
            await c.execute("INSERT INTO support_tickets (user_id,message) VALUES ($1,$2)", uid, text)
        for aid in ADMIN_IDS:
            try: await context.bot.send_message(aid, f"🎫 Ticket\n👤 `{uid}`\n📝 {text[:400]}\n\nReply: `/reply_ticket <id> <msg>`")
            except: pass
        await update.message.reply_text("✅ Ticket sent!")
        context.user_data.pop('awaiting_support', None); return

    # Status post
    if context.user_data.get('posting_status'):
        async with db_pool.acquire() as c:
            await c.execute("INSERT INTO statuses (user_id,content,expires_at) VALUES ($1,$2,NOW()+INTERVAL '24 hours')", uid, text[:300])
        await update.message.reply_text("✅ Status posted! (24h)")
        context.user_data.pop('posting_status', None); return

    # Registration steps
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

    if step == 'city':
        if len(text) < 2 or len(text) > 50:
            await update.message.reply_text("⚠️ 2-50 chars"); return
        await set_city(uid, text[:50])
        context.user_data['reg_step'] = None
        # Check anon target
        anon_t = context.user_data.pop('anon_target', None)
        if anon_t:
            try: await connect_anon(uid, anon_t, context, lang); return
            except: pass
        on = await online_count()
        await update.message.reply_text(f"{t('reg_done', lang)}\n\n{t('online_count', lang, n=on)}",
                                        reply_markup=await main_menu_kb(lang))
        return

    if step == 'bio':
        await save_profile(uid, bio=text[:200])
        context.user_data['reg_step'] = 'city'
        await update.message.reply_text(t("ask_city", lang)); return

    if step in ('gender','pref_gender','interest','pref_language'):
        await update.message.reply_text("⚠️ Use buttons"); return

    # Edit profile
    es = context.user_data.get('edit_step')
    if es:
        if es == 'name': await save_profile(uid, display_name=text[:50])
        elif es == 'bio': await save_profile(uid, bio=text[:200])
        elif es == 'city': await set_city(uid, text[:50])
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

    # Chat message
    await handle_chat_msg(update, context)


# ============ REG CALLBACKS ============
async def gender_callback(update, context):
    q = update.callback_query; await q.answer()
    g = q.data.split("_")[1]; uid = q.from_user.id; lang = await get_lang(uid)
    await save_profile(uid, gender=g)
    context.user_data['reg_step'] = 'pref_gender'
    await q.edit_message_text(t("ask_pref", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("male", lang), callback_data="pref_male"),
             InlineKeyboardButton(t("female", lang), callback_data="pref_female")],
            [InlineKeyboardButton(t("any", lang), callback_data="pref_any")]]))


async def pref_gender_callback(update, context):
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


async def interest_callback(update, context):
    q = update.callback_query; await q.answer()
    i = q.data.split("_")[1]; uid = q.from_user.id; lang = await get_lang(uid)
    await save_profile(uid, interest=i)
    context.user_data['reg_step'] = 'pref_language'
    await q.edit_message_text(t("ask_lang_pref", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 Bangla", callback_data="plang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="plang_en")],
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="plang_hi"),
             InlineKeyboardButton("🌍 Any", callback_data="plang_any")]]))


async def pref_lang_callback(update, context):
    q = update.callback_query; await q.answer()
    pl = q.data.split("_")[1]; uid = q.from_user.id; lang = await get_lang(uid)
    await save_profile(uid, pref_language=pl)
    context.user_data['reg_step'] = 'bio'
    await q.edit_message_text(t("ask_bio", lang))


# ============ MAIN MENU ============
async def main_menu_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    on = await online_count()
    try: await q.edit_message_text(f"{t('main_menu', lang)}\n\n{t('online_count', lang, n=on)}",
                                   reply_markup=await main_menu_kb(lang))
    except: pass


async def refresh_online(update, context):
    q = update.callback_query; uid = q.from_user.id; lang = await get_lang(uid)
    on = await online_count()
    await q.answer(t("online_count", lang, n=on), show_alert=True)


# ============ FIND PARTNER (with Guy/Girl/Same Age) ============
async def find_partner(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id; await touch_user(uid); lang = await get_lang(uid)
    prof = await get_profile(uid)
    if not prof:
        await q.edit_message_text(t("reg_first", lang)); return
    
    # Determine pref based on button
    data = q.data
    if data == "chat_guy": pref = "male"
    elif data == "chat_girl": pref = "female"
    else: pref = prof.get('pref_gender') or 'any'
    
    await perform_search(update, context, uid, pref, lang)


async def perform_search(update, context, uid, pref_override, lang):
    """Core search logic with same-age support."""
    prof = await get_profile(uid)
    ex = await get_chat(uid)
    if ex:
        await safe_edit_search(update, t("already_in_chat", lang), chat_kb(ex['partner_id'], lang))
        return

    # Chat limit
    if not await is_vip(uid):
        async with db_pool.acquire() as c:
            r = await c.fetchrow("SELECT chats_today,chats_today_date FROM users WHERE user_id=$1", uid)
            today = datetime.now().date()
            if r and r['chats_today_date'] == today and (r['chats_today'] or 0) >= MAX_DAILY_CHATS_FREE:
                await safe_edit_search(update, t("chat_limit_reached", lang),
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton(t("premium", lang), callback_data="show_vip")],
                        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
                return
            if not r or r['chats_today_date'] != today:
                await c.execute("UPDATE users SET chats_today=1,chats_today_date=$1 WHERE user_id=$2", today, uid)
            else:
                await c.execute("UPDATE users SET chats_today=chats_today+1 WHERE user_id=$1", uid)

    g = prof.get('gender') or 'any'
    pg = pref_override
    it = prof.get('interest') or 'any'
    pl = prof.get('pref_language') or 'any'
    ag = prof.get('age') or 18
    mi = prof.get('min_age') or 18
    ma = prof.get('max_age') or 99
    vip = await is_vip(uid)
    same_age = await get_same_age(uid)

    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM match_queue WHERE user_id=$1", uid)
        rows = await c.fetch("""SELECT mq.* FROM match_queue mq WHERE mq.user_id != $1
            AND NOT EXISTS (SELECT 1 FROM blocks WHERE (blocker_id=$1 AND blocked_id=mq.user_id)
            OR (blocker_id=mq.user_id AND blocked_id=$1))
            ORDER BY mq.is_vip DESC, mq.queued_at ASC LIMIT 50""", uid)
        cands = [dict(r) for r in rows]

    def score(c):
        s = 0
        # Gender filter
        if pg != 'any' and c['gender'] != pg: return -1
        if c['pref_gender'] != 'any' and c['pref_gender'] != g: return -1
        s += 15
        # Age filter
        ca = c['age'] if c['age'] else 18
        if ca < mi or ca > ma: return -1
        cmi = c['min_age'] if c['min_age'] else 18
        cma = c['max_age'] if c['max_age'] else 99
        if ag < cmi or ag > cma: return -1
        # Same age strict
        if same_age and abs(ca - ag) > 2: return -1
        if same_age: s += 10
        # Interest
        if it != 'any' and c['interest'] == it: s += 5
        # Language
        if pl != 'any' and c['pref_language'] == pl: s += 3
        # VIP priority
        if c['is_vip']: s += 2
        return s

    best = None; bs = -1
    for c in cands:
        sc = score(c)
        if sc > bs: best = c; bs = sc

    if best and bs >= 10:
        pid = best['user_id']
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM match_queue WHERE user_id=$1", pid)
            await c.execute("""INSERT INTO active_chats (user_id,partner_id) VALUES ($1,$2),($2,$1)
                ON CONFLICT (user_id) DO UPDATE SET partner_id=EXCLUDED.partner_id, started_at=NOW(), is_ai=FALSE""", uid, pid)
            await c.execute("UPDATE users SET total_chats=total_chats+1 WHERE user_id IN ($1,$2)", uid, pid)
            await c.execute("INSERT INTO chat_log (user_id,partner_id) VALUES ($1,$2)", uid, pid)

        lvl = await add_xp(uid, XP_PER_CHAT)
        await mission_progress(uid, "chat_3", 1)
        if lvl:
            try: await context.bot.send_message(uid, t("level_up", lang, level=lvl))
            except: pass
        await check_achievements(uid, context)

        pl_lang = await get_lang(pid)
        await safe_edit_search(update, t("partner_found", lang), chat_kb(pid, lang))
        try:
            await context.bot.send_message(pid, t("partner_found", pl_lang), reply_markup=chat_kb(uid, pl_lang))
        except: pass

        reward = CHAT_COIN_REWARD * 2 if vip else CHAT_COIN_REWARD
        await add_coins(uid, reward)

        timer = CHAT_TIMER_SECONDS * 2 if vip else CHAT_TIMER_SECONDS
        context.job_queue.run_once(chat_timer_end, timer, data={'user_id': uid}, name=f"end1_{uid}")
        context.job_queue.run_once(chat_timer_end, timer, data={'user_id': pid}, name=f"end2_{pid}")
    else:
        async with db_pool.acquire() as c:
            await c.execute("""INSERT INTO match_queue (user_id,gender,pref_gender,pref_language,interest,is_vip,age,min_age,max_age,same_age)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT (user_id) DO UPDATE SET
                queued_at=NOW(), is_vip=EXCLUDED.is_vip, pref_gender=EXCLUDED.pref_gender,
                pref_language=EXCLUDED.pref_language, interest=EXCLUDED.interest,
                gender=EXCLUDED.gender, age=EXCLUDED.age, min_age=EXCLUDED.min_age,
                max_age=EXCLUDED.max_age, same_age=EXCLUDED.same_age""",
                uid, g, pg, pl, it, vip, ag, mi, ma, same_age)

        same_age_lbl = "🟢 ON" if same_age else "⚪ OFF"
        text = (
            f"🔍 {t('searching', lang)}\n\n"
            f"⚙️ {t('same_age', lang)}: {same_age_lbl}"
        )
        await safe_edit_search(update, text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton(f"⚙️ Same Age: {same_age_lbl}", callback_data="toggle_same_age")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
                [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
                [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
                [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))

        jn = f"queue_timeout_{uid}"
        for j in context.job_queue.get_jobs_by_name(jn): j.schedule_removal()
        context.job_queue.run_once(queue_timeout, QUEUE_TIMEOUT_SECONDS, data={'user_id': uid}, name=jn)


async def safe_edit_search(update, text, reply_markup=None):
    """Safely edit or send message (works both from callback and message)."""
    q = update.callback_query
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            if q.message:
                await q.message.reply_text(text, reply_markup=reply_markup)
        except: pass


async def toggle_same_age_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    new_val = await toggle_same_age(uid)
    same_age_lbl = "🟢 ON" if new_val else "⚪ OFF"
    prof = await get_profile(uid)
    pg = prof.get('pref_gender') or 'any'
    # Re-run search with new filter
    await q.edit_message_text(
        f"🔍 {t('searching', lang)}\n\n⚙️ {t('same_age', lang)}: {same_age_lbl}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"⚙️ Same Age: {same_age_lbl}", callback_data="toggle_same_age")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_search")],
            [InlineKeyboardButton("🤖 AI Chat", callback_data="ai_chat")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    # Re-queue
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM match_queue WHERE user_id=$1", uid)
        if r:
            await c.execute("UPDATE match_queue SET same_age=$1 WHERE user_id=$2", new_val, uid)


async def cancel_search(update, context):
    q = update.callback_query; await q.answer("Cancelled")
    uid = q.from_user.id; lang = await get_lang(uid)
    try:
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM match_queue WHERE user_id=$1", uid)
        for j in context.job_queue.get_jobs_by_name(f"queue_timeout_{uid}"): j.schedule_removal()
        on = await online_count()
        await q.edit_message_text(f"{t('search_cancelled', lang)}\n\n{t('main_menu', lang)}\n\n{t('online_count', lang, n=on)}",
                                  reply_markup=await main_menu_kb(lang))
    except Exception as e: logger.error(f"cancel: {e}")


# ============ AI CHAT ============
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
    try:
        await q.edit_message_text(t("ai_mode_on", lang),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="end_chat")]]))
    except:
        await q.message.reply_text(t("ai_mode_on", lang),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="end_chat")]]))


# ============ CHAT MSG ============
async def handle_chat_msg(update, context):
    uid = update.effective_user.id
    lang = await get_lang(uid)
    chat = await get_chat(uid)
    if not chat: return
    if rate_limited(uid, 20, 10):
        await update.message.reply_text(t("wait_moment", lang)); return
    if update.message.text and has_bad_words(update.message.text):
        await update.message.reply_text(t("spam_warning", lang)); return

    await add_xp(uid, XP_PER_MESSAGE)
    await mission_progress(uid, "msg_20", 1)

    if chat.get('is_ai'):
        await handle_ai_msg(update, context, lang); return

    pid = chat['partner_id']
    rid = context.user_data.get('room_id')
    if rid:
        await handle_group_msg(update, context, rid); return
    vrid = context.user_data.get('voice_room_id')
    if vrid:
        await handle_voice_room_msg(update, context, vrid); return

    try:
        await context.bot.copy_message(chat_id=pid, from_chat_id=uid, message_id=update.message.message_id)
        async with db_pool.acquire() as c:
            await c.execute("""UPDATE chat_log SET messages=messages+1
                WHERE id=(SELECT id FROM chat_log WHERE user_id=$1 AND ended_at IS NULL ORDER BY id DESC LIMIT 1)""", uid)
    except Exception as e: logger.error(f"Copy: {e}")


async def handle_ai_msg(update, context, lang):
    uid = update.effective_user.id
    text = update.message.text or ""
    if not text or has_bad_words(text): return
    typing = await update.message.reply_text("🤖...")
    hist = context.user_data.get('ai_history', [])
    hist.append({"role": "user", "content": text})
    sys = "You are a friendly anonymous chat partner. Reply in user's language. Short replies under 300 chars. Be warm, funny. Use emojis."
    ans = None
    for m in AI_MODELS:
        try:
            r = await asyncio.to_thread(groq_client.chat.completions.create,
                model=m, messages=[{"role": "system", "content": sys}] + hist[-10:],
                temperature=0.8, max_tokens=400)
            ans = r.choices[0].message.content.strip()
            break
        except Exception as e: logger.warning(f"AI {m}: {e}")
    if not ans:
        await typing.edit_text("🤖 Busy, try again."); return
    hist.append({"role": "assistant", "content": ans})
    context.user_data['ai_history'] = hist[-10:]
    await typing.edit_text(ans)


# ============ GROUP ROOMS ============
async def group_menu(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        rooms = await c.fetch("""SELECT r.room_id,r.name,COUNT(m.user_id) cnt FROM group_rooms r
            LEFT JOIN group_members m ON m.room_id=r.room_id WHERE r.is_active=TRUE
            GROUP BY r.room_id,r.name HAVING COUNT(m.user_id) < $1 ORDER BY r.room_id DESC LIMIT 5""", GROUP_ROOM_MAX)
    rows = []
    for r in rooms:
        nm = r['name'] or f"Room {r['room_id']}"
        rows.append([InlineKeyboardButton(f"👥 {nm} ({r['cnt']}/{GROUP_ROOM_MAX})", callback_data=f"joinroom_{r['room_id']}")])
    rows.append([InlineKeyboardButton("➕ Create Room", callback_data="create_room")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    try: await q.edit_message_text(t("group_room_menu", lang), reply_markup=InlineKeyboardMarkup(rows))
    except: await q.message.reply_text(t("group_room_menu", lang), reply_markup=InlineKeyboardMarkup(rows))


async def create_room(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    async with db_pool.acquire() as c:
        rid = await c.fetchval("INSERT INTO group_rooms (host_id) VALUES ($1) RETURNING room_id", uid)
        await c.execute("INSERT INTO group_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['room_id'] = rid
    try:
        await q.edit_message_text(f"✅ Room {rid} created!\n\nShare ID: `{rid}`\nOr send: /joinroom {rid}\n\n/leaveroom to leave.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_room")]]))
    except:
        await q.message.reply_text(f"✅ Room {rid} created!\n\n/joinroom {rid}")


async def join_room_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    rid = int(q.data.split("_")[1])
    async with db_pool.acquire() as c:
        room = await c.fetchrow("SELECT * FROM group_rooms WHERE room_id=$1 AND is_active=TRUE", rid)
        if not room:
            await q.edit_message_text(t("group_room_not_found", lang), reply_markup=await main_menu_kb(lang)); return
        cnt = await c.fetchval("SELECT COUNT(*) FROM group_members WHERE room_id=$1", rid)
        if cnt >= GROUP_ROOM_MAX:
            await q.edit_message_text(t("group_room_full", lang), reply_markup=await main_menu_kb(lang)); return
        await c.execute("INSERT INTO group_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['room_id'] = rid
    await q.edit_message_text(f"✅ Joined Room {rid}!\n\n/leaveroom to exit.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_room")]]))


async def join_room_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    if not context.args:
        await update.message.reply_text("Usage: /joinroom <id>"); return
    try: rid = int(context.args[0])
    except: await update.message.reply_text("❌ Invalid"); return
    async with db_pool.acquire() as c:
        room = await c.fetchrow("SELECT * FROM group_rooms WHERE room_id=$1 AND is_active=TRUE", rid)
        if not room:
            await update.message.reply_text(t("group_room_not_found", lang)); return
        cnt = await c.fetchval("SELECT COUNT(*) FROM group_members WHERE room_id=$1", rid)
        if cnt >= GROUP_ROOM_MAX:
            await update.message.reply_text(t("group_room_full", lang)); return
        await c.execute("INSERT INTO group_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['room_id'] = rid
    await update.message.reply_text(f"✅ Joined Room {rid}!")


async def leave_room_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    rid = context.user_data.pop('room_id', None)
    if rid:
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM group_members WHERE room_id=$1 AND user_id=$2", rid, uid)
    await q.edit_message_text(t("group_room_left", lang), reply_markup=await main_menu_kb(lang))


async def leave_room_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    rid = context.user_data.pop('room_id', None)
    if not rid:
        await update.message.reply_text("❌ Not in room"); return
    async with db_pool.acquire() as c:
        await c.execute("DELETE FROM group_members WHERE room_id=$1 AND user_id=$2", rid, uid)
    await update.message.reply_text(t("group_room_left", lang))


async def handle_group_msg(update, context, rid):
    uid = update.effective_user.id
    async with db_pool.acquire() as c:
        mem = await c.fetch("SELECT user_id FROM group_members WHERE room_id=$1 AND user_id != $2", rid, uid)
    for m in mem:
        try: await context.bot.copy_message(chat_id=m['user_id'], from_chat_id=uid, message_id=update.message.message_id)
        except: pass


# ============ VOICE ROOMS ============
async def voice_menu(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not await is_vip(uid):
        try:
            await q.edit_message_text("⭐ Voice Room is Premium only!\n\nUpgrade to Diamond tier.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐ Get Premium", callback_data="show_vip")],
                    [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
        except: pass
        return
    async with db_pool.acquire() as c:
        rooms = await c.fetch("""SELECT r.room_id,COUNT(m.user_id) cnt FROM voice_rooms r
            LEFT JOIN voice_members m ON m.room_id=r.room_id WHERE r.is_active=TRUE
            GROUP BY r.room_id HAVING COUNT(m.user_id) < 6 ORDER BY r.room_id DESC LIMIT 5""")
    rows = []
    for r in rooms:
        rows.append([InlineKeyboardButton(f"🎤 Room {r['room_id']} ({r['cnt']}/6)", callback_data=f"jvr_{r['room_id']}")])
    rows.append([InlineKeyboardButton("➕ Create Voice Room", callback_data="create_vr")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    try: await q.edit_message_text("🎤 Voice Rooms\n\nJoin or create a voice-only room.", reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def create_voice_room(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not await is_vip(uid):
        await q.answer("Premium only", show_alert=True); return
    async with db_pool.acquire() as c:
        rid = await c.fetchval("INSERT INTO voice_rooms (host_id) VALUES ($1) RETURNING room_id", uid)
        await c.execute("INSERT INTO voice_members (room_id,user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", rid, uid)
    context.user_data['voice_room_id'] = rid
    await q.edit_message_text(f"🎤 Voice Room {rid} created!\n\nSend voice notes.\n\n/leavevoice to exit.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_vr")]]))


async def join_voice_room(update, context):
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
    await q.edit_message_text(f"🎤 Joined Voice Room {rid}!\n\nSend voice notes.\n\n/leavevoice to exit.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Leave", callback_data="leave_vr")]]))


async def leave_voice_room(update, context):
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
        try: await q.edit_message_text("🎤 Left.", reply_markup=await main_menu_kb(lang))
        except: pass
    else:
        await update.message.reply_text("🎤 Left.")


async def handle_voice_room_msg(update, context, rid):
    uid = update.effective_user.id
    if not (update.message.voice or update.message.audio): return
    async with db_pool.acquire() as c:
        mem = await c.fetch("SELECT user_id FROM voice_members WHERE room_id=$1 AND user_id != $2", rid, uid)
    for m in mem:
        try: await context.bot.copy_message(chat_id=m['user_id'], from_chat_id=uid, message_id=update.message.message_id)
        except: pass


# ============ LIKE SYSTEM ============
async def like_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try:
        pid = int(q.data.split("_")[1])
    except: return
    ok = await add_like(uid, pid)
    if ok:
        await q.answer(t("liked_success", lang), show_alert=False)
        await mission_progress(uid, "like_3", 1)
        try:
            p_lang = await get_lang(pid)
            await context.bot.send_message(pid, t("liked_you", p_lang))
        except: pass
    else:
        await q.answer("Already liked", show_alert=False)


async def view_likers(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    likers = await get_likers(uid, limit=20)
    if not likers:
        try: await q.edit_message_text(t("no_likers", lang), reply_markup=await main_menu_kb(lang))
        except: pass
        return
    text = f"❤️ {t('view_likers', lang)}\n\n"
    for l in likers:
        aid = l.get('anon_id') or f"user_{l['liker_id']}"
        name = l.get('display_name') or "Anonymous"
        text += f"• {name} (@{aid})\n"
    try: await q.edit_message_text(text[:4000], reply_markup=await main_menu_kb(lang))
    except: pass


async def view_profile_cb(update, context):
    """View partner's profile."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try:
        pid = int(q.data.split("_")[1])
    except: return
    # Record view
    await record_view(uid, pid)
    # Notify target
    try:
        p_lang = await get_lang(pid)
        await context.bot.send_message(pid, t("partner_viewed", p_lang))
    except: pass
    prof = await get_profile(pid)
    stats = await get_stats(pid)
    if not prof:
        await q.answer("Profile not found", show_alert=True); return
    gm = {"male":"👦","female":"👧","other":"🌈"}
    aid = (stats or {}).get('anon_id') or f"user_{pid}"
    text = (
        f"👤 {prof.get('display_name', 'Anon')}\n"
        f"🆔 /{aid}\n"
        f"🎂 Age: {prof.get('age', '?')} {gm.get(prof.get('gender'), '?')}\n"
        f"🏙️ City: {(stats or {}).get('city') or 'N/A'}\n"
        f"💡 Interest: {prof.get('interest', 'any')}\n"
        f"❤️ Likes: {(stats or {}).get('likes_received', 0)}\n"
        f"👀 Views: {(stats or {}).get('profile_views', 0)}\n"
        f"⭐ {'Premium' if (stats or {}).get('is_vip') else 'Free'}\n\n"
        f"💬 {(prof.get('bio') or 'N/A')[:200]}"
    )
    kb_rows = [
        [InlineKeyboardButton("❤️ Like", callback_data=f"like_{pid}")],
        [InlineKeyboardButton("💬 Message", callback_data=f"msg_user_{pid}")],
        [InlineKeyboardButton("🚫 Block", callback_data=f"block_{pid}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
    try: await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
    except: await q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))


async def msg_user_cb(update, context):
    """Start chat with specific user."""
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[2])
    except: return
    # Direct connect
    await connect_anon(uid, pid, context, lang)


async def block_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[1])
    except: return
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO blocks (blocker_id,blocked_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", uid, pid)
        await c.execute("DELETE FROM active_chats WHERE user_id=$1 OR user_id=$2", uid, pid)
    await q.answer("✅ Blocked", show_alert=True)


async def show_blocked(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    blocked = await get_blocked(uid)
    if not blocked:
        try: await q.edit_message_text(t("no_blocked", lang), reply_markup=await main_menu_kb(lang))
        except: pass
        return
    rows = []
    for b in blocked[:10]:
        name = b.get('display_name') or f"User {b['blocked_id']}"
        rows.append([InlineKeyboardButton(f"🔓 Unblock {name[:20]}", callback_data=f"unblock_{b['blocked_id']}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    try: await q.edit_message_text(t("blocked_users", lang), reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def unblock_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: pid = int(q.data.split("_")[1])
    except: return
    await unblock_user(uid, pid)
    await q.answer(t("unblocked", lang), show_alert=True)
    await show_blocked(update, context)


# ============ BROWSE / NEARBY ============
async def browse_people_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    users = await browse_people(uid, limit=10)
    if not users:
        try: await q.edit_message_text(t("no_users", lang), reply_markup=await main_menu_kb(lang))
        except: pass
        return
    rows = []
    for u in users:
        aid = u.get('anon_id') or f"user_{u['user_id']}"
        name = u.get('display_name') or "Anon"
        verified = "✅" if u.get('is_verified') else ""
        rows.append([InlineKeyboardButton(f"{verified} {name} (@{aid})", callback_data=f"viewprof_{u['user_id']}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    try: await q.edit_message_text(t("browse_title", lang), reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def nearby_people_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        city = await c.fetchval("SELECT city FROM users WHERE user_id=$1", uid)
    if not city:
        try: await q.edit_message_text(t("choose_city", lang),
            reply_markup=city_kb(lang)); return
        except: pass
        return
    users = await nearby_people(uid, limit=10)
    if not users:
        try: await q.edit_message_text(t("no_users", lang), reply_markup=await main_menu_kb(lang))
        except: pass
        return
    rows = []
    for u in users:
        aid = u.get('anon_id') or f"user_{u['user_id']}"
        name = u.get('display_name') or "Anon"
        rows.append([InlineKeyboardButton(f"📍 {name} ({u.get('city', '')})", callback_data=f"viewprof_{u['user_id']}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    try: await q.edit_message_text(f"{t('nearby_title', lang)} ({city})", reply_markup=InlineKeyboardMarkup(rows))
    except: pass


def city_kb(lang):
    rows = []
    row = []
    for i, city in enumerate(CITIES[:24]):
        row.append(InlineKeyboardButton(city, callback_data=f"setcity_{city[:20]}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


async def set_city_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try: city = q.data.replace("setcity_", "")[:50]
    except: return
    await set_city(uid, city)
    await q.answer(f"✅ {city}", show_alert=True)


async def choose_city_cb(update, context):
    q = update.callback_query; await q.answer()
    lang = await get_lang(q.from_user.id)
    try: await q.edit_message_text(t("choose_city", lang), reply_markup=city_kb(lang))
    except: pass


# ============ ANON LINK ============
async def show_anon_link(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    code = await get_or_create_anon_link(uid)
    if not code:
        await q.answer("Error", show_alert=True); return
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=anon_{code}"
    try: await q.edit_message_text(t("anon_link_msg", lang, link=link),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    except: pass


async def link_anon_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    code = await get_or_create_anon_link(uid)
    if not code:
        await update.message.reply_text("Error"); return
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=anon_{code}"
    await update.message.reply_text(t("anon_link_msg", lang, link=link))


# ============ GAMES / ICE / COMPAT ============
async def tod_start(update, context):
    q = update.callback_query; await q.answer()
    try:
        await q.edit_message_text("🎲 Truth or Dare:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎯 Truth", callback_data="tod_truth"),
                 InlineKeyboardButton("🔥 Dare", callback_data="tod_dare")],
                [InlineKeyboardButton("🎲 Random", callback_data="tod_random")]]))
    except: pass


async def tod_truth(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    async with db_pool.acquire() as c:
        await c.execute("UPDATE users SET truth_count=truth_count+1 WHERE user_id=$1", uid)
    await q.message.reply_text(f"🎯 Truth:\n\n{random.choice(TRUTH_QUESTIONS)}")


async def tod_dare(update, context):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(f"🔥 Dare:\n\n{random.choice(DARE_TASKS)}")


async def tod_random(update, context):
    q = update.callback_query; await q.answer()
    if random.random() > 0.5: await tod_truth(update, context)
    else: await tod_dare(update, context)


async def ice_breaker(update, context):
    q = update.callback_query; await q.answer()
    await q.message.reply_text(f"🧊 Ice-Breaker:\n\n{random.choice(ICE_BREAKERS)}")


async def compat(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    chat = await get_chat(uid)
    if not chat or chat.get('is_ai'):
        await q.answer("No real partner", show_alert=True); return
    pid = chat['partner_id']
    p1 = await get_profile(uid); p2 = await get_profile(pid)
    if not p1 or not p2:
        await q.answer("No data", show_alert=True); return
    score = 0
    if p1.get('interest') == p2.get('interest') and p1.get('interest') != 'any': score += 40
    if p1.get('pref_language') == p2.get('pref_language'): score += 20
    if abs((p1.get('age') or 25) - (p2.get('age') or 25)) <= 5: score += 20
    if p1.get('gender') == p2.get('pref_gender') or p2.get('pref_gender') == 'any': score += 20
    score = min(score, 100)
    bar = "🟩" * (score // 10) + "⬜" * (10 - score // 10)
    await q.message.reply_text(f"💯 Compatibility: {score}%\n\n{bar}")


async def extend_chat(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    coins = await get_coins(uid)
    if coins < 20:
        await q.answer("Need 20 coins", show_alert=True); return
    if await deduct_coins(uid, 20):
        await q.answer("⏱️ +10 min added!", show_alert=True)
        for jn in [f"end1_{uid}", f"end2_{uid}"]:
            for j in context.job_queue.get_jobs_by_name(jn): j.schedule_removal()
        chat = await get_chat(uid)
        if chat:
            pid = chat['partner_id']
            context.job_queue.run_once(chat_timer_end, CHAT_TIMER_SECONDS, data={'user_id': uid}, name=f"end1_{uid}")
            context.job_queue.run_once(chat_timer_end, CHAT_TIMER_SECONDS, data={'user_id': pid}, name=f"end2_{pid}")


async def chat_summary(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    if not groq_client:
        await q.answer("AI off", show_alert=True); return
    chat = await get_chat(uid)
    if not chat:
        await q.answer("No chat", show_alert=True); return
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT messages FROM chat_log WHERE user_id=$1 AND ended_at IS NULL ORDER BY id DESC LIMIT 1", uid)
    msgs = r['messages'] if r else 0
    prompt = f"Give a friendly one-line summary of an anonymous chat with {msgs} messages. Positive, under 200 chars."
    try:
        resp = await asyncio.to_thread(groq_client.chat.completions.create, model=AI_MODELS[0],
            messages=[{"role": "user", "content": prompt}], temperature=0.9, max_tokens=200)
        summary = resp.choices[0].message.content.strip()
    except: summary = f"Chat ended after {msgs} messages!"
    await q.message.reply_text(f"📝 Chat Summary:\n\n{summary}")


# ============ STATUS ============
async def status_menu(update, context):
    q = update.callback_query; await q.answer()
    rows = [
        [InlineKeyboardButton("📸 Post Status", callback_data="post_status")],
        [InlineKeyboardButton("👀 View Statuses", callback_data="view_statuses")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
    try: await q.edit_message_text("📸 Anonymous Status\n\n24-hour status.", reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def post_status(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['posting_status'] = True
    try: await q.edit_message_text("📸 Send your status text (max 300 chars):")
    except: pass


async def view_statuses(update, context):
    q = update.callback_query; await q.answer()
    lang = await get_lang(q.from_user.id)
    async with db_pool.acquire() as c:
        statuses = await c.fetch("""SELECT s.content,p.display_name,u.anon_id FROM statuses s
            LEFT JOIN profiles p ON p.user_id=s.user_id
            LEFT JOIN users u ON u.user_id=s.user_id
            WHERE s.expires_at > NOW() ORDER BY s.created_at DESC LIMIT 10""")
    if not statuses:
        try: await q.edit_message_text("📸 No active statuses.", reply_markup=await main_menu_kb(lang))
        except: pass
        return
    text = "📸 Latest Statuses:\n\n"
    for s in statuses:
        nm = s['display_name'] or "Anon"
        aid = s['anon_id'] or ""
        text += f"💬 {nm} (@{aid}): {s['content'][:100]}\n\n"
    try: await q.edit_message_text(text[:4000], reply_markup=await main_menu_kb(lang))
    except: pass


# ============ DELETE MESSAGES / CONTACT PROFILE ============
async def delete_msgs_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    # Just notify - Telegram doesn't allow bulk delete from bot
    await q.answer(t("msgs_deleted", lang), show_alert=True)


# ============ END / NEXT ============
async def end_chat_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    chat = await get_chat(uid)
    if not chat:
        try: await q.edit_message_text(t("not_in_chat", lang), reply_markup=await main_menu_kb(lang))
        except: pass
        return
    pid = chat['partner_id']; is_ai = chat.get('is_ai', False)
    await remove_chat(uid, pid)
    async with db_pool.acquire() as c:
        await c.execute("""UPDATE chat_log SET ended_at=NOW()
            WHERE user_id=$1 AND ended_at IS NULL""", uid)
    for n in [f"end1_{uid}", f"end2_{uid}", f"end1_{pid}", f"end2_{pid}"]:
        for j in context.job_queue.get_jobs_by_name(n): j.schedule_removal()
    try: await q.edit_message_text(t("chat_ended", lang), reply_markup=await main_menu_kb(lang))
    except: pass
    if not is_ai:
        try:
            pl = await get_lang(pid)
            await context.bot.send_message(pid, t("partner_ended", pl), reply_markup=await main_menu_kb(pl))
        except: pass


async def next_partner(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    chat = await get_chat(uid)
    if chat:
        pid = chat['partner_id']; is_ai = chat.get('is_ai', False)
        await remove_chat(uid, pid)
        async with db_pool.acquire() as c:
            await c.execute("UPDATE chat_log SET ended_at=NOW() WHERE user_id=$1 AND ended_at IS NULL", uid)
        for n in [f"end1_{uid}", f"end2_{uid}", f"end1_{pid}", f"end2_{pid}"]:
            for j in context.job_queue.get_jobs_by_name(n): j.schedule_removal()
        if not is_ai:
            try:
                pl = await get_lang(pid)
                await context.bot.send_message(pid, t("partner_ended", pl), reply_markup=await main_menu_kb(pl))
            except: pass
    prof = await get_profile(uid)
    pg = prof.get('pref_gender') or 'any' if prof else 'any'
    await safe_edit_search(update, "🔍...")
    await asyncio.sleep(0.5)
    await perform_search(update, context, uid, pg, lang)


async def add_friend_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; fid = int(q.data.split("_")[1])
    if uid == fid:
        await q.answer("Cannot add self", show_alert=True); return
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO friends (user_id,friend_id) VALUES ($1,$2),($2,$1) ON CONFLICT DO NOTHING", uid, fid)
    await q.answer("✅ Friend added!", show_alert=True)


# ============ REPORT ============
async def report_cb(update, context):
    q = update.callback_query; await q.answer()
    try: pid = int(q.data.split("_")[1])
    except: return
    reasons = [("Spam","spam"),("Harass","harass"),("Scam","scam"),
               ("Fake","fake"),("18-","under"),("Other","other")]
    rows = [[InlineKeyboardButton(r[0], callback_data=f"rpr_{r[1]}_{pid}")] for r in reasons]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="end_chat")])
    try: await q.edit_message_text("⚠️ Report reason:", reply_markup=InlineKeyboardMarkup(rows))
    except: pass


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
        if uniq and uniq >= AUTO_BAN_REPORT_COUNT:
            await c.execute("UPDATE users SET is_banned=TRUE WHERE user_id=$1", rid)
            await c.execute("UPDATE reports SET status='actioned' WHERE reported_id=$1", rid)
            for aid in ADMIN_IDS:
                try: await context.bot.send_message(aid, f"🚨 Auto-Ban {rid} ({uniq} reports)")
                except: pass
    try: await q.edit_message_text(t("report_blocked", lang), reply_markup=await main_menu_kb(lang))
    except: pass


# ============ PROFILE ============
async def my_profile(update, context):
    q = update.callback_query
    try: await q.answer()
    except: pass
    try:
        uid = q.from_user.id; lang = await get_lang(uid)
        prof = await get_profile(uid)
        if not prof:
            try: await q.edit_message_text(t("reg_first", lang))
            except: pass
            return
        st = await get_stats(uid) or {}
        gm = {"male":"👦","female":"👧","other":"🌈"}
        vip = await is_vip(uid); tier = await get_tier(uid) if vip else None
        xp = st.get('xp') or 0; lvl = st.get('level') or 1
        if lvl < 1: lvl = 1
        if lvl >= len(LEVEL_THRESHOLDS): nx = 0
        else: nx = LEVEL_THRESHOLDS[lvl]
        verified = "✅" if st.get('is_verified') else "❌"
        aid = st.get('anon_id') or f"user_{uid}"
        text = (
            f"👤 {prof.get('display_name', 'N/A')}\n"
            f"🆔 /{aid}\n"
            f"🎂 {prof.get('age', '?')} {gm.get(prof.get('gender'), '?')}\n"
            f"🏙️ {st.get('city') or 'N/A'}\n"
            f"💡 {prof.get('interest', 'any')}\n"
            f"🎯 {prof.get('pref_gender', 'any')} • {prof.get('pref_language', 'any')}\n"
            f"✅ Verified: {verified}\n\n"
            f"📈 Lv{lvl} • XP {xp}/{nx}\n"
            f"🪙 {st.get('coins') or 0}\n"
            f"🔥 {st.get('streak') or 0}\n"
            f"💬 {st.get('total_chats') or 0}\n"
            f"❤️ {st.get('likes_received') or 0}\n"
            f"👀 {st.get('profile_views') or 0}\n"
            f"⭐ {tier or 'Free'}\n\n"
            f"💬 {(prof.get('bio') or 'N/A')[:150]}"
        )
        kb_rows = [
            [InlineKeyboardButton(t("edit_profile", lang), callback_data="edit_profile")],
            [InlineKeyboardButton(t("view_likers", lang), callback_data="view_likers"),
             InlineKeyboardButton(t("blocked_users", lang), callback_data="show_blocked")],
            [InlineKeyboardButton(t("advanced_settings", lang), callback_data="advanced_settings")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
        try:
            await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        except Exception as e:
            logger.error(f"my_profile edit: {e}")
            try: await q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
            except: pass
    except Exception as e:
        logger.error(f"my_profile error: {e}")
        try: await q.message.reply_text(f"⚠️ Error: {str(e)[:100]}")
        except: pass


async def advanced_settings(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    same_age = await get_same_age(uid)
    sa_lbl = "🟢 ON" if same_age else "⚪ OFF"
    rows = [
        [InlineKeyboardButton(f"⚙️ Same Age: {sa_lbl}", callback_data="toggle_same_age_setting")],
        [InlineKeyboardButton("🏙️ Change City", callback_data="choose_city")],
        [InlineKeyboardButton("🎂 Birthday", callback_data="edit_birthday")],
        [InlineKeyboardButton("💎 Coins → Stars", callback_data="coins_to_stars")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
    try: await q.edit_message_text(t("advanced_settings", lang), reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def toggle_same_age_setting(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    new_val = await toggle_same_age(uid)
    await q.answer(t("same_age_on", lang) if new_val else t("same_age_off", lang), show_alert=False)
    await advanced_settings(update, context)


async def coins_to_stars_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    coins = await get_coins(uid)
    if coins < 100:
        await q.answer(t("not_enough_coins_convert", lang), show_alert=True); return
    stars = await convert_coins_to_stars(uid, coins)
    if stars > 0:
        await q.answer(t("converted", lang, coins=stars*100, stars=stars), show_alert=True)
    else:
        await q.answer("Error", show_alert=True)


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
    try: await q.edit_message_text("✏️ Edit Profile:", reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def edit_name(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['edit_step'] = 'name'
    try: await q.edit_message_text("✏️ Send new name:")
    except: pass


async def edit_bio(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['edit_step'] = 'bio'
    try: await q.edit_message_text("✏️ Send new bio:")
    except: pass


async def edit_birthday(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['edit_step'] = 'birthday'
    try: await q.edit_message_text("🎂 DD-MM-YYYY:")
    except: pass


async def edit_pref_gender(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    try:
        await q.edit_message_text(t("ask_pref", lang), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("male", lang), callback_data="setpg_male"),
             InlineKeyboardButton(t("female", lang), callback_data="setpg_female")],
            [InlineKeyboardButton(t("any", lang), callback_data="setpg_any")]]))
    except: pass


async def set_pref_gender(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    p = q.data.split("_")[1]
    await save_profile(uid, pref_gender=p)
    try: await q.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_kb(lang))
    except: pass


async def edit_interest(update, context):
    q = update.callback_query; await q.answer()
    try:
        await q.edit_message_text(t("ask_interest", "en"), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 Music", callback_data="setint_music"),
             InlineKeyboardButton("🎬 Movie", callback_data="setint_movie")],
            [InlineKeyboardButton("📚 Study", callback_data="setint_study"),
             InlineKeyboardButton("🎮 Gaming", callback_data="setint_gaming")],
            [InlineKeyboardButton("💕 Love", callback_data="setint_love"),
             InlineKeyboardButton("🌍 Any", callback_data="setint_any")]]))
    except: pass


async def set_interest(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    i = q.data.split("_")[1]
    await save_profile(uid, interest=i)
    try: await q.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_kb(lang))
    except: pass


async def edit_lang(update, context):
    q = update.callback_query; await q.answer()
    try:
        await q.edit_message_text(t("ask_lang_pref", "en"), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 Bangla", callback_data="setplang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="setplang_en")],
            [InlineKeyboardButton("🇮🇳 Hindi", callback_data="setplang_hi"),
             InlineKeyboardButton("🌍 Any", callback_data="setplang_any")]]))
    except: pass


async def set_plang(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    pl = q.data.split("_")[1]
    await save_profile(uid, pref_language=pl)
    try: await q.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_kb(lang))
    except: pass


async def edit_age_range(update, context):
    q = update.callback_query; await q.answer()
    try:
        await q.edit_message_text("📅 Age Range:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("18-25", callback_data="setage_18_25"),
             InlineKeyboardButton("25-35", callback_data="setage_25_35")],
            [InlineKeyboardButton("35-50", callback_data="setage_35_50"),
             InlineKeyboardButton("18-99", callback_data="setage_18_99")]]))
    except: pass


async def set_age(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    parts = q.data.replace("setage_", "").split("_")
    await save_profile(uid, min_age=int(parts[0]), max_age=int(parts[1]))
    try: await q.edit_message_text(t("profile_saved", lang), reply_markup=await main_menu_kb(lang))
    except: pass


# ============ ACH / MISSIONS / FRIENDS ============
async def show_achievements(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    unlocked = await user_achievements(uid)
    text = f"{t('achievements_title', lang)}\n\n"
    for k, (e, title) in ACHIEVEMENTS.items():
        text += f"{'✅' if k in unlocked else '🔒'} {e} {title}\n"
    try: await q.edit_message_text(text[:4000], reply_markup=await main_menu_kb(lang))
    except: pass


async def show_missions(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    st = await missions_status(uid)
    text = f"{t('missions_title', lang)}\n\n"
    for k, m in st.items():
        if m['completed']: text += f"✅ {m['text']} — +{m['reward']}\n"
        else: text += f"⏳ {m['text']} ({m['progress']}/{m['target']}) — +{m['reward']}\n"
    try: await q.edit_message_text(text, reply_markup=await main_menu_kb(lang))
    except: pass


async def show_friends(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT f.friend_id,p.display_name,u.anon_id FROM friends f
            LEFT JOIN profiles p ON p.user_id=f.friend_id
            LEFT JOIN users u ON u.user_id=f.friend_id WHERE f.user_id=$1 LIMIT 20""", uid)
    if not rows:
        text = "👫 No friends yet.\n\nAdd from chat."
    else:
        text = "👫 Friends:\n\n"
        for r in rows:
            name = r['display_name'] or 'Anon'
            aid = r['anon_id'] or ''
            text += f"• {name} (@{aid})\n"
    try: await q.edit_message_text(text[:4000], reply_markup=await main_menu_kb(lang))
    except: pass


# ============ SAFETY / HELP / SUPPORT ============
async def safety_cb(update, context):
    q = update.callback_query; await q.answer()
    text = "🛡 Safety:\n\n• Never share OTP\n• Never send money\n• Don't share address\n• Report bad behavior\n\n🚫 5 reports = auto-ban"
    try: await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    except: pass


async def help_cb(update, context):
    q = update.callback_query; await q.answer()
    text = "📖 Commands:\n\n/start /stop /newchat /profile /coins /vip /link /link_anon\n/leaderboard /language /missions /achievements\n/joinroom /leaveroom /leavevoice\n\n🔒 Anonymous"
    try: await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    except: pass


async def support_ticket(update, context):
    q = update.callback_query; await q.answer()
    context.user_data['awaiting_support'] = True
    try: await q.edit_message_text("🎫 Send your support message:")
    except: pass


async def reply_ticket_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /reply_ticket <ticket_id> <message>"); return
    try:
        tid = int(context.args[0]); msg = " ".join(context.args[1:])
        async with db_pool.acquire() as c:
            r = await c.fetchrow("SELECT user_id FROM support_tickets WHERE ticket_id=$1", tid)
            if not r:
                await update.message.reply_text("❌ Not found"); return
            await c.execute("UPDATE support_tickets SET admin_reply=$1,status='closed',replied_at=NOW() WHERE ticket_id=$2", msg, tid)
        try: await context.bot.send_message(r['user_id'], f"📩 Support Reply:\n\n{msg}")
        except: pass
        await update.message.reply_text("✅ Replied")
    except Exception as e: await update.message.reply_text(f"❌ {e}")


# ============ COINS / PREMIUM ============
async def show_coins(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    c = await get_coins(uid); vip = await is_vip(uid); tier = await get_tier(uid) if vip else None
    st = await get_stats(uid) or {}
    stars = st.get('stars_balance') or 0
    text = f"🪙 Coins: {c}\n💎 Stars: {stars}\n⭐ Premium: {'✅ ' + (tier or 'Active') if vip else '❌ Inactive'}"
    try: await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(t("invite", lang), callback_data="show_link")],
        [InlineKeyboardButton("⭐ Premium", callback_data="show_vip")],
        [InlineKeyboardButton("💰 Top-Up", callback_data="coins_topup")],
        [InlineKeyboardButton("💎 Coins→Stars", callback_data="coins_to_stars")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    except: pass


async def coins_topup(update, context):
    q = update.callback_query; await q.answer()
    rows = [
        [InlineKeyboardButton("100 coins — 50৳", callback_data="topup_100")],
        [InlineKeyboardButton("500 coins — 200৳", callback_data="topup_500")],
        [InlineKeyboardButton("2000 coins — 700৳", callback_data="topup_2000")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]
    try: await q.edit_message_text("💰 Coins Top-Up:\n\nSend bKash/Rocket. Admin approves.", reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def topup_select(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    parts = q.data.split("_"); coins = parts[1]
    price_map = {"100": 50, "500": 200, "2000": 700}
    price = price_map.get(coins, 50)
    context.user_data['awaiting_payment'] = True
    context.user_data['payment_method'] = f"Topup {coins} coins"
    context.user_data['payment_tier'] = f"topup_{coins}"
    try:
        await q.edit_message_text(f"💰 Top-Up {coins} coins for {price}৳\n\nSend to:\n`{BKASH_NUMBER}` (bKash)\n`{ROCKET_NUMBER}` (Rocket)\n\nThen send TrxID/Screenshot.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")]]))
    except: pass


async def show_vip(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    if await is_vip(uid):
        tier = await get_tier(uid)
        try: await q.edit_message_text(f"⭐ You're Premium! Tier: {tier}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
        except: pass
        return
    rows = []
    for k, info in PREMIUM_TIERS.items():
        rows.append([InlineKeyboardButton(f"{info['name']} — {info['price']}৳", callback_data=f"tier_{k}")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    text = t("choose_tier", lang) + "\n\n"
    for k, info in PREMIUM_TIERS.items():
        text += f"{info['name']} — {info['price']}৳ / {info['stars']}⭐\n{info['features']}\n\n"
    try: await q.edit_message_text(text[:4000], reply_markup=InlineKeyboardMarkup(rows))
    except: pass


async def tier_select(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    tier = q.data.replace("tier_", "")
    info = PREMIUM_TIERS.get(tier)
    if not info: return
    context.user_data['payment_tier'] = tier
    text = (f"{info['name']}\n💰 {info['price']}৳ — {info['days']} days\n🎁 {info['coins']} coins\n"
            f"✨ {info['features']}\n\n{t('choose_payment', lang)}")
    try: await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(t("stars_btn", lang, n=info['stars']), callback_data=f"stars_{tier}")],
        [InlineKeyboardButton("📱 bKash", callback_data=f"pay_bkash_{tier}"),
         InlineKeyboardButton("📱 Rocket", callback_data=f"pay_rocket_{tier}")],
        [InlineKeyboardButton("💎 Binance", callback_data=f"pay_binance_{tier}")],
        [InlineKeyboardButton("🪙 USDT BSC20", callback_data=f"pay_bsc20_{tier}"),
         InlineKeyboardButton("🪙 USDT TRC20", callback_data=f"pay_trc20_{tier}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    except: pass


async def stars_payment(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    tier = q.data.replace("stars_", "")
    info = PREMIUM_TIERS.get(tier)
    if not info: return
    try:
        await context.bot.send_invoice(
            chat_id=uid,
            title=f"⭐ {info['name']} Premium",
            description=f"{info['days']} days premium + {info['coins']} coins",
            payload=f"premium_{tier}_{uid}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{info['name']}", amount=info['stars'])])
    except Exception as e:
        logger.error(f"Stars invoice error: {e}")
        await q.answer("❌ Payment failed", show_alert=True)


async def payment_method(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    parts = q.data.split("_")
    method = parts[1]; tier = parts[2] if len(parts) > 2 else "bronze"
    info = PREMIUM_TIERS.get(tier, PREMIUM_TIERS["bronze"])
    m = {"bkash": (BKASH_NUMBER, "bKash"), "rocket": (ROCKET_NUMBER, "Rocket"),
         "binance": (BINANCE_ID, "Binance Pay ID"), "bsc20": (USDT_BSC20, "USDT BSC20"),
         "trc20": (USDT_TRC20, "USDT TRC20")}
    if method not in m: return
    num, mname = m[method]
    context.user_data['awaiting_payment'] = True
    context.user_data['payment_method'] = mname

    tpl = {
        "bn": (f"💳 {mname} পেমেন্ট\n\n📦 প্যাকেজ: {info['name']}\n💰 মূল্য: {info['price']}৳ ({info['days']} দিন)\n\n"
               f"📍 ঠিকানা:\n`{num}`\n\n✅ পাঠানোর পর TrxID/Screenshot এখানে পাঠান।\n\n⏱️ ৫-১০ মিনিটে verify হবে।",
               "📋 কপি করুন", "❌ বাতিল", "🏠 মেনু"),
        "hi": (f"💳 {mname} भुगतान\n\n📦 पैकेज: {info['name']}\n💰 मूल्य: {info['price']}৳ ({info['days']} दिन)\n\n"
               f"📍 पता:\n`{num}`\n\n✅ भेजने के बाद TrxID/Screenshot भेजें।\n\n⏱️ 5-10 मिनट।",
               "📋 कॉपी", "❌ रद्द", "🏠 मेनू"),
        "ru": (f"💳 {mname} оплата\n\n📦 Пакет: {info['name']}\n💰 Цена: {info['price']}৳ ({info['days']} дней)\n\n"
               f"📍 Адрес:\n`{num}`\n\n✅ После отправки пришлите TrxID/скриншот.\n\n⏱️ Проверка 5-10 мин.",
               "📋 Копировать", "❌ Отмена", "🏠 Меню"),
        "en": (f"💳 {mname} Payment\n\n📦 Package: {info['name']}\n💰 Price: {info['price']}৳ ({info['days']} days)\n\n"
               f"Send to:\n`{num}`\n\n✅ After sending, send TrxID/Screenshot here.\n\n⏱️ Verify in 5-10 min.",
               "📋 Copy", "❌ Cancel", "🏠 Menu"),
    }
    text, copy_lbl, cancel_lbl, menu_lbl = tpl.get(lang, tpl["en"])
    try: await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(copy_lbl, callback_data=f"copy_{method}")],
        [InlineKeyboardButton(cancel_lbl, callback_data="cancel_payment")],
        [InlineKeyboardButton(menu_lbl, callback_data="main_menu")]]))
    except: pass


async def copy_number(update, context):
    q = update.callback_query; await q.answer()
    m = q.data.replace("copy_", "")
    nums = {"bkash": BKASH_NUMBER, "rocket": ROCKET_NUMBER, "binance": BINANCE_ID,
            "bsc20": USDT_BSC20, "trc20": USDT_TRC20}
    await q.message.reply_text(f"`{nums.get(m, 'N/A')}`\n\n👇 Tap to copy")


async def cancel_payment(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    for k in ['awaiting_payment','payment_tier','payment_method']: context.user_data.pop(k, None)
    try: await q.edit_message_text("✅ Cancelled.", reply_markup=await main_menu_kb(lang))
    except: pass


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
        await c.execute("INSERT INTO payments (user_id,tier,method,amount_bdt,status,approved_at) VALUES ($1,$2,'Telegram Stars',$3,'approved',NOW())",
                        uid, tier, info['price'])
    await update.message.reply_text(
        t("premium_activated", lang, tier=info['name'], days=info['days'], coins=info['coins']),
        reply_markup=await main_menu_kb(lang))


# ============ LINK / COMMANDS ============
async def show_link(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{uid}"
    try: await q.edit_message_text(t("referral_msg", lang, link=link, coins=REFERRAL_COIN_REWARD),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    except: pass


async def link_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    bot = await context.bot.get_me()
    link = f"https://t.me/{bot.username}?start=ref_{uid}"
    await update.message.reply_text(t("referral_msg", lang, link=link, coins=REFERRAL_COIN_REWARD))


async def newchat_cmd(update, context):
    """MeChat-style /newchat command."""
    uid = update.effective_user.id; lang = await get_lang(uid)
    prof = await get_profile(uid)
    if not prof:
        await update.message.reply_text(t("reg_first", lang)); return
    ex = await get_chat(uid)
    if ex:
        await update.message.reply_text(t("already_in_chat", lang), reply_markup=chat_kb(ex['partner_id'], lang)); return
    # Show choice
    await update.message.reply_text(
        f"💗 {t('find_partner', lang)}\n\n{t('choose_tier', lang)}" if False else
        f"💗 Choose who you want to chat with 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("random_free", lang), callback_data="find_partner")],
            [InlineKeyboardButton(t("chat_with_guy", lang), callback_data="chat_guy"),
             InlineKeyboardButton(t("chat_with_girl", lang), callback_data="chat_girl")],
            [InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))


async def coins_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    c = await get_coins(uid); vip = await is_vip(uid); tier = await get_tier(uid) if vip else None
    await update.message.reply_text(t("coins_balance", lang, coins=c, vip=('✅ ' + (tier or 'Active')) if vip else '❌'))


async def vip_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    rows = [[InlineKeyboardButton(f"{info['name']} — {info['price']}৳ / {info['stars']}⭐", callback_data=f"tier_{k}")] for k, info in PREMIUM_TIERS.items()]
    await update.message.reply_text(t("choose_tier", lang), reply_markup=InlineKeyboardMarkup(rows))


async def language_cmd(update, context):
    await update.message.reply_text(t("language_select", "en"),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn"),
             InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi"),
             InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]]))


async def profile_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    prof = await get_profile(uid)
    if not prof:
        await update.message.reply_text(t("reg_first", lang)); return
    st = await get_stats(uid) or {}
    lvl = st.get('level', 1) or 1; xp = st.get('xp', 0) or 0
    nx = LEVEL_THRESHOLDS[lvl] if lvl < len(LEVEL_THRESHOLDS) else 0
    aid = st.get('anon_id') or f"user_{uid}"
    await update.message.reply_text(
        f"👤 {prof.get('display_name')}\n🆔 /{aid}\n"
        f"📈 Lv{lvl} • XP {xp}/{nx}\n"
        f"🪙 {st.get('coins', 0)}\n🔥 {st.get('streak', 0)}\n💬 {st.get('total_chats', 0)}\n"
        f"❤️ {st.get('likes_received', 0)} • 👀 {st.get('profile_views', 0)}")


async def missions_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    st = await missions_status(uid)
    text = f"{t('missions_title', lang)}\n\n"
    for k, m in st.items():
        if m['completed']: text += f"✅ {m['text']} +{m['reward']}\n"
        else: text += f"⏳ {m['text']} ({m['progress']}/{m['target']}) +{m['reward']}\n"
    await update.message.reply_text(text)


async def achievements_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    unlocked = await user_achievements(uid)
    text = f"{t('achievements_title', lang)}\n\n"
    for k, (e, title) in ACHIEVEMENTS.items():
        text += f"{'✅' if k in unlocked else '🔒'} {e} {title}\n"
    await update.message.reply_text(text[:4000])


async def leaderboard(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT u.user_id,p.display_name,u.total_chats,u.xp,u.level
            FROM users u JOIN profiles p ON p.user_id=u.user_id WHERE u.total_chats>0
            ORDER BY u.xp DESC LIMIT 10""")
    if not rows:
        try: await q.edit_message_text(t("leaderboard_empty", lang), reply_markup=await main_menu_kb(lang))
        except: pass
        return
    text = t("leaderboard_title", lang) + "\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        text += f"{m} {r['display_name'] or 'Anon'} — Lv{r['level']} • {r['total_chats']} chats\n"
    try: await q.edit_message_text(text, reply_markup=await main_menu_kb(lang))
    except: pass


async def leaderboard_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    async with db_pool.acquire() as c:
        rows = await c.fetch("""SELECT u.user_id,p.display_name,u.total_chats,u.xp,u.level
            FROM users u JOIN profiles p ON p.user_id=u.user_id WHERE u.total_chats>0
            ORDER BY u.xp DESC LIMIT 10""")
    if not rows:
        await update.message.reply_text(t("leaderboard_empty", lang)); return
    text = t("leaderboard_title", lang) + "\n\n"
    medals = ["🥇","🥈","🥉"]
    for i, r in enumerate(rows):
        m = medals[i] if i < 3 else f"{i+1}."
        text += f"{m} {r['display_name'] or 'Anon'} — Lv{r['level']} • {r['total_chats']} chats\n"
    await update.message.reply_text(text)


# ============ STOP / RESET / STATS ============
async def stop_cmd(update, context):
    uid = update.effective_user.id; lang = await get_lang(uid)
    chat = await get_chat(uid)
    if not chat:
        await update.message.reply_text(t("not_in_chat", lang)); return
    pid = chat['partner_id']; is_ai = chat.get('is_ai', False)
    await remove_chat(uid, pid)
    async with db_pool.acquire() as c:
        await c.execute("UPDATE chat_log SET ended_at=NOW() WHERE user_id=$1 AND ended_at IS NULL", uid)
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
        on = await online_count()
        iq = await c.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        ch = (await c.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
    await update.message.reply_text(f"📊\n👥 {tu}\n🟢 {on}\n⏳ {iq}\n💬 {ch}")


# ============ ADMIN ============
async def admin_stats(update, context):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("⛔"); return
    async with db_pool.acquire() as c:
        tu = await c.fetchval("SELECT COUNT(*) FROM users") or 0
        on = await online_count()
        q = await c.fetchval("SELECT COUNT(*) FROM match_queue") or 0
        ch = (await c.fetchval("SELECT COUNT(*) FROM active_chats") or 0) // 2
        pend = await c.fetchval("SELECT COUNT(*) FROM reports WHERE status='pending'") or 0
        bn = await c.fetchval("SELECT COUNT(*) FROM users WHERE is_banned=TRUE") or 0
        vp = await c.fetchval("SELECT COUNT(*) FROM users WHERE is_vip=TRUE") or 0
        co = await c.fetchval("SELECT SUM(coins) FROM users") or 0
        rm = await c.fetchval("SELECT COUNT(*) FROM group_rooms WHERE is_active=TRUE") or 0
        vr = await c.fetchval("SELECT COUNT(*) FROM voice_rooms WHERE is_active=TRUE") or 0
        pp = await c.fetchval("SELECT COUNT(*) FROM payments WHERE status='pending'") or 0
        rev = await c.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved'") or 0
        tk = await c.fetchval("SELECT COUNT(*) FROM support_tickets WHERE status='open'") or 0
    await update.message.reply_text(
        f"📊 Admin Dashboard\n\n"
        f"👥 Users: {tu}\n🟢 Online: {on}\n⏳ Queue: {q}\n💬 Chats: {ch}\n"
        f"👥 Rooms: {rm} | 🎤 Voice: {vr}\n⚠️ Reports: {pend}\n🚫 Banned: {bn}\n"
        f"⭐ Premium: {vp}\n🪙 Coins: {co}\n\n"
        f"💳 Pending Pay: {pp}\n🎫 Open Tickets: {tk}\n💰 Revenue: {rev}৳")


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
        tid = int(context.args[0]); tier_key = context.args[1]
        if tier_key.startswith("topup_"):
            coins = int(tier_key.replace("topup_", ""))
            await add_coins(tid, coins)
            await update.message.reply_text(f"✅ Added {coins} coins to {tid}")
        else:
            info = PREMIUM_TIERS.get(tier_key)
            if not info:
                await update.message.reply_text("❌ Invalid tier"); return
            await set_vip(tid, tier_key, info['days'])
            await add_coins(tid, info['coins'])
            try:
                tl = await get_lang(tid)
                await context.bot.send_message(tid, t("premium_activated", tl,
                    tier=info['name'], days=info['days'], coins=info['coins']))
            except: pass
            await update.message.reply_text(f"✅ Premium for {tid} ({tier_key})")
        async with db_pool.acquire() as c:
            await c.execute("UPDATE payments SET status='approved',approved_at=NOW(),approved_by=$1 WHERE user_id=$2 AND status='pending'",
                            update.effective_user.id, tid)
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
        await update.message.reply_text("✅ No pending"); return
    text = "💳 Pending:\n\n"
    for r in rows:
        text += f"🆔 #{r['payment_id']}\n👤 `{r['user_id']}`\n📦 {r['tier']} • {r['method']}\n➡️ /approve {r['user_id']} {r['tier']}\n\n"
    await update.message.reply_text(text[:4000])


async def revenue_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    async with db_pool.acquire() as c:
        app = await c.fetchval("SELECT COUNT(*) FROM payments WHERE status='approved'") or 0
        pend = await c.fetchval("SELECT COUNT(*) FROM payments WHERE status='pending'") or 0
        tot = await c.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved'") or 0
        today = await c.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved' AND approved_at > NOW() - INTERVAL '1 day'") or 0
        month = await c.fetchval("SELECT COALESCE(SUM(amount_bdt),0) FROM payments WHERE status='approved' AND approved_at > NOW() - INTERVAL '30 days'") or 0
    await update.message.reply_text(
        f"💰 Revenue\n\n✅ Approved: {app}\n⏳ Pending: {pend}\n\n"
        f"💵 Total: {tot}৳\n📅 Today: {today}৳\n📆 30d: {month}৳")


async def userinfo_cmd(update, context):
    if update.effective_user.id not in ADMIN_IDS: return
    if not context.args:
        await update.message.reply_text("Usage: /userinfo <id>"); return
    try:
        tid = int(context.args[0])
        prof = await get_profile(tid)
        st = await get_stats(tid)
        if not st:
            await update.message.reply_text("Not found"); return
        await update.message.reply_text(
            f"👤 `{tid}`\n📛 {(prof or {}).get('display_name', '?')}\n"
            f"🆔 /{st.get('anon_id') or 'user'}\n"
            f"📈 Lv{st.get('level', 1)} • XP {st.get('xp', 0)}\n"
            f"🪙 {st.get('coins', 0)}\n🔥 {st.get('streak', 0)}\n💬 {st.get('total_chats', 0)}\n"
            f"⭐ {'Yes (' + (st.get('vip_tier') or '?') + ')' if st.get('is_vip') else 'No'}")
    except Exception as e: await update.message.reply_text(f"❌ {e}")


# ============ MAIN ============
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
        ("vip", vip_cmd), ("language", language_cmd), ("profile", profile_cmd),
        ("missions", missions_cmd), ("achievements", achievements_cmd),
        ("leaderboard", leaderboard_cmd), ("joinroom", join_room_cmd),
        ("leaveroom", leave_room_cmd), ("leavevoice", leave_voice_room),
        ("newchat", newchat_cmd), ("link_anon", link_anon_cmd),
        ("adminstats", admin_stats), ("ban", ban_cmd), ("unban", unban_cmd),
        ("approve", approve_cmd), ("verify", verify_cmd),
        ("broadcast", broadcast_cmd), ("pending", pending_cmd),
        ("revenue", revenue_cmd), ("userinfo", userinfo_cmd),
        ("reply_ticket", reply_ticket_cmd),
    ]
    for n, f in cmds: app.add_handler(CommandHandler(n, f))

    callbacks = [
        ("^lang_", language_callback), ("^change_language$", change_language),
        ("^age_", age_gate_callback), ("^gender_", gender_callback),
        ("^pref_", pref_gender_callback), ("^int_", interest_callback),
        ("^plang_", pref_lang_callback),
        ("^setpg_", set_pref_gender), ("^setint_", set_interest),
        ("^setplang_", set_plang), ("^setage_", set_age),
        ("^setcity_", set_city_cb), ("^choose_city$", choose_city_cb),
        ("^edit_name$", edit_name), ("^edit_bio$", edit_bio),
        ("^edit_pref_gender$", edit_pref_gender), ("^edit_interest$", edit_interest),
        ("^edit_lang$", edit_lang), ("^edit_age_range$", edit_age_range),
        ("^edit_birthday$", edit_birthday), ("^edit_profile$", edit_profile),
        ("^advanced_settings$", advanced_settings),
        ("^toggle_same_age_setting$", toggle_same_age_setting),
        ("^coins_to_stars$", coins_to_stars_cb),
        ("^main_menu$", main_menu_cb), ("^refresh_online$", refresh_online),
        ("^find_partner$", find_partner), ("^chat_guy$", find_partner),
        ("^chat_girl$", find_partner), ("^toggle_same_age$", toggle_same_age_cb),
        ("^cancel_search$", cancel_search),
        ("^ai_chat$", ai_chat_start), ("^show_link$", show_link),
        ("^show_anon_link$", show_anon_link),
        ("^show_coins$", show_coins), ("^show_vip$", show_vip),
        ("^coins_topup$", coins_topup), ("^topup_", topup_select),
        ("^show_achievements$", show_achievements), ("^show_missions$", show_missions),
        ("^show_friends$", show_friends), ("^show_blocked$", show_blocked),
        ("^unblock_", unblock_cb),
        ("^view_likers$", view_likers),
        ("^browse_people$", browse_people_cb), ("^nearby_people$", nearby_people_cb),
        ("^tier_", tier_select), ("^stars_", stars_payment),
        ("^pay_", payment_method),
        ("^copy_", copy_number), ("^cancel_payment$", cancel_payment),
        ("^end_chat$", end_chat_cb), ("^next_partner$", next_partner),
        ("^addfriend_", add_friend_cb),
        ("^like_", like_cb), ("^block_", block_cb),
        ("^viewprof_", view_profile_cb), ("^msg_user_", msg_user_cb),
        ("^rpr_", report_reason_cb), ("^report_", report_cb),
        ("^my_profile$", my_profile), ("^safety$", safety_cb),
        ("^help$", help_cb), ("^support_ticket$", support_ticket),
        ("^leaderboard$", leaderboard),
        ("^group_menu$", group_menu), ("^create_room$", create_room),
        ("^joinroom_", join_room_cb), ("^leave_room$", leave_room_cb),
        ("^voice_menu$", voice_menu), ("^create_vr$", create_voice_room),
        ("^jvr_", join_voice_room), ("^leave_vr$", leave_voice_room),
        ("^tod_start$", tod_start), ("^tod_truth$", tod_truth),
        ("^tod_dare$", tod_dare), ("^tod_random$", tod_random),
        ("^ice_breaker$", ice_breaker), ("^compat$", compat),
        ("^extend_chat$", extend_chat), ("^chat_summary$", chat_summary),
        ("^delete_msgs$", delete_msgs_cb),
        ("^status_menu$", status_menu), ("^post_status$", post_status),
        ("^view_statuses$", view_statuses),
    ]
    for p, f in callbacks: app.add_handler(CallbackQueryHandler(f, pattern=p))

    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(~filters.COMMAND, handle_text))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
