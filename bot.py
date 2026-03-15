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
OVER_ALERT_INTERVAL = 5  # send over-limit alert every 5 minutes only

keyboard = [
    ["☕ Start Break", "☕ End Break"],
    ["🚶 Start Away", "🚶 End Away"],
    ["📊 Status", "📋 My Total"],
]

reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# keep scheduled over-limit jobs in memory
break_over_jobs = {}
away_over_jobs = {}


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


def format_time(dt):
    return dt.astimezone(TIMEZONE).strftime("%I:%M %p")


def format_session_minutes(minutes: int):
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def get_session_minutes(start_dt, end_dt):
    return max(0, int((end_dt - start_dt).total_seconds() // 60))


def get_status_text(user_data):
    active = user_data.get("active")
    if not active:
        return "You are currently working."

    kind = active["type"]
    start_time = datetime.datetime.fromisoformat(active["start"])
    started = format_time(start_time)

    if kind == "break":
        return f"You are currently on BREAK since {started}."
    return f"You are currently AWAY since {started}."


def cancel_break_over_job(user_id: str):
    job = break_over_jobs.get(user_id)
    if job:
        job.schedule_removal()
        break_over_jobs.pop(user_id, None)


def cancel_away_over_job(user_id: str):
    job = away_over_jobs.get(user_id)
    if job:
        job.schedule_removal()
        away_over_jobs.pop(user_id, None)


async def break_over_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]

    data = load_data()
    user = data.get("users", {}).get(user_id)
    if not user:
        return

    active = user.get("active")
    if not active or active.get("type") != "break":
        return

    now = now_local()
    start_time = datetime.datetime.fromisoformat(active["start"])
    session_minutes = get_session_minutes(start_time, now)

    if session_minutes <= BREAK_LIMIT:
        return

    over_minutes = session_minutes - BREAK_LIMIT

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🚨 OVERBREAK ALERT\n\n"
            f"User: {user['name']}\n"
            f"Over break: {over_minutes} minutes"
        )
    )


async def away_over_callback(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    user_id = job_data["user_id"]
    chat_id = job_data["chat_id"]

    data = load_data()
    user = data.get("users", {}).get(user_id)
    if not user:
        return

    active = user.get("active")
    if not active or active.get("type") != "away":
        return

    now = now_local()
    start_time = datetime.datetime.fromisoformat(active["start"])
    session_minutes = get_session_minutes(start_time, now)

    if session_minutes <= AWAY_LIMIT:
        return

    over_minutes = session_minutes - AWAY_LIMIT

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🚨 OVERAWAY ALERT\n\n"
            f"User: {user['name']}\n"
            f"Over away: {over_minutes} minutes"
        )
    )


def schedule_break_over_job(context: ContextTypes.DEFAULT_TYPE, user_id: str, chat_id: int):
    cancel_break_over_job(user_id)

    break_over_jobs[user_id] = context.job_queue.run_repeating(
        break_over_callback,
        interval=OVER_ALERT_INTERVAL * 60,
        first=BREAK_LIMIT * 60 + 60,  # first alert roughly 1 minute after limit
        data={
            "user_id": user_id,
            "chat_id": chat_id,
        },
        name=f"break_over_{user_id}"
    )


def schedule_away_over_job(context: ContextTypes.DEFAULT_TYPE, user_id: str, chat_id: int):
    cancel_away_over_job(user_id)

    away_over_jobs[user_id] = context.job_queue.run_repeating(
        away_over_callback,
        interval=OVER_ALERT_INTERVAL * 60,
        first=AWAY_LIMIT * 60 + 60,  # first alert roughly 1 minute after limit
        data={
            "user_id": user_id,
            "chat_id": chat_id,
        },
        name=f"away_over_{user_id}"
    )


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
        "Break Tracker is ready.\n\n"
        "Buttons are now active.\n"
        "This chat is set as the summary destination for 7:00 AM and 7:00 PM reports.",
        reply_markup=reply_markup
    )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text
    user_id = str(update.effective_user.id)
    full_name = update.effective_user.full_name
    chat_id = update.effective_chat.id

    data = load_data()
    ensure_user(data, user_id, full_name)
    user = data["users"][user_id]
    now = now_local()

    if text == "☕ Start Break":
        if user["active"] is not None:
            await update.message.reply_text(
                "You already have an active status. Please end it first before starting a new one."
            )
            return

        user["active"] = {
            "type": "break",
            "start": now.isoformat()
        }
        save_data(data)

        schedule_break_over_job(context, user_id, chat_id)

        await update.message.reply_text(
            f"{user['name']}\n"
            f"☕ Break started at {format_time(now)}"
        )

    elif text == "☕ End Break":
        active = user.get("active")
        if not active or active["type"] != "break":
            await update.message.reply_text("You do not have an active break.")
            return

        start_time = datetime.datetime.fromisoformat(active["start"])
        session_minutes = get_session_minutes(start_time, now)
        session_text = format_session_minutes(session_minutes)

        user["break_total"] += session_minutes
        user["active"] = None
        save_data(data)

        cancel_break_over_job(user_id)

        ended_at = format_time(now)
        remaining = max(0, BREAK_LIMIT - user["break_total"])

        if user["break_total"] > BREAK_LIMIT:
            exceeded = user["break_total"] - BREAK_LIMIT
            await update.message.reply_text(
                f"{user['name']}\n"
                f"☕ Break ended at {ended_at}\n"
                f"This session: {session_text}\n"
                f"Total break today: {user['break_total']} mins\n"
                f"Remaining break time: 0 mins\n"
                f"⚠️ You exceeded the break limit by {exceeded} mins."
            )
        else:
            await update.message.reply_text(
                f"{user['name']}\n"
                f"☕ Break ended at {ended_at}\n"
                f"This session: {session_text}\n"
                f"Total break today: {user['break_total']} mins\n"
                f"Remaining break time: {remaining} mins"
            )

    elif text == "🚶 Start Away":
        if user["active"] is not None:
            await update.message.reply_text(
                "You already have an active status. Please end it first before starting a new one."
            )
            return

        user["active"] = {
            "type": "away",
            "start": now.isoformat()
        }
        save_data(data)

        schedule_away_over_job(context, user_id, chat_id)

        await update.message.reply_text(
            f"{user['name']}\n"
            f"🚶 Away started at {format_time(now)}"
        )

    elif text == "🚶 End Away":
        active = user.get("active")
        if not active or active["type"] != "away":
            await update.message.reply_text("You do not have an active away status.")
            return

        start_time = datetime.datetime.fromisoformat(active["start"])
        session_minutes = get_session_minutes(start_time, now)
        session_text = format_session_minutes(session_minutes)

        user["away_total"] += session_minutes
        user["active"] = None
        save_data(data)

        cancel_away_over_job(user_id)

        ended_at = format_time(now)
        remaining = max(0, AWAY_LIMIT - user["away_total"])

        if user["away_total"] > AWAY_LIMIT:
            exceeded = user["away_total"] - AWAY_LIMIT
            await update.message.reply_text(
                f"{user['name']}\n"
                f"🚶 Away ended at {ended_at}\n"
                f"This session: {session_text}\n"
                f"Total away today: {user['away_total']} mins\n"
                f"Remaining away time: 0 mins\n"
                f"⚠️ You exceeded the away limit by {exceeded} mins."
            )
        else:
            await update.message.reply_text(
                f"{user['name']}\n"
                f"🚶 Away ended at {ended_at}\n"
                f"This session: {session_text}\n"
                f"Total away today: {user['away_total']} mins\n"
                f"Remaining away time: {remaining} mins"
            )

    elif text == "📊 Status":
        users = data["users"]

        break_users_list = []
        away_users_list = []
        working_users_list = []

        for _, u in users.items():
            active = u.get("active")

            if not active:
                working_users_list.append(u["name"])
            elif active["type"] == "break":
                break_users_list.append(u["name"])
            elif active["type"] == "away":
                away_users_list.append(u["name"])

        message = "📊 Live Team Status\n\n"

        message += f"☕ On Break ({len(break_users_list)})\n"
        if break_users_list:
            for name in break_users_list:
                message += f"- {name}\n"
        message += "\n"

        message += f"🚶 Away ({len(away_users_list)})\n"
        if away_users_list:
            for name in away_users_list:
                message += f"- {name}\n"
        message += "\n"

        message += f"✅ Working ({len(working_users_list)})"

        await update.message.reply_text(message)

    elif text == "📋 My Total":
        break_total = user["break_total"]
        away_total = user["away_total"]
        combined_total = break_total + away_total

        break_remaining = max(0, BREAK_LIMIT - break_total)
        away_remaining = max(0, AWAY_LIMIT - away_total)

        await update.message.reply_text(
            f"{user['name']}\n"
            f"Break total: {break_total} mins\n"
            f"Break remaining: {break_remaining} mins\n"
            f"Away total: {away_total} mins\n"
            f"Away remaining: {away_remaining} mins\n"
            f"Combined total: {combined_total} mins"
        )


async def send_shift_summary(context: ContextTypes.DEFAULT_TYPE, title: str):
    data = load_data()
    chat_id = data.get("summary_chat_id")
    users = data.get("users", {})

    if not chat_id:
        return

    now = now_local()

    # include active sessions up to shift cutoff, then continue into next shift
    for user_id, user in users.items():
        active = user.get("active")
        if active:
            start_time = datetime.datetime.fromisoformat(active["start"])
            minutes = get_session_minutes(start_time, now)

            if minutes > 0:
                if active["type"] == "break":
                    user["break_total"] += minutes
                elif active["type"] == "away":
                    user["away_total"] += minutes

            # restart active session from summary cutoff
            user["active"]["start"] = now.isoformat()

            # reschedule over-limit jobs for active sessions into new shift
            if active["type"] == "break":
                schedule_break_over_job(context, user_id, chat_id)
            elif active["type"] == "away":
                schedule_away_over_job(context, user_id, chat_id)

    lines = [f"{title}\n"]

    has_data = False
    for _, user in users.items():
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
        lines.append("No break or away logs for this shift.")

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"Failed to send summary: {e}")

    # reset totals for next shift
    for user in users.values():
        user["break_total"] = 0
        user["away_total"] = 0

    save_data(data)


async def seven_am_summary(context: ContextTypes.DEFAULT_TYPE):
    await send_shift_summary(context, "🌙 Night Shift Summary (7:00 PM - 7:00 AM)")


async def seven_pm_summary(context: ContextTypes.DEFAULT_TYPE):
    await send_shift_summary(context, "🌞 Morning Shift Summary (7:00 AM - 7:00 PM)")


def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN is missing")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    # 7:00 AM = night shift summary
    app.job_queue.run_daily(
        seven_am_summary,
        time=datetime.time(hour=7, minute=0, tzinfo=TIMEZONE),
        name="seven_am_summary"
    )

    # 7:00 PM = morning shift summary
    app.job_queue.run_daily(
        seven_pm_summary,
        time=datetime.time(hour=19, minute=0, tzinfo=TIMEZONE),
        name="seven_pm_summary"
    )

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()