import os
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL") or "@your_channel").strip()
SUBSCRIBE_TO = (os.getenv("SUBSCRIBE_TO") or f"https://t.me/{CHANNEL.lstrip('@')}").strip()
SUGGEST_TO = "https://t.me/stridiv"

ALLOWED_ADMINS = set()
raw_admins = (os.getenv("ALLOWED_ADMINS") or "").strip()
if raw_admins:
    for x in raw_admins.split(","):
        x = x.strip()
        if x.isdigit():
            ALLOWED_ADMINS.add(int(x))

def keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Подписаться на канал", url=SUBSCRIBE_TO),
        InlineKeyboardButton("✉️ Предложить новость", url=SUGGEST_TO),
    ]])

def allowed(user_id: Optional[int]) -> bool:
    return (not ALLOWED_ADMINS) or (user_id in ALLOWED_ADMINS)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Пришли пост (текст/фото/видео/файл) — опубликую в канал с кнопками.\n/myid — твой ID")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой ID: {update.effective_user.id}")

async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    uid = update.effective_user.id if update.effective_user else None
    if not allowed(uid):
        await msg.reply_text("⛔️ Нет прав на публикацию.")
        return

    if msg.text and not (msg.photo or msg.video or msg.document or msg.animation):
        await context.bot.send_message(chat_id=CHANNEL, text=msg.text, reply_markup=keyboard())
        await msg.reply_text("✅ Опубликовано.")
        return

    if msg.photo:
        await context.bot.send_photo(chat_id=CHANNEL, photo=msg.photo[-1].file_id, caption=msg.caption or "", reply_markup=keyboard())
        await msg.reply_text("✅ Опубликовано.")
        return

    if msg.video:
        await context.bot.send_video(chat_id=CHANNEL, video=msg.video.file_id, caption=msg.caption or "", reply_markup=keyboard())
        await msg.reply_text("✅ Опубликовано.")
        return

    if msg.document:
        await context.bot.send_document(chat_id=CHANNEL, document=msg.document.file_id, caption=msg.caption or "", reply_markup=keyboard())
        await msg.reply_text("✅ Опубликовано.")
        return

    if msg.animation:
        await context.bot.send_animation(chat_id=CHANNEL, animation=msg.animation.file_id, caption=msg.caption or "", reply_markup=keyboard())
        await msg.reply_text("✅ Опубликовано.")
        return

    await msg.reply_text("⚠️ Тип сообщения пока не поддержан.")

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, publish))
    print("🤖 Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
