import os
import logging
import asyncio
import aiosqlite
import random
import string
import io
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher import Dispatcher
from openpyxl import Workbook
from dotenv import load_dotenv

load_dotenv()

# Configuration
TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x)
DB_PATH = os.getenv("DB_PATH", "gmail_buy_pro.db")
DEFAULT_ORDER_TIMEOUT_MIN = 5
BONUS_PER_REF = float(os.getenv("BONUS_PER_REF", "1.5"))

# Database initialization
INIT_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    balance REAL DEFAULT 0,
    total_registered INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,
    qty INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active INTEGER DEFAULT 1,
    time_limit_minutes INTEGER,
    recovery_email TEXT
);

CREATE TABLE IF NOT EXISTS gmails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE,
    password TEXT,
    first_name TEXT,
    creator_id INTEGER,
    order_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'pending',
    locked INTEGER DEFAULT 1,
    FOREIGN KEY (creator_id) REFERENCES users(id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer INTEGER,
    referred INTEGER,
    bonus REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS withdraws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(INIT_SQL)
        await db.commit()

async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db

# Message templates
START = """স্বাগতম *Gmail Buy Pro*! 
ব্যবহার শুরু করতে /help লিখুন।
"""

NO_ORDER = """⚠️ কোনো অর্ডার সক্রিয় নেই।
Admin নতুন অর্ডার না দিলে Gmail তৈরি করা যাবে না।"""

ORDER_STARTED = """✅ অর্ডার শুরু হয়েছে!
টাইপ: {type}
পরিমাণ: {qty}
সময়সীমা: {minutes} মিনিট
Recovery Email: {reco}
"""

GENERATED_GMAIL = """👤 First Name: {first_name}
📧 Gmail: {email}
🔑 Password: {password}
{recovery}
⚠️ নির্দেশনা:
উপরের Gmail/Password ঠিক 그대로 ব্যবহার করতে হবে।
এর বাইরে কিছু পরিবর্তন করা যাবে না।
📵 Gmail তৈরির পর এটি মোবাইল থেকে remove করে দিন।
No money will be paid otherwise.
"""

NEW_GMAIL_NOTIFY_ADMIN = """📬 New Gmail Registered
Creator: @{username} (ID: {chat_id})
Email: {email}
Password: {password}
First Name: {first_name}
Order Progress: {created}/{qty}
"""

SEND_CONFIRM = "✅ Send চাপলে বর্তমান তৈরি হওয়া সব Gmail `.xlsx` ফাইল হিসেবে যাবে।"

BALANCE_ADDED = "💰 ব্যালেন্স যুক্ত হয়েছে: {amount} ৳\nUser: {chat_id}"

WITHDRAW_REQUEST = "✅ Withdraw request তৈরি হয়েছে: {amount} ৳\nStatus: pending"

BROADCAST_ALL = "📢 *Admin Message:*\n\n{message}"
BROADCAST_USER = "📬 *Admin Direct Message:*\n\n{message}"

# Utility functions
FIRST_NAMES = [
    "Niloy", "Rahul", "Mark", "Jack", "Henry", "Alice", "Maya", "Liam", "Noah", "Emma",
    "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
    "Abigail", "Emily", "Elizabeth", "Sofia", "Ella", "Scarlett", "Grace", "Chloe", "Victoria",
    "Riley", "Aria", "Lily", "Aurora", "Zoey", "Hannah", "Lillian", "Addison", "Natalie",
    "Luna", "Savannah", "Brooklyn", "Zoe", "Stella", "Leah", "Audrey", "Claire", "Samantha",
    "Aaliyah", "Rebecca", "Anna", "Caroline", "Nova", "Genesis", "Emilia", "Kennedy", "Sarah"
]

def random_first_name():
    return random.choice(FIRST_NAMES)

def random_email():
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{name}@gmail.com"

def random_password():
    L = random.randint(8, 12)
    chars = string.ascii_letters + string.digits + "!@#$%&*"
    return ''.join(random.choices(chars, k=L))

def calc_bonus_for_refcount(n):
    return round(n * BONUS_PER_REF, 2)

# Bot setup
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# Admin check
async def is_admin(user_id):
    return user_id in ADMIN_IDS

# User handlers
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    db = await get_db()
    await db.execute("INSERT OR IGNORE INTO users(id, username) VALUES(?,?)", 
                    (message.from_user.id, message.from_user.username or ""))
    await db.commit()
    await message.reply(START)

@dp.message_handler(commands=['balance'])
async def cmd_balance(message: types.Message):
    db = await get_db()
    row = await db.execute_fetchone("SELECT balance FROM users WHERE id = ?", (message.from_user.id,))
    bal = row['balance'] if row else 0
    await message.reply(f"💳 আপনার বর্তমান ব্যালেন্স: {bal} ৳")

@dp.message_handler(commands=['register'])
async def cmd_register(message: types.Message):
    db = await get_db()
    order = await db.execute_fetchone("SELECT * FROM orders WHERE active = 1 ORDER BY id DESC LIMIT 1")
    if not order:
        await message.reply(NO_ORDER)
        return
    
    # Generate unique email
    email = random_email()
    pwd = random_password()
    fname = random_first_name()
    recovery = f"📩 Recovery: {order['recovery_email']}" if order['recovery_email'] else ""
    
    msg = GENERATED_GMAIL.format(first_name=fname, email=email, password=pwd, recovery=recovery)
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("✅ Done", callback_data=f"done_register:{email}:{pwd}:{fname}:{order['id']}"))
    keyboard.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_register"))
    await message.reply(msg, reply_markup=keyboard)

@dp.message_handler(commands=['withdraw'])
async def cmd_withdraw(message: types.Message):
    args = message.get_args()
    if not args:
        await message.reply("Usage: /withdraw <amount>")
        return
    
    try:
        amount = float(args)
    except:
        await message.reply("Invalid amount")
        return
    
    db = await get_db()
    user = await db.execute_fetchone("SELECT balance FROM users WHERE id = ?", (message.from_user.id,))
    
    if not user or user['balance'] < amount:
        await message.reply("❌ Insufficient balance")
        return
    
    await db.execute("INSERT INTO withdraws(user_id, amount) VALUES(?,?)", (message.from_user.id, amount))
    await db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, message.from_user.id))
    await db.commit()
    
    await message.reply(WITHDRAW_REQUEST.format(amount=amount))
    
    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🔄 New withdraw request:\nUser: {message.from_user.id}\nAmount: {amount} ৳")
        except:
            pass

# Admin handlers
@dp.message_handler(commands=['order'])
async def cmd_order(message: types.Message):
    if not await is_admin(message.from_user.id):
        return
    
    args = message.get_args().split()
    if len(args) < 2:
        await message.reply("Usage: /order reco/non <amount>")
        return
    
    typ =