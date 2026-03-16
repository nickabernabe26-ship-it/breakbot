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

ROLES = ["CS", "TL", "HTL", "QI", "WD", "DP"]
DEFAULT_BREAK_LIMIT = 60
AWAY_LIMIT = 60
NEAR_LIMIT_MINUTES = 5  # show ⚠️ when within 5 mins of limit

keyboard = [
    ["☕ Start Break", "☕ End Break"],
    ["🚶 Start Away", "🚶 End Away"],
    ["📊 Status", "📋 My Total"],
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "default_break_limit": DEFAULT_BREAK_LIMIT,
            "away_limit": AWAY_LIMIT,
            "users": {}
        }

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {
            "default_break_limit": DEFAULT_BREAK_LIMIT,
            "away_limit": AWAY_LIMIT,
            "users": {}
        }

    data.setdefault("default_break_limit", DEFAULT_BREAK_LIMIT)
    data.setdefault("away_limit", AWAY_LIMIT)
    data.setdefault("users", {})
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def now_local():
    return datetime.datetime.now(TIMEZONE)


def format_clock(dt: datetime.datetime) -> str:
    return dt.astimezone(TIMEZONE).strftime("%I:%M %p")


def minutes_between(start: datetime.datetime, end: datetime.datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))


def format_session_minutes(total_minutes: int) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes} mins"


def format_elapsed_hhmm(total_minutes: int) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def role_count(users):
    counts = {role: 0 for role in ROLES}
    for user in users:
        role = user.get("role")
        if role in counts:
            counts[role] += 1
    return counts


def ensure_user(data, user_id: str, chat_id: int, fallback_name: str):
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "name": fallback_name.upper(),
            "role": "UNKNOWN",
            "break_total": 0,
            "away_total": 0,
            "active": None,
            "chat_id": chat_id,
            "custom_break_limit": None,
        }
    else:
        data["users"][user_id]["chat_id"] = chat_id


def get_user_break_limit(data, user):
    custom = user.get("custom_break_limit")
    if isinstance(custom, int) and custom > 0:
        return custom
    return int(data.get("default_break_limit", DEFAULT_BREAK_LIMIT))


def get_status_marker(elapsed: int, limit: int) -> str:
    if elapsed > limit:
        return " 🚨"
    if elapsed >= max(1, limit - NEAR_LIMIT_MINUTES):
        return " ⚠️"
    return ""


def get_users_for_chat(data, chat_id: int):
    return {
        uid: user
        for uid, user in data["users"].items()
        if user.get("chat_id") == chat_id
    }


def find_user_by_registered_name(data, chat_id: int, target_name: str):
    target = target_name.strip().upper()
    for uid, user in get_users_for_chat(data, chat_id).items():
        if user.get("name", "").strip().upper() == target:
            return uid, user
    return None, None


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False

    if update.effective_chat.type == "private":
        return True

    member = await context.bot.get_chat_member(
        update.effective_chat.id,
        update.effective_user.id
    )
    return member.status in ("administrator", "creator")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    data = load_data()
    uid = str(update.effective_user.id)
    ensure_user(data, uid, update.effective_chat.id, update.effective_user.first_name)
    save_data(data)

    await update.message.reply_text(
        "Break Tracker is ready.\n\n"
        "Register first using:\n"
        "/register CS\n"
        "/register TL\n"
        "/register HTL\n"
        "/register QI\n"
        "/register WD\n"
        "/register DP",
        reply_markup=reply_markup
    )


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/register CS")
        return

    role = context.args[0].upper().strip()
    if role not in ROLES:
        await update.message.reply_text(
            "Invalid role.\nUse one of: CS, TL, HTL, QI, WD, DP"
        )
        return

    uid = str(update.effective_user.id)
    chat_id = update.effective_chat.id
    raw_name = update.effective_user.first_name.upper().replace(" ", "-")

    # FIX: prevent duplicate names like IND06-CS-IND06-CS-NIKKA
    if raw_name.startswith("IND06-"):
        registered_name = raw_name
    else:
        registered_name = f"IND06-{role}-{raw_name}"

    data = load_data()
    data["users"][uid] = {
        "name": registered_name,
        "role": role,
        "break_total": 0,
        "away_total": 0,
        "active": None,
        "chat_id": chat_id,
        "custom_break_limit": None,
    }
    save_data(data)

    await update.message.reply_text(
        f"✅ Registration successful\n\n"
        f"Name: {registered_name}\n"
        f"Role: {role}"
    )


async def start_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    data = load_data()
    uid = str(update.effective_user.id)
    user = data["users"].get(uid)

    if not user:
        await update.message.reply_text("Please register first.\n/register CS")
        return

    if user.get("active") is not None:
        await update.message.reply_text(
            "You already have an active status. Please end it first."
        )
        return

    current = now_local()
    user["active"] = {
        "type": "break",
        "start": current.isoformat()
    }
    save_data(data)

    await update.message.reply_text(
        f"{user['name']}\n"
        f"☕ Break started at {format_clock(current)}"
    )


async def end_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    data = load_data()
    uid = str(update.effective_user.id)
    user = data["users"].get(uid)

    if not user or not user.get("active") or user["active"]["type"] != "break":
        await update.message.reply_text("You do not have an active break.")
        return

    current = now_local()
    start_dt = datetime.datetime.fromisoformat(user["active"]["start"])
    session_minutes = minutes_between(start_dt, current)

    user["break_total"] += session_minutes
    user["active"] = None

    break_limit = get_user_break_limit(data, user)
    remaining = max(0, break_limit - user["break_total"])
    exceeded = max(0, user["break_total"] - break_limit)

    save_data(data)

    message = (
        f"{user['name']}\n"
        f"☕ Break ended at {format_clock(current)}\n"
        f"This session: {format_session_minutes(session_minutes)}\n"
        f"Total break today: {user['break_total']} mins\n"
        f"Remaining break time: {remaining} mins"
    )

    if exceeded > 0:
        message += f"\n⚠️ You exceeded the break limit by {exceeded} mins."

    await update.message.reply_text(message)


async def start_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    data = load_data()
    uid = str(update.effective_user.id)
    user = data["users"].get(uid)

    if not user:
        await update.message.reply_text("Please register first.\n/register CS")
        return

    if user.get("active") is not None:
        await update.message.reply_text(
            "You already have an active status. Please end it first."
        )
        return

    current = now_local()
    user["active"] = {
        "type": "away",
        "start": current.isoformat()
    }
    save_data(data)

    await update.message.reply_text(
        f"{user['name']}\n"
        f"🚶 Away started at {format_clock(current)}"
    )


async def end_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    data = load_data()
    uid = str(update.effective_user.id)
    user = data["users"].get(uid)

    if not user or not user.get("active") or user["active"]["type"] != "away":
        await update.message.reply_text("You do not have an active away status.")
        return

    current = now_local()
    start_dt = datetime.datetime.fromisoformat(user["active"]["start"])
    session_minutes = minutes_between(start_dt, current)

    user["away_total"] += session_minutes
    user["active"] = None

    away_limit = int(data.get("away_limit", AWAY_LIMIT))
    remaining = max(0, away_limit - user["away_total"])
    exceeded = max(0, user["away_total"] - away_limit)

    save_data(data)

    message = (
        f"{user['name']}\n"
        f"🚶 Away ended at {format_clock(current)}\n"
        f"This session: {format_session_minutes(session_minutes)}\n"
        f"Total away today: {user['away_total']} mins\n"
        f"Remaining away time: {remaining} mins"
    )

    if exceeded > 0:
        message += f"\n⚠️ You exceeded the away limit by {exceeded} mins."

    await update.message.reply_text(message)


async def mytotal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    data = load_data()
    uid = str(update.effective_user.id)
    user = data["users"].get(uid)

    if not user:
        await update.message.reply_text("Please register first.")
        return

    break_limit = get_user_break_limit(data, user)
    away_limit = int(data.get("away_limit", AWAY_LIMIT))

    await update.message.reply_text(
        f"{user['name']}\n"
        f"Break total: {user['break_total']} mins\n"
        f"Break remaining: {max(0, break_limit - user['break_total'])} mins\n"
        f"Away total: {user['away_total']} mins\n"
        f"Away remaining: {max(0, away_limit - user['away_total'])} mins\n"
        f"Combined total: {user['break_total'] + user['away_total']} mins"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    data = load_data()
    chat_id = update.effective_chat.id
    users = get_users_for_chat(data, chat_id)

    break_users = []
    away_users = []
    working_users = []

    current = now_local()

    for user in users.values():
        active = user.get("active")
        if not active:
            working_users.append(user)
            continue

        start_dt = datetime.datetime.fromisoformat(active["start"])
        elapsed = minutes_between(start_dt, current)

        if active["type"] == "break":
            limit = get_user_break_limit(data, user)
            break_users.append({
                "name": user["name"],
                "elapsed": elapsed,
                "since": format_clock(start_dt),
                "marker": get_status_marker(elapsed, limit),
                "role": user.get("role", "UNKNOWN"),
            })
        elif active["type"] == "away":
            limit = int(data.get("away_limit", AWAY_LIMIT))
            away_users.append({
                "name": user["name"],
                "elapsed": elapsed,
                "since": format_clock(start_dt),
                "marker": get_status_marker(elapsed, limit),
                "role": user.get("role", "UNKNOWN"),
            })

    working_counts = role_count(working_users)
    break_counts = role_count(break_users)
    away_counts = role_count(away_users)

    lines = ["📊 LIVE TEAM STATUS\n"]

    lines.append(f"☕ Break ({len(break_users)})")
    lines.append(" | ".join([f"{role}: {break_counts[role]}" for role in ROLES]))
    if break_users:
        for item in sorted(break_users, key=lambda x: x["name"]):
            lines.append(
                f"• {item['name']} — since {item['since']} ({format_elapsed_hhmm(item['elapsed'])}){item['marker']}"
            )
    lines.append("")

    lines.append(f"🚶 Away ({len(away_users)})")
    lines.append(" | ".join([f"{role}: {away_counts[role]}" for role in ROLES]))
    if away_users:
        for item in sorted(away_users, key=lambda x: x["name"]):
            lines.append(
                f"• {item['name']} — since {item['since']} ({format_elapsed_hhmm(item['elapsed'])}){item['marker']}"
            )
    lines.append("")

    lines.append(f"✅ Working ({len(working_users)})")
    lines.append(" | ".join([f"{role}: {working_counts[role]}" for role in ROLES]))

    await update.message.reply_text("\n".join(lines))


async def teamstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await status(update, context)


async def setbreak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/setbreak 90")
        return

    try:
        new_limit = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Break limit must be a number.")
        return

    if new_limit <= 0:
        await update.message.reply_text("Break limit must be greater than 0.")
        return

    data = load_data()
    data["default_break_limit"] = new_limit
    save_data(data)

    await update.message.reply_text(
        f"✅ Default break limit updated\n\n"
        f"New default break limit: {new_limit} minutes"
    )


async def setuserbreak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage:\n/setuserbreak IND06-CS-NIKKA 30")
        return

    target_name = " ".join(context.args[:-1]).strip()
    try:
        custom_limit = int(context.args[-1])
    except ValueError:
        await update.message.reply_text("Break limit must be a number.")
        return

    if custom_limit <= 0:
        await update.message.reply_text("Break limit must be greater than 0.")
        return

    data = load_data()
    uid, user = find_user_by_registered_name(data, update.effective_chat.id, target_name)

    if not user:
        await update.message.reply_text("User not found.")
        return

    user["custom_break_limit"] = custom_limit
    save_data(data)

    await update.message.reply_text(
        f"✅ User break limit updated\n\n"
        f"User: {user['name']}\n"
        f"Break limit: {custom_limit} minutes"
    )


async def resetuserbreak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/resetuserbreak IND06-CS-NIKKA")
        return

    target_name = " ".join(context.args).strip()
    data = load_data()
    uid, user = find_user_by_registered_name(data, update.effective_chat.id, target_name)

    if not user:
        await update.message.reply_text("User not found.")
        return

    user["custom_break_limit"] = None
    save_data(data)

    await update.message.reply_text(
        f"✅ User custom break limit removed\n\n"
        f"User: {user['name']} now uses the default break limit."
    )


async def currentlimits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    data = load_data()
    chat_users = get_users_for_chat(data, update.effective_chat.id)

    lines = [
        "Current limits\n",
        f"Default break: {data.get('default_break_limit', DEFAULT_BREAK_LIMIT)} mins",
        f"Default away: {data.get('away_limit', AWAY_LIMIT)} mins",
        "",
        "Custom break limits:"
    ]

    found = False
    for user in sorted(chat_users.values(), key=lambda x: x["name"]):
        custom = user.get("custom_break_limit")
        if isinstance(custom, int) and custom > 0:
            found = True
            lines.append(f"{user['name']} — {custom} mins")

    if not found:
        lines.append("None")

    await update.message.reply_text("\n".join(lines))


async def forceend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/forceend IND06-CS-NIKKA")
        return

    target_name = " ".join(context.args).strip()
    data = load_data()
    uid, user = find_user_by_registered_name(data, update.effective_chat.id, target_name)

    if not user:
        await update.message.reply_text("User not found.")
        return

    active = user.get("active")
    if not active:
        await update.message.reply_text(f"{user['name']} has no active status.")
        return

    current = now_local()
    start_dt = datetime.datetime.fromisoformat(active["start"])
    session_minutes = minutes_between(start_dt, current)

    if active["type"] == "break":
        user["break_total"] += session_minutes
        limit = get_user_break_limit(data, user)
        remaining = max(0, limit - user["break_total"])
        exceeded = max(0, user["break_total"] - limit)
        status_type = "Break"
        remaining_text = f"Remaining break time: {remaining} mins"
        exceeded_text = f"\n⚠️ Exceeded break limit by {exceeded} mins." if exceeded > 0 else ""
    else:
        user["away_total"] += session_minutes
        limit = int(data.get("away_limit", AWAY_LIMIT))
        remaining = max(0, limit - user["away_total"])
        exceeded = max(0, user["away_total"] - limit)
        status_type = "Away"
        remaining_text = f"Remaining away time: {remaining} mins"
        exceeded_text = f"\n⚠️ Exceeded away limit by {exceeded} mins." if exceeded > 0 else ""

    user["active"] = None
    save_data(data)

    await update.message.reply_text(
        f"✅ Active status ended by admin\n\n"
        f"User: {user['name']}\n"
        f"Type: {status_type}\n"
        f"Ended at: {format_clock(current)}\n"
        f"This session: {format_session_minutes(session_minutes)}\n"
        f"{remaining_text}{exceeded_text}"
    )


async def resetuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/resetuser IND06-CS-NIKKA")
        return

    target_name = " ".join(context.args).strip()
    data = load_data()
    uid, user = find_user_by_registered_name(data, update.effective_chat.id, target_name)

    if not user:
        await update.message.reply_text("User not found.")
        return

    user["break_total"] = 0
    user["away_total"] = 0
    user["active"] = None
    save_data(data)

    await update.message.reply_text(
        f"✅ User reset successfully\n\nUser: {user['name']}"
    )


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
    app.add_handler(CommandHandler("mytotal", mytotal))
    app.add_handler(CommandHandler("teamstatus", teamstatus))
    app.add_handler(CommandHandler("setbreak", setbreak))
    app.add_handler(CommandHandler("setuserbreak", setuserbreak))
    app.add_handler(CommandHandler("resetuserbreak", resetuserbreak))
    app.add_handler(CommandHandler("currentlimits", currentlimits))
    app.add_handler(CommandHandler("forceend", forceend))
    app.add_handler(CommandHandler("resetuser", resetuser))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    print("BOT RUNNING")
    app.run_polling()


if __name__ == "__main__":
    main()