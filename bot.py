import os
import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")

break_users = {}
away_users = {}

BREAK_LIMIT = 60
AWAY_LIMIT = 40

keyboard = [
    ["☕ Start Break", "☕ End Break"],
    ["🚶 Start Away", "🚶 End Away"],
    ["📊 Status"]
]

reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Break Tracker Ready",
        reply_markup=reply_markup
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.effective_user.id

    now = datetime.datetime.now()

    # START BREAK
    if text == "☕ Start Break":
        break_users[user] = now
        await update.message.reply_text("Break started.")

    # END BREAK
    elif text == "☕ End Break":
        if user not in break_users:
            await update.message.reply_text("No active break.")
            return

        duration = now - break_users[user]
        minutes = int(duration.total_seconds() / 60)

        del break_users[user]

        if minutes > BREAK_LIMIT:
            await update.message.reply_text(
                f"Break time: {minutes} minutes ⚠️\nYou exceeded the 60 minute limit."
            )
        else:
            await update.message.reply_text(f"Break time: {minutes} minutes")

    # START AWAY
    elif text == "🚶 Start Away":
        away_users[user] = now
        await update.message.reply_text("Away started.")

    # END AWAY
    elif text == "🚶 End Away":
        if user not in away_users:
            await update.message.reply_text("No active away.")
            return

        duration = now - away_users[user]
        minutes = int(duration.total_seconds() / 60)

        del away_users[user]

        if minutes > AWAY_LIMIT:
            await update.message.reply_text(
                f"Away time: {minutes} minutes ⚠️\nYou exceeded the 40 minute limit."
            )
        else:
            await update.message.reply_text(f"Away time: {minutes} minutes")

    # STATUS
    elif text == "📊 Status":
        msg = "Status:\n"

        if user in break_users:
            msg += "Currently on BREAK\n"
        elif user in away_users:
            msg += "Currently AWAY\n"
        else:
            msg += "Working"

        await update.message.reply_text(msg)


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()