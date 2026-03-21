import os
import json
import asyncio
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
DATA_FILE = "/mnt/data/break_data.json"
TIMEZONE = ZoneInfo("Asia/Manila")

ROLES = ["CS", "CSL", "HTL", "PHTL", "AS", "QI", "WD", "DP", "PL"]

DEFAULT_BREAK_LIMIT = 60
DEFAULT_AWAY_TOTAL_LIMIT = 60
AWAY_SESSION_LIMIT = 20
NEAR_LIMIT_MINUTES = 5

keyboard = [
    ["🟢 On Duty"],
    ["☕ Start Break", "☕ End Break"],
    ["🚶 Start Away", "🚶 End Away"],
    ["📊 Status", "📋 My Total"],
]
reply_markup = ReplyKeyboardMarkup(
    keyboard,
    resize_keyboard=True,
    is_persistent=True,
)
DATA_LOCK = asyncio.Lock()


def default_data():
    return {
        "default_break_limit": DEFAULT_BREAK_LIMIT,
        "away_total_limit": DEFAULT_AWAY_TOTAL_LIMIT,
        "away_session_limit": AWAY_SESSION_LIMIT,
        "users": {},
    }


def normalize_role(role: str) -> str:
    role = (role or "CS").upper()
    return role if role in ROLES else "CS"


def detect_role_from_username_or_name(username=None, fallback_name=None):
    text = f"{username or ''} {fallback_name or ''}".lower()

    if "phtl" in text:
        return "PHTL"
    if "htl" in text:
        return "HTL"
    if "csl" in text:
        return "CSL"
    if "-as-" in text:
        return "AS"
    if "pl" in text:
        return "PL"
    if "qi" in text:
        return "QI"
    if "wd" in text:
        return "WD"
    if "dp" in text:
        return "DP"

        return "CS"


def strip_existing_prefix(name: str) -> str:
    value = (name or "UNKNOWN").upper().replace(" ", "-")
    prefixes = [
        "IND06-CS-",
        "IND06-CSL-",
        "IND06-HTL-",
        "IND06-QI-",
        "IND06-WD-",
        "IND06-DP-",
        "IND06-PL-",
        "IND06-TL-",
    ]
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix):]
    if value.startswith("IND06-"):
        return value[6:]
    return value


def build_display_name(role: str, fallback_name: str):
    clean_name = strip_existing_prefix(fallback_name)
    return f"IND06-{role}-{clean_name}"


def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = default_data()

    data.setdefault("default_break_limit", DEFAULT_BREAK_LIMIT)
    data.setdefault("away_total_limit", DEFAULT_AWAY_TOTAL_LIMIT)
    data.setdefault("away_session_limit", AWAY_SESSION_LIMIT)
    data.setdefault("users", {})

    for user in data["users"].values():
        original_name = user.get("name", "UNKNOWN")
        username = user.get("username")
        fixed_role = detect_role_from_username_or_name(username, original_name)

        user["role"] = normalize_role(fixed_role)
        user["name"] = build_display_name(user["role"], original_name)
        user.setdefault("break_total", 0)
        user.setdefault("away_total", 0)
        user.setdefault("active", None)
        user.setdefault("chat_id", None)
        user.setdefault("custom_break_limit", None)
        user.setdefault("username", username)
        user.setdefault("on_duty", False)

    return data


def save_data(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    temp_file = f"{DATA_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, DATA_FILE)


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
        role = normalize_role(user.get("role", "UNKNOWN"))
        if role in counts:
            counts[role] += 1
    return counts


def ensure_user(data, user_id: str, chat_id: int, fallback_name: str, username=None):
    users = data["users"]
    role = detect_role_from_username_or_name(username, fallback_name)
    display_name = build_display_name(role, fallback_name)

    if user_id not in users:
        users[user_id] = {
            "name": display_name,
            "role": role,
            "break_total": 0,
            "away_total": 0,
            "active": None,
            "chat_id": chat_id,
            "custom_break_limit": None,
            "username": username,
            "on_duty": False,
        }
    else:
        user = users[user_id]
        user["chat_id"] = chat_id
        user["role"] = role
        user["name"] = display_name
        user.setdefault("break_total", 0)
        user.setdefault("away_total", 0)
        user.setdefault("active", None)
        user.setdefault("custom_break_limit", None)
        user["username"] = username
        user.setdefault("on_duty", False)


def get_user_break_limit(data, user):
    custom = user.get("custom_break_limit")
    if isinstance(custom, int) and custom > 0:
        return custom
    return int(data.get("default_break_limit", DEFAULT_BREAK_LIMIT))


def get_away_total_limit(data):
    return int(data.get("away_total_limit", DEFAULT_AWAY_TOTAL_LIMIT))


def get_away_session_limit(data):
    return int(data.get("away_session_limit", AWAY_SESSION_LIMIT))


def get_status_marker(elapsed: int, limit: int, status_type: str) -> str:
    if elapsed > limit:
        return " ⚠️ OVER BREAK" if status_type == "break" else " ⚠️ OVER AWAY"
    if elapsed >= max(1, limit - NEAR_LIMIT_MINUTES):
        return " ⚠️ NEAR BREAK LIMIT" if status_type == "break" else " ⚠️ NEAR AWAY LIMIT"
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


def find_user_flexible(data, chat_id: int, raw_target: str):
    target = raw_target.strip().upper().replace("@", "").replace(" ", "-")
    target_no_prefix = strip_existing_prefix(target)

    for uid, user in get_users_for_chat(data, chat_id).items():
        name = (user.get("name", "") or "").strip().upper()
        username = (user.get("username", "") or "").strip().upper()
        name_no_prefix = strip_existing_prefix(name)

        if target == name:
            return uid, user
        if username and target == username:
            return uid, user
        if target == name_no_prefix:
            return uid, user
        if username and target in username:
            return uid, user
        if target_no_prefix == name_no_prefix:
            return uid, user

    return None, None


def get_summary_chat_id(data):
    group_ids = []
    any_ids = []

    for user in data["users"].values():
        chat_id = user.get("chat_id")
        if isinstance(chat_id, int):
            any_ids.append(chat_id)
            if chat_id < 0:
                group_ids.append(chat_id)

    if group_ids:
        return group_ids[0]
    if any_ids:
        return any_ids[0]
    return None


def close_active_session(data, user, end_time):
    active = user.get("active")
    if not active:
        return None

    try:
        start_dt = datetime.datetime.fromisoformat(active["start"])
    except Exception:
        return None

    session_minutes = minutes_between(start_dt, end_time)
    status_type = active.get("type")

    if status_type == "break":
        user["break_total"] = user.get("break_total", 0) + session_minutes
    elif status_type == "away":
        user["away_total"] = user.get("away_total", 0) + session_minutes
    else:
        return None

    user["active"] = None

    return {
        "type": status_type,
        "start_dt": start_dt,
        "session_minutes": session_minutes,
    }


def is_working_user(user):
    if user.get("active") is not None:
        return False
    if user.get("on_duty"):
        return True
    if user.get("break_total", 0) > 0:
        return True
    if user.get("away_total", 0) > 0:
        return True
    return False


def build_whole_shift_summary(data, chat_id: int):
    users = get_users_for_chat(data, chat_id)

    if not users:
        return "📊 WHOLE SHIFT SUMMARY\n\nNo users found in this chat.", []

    current = now_local()
    overbreak = []
    overaway = []

    lines = ["📊 WHOLE SHIFT SUMMARY", ""]

    for user in sorted(users.values(), key=lambda x: x["name"]):
        break_total = user.get("break_total", 0)
        away_total = user.get("away_total", 0)

        active = user.get("active")
        if active:
            try:
                start_dt = datetime.datetime.fromisoformat(active["start"])
                elapsed = minutes_between(start_dt, current)
                if active.get("type") == "break":
                    break_total += elapsed
                elif active.get("type") == "away":
                    away_total += elapsed
            except Exception:
                pass

        break_limit = get_user_break_limit(data, user)
        away_limit = get_away_total_limit(data)

        break_flag = ""
        away_flag = ""

        if break_total > break_limit:
            break_flag = " ⚠️ OVER BREAK"
            if user.get("username"):
                overbreak.append(f"@{user['username']}")
            else:
                overbreak.append(user["name"])

        if away_total > away_limit:
            away_flag = " ⚠️ OVER AWAY"
            if user.get("username"):
                overaway.append(f"@{user['username']}")
            else:
                overaway.append(user["name"])

        lines.append(f"{user['name']}")
        lines.append(f"Break: {break_total} mins{break_flag}")
        lines.append(f"Away: {away_total} mins{away_flag}")
        lines.append("")

    tagged = list(dict.fromkeys(overbreak + overaway))
    return "\n".join(lines).strip(), tagged


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False

    if update.effective_chat.type == "private":
        return True

    member = await context.bot.get_chat_member(
        update.effective_chat.id,
        update.effective_user.id,
    )
    return member.status in ("administrator", "creator")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        uid = str(update.effective_user.id)
        ensure_user(
            data,
            uid,
            update.effective_chat.id,
            update.effective_user.first_name,
            update.effective_user.username,
        )
        save_data(data)

    await update.message.reply_text(
        "Break Tracker is ready.\n\n"
        "Buttons are active.\n"
        "User record and role are detected automatically.",
        reply_markup=reply_markup,
    )


async def onduty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        uid = str(update.effective_user.id)
        ensure_user(
            data,
            uid,
            update.effective_chat.id,
            update.effective_user.first_name,
            update.effective_user.username,
        )
        user = data["users"].get(uid)
        user["on_duty"] = True
        save_data(data)

    # silent - no group message


async def start_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        uid = str(update.effective_user.id)
        ensure_user(
            data,
            uid,
            update.effective_chat.id,
            update.effective_user.first_name,
            update.effective_user.username,
        )
        user = data["users"].get(uid)

        if user.get("active") is not None:
            await update.message.reply_text(
                "You already have an active status. Please end it first."
            )
            return

        current = now_local()
        user["active"] = {
            "type": "break",
            "start": current.isoformat(),
        }
        user["on_duty"] = True
        save_data(data)

    await update.message.reply_text(
        f"{user['name']}\n☕ Break started at {format_clock(current)}"
    )


async def end_break(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        uid = str(update.effective_user.id)

        ensure_user(
            data,
            uid,
            update.effective_chat.id,
            update.effective_user.first_name,
            update.effective_user.username,
        )
        user = data["users"].get(uid)

        active = user.get("active")
        if not active or "start" not in active:
            await update.message.reply_text("You do not have an active break.")
            return

        if active.get("type") != "break":
            await update.message.reply_text("You currently have an active away, not break.")
            return

        current = now_local()
        closed = close_active_session(data, user, current)

        if not closed:
            await update.message.reply_text(
                "Your active break data looks invalid. Admin may use /forceend if needed."
            )
            return

        session_minutes = closed["session_minutes"]

        break_limit = get_user_break_limit(data, user)
        remaining = max(0, break_limit - user["break_total"])
        exceeded = max(0, user["break_total"] - break_limit)

        user["on_duty"] = True
        save_data(data)

    message = (
        f"{user['name']}\n"
        f"☕ Break ended at {format_clock(current)}\n"
        f"This session: {format_session_minutes(session_minutes)}\n"
        f"Total break today: {user['break_total']} mins\n"
        f"Remaining break time: {remaining} mins"
    )

    if exceeded > 0:
        message += f"\n⚠️ OVER BREAK by {exceeded} mins."

    await update.message.reply_text(message)


async def start_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        uid = str(update.effective_user.id)
        ensure_user(
            data,
            uid,
            update.effective_chat.id,
            update.effective_user.first_name,
            update.effective_user.username,
        )
        user = data["users"].get(uid)

        if user.get("active") is not None:
            await update.message.reply_text(
                "You already have an active status. Please end it first."
            )
            return

        current = now_local()
        user["active"] = {
            "type": "away",
            "start": current.isoformat(),
        }
        user["on_duty"] = True
        save_data(data)

    await update.message.reply_text(
        f"{user['name']}\n🚶 Away started at {format_clock(current)}"
    )


async def end_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        uid = str(update.effective_user.id)

        ensure_user(
            data,
            uid,
            update.effective_chat.id,
            update.effective_user.first_name,
            update.effective_user.username,
        )
        user = data["users"].get(uid)

        active = user.get("active")
        if not active or "start" not in active:
            await update.message.reply_text("You do not have an active away status.")
            return

        if active.get("type") != "away":
            await update.message.reply_text("You currently have an active break, not away.")
            return

        current = now_local()
        closed = close_active_session(data, user, current)

        if not closed:
            await update.message.reply_text(
                "Your active away data looks invalid. Admin may use /forceend if needed."
            )
            return

        session_minutes = closed["session_minutes"]

        away_total_limit = get_away_total_limit(data)
        away_session_limit = get_away_session_limit(data)

        remaining = max(0, away_total_limit - user["away_total"])
        session_exceeded = max(0, session_minutes - away_session_limit)
        total_exceeded = max(0, user["away_total"] - away_total_limit)

        user["on_duty"] = True
        save_data(data)

    message = (
        f"{user['name']}\n"
        f"🚶 Away ended at {format_clock(current)}\n"
        f"This session: {format_session_minutes(session_minutes)}\n"
        f"Total away today: {user['away_total']} mins\n"
        f"Remaining away time: {remaining} mins"
    )

    if session_exceeded > 0:
        message += f"\n⚠️ OVER AWAY SESSION by {session_exceeded} mins."
    if total_exceeded > 0:
        message += f"\n⚠️ OVER AWAY TOTAL by {total_exceeded} mins."

    await update.message.reply_text(message)


async def mytotal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        uid = str(update.effective_user.id)
        ensure_user(
            data,
            uid,
            update.effective_chat.id,
            update.effective_user.first_name,
            update.effective_user.username,
        )
        user = data["users"].get(uid)

        break_limit = get_user_break_limit(data, user)
        away_total_limit = get_away_total_limit(data)
        away_session_limit = get_away_session_limit(data)

    await update.message.reply_text(
        f"{user['name']}\n"
        f"Break total: {user['break_total']} mins\n"
        f"Break remaining: {max(0, break_limit - user['break_total'])} mins\n"
        f"Away total: {user['away_total']} mins\n"
        f"Away remaining: {max(0, away_total_limit - user['away_total'])} mins\n"
        f"Per away max: {away_session_limit} mins\n"
        f"Combined total: {user['break_total'] + user['away_total']} mins"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    async with DATA_LOCK:
        data = load_data()
        chat_id = update.effective_chat.id
        users = get_users_for_chat(data, chat_id)

    break_users = []
    away_users = []
    working_users = []

    current = now_local()

    for user in users.values():
        active = user.get("active")
        if active:
            try:
                start_dt = datetime.datetime.fromisoformat(active["start"])
            except Exception:
                continue

            elapsed = minutes_between(start_dt, current)

            if active["type"] == "break":
                limit = get_user_break_limit(data, user)
                break_users.append({
                    "name": user["name"],
                    "elapsed": elapsed,
                    "since": format_clock(start_dt),
                    "marker": get_status_marker(elapsed, limit, "break"),
                    "role": normalize_role(user.get("role", "UNKNOWN")),
                })
            elif active["type"] == "away":
                limit = get_away_session_limit(data)
                away_users.append({
                    "name": user["name"],
                    "elapsed": elapsed,
                    "since": format_clock(start_dt),
                    "marker": get_status_marker(elapsed, limit, "away"),
                    "role": normalize_role(user.get("role", "UNKNOWN")),
                })
        else:
            if is_working_user(user):
                working_users.append(user)

    working_counts = role_count(working_users)
    break_counts = role_count(break_users)
    away_counts = role_count(away_users)

    lines = ["📊 LIVE TEAM STATUS\n"]

    lines.append(f"☕ Break ({len(break_users)})")
    lines.append(" | ".join([f"{role}: {break_counts[role]}" for role in ROLES]))
    if break_users:
        for item in sorted(break_users, key=lambda x: x["name"]):
            lines.append(
                f"• {item['name']} — since {item['since']} "
                f"({format_elapsed_hhmm(item['elapsed'])}){item['marker']}"
            )
    lines.append("")

    lines.append(f"🚶 Away ({len(away_users)})")
    lines.append(" | ".join([f"{role}: {away_counts[role]}" for role in ROLES]))
    if away_users:
        for item in sorted(away_users, key=lambda x: x["name"]):
            lines.append(
                f"• {item['name']} — since {item['since']} "
                f"({format_elapsed_hhmm(item['elapsed'])}){item['marker']}"
            )
    lines.append("")

    lines.append(f"✅ Working ({len(working_users)})")
    lines.append(" | ".join([f"{role}: {working_counts[role]}" for role in ROLES]))
    if working_users:
        for item in sorted(working_users, key=lambda x: x["name"]):
            lines.append(f"• {item['name']}")

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
        await update.message.reply_text("Usage:\n/setbreak 60")
        return

    try:
        new_limit = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Break limit must be a number.")
        return

    if new_limit <= 0:
        await update.message.reply_text("Break limit must be greater than 0.")
        return

    async with DATA_LOCK:
        data = load_data()
        data["default_break_limit"] = new_limit
        save_data(data)

    await update.message.reply_text(
        f"✅ Default break limit updated\n\n"
        f"New default break limit: {new_limit} minutes"
    )


async def setallbreak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/setallbreak 90")
        return

    try:
        new_limit = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Break limit must be a number.")
        return

    if new_limit <= 0:
        await update.message.reply_text("Break limit must be greater than 0.")
        return

    async with DATA_LOCK:
        data = load_data()
        for user in data["users"].values():
            user["custom_break_limit"] = new_limit
        save_data(data)

    await update.message.reply_text(
        f"✅ All users break limit updated\n\n"
        f"New break limit for everyone: {new_limit} minutes"
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

    async with DATA_LOCK:
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


async def setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage:\n/setlimit 90\n/setlimit indo06 nikka 30"
        )
        return

    async with DATA_LOCK:
        data = load_data()

        # /setlimit 90
        if len(context.args) == 1:
            try:
                new_limit = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Break limit must be a number.")
                return

            if new_limit <= 0:
                await update.message.reply_text("Break limit must be greater than 0.")
                return

            data["default_break_limit"] = new_limit
            save_data(data)

            await update.message.reply_text(
                f"✅ Break limit updated for all users.\n\nNew limit: {new_limit} minutes"
            )
            return

        # /setlimit indo06 nikka 30
        try:
            custom_limit = int(context.args[-1])
        except ValueError:
            await update.message.reply_text("Break limit must be a number.")
            return

        if custom_limit <= 0:
            await update.message.reply_text("Break limit must be greater than 0.")
            return

        target_name = " ".join(context.args[:-1]).strip()
        uid, user = find_user_flexible(data, update.effective_chat.id, target_name)

        if not user:
            await update.message.reply_text(
                "User not found. Make sure the user already clicked any button in this chat."
            )
            return

        user["custom_break_limit"] = custom_limit
        save_data(data)

    await update.message.reply_text(
        f"✅ Custom break limit updated.\n\nUser: {user['name']}\nBreak limit: {custom_limit} minutes"
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

    async with DATA_LOCK:
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

    async with DATA_LOCK:
        data = load_data()
        chat_users = get_users_for_chat(data, update.effective_chat.id)

    lines = [
        "Current limits\n",
        f"Default break: {data.get('default_break_limit', DEFAULT_BREAK_LIMIT)} mins",
        f"Default away total: {data.get('away_total_limit', DEFAULT_AWAY_TOTAL_LIMIT)} mins",
        f"Per away session max: {data.get('away_session_limit', AWAY_SESSION_LIMIT)} mins",
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

    async with DATA_LOCK:
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
        closed = close_active_session(data, user, current)

        if not closed:
            user["active"] = None
            save_data(data)
            await update.message.reply_text(
                f"⚠️ Invalid active session removed for {user['name']}."
            )
            return

        session_minutes = closed["session_minutes"]

        if closed["type"] == "break":
            limit = get_user_break_limit(data, user)
            remaining = max(0, limit - user["break_total"])
            exceeded = max(0, user["break_total"] - limit)
            status_type = "Break"
            remaining_text = f"Remaining break time: {remaining} mins"
            exceeded_text = f"\n⚠️ OVER BREAK by {exceeded} mins." if exceeded > 0 else ""
        else:
            away_total_limit = get_away_total_limit(data)
            away_session_limit = get_away_session_limit(data)
            remaining = max(0, away_total_limit - user["away_total"])
            session_exceeded = max(0, session_minutes - away_session_limit)
            total_exceeded = max(0, user["away_total"] - away_total_limit)
            status_type = "Away"
            remaining_text = f"Remaining away time: {remaining} mins"
            exceeded_text = ""
            if session_exceeded > 0:
                exceeded_text += f"\n⚠️ OVER AWAY SESSION by {session_exceeded} mins."
            if total_exceeded > 0:
                exceeded_text += f"\n⚠️ OVER AWAY TOTAL by {total_exceeded} mins."

        user["on_duty"] = True
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

    async with DATA_LOCK:
        data = load_data()
        uid, user = find_user_by_registered_name(data, update.effective_chat.id, target_name)

        if not user:
            await update.message.reply_text("User not found.")
            return

        user["break_total"] = 0
        user["away_total"] = 0
        user["active"] = None
        user["on_duty"] = False
        save_data(data)

    await update.message.reply_text(
        f"✅ User reset successfully\n\nUser: {user['name']}"
    )


async def resetall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("This command is for admins only.")
        return

    async with DATA_LOCK:
        data = load_data()
        chat_id = update.effective_chat.id

        # reset current chat only
        users_to_delete = [
            uid for uid, user in data["users"].items()
            if user.get("chat_id") == chat_id
        ]
        for uid in users_to_delete:
            del data["users"][uid]

        data["default_break_limit"] = DEFAULT_BREAK_LIMIT
        save_data(data)

    await update.message.reply_text(
    "🔄 Reset all complete.\n"
    "✅ Ready for new shift.\n"
    "✅ Break limit reset to 60 mins.",
    reply_markup=reply_markup,
)


async def endshift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not await is_admin(update, context):
        await update.message.reply_text("Admin only")
        return

    async with DATA_LOCK:
        data = load_data()
        chat_id = update.effective_chat.id
        msg, _ = build_whole_shift_summary(data, chat_id)

    await update.message.reply_text(msg)


async def auto_shift_summary(context: ContextTypes.DEFAULT_TYPE):
    async with DATA_LOCK:
        data = load_data()
        summary_chat_id = get_summary_chat_id(data)

        if not summary_chat_id:
            return

        msg, tagged = build_whole_shift_summary(data, summary_chat_id)

    try:
        await context.bot.send_message(chat_id=summary_chat_id, text=msg)
    except Exception:
        return

    if tagged:
        try:
            await context.bot.send_message(
                chat_id=summary_chat_id,
                text=(
                    f"🚨 Attention: {' '.join(tagged)}\n"
                    f"😭 Overaway/Overbreak detected. Please check your team."
                )
            )
        except Exception:
            pass


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text

    if text == "🟢 On Duty":
        await onduty(update, context)
    elif text == "☕ Start Break":
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

    app.job_queue.run_daily(
        auto_shift_summary,
        time=datetime.time(hour=7, minute=0, tzinfo=TIMEZONE),
        name="morning_shift_summary",
    )

    app.job_queue.run_daily(
        auto_shift_summary,
        time=datetime.time(hour=19, minute=0, tzinfo=TIMEZONE),
        name="night_shift_summary",
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mytotal", mytotal))
    app.add_handler(CommandHandler("teamstatus", teamstatus))
    app.add_handler(CommandHandler("setbreak", setbreak))
    app.add_handler(CommandHandler("setallbreak", setallbreak))
    app.add_handler(CommandHandler("setuserbreak", setuserbreak))
    app.add_handler(CommandHandler("setlimit", setlimit))
    app.add_handler(CommandHandler("resetuserbreak", resetuserbreak))
    app.add_handler(CommandHandler("currentlimits", currentlimits))
    app.add_handler(CommandHandler("forceend", forceend))
    app.add_handler(CommandHandler("resetuser", resetuser))
    app.add_handler(CommandHandler("resetall", resetall))
    app.add_handler(CommandHandler("endshift", endshift))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))

    print("BOT RUNNING")
    app.run_polling()


if __name__ == "__main__":
    main()