from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import datetime

TOKEN = "8627613345:AAGcA7LYcwiOkH8IGrYuVJg2_D1VbdykT0U"

users = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Break Tracker Bot Ready")

async def away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.id
    users[user] = datetime.datetime.now()
    await update.message.reply_text("Away started")

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.id

    if user not in users:
        await update.message.reply_text("No active break")
        return

    start_time = users[user]
    end_time = datetime.datetime.now()

    duration = end_time - start_time
    minutes = int(duration.total_seconds() / 60)

    await update.message.reply_text(f"Break time: {minutes} minutes")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("away", away))
app.add_handler(CommandHandler("back", back))

print("Bot running...")

app.run_polling()