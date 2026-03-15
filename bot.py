import os
import json
import datetime
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "break_data.json"

TIMEZONE = ZoneInfo("Asia/Manila")

BREAK_LIMIT = 60
AWAY_LIMIT = 60

ROLES = ["CS", "TL", "HTL", "QI", "WD", "DP"]

keyboard = [
    ["☕ Start Break", "☕ End Break"],
    ["🚶 Start Away", "🚶 End Away"],
    ["📊 Status", "📋 My Total"]
]

reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"summary_chat_id": None, "users": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"summary_chat_id": None, "users": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def now():
    return datetime.datetime.now(TIMEZONE)

def minutes(start, end):
    return int((end - start).total_seconds() / 60)

def role_count(users):
    count = {r: 0 for r in ROLES}
    for u in users:
        role = u.get("role")
        if role in count:
            count[role] += 1
    return count

def ensure_user(data, user_id, chat_id, fallback_name):
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "name": fallback_name,
            "role": "UNKNOWN",
            "break_total": 0,
            "away_total": 0,
            "active": None,
            "chat_id": chat_id,
        }
    else:
        data["users"][user_id]["chat_id"] = chat_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    data["summary_chat_id"] = update.effective_chat.id

    uid = str(update.effective_user.id)
    ensure_user(data, uid, update.effective_chat.id, update.effective_user.first_name.upper())
    save_data(data)

    await update.message.reply_text(
        "Break Tracker is ready.\n\n"
        "Use /register ROLE\n"
        "Example:\n"
        "/register CS",
        reply_markup=reply_markup
    )

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/register CS")
        return

    role = context.args[0].upper().strip()

    if role not in ROLES:
        await update.message.reply_text("Invalid role.\nUse one of: CS, TL, HTL, QI, WD, DP")
        return

    uid = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    name = update.effective_user.first_name.upper()

    reg_name = f"IND06-{role}-{name}"

    data = load_data()
    data["users"][uid] = {
        "name": reg_name,
        "role": role,
        "break_total": 0,
        "away_total": 0,
        "active": None,
        "chat_id": chat_id,
    }
    save_data(data)

    await update.message.reply_text(
        f"✅ Registration successful\n\n"
        f"Name: {reg_name}\n"
        f"Role: {role}"
    )

async def start_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)

    user = data["users"].get(uid)

    if not user:
        await update.message.reply_text("Please register first.\n/register CS")
        return

    if user["active"]:
        await update.message.reply_text("You already have an active status.")
        return

    current = now()
    user["active"] = {
        "type": "break",
        "start": current.isoformat()
    }

    save_data(data)

    await update.message.reply_text(
        f"{user['name']}\n"
        f"☕ Break started at {current.strftime('%I:%M %p')}"
    )

async def end_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)

    user = data["users"].get(uid)

    if not user or not user["active"] or user["active"]["type"] != "break":
        await update.message.reply_text("You do not have an active break.")
        return

    current = now()
    start_dt = datetime.datetime.fromisoformat(user["active"]["start"])
    m = minutes(start_dt, current)

    user["break_total"] += m
    user["active"] = None
    save_data(data)

    msg = (
        f"{user['name']}\n"
        f"☕ Break ended at {current.strftime('%I:%M %p')}\n"
        f"This session: {m} mins\n"
        f"Total break today: {user['break_total']} mins"
    )

    if user["break_total"] > BREAK_LIMIT:
        msg += f"\n⚠️ You exceeded the break limit by {user['break_total'] - BREAK_LIMIT} mins."
    else:
        msg += f"\nRemaining break time: {BREAK_LIMIT - user['break_total']} mins"

    await update.message.reply_text(msg)

async def start_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)

    user = data["users"].get(uid)

    if not user:
        await update.message.reply_text("Please register first.\n/register CS")
        return

    if user["active"]:
        await update.message.reply_text("You already have an active status.")
        return

    current = now()
    user["active"] = {
        "type": "away",
        "start": current.isoformat()
    }

    save_data(data)

    await update.message.reply_text(
        f"{user['name']}\n"
        f"🚶 Away started at {current.strftime('%I:%M %p')}"
    )

async def end_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)

    user = data["users"].get(uid)

    if not user or not user["active"] or user["active"]["type"] != "away":
        await update.message.reply_text("You do not have an active away status.")
        return

    current = now()
    start_dt = datetime.datetime.fromisoformat(user["active"]["start"])
    m = minutes(start_dt, current)

    user["away_total"] += m
    user["active"] = None
    save_data(data)

    msg = (
        f"{user['name']}\n"
        f"🚶 Away ended at {current.strftime('%I:%M %p')}\n"
        f"This session: {m} mins\n"
        f"Total away today: {user['away_total']} mins"
    )

    if user["away_total"] > AWAY_LIMIT:
        msg += f"\n⚠️ You exceeded the away limit by {user['away_total'] - AWAY_LIMIT} mins."
    else:
        msg += f"\nRemaining away time: {AWAY_LIMIT - user['away_total']} mins"

    await update.message.reply_text(msg)

async def mytotal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)

    user = data["users"].get(uid)

    if not user:
        await update.message.reply_text("Please register first.")
        return

    await update.message.reply_text(
        f"{user['name']}\n"
        f"Break total: {user['break_total']} mins\n"
        f"Break remaining: {max(0, BREAK_LIMIT - user['break_total'])} mins\n"
        f"Away total: {user['away_total']} mins\n"
        f"Away remaining: {max(0, AWAY_LIMIT - user['away_total'])} mins\n"
        f"Combined total: {user['break_total'] + user['away_total']} mins"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    chat_id = update.effective_chat.id

    break_users = []
    away_users = []
    work_users = []

    for u in data["users"].values():
        if u.get("chat_id") != chat_id:
            continue

        if not u["active"]:
            work_users.append(u)
        elif u["active"]["type"] == "break":
            break_users.append(u)
        else:
            away_users.append(u)

    b = role_count(break_users)
    a = role_count(away_users)
    w = role_count(work_users)

    msg = "📊 Live Team Status\n\n"

    msg += f"☕ On Break ({len(break_users)})\n"
    msg += " | ".join([f"{k}: {v}" for k, v in b.items()])
    msg += "\n\n"

    msg += f"🚶 Away ({len(away_users)})\n"
    msg += " | ".join([f"{k}: {v}" for k, v in a.items()])
    msg += "\n\n"

    msg += f"✅ Working ({len(work_users)})\n"
    msg += " | ".join([f"{k}: {v}" for k, v in w.items()])

    await update.message.reply_text(msg)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text

    if text == "☕ Start Break":
        await start_break(update, context)
    elif text == "☕ End Break":
        await end_break(update, context)
    elif text == "🚶 Start Away":
        await start_away(update, context)
    elif text == "🚶 End Away":
        await end_away(update, context)
    elif text == "📊 Status":
        await status(update, context)
    elif text == "📋 My Total":
        await mytotal(update, context)

def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("teamstatus", status))
    app.add_handler(CommandHandler("mytotal", mytotal))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    print("BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()