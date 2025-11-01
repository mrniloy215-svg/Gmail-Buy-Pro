import os
import logging
import asyncio
import aiosqlite
import random
import string
import io
from datetime import datetime
from aiogram import Bot, Dispatcher, executor, types
from openpyxl import Workbook
from dotenv import load_dotenv

load_dotenv()

Config

TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_IDS = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x)
DB_PATH = os.getenv("DB_PATH", "gmail_buy_pro.db")

Logging

logging.basicConfig(level=logging.INFO)

Bot setup

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

Database init

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
"""

async def init_db():
async with aiosqlite.connect(DB_PATH) as db:
await db.executescript(INIT_SQL)
await db.commit()

async def get_db():
db = await aiosqlite.connect(DB_PATH)
db.row_factory = aiosqlite.Row
return db

Messages

START = """স্বাগতম Gmail Buy Pro!\n\n/ Register new Gmail\n/balance - ব্যালেন্স চেক\n/withdraw <amount> - টাকা উত্তোলন"""
NO_ORDER = "⚠️ কোনো অর্ডার সক্রিয় নেই। Admin নতুন অর্ডার না দিলে Gmail তৈরি করা যাবে না।"
ORDER_STARTED = "✅ অর্ডার শুরু হয়েছে!\nType: {type}\nQuantity: {qty}\nTime Limit: {minutes} মিনিট\nRecovery: {reco}"
GENERATED_GMAIL = """✅ নতুন Gmail তৈরি হয়েছে:
👤 First Name: {first_name}
📧 Email: {email}
🔑 Password: {password}
{recovery}

⚠️ নির্দেশনা:

1. Gmail/Password ঠিক যেমন আছে ব্যবহার করুন
2. কোনো পরিবর্তন করবেন না
3. Gmail তৈরি পর মোবাইল থেকে remove করুন
"""

Utility

FIRST_NAMES = ["Niloy","Rahul","Mark","Jack","Henry","Alice","Maya","Liam","Noah","Emma","Olivia","Ava","Sophia","Isabella","Mia","Charlotte","Amelia","Harper","Evelyn","Abigail","Emily","Elizabeth","Sofia","Ella","Scarlett","Grace","Chloe","Victoria","Riley","Aria","Lily","Aurora","Zoey","Hannah","Lillian","Addison","Natalie","Luna","Savannah","Brooklyn","Zoe","Stella","Leah","Audrey","Claire","Samantha"]

def random_first_name(): return random.choice(FIRST_NAMES)
def random_email(): return ''.join(random.choices(string.ascii_lowercase+string.digits,k=10))+"@gmail.com"
def random_password(): return ''.join(random.choices(string.ascii_letters+string.digits+"!@#$%&*",k=random.randint(8,12)))

async def is_admin(user_id): return user_id in ADMIN_IDS

Handlers

@dp.message_handler(commands=['start','help'])
async def cmd_start(message: types.Message):
db = await get_db()
await db.execute("INSERT OR IGNORE INTO users(id, username) VALUES(?,?)",(message.from_user.id,message.from_user.username or ""))
await db.commit()
await message.reply(START)

@dp.message_handler(commands=['balance'])
async def cmd_balance(message: types.Message):
db = await get_db()
row = await db.execute_fetchone("SELECT balance FROM users WHERE id=?",(message.from_user.id,))
bal = row['balance'] if row else 0
await message.reply(f"💳 আপনার বর্তমান ব্যালেন্স: {bal} ৳")

@dp.message_handler(commands=['register'])
async def cmd_register(message: types.Message):
db = await get_db()
order = await db.execute_fetchone("SELECT * FROM orders WHERE active=1 ORDER BY id DESC LIMIT 1")
if not order:
await message.reply(NO_ORDER)
return
existing = await db.execute_fetchone("SELECT COUNT(*) as count FROM gmails WHERE creator_id=? AND order_id=?",(message.from_user.id, order['id']))
if existing and existing['count']>0:
await message.reply("❌ আপনি ইতিমধ্যে এই অর্ডারে একটি Gmail তৈরি করেছেন।")
return
for attempt in range(10):
email = random_email()
exists = await db.execute_fetchone("SELECT id FROM gmails WHERE email=?",(email,))
if not exists: break
else:
await message.reply("❌ Email generate করতে সমস্যা হচ্ছে। আবার চেষ্টা করুন।")
return
pwd = random_password()
fname = random_first_name()
recovery = f"📩 Recovery: {order['recovery_email']}" if order['recovery_email'] else ""
msg = GENERATED_GMAIL.format(first_name=fname,email=email,password=pwd,recovery=recovery)
keyboard = types.InlineKeyboardMarkup()
keyboard.add(
types.InlineKeyboardButton("✅ Confirm",callback_data=f"confirm:{email}:{pwd}:{fname}:{order['id']}"),
types.InlineKeyboardButton("❌ Cancel",callback_data="cancel")
)
await message.reply(msg,reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('confirm:'))
async def process_confirmation(callback_query: types.CallbackQuery):
data = callback_query.data.split(':')
email,password,fname,order_id = data[1],data[2],data[3],int(data[4])
db = await get_db()
try:
await db.execute("INSERT INTO gmails(email,password,first_name,creator_id,order_id) VALUES (?,?,?,?,?)",(email,password,fname,callback_query.from_user.id,order_id))
await db.execute("UPDATE users SET total_registered=total_registered+1, balance=balance+5 WHERE id=?",(callback_query.from_user.id,))
await db.commit()
order = await db.execute_fetchone("SELECT qty FROM orders WHERE id=?",(order_id,))
count_created = await db.execute_fetchone("SELECT COUNT(*) as count FROM gmails WHERE order_id=?",(order_id,))
await bot.send_message(callback_query.from_user.id,f"✅ Gmail সফলভাবে রেজিস্টার্ড হয়েছে!\n\n📧 {email}\n💰 5 ৳ ব্যালেন্স যোগ করা হয়েছে\n\nপরবর্তী Gmail তৈরি করতে আবার /register লিখুন")
for admin_id in ADMIN_IDS:
try:
await bot.send_message(admin_id,f"📬 নতুন Gmail রেজিস্টার্ড\nব্যবহারকারী: @{callback_query.from_user.username or 'N/A'} (ID: {callback_query.from_user.id})\nEmail: {email}\nPassword: {password}\nFirst Name: {fname}\nঅর্ডার প্রোগ্রেস: {count_created['count']}/{order['qty']}")
except: pass
except aiosqlite.IntegrityError:
await bot.send_message(callback_query.from_user.id,"❌ এই Gmail ইতিমধ্যে exists। আবার চেষ্টা করুন।")
except Exception as e:
await bot.send_message(callback_query.from_user.id,"❌ Error occurred. আবার চেষ্টা করুন।")
print(f"Error: {e}")
await callback_query.message.delete()

@dp.callback_query_handler(lambda c: c.data=="cancel")
async def process_cancel(callback_query: types.CallbackQuery):
await bot.send_message(callback_query.from_user.id,"❌ Gmail তৈরি বাতিল করা হয়েছে।")
await callback_query.message.delete()

Withdraw

@dp.message_handler(commands=['withdraw'])
async def cmd_withdraw(message: types.Message):
args = message.get_args()
if not args:
await message.reply("Usage: /withdraw <amount>\nExample: /withdraw 100")
return
try: amount = float(args)
except:
await message.reply("❌ সঠিক Amount লিখুন")
return
if amount<10:
await message.reply("❌ নূন্যতম উত্তোলন金额 10 ৳")
return
db = await get_db()
user = await db.execute_fetchone("SELECT balance FROM users WHERE id=?",(message.from_user.id,))
if not user or user['balance']<amount:
await message.reply("❌ পর্যাপ্ত ব্যালেন্স নেই")
return
await db.execute("UPDATE users SET balance=balance-? WHERE id=?",(amount,message.from_user.id))
await db.commit()
await message.reply(f"✅ {amount} ৳ উত্তোলনের রিকোয়েস্ট করা হয়েছে। Admin অনুমোদন করবেন।")
for admin_id in ADMIN_IDS:
try: await bot.send_message(admin_id,f"🔄 নতুন উত্তোলন রিকোয়েস্ট:\nব্যবহারকারী: @{message.from_user.username or 'N/A'} (ID: {message.from_user.id})\nAmount: {amount} ৳\nবর্তমান ব্যালেন্স: {user['balance']-amount} ৳")
except: pass

Admin Commands

@dp.message_handler(commands=['order'])
async def cmd_order(message: types.Message):
if not await is_admin(message.from_user.id): return
args = message.get_args().split()
if len(args)<2:
await message.reply("Usage: /order <type> <quantity>\nExample: /order reco 50")
return
typ = args[0]
try: qty=int(args[1])
except:
await message.reply("❌ Quantity must be number")
return
time_limit=60
db=await get_db()
await db.execute("UPDATE orders SET active=0 WHERE active=1")
await db.execute("INSERT INTO orders(type,qty,active,time_limit_minutes) VALUES(?,?,1,?)",(typ,qty,time_limit))
await db.commit()
recovery_info="Not set - use /reco <email> to set"
await message.reply(ORDER_STARTED.format(type=typ,qty=qty,minutes=time_limit,reco=recovery_info))
async def deactivate_order():
await asyncio.sleep(time_limit*60)
db2=await get_db()
await db2.execute("UPDATE orders SET active=0 WHERE active=1")
await db2.commit()
await message.reply(f"⏰ অর্ডার {time_limit} মিনিট পর অটো বন্ধ করা হয়েছে")
asyncio.create_task(deactivate_order())

@dp.message_handler(commands=['reco'])
async def cmd_reco(message: types.Message):
if not await is_admin(message.from_user.id): return
args=message.get_args().strip()
if not args:
await message.reply("Usage: /reco <recovery_email>\nExample: /reco recovery@gmail.com")
return
db=await get_db()
await db.execute("UPDATE orders SET recovery_email=? WHERE active=1",(args,))
await db.commit()
await message.reply(f"✅ Recovery email set to: {args}")

@dp.message_handler(commands=['stoporder'])
async def cmd_stoporder(message: types.Message):
if not await is_admin(message.from_user.id): return
db=await get_db()
await db.execute("UPDATE orders SET active=0 WHERE active=1")
await db.commit()
await message.reply("✅ সকল active order বন্ধ করা হয়েছে")

@dp.message_handler(commands=['send'])
async def cmd_send(message: types.Message):
if not await is_admin(message.from_user.id): return
db=await get_db()
order=await db.execute_fetchone("SELECT * FROM orders WHERE active=1 ORDER BY id DESC LIMIT 1")
if not order:
await message.reply("❌ কোনো active order নেই")
return
gmails=await db.execute_fetchall("SELECT email,password,first_name FROM gmails WHERE order_id=?",(order['id'],))
if not gmails:
await message.reply("❌ এই অর্ডারে কোনো Gmail তৈরি হয়নি")
return
wb=Workbook()
ws=wb.active
ws.title="Gmails"
ws.append(["Email","Password","First Name"])
for g in gmails: ws.append([g['email'],g['password'],g['first_name']])
bio=io.BytesIO()
wb.save(bio)
bio.seek(0)
filename=f"gmails_order_{order['id']}.xlsx"
await message.reply_document(bio,caption=f"📧 Total Gmails: {len(gmails)}\nOrder ID: {order['id']}\nType: {order['type']}",filename=filename)

@dp.message_handler(commands=['stats'])
async def cmd_stats(message: types.Message):
if not await is_admin(message.from_user.id): return
db=await get_db()
user_count=await db.execute_fetchone("SELECT COUNT() as count FROM users")
gmail_count=await db.execute_fetchone("SELECT COUNT() as count FROM gmails")
active_order=await db.execute_fetchone("SELECT * FROM orders WHERE active=1")
stats_text=f"📊 Bot Statistics:\n\n👥 Total Users: {user_count['count']}\n📧 Total Gmails: {gmail_count['count']}\n"
if active_order:
created_count=await db.execute_fetchone("SELECT COUNT(*) as count FROM gmails WHERE order_id=?",(active_order['id'],))
stats_text+=f"\n📦 Active Order:\nType: {active_order['type']}\nQuantity: {active_order['qty']}\nCreated: {created_count['count']}\nProgress: {created_count['count']}/{active_order['qty']}\n"
if active_order['recovery_email']: stats_text+=f"Recovery: {active_order['recovery_email']}\n"
else: stats_text+="\n📦 No active order\n"
await message.reply(stats_text)

@dp.message_handler(commands=['credit'])
async def cmd_credit(message: types.Message):
if not await is_admin(message.from_user.id): return
args=message.get_args().split()
if len(args)<2:
await message.reply("Usage: /credit <user_id> <amount>\nExample: /credit 123456 100")
return
try:
user_id=int(args[0])
amount=float(args[1])
except:
await message.reply("❌ Invalid user_id or amount")
return
db=await get_db()
user=await db.execute_fetchone("SELECT id FROM users WHERE id=?",(user_id,))
if not user:
await message.reply("❌ User not found")
return
await db.execute("UPDATE users SET balance=balance+? WHERE id=?",(amount,user_id))
await db.commit()
await message.reply(f"✅ {amount} ৳ credited to user {user_id}")
try: await bot.send_message(user_id,f"💰 আপনার ব্যালেন্সে {amount} ৳ যোগ করা হয়েছে")
except: pass

Startup

async def on_startup(dp):
await init_db()
logging.info("Bot started")
for admin_id in ADMIN_IDS:
try: await bot.send_message(admin_id,"🤖 Bot started successfully!")
except: pass

if name=="main":
executor.start_polling(dp,on_startup=on_startup,skip_updates=True)
