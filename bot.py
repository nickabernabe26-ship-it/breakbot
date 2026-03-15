import os
import json
import datetime
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "break_data.json"
TIMEZONE = ZoneInfo("Asia/Manila")

BREAK_LIMIT = 60
AWAY_LIMIT = 40

keyboard = [
    ["☕ Start Break", "☕ End Break"],
    ["🚶 Start Away", "🚶 End Away"],
    ["📊 Status", "📋 My Total"],
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


def now_local():
    return datetime.datetime.now(TIMEZONE)


def ensure_user(data, user_id, full_name):
    users = data["users"]
    if user_id not in users:
        users[user_id] = {
            "name": full_name,
            "break_total": 0,
            "away_total": 0,
            "active": None
        }
    else:
        users[user_id]["name"] = full_name


def format_minutes(minutes: int):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def get_status_text(user_data):
    active = user_data.get("active")
    if not active:
        return "Working"

    kind = active["type"]
    start_time = datetime.datetime.fromisoformat(active["start"])
    started = start_time.astimezone(TIMEZONE).strftime("%I:%M %p")

    if kind == "break":
        return f"Currently on BREAK since {started}"
    return f"Currently AWAY since {started}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    data["summary_chat_id"] = update.effective_chat.id

    user_id = str(update.effective_user.id)
    full_name = update.effective_user.full_name
    ensure_user(data, user_id, full_name)
    save_data(data)

    await update.message.reply_text(
        "Break Tracker Ready\n\n"
        "Buttons are now active.\n"
        "This chat is also set for the 12:00 AM daily summary.",
        reply_markup=reply_markup
    )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text
    user_id = str(update.effective_user.id)
    full_name = update.effective_user.full_name

    data = load_data()
    ensure_user(data, user_id, full_name)
    user = data["users"][user_id]
    now = now_local()

    if text == "☕ Start Break":
        if user["active"] is not None:
            await update.message.reply_text("May active status ka na. I-end mo muna bago mag-start ulit.")
            return

        user["active"] = {
            "type": "break",
            "start": now.isoformat()
        }
        save_data(data)
        await update.message.reply_text("☕ Break started.")

    elif text == "☕ End Break":
        active = user.get("active")
        if not active or active["type"] != "break":
            await update.message.reply_text("Wala kang active break.")
            return

        start_time = datetime.datetime.fromisoformat(active["start"])
        minutes = int((now - start_time).total_seconds() // 60)

        user["break_total"] += max(0, minutes)
        user["active"] = None
        save_data(data)

        if user["break_total"] > BREAK_LIMIT:
            exceeded = user["break_total"] - BREAK_LIMIT
            await update.message.reply_text(
                f"☕ Break ended.\n"
                f"This session: {minutes} mins\n"
                f"Total break today: {user['break_total']} mins\n"
                f"⚠️ Exceeded break limit by {exceeded} mins."
            )
        else:
            remaining = BREAK_LIMIT - user["break_total"]
            await update.message.reply_text(
                f"☕ Break ended.\n"
                f"This session: {minutes} mins\n"
                f"Total break today: {user['break_total']} mins\n"
                f"Remaining break time: {remaining} mins"
            )

    elif text == "🚶 Start Away":
        if user["active"] is not None:
            await update.message.reply_text("May active status ka na. I-end mo muna bago mag-start ulit.")
            return

        user["active"] = {
            "type": "away",
            "start": now.isoformat()
        }
        save_data(data)
        await update.message.reply_text("🚶 Away started.")

    elif text == "🚶 End Away":
        active = user.get("active")
        if not active or active["type"] != "away":
            await update.message.reply_text("Wala kang active away.")
            return

        start_time = datetime.datetime.fromisoformat(active["start"])
        minutes = int((now - start_time).total_seconds() // 60)

        user["away_total"] += max(0, minutes)
        user["active"] = None
        save_data(data)

        if user["away_total"] > AWAY_LIMIT:
            exceeded = user["away_total"] - AWAY_LIMIT
            await update.message.reply_text(
                f"🚶 Away ended.\n"
                f"This session: {minutes} mins\n"
                f"Total away today: {user['away_total']} mins\n"
                f"⚠️ Exceeded away limit by {exceeded} mins."
            )
        else:
            remaining = AWAY_LIMIT - user["away_total"]
            await update.message.reply_text(
                f"🚶 Away ended.\n"
                f"This session: {minutes} mins\n"
                f"Total away today: {user['away_total']} mins\n"
                f"Remaining away time: {remaining} mins"
            )

    elif text == "📊 Status":
        status_text = get_status_text(user)
        await update.message.reply_text(status_text)

    elif text == "📋 My Total":
        total_all = user["break_total"] + user["away_total"]
        await update.message.reply_text(
            f"📋 {user['name']}\n"
            f"Break total: {user['break_total']} mins\n"
            f"Away total: {user['away_total']} mins\n"
            f"Combined total: {total_all} mins"
        )


async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    chat_id = data.get("summary_chat_id")
    users = data.get("users", {})

    if not chat_id:
        return

    now = now_local()

    # isama ang active sessions hanggang 12:00 AM, tapos ituloy sila sa bagong araw
    for user_id, user in users.items():
        active = user.get("active")
        if active:
            start_time = datetime.datetime.fromisoformat(active["start"])
            minutes = int((now - start_time).total_seconds() // 60)

            if minutes > 0:
                if active["type"] == "break":
                    user["break_total"] += minutes
                elif active["type"] == "away":
                    user["away_total"] += minutes

            # reset start time para magpatuloy ang active status sa bagong araw
            user["active"]["start"] = now.isoformat()

    lines = ["📅 Daily Break/Away Summary\n"]

    has_data = False
    for user_id, user in users.items():
        break_total = user.get("break_total", 0)
        away_total = user.get("away_total", 0)
        combined = break_total + away_total

        if break_total == 0 and away_total == 0:
            continue

        has_data = True
        lines.append(
            f"{user['name']}\n"
            f"☕ Break: {break_total} mins"
            + (" ⚠️" if break_total > BREAK_LIMIT else "")
            + f"\n🚶 Away: {away_total} mins"
            + (" ⚠️" if away_total > AWAY_LIMIT else "")
            + f"\n🧾 Total: {combined} mins\n"
        )

    if not has_data:
        lines.append("No break or away logs for today.")

    message = "\n".join(lines)

    try:
        await context.bot.send_message(chat_id=chat_id, text=message, reply_markup=reply_markup)
    except Exception as e:
        print(f"Failed to send summary: {e}")

    # reset daily totals after summary
    for user_id, user in users.items():
        user["break_total"] = 0
        user["away_total"] = 0

    save_data(data)


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    # auto summary every 12:00 AM Manila time
    app.job_queue.run_daily(
        daily_summary,
        time=datetime.time(hour=0, minute=0, tzinfo=TIMEZONE),
        name="daily_summary"
    )

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()