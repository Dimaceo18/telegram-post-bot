import os
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL") or "@your_channel").strip()

SUGGEST_TO = "https://t.me/stridiv"

SUBSCRIBE_TO = (os.getenv("SUBSCRIBE_TO") or "").strip()
if not SUBSCRIBE_TO:
    SUBSCRIBE_TO = f"https://t.me/{CHANNEL.lstrip('@')}"

ALLOWED_ADMINS = set()
raw_admins = (os.getenv("ALLOWED_ADMINS") or "").strip()
if raw_admins:
    for part in raw_admins.split(","):
        part = part.strip()
        if part.isdigit():
            ALLOWED_ADMINS.add(int(part))


def post_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Подписаться на канал", url=SUBSCRIBE_TO),
            InlineKeyboardButton("✉️ Предложить новость", url=SUGGEST_TO),
        ]]
    )


def is_allowed(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    return (len(ALLOWED_ADMINS) == 0) or (user_id in ALLOWED_ADMINS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Пришли текст/фото/видео/документ — я опубликую это в канале с кнопками.\n\n"
        "Команды:\n"
        "/myid — узнать свой Telegram ID\n"
        "/test — показать настройки"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Ваш Telegram ID: {update.effective_user.id}")


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚙️ Настройки:\n"
        f"CHANNEL: {CHANNEL}\n"
        f"SUBSCRIBE_TO: {SUBSCRIBE_TO}\n"
        f"SUGGEST_TO: {SUGGEST_TO}\n"
        f"ALLOWED_ADMINS: {', '.join(map(str, sorted(ALLOWED_ADMINS))) if ALLOWED_ADMINS else 'не задано (разрешены все)'}"
    )


async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user_id = update.effective_user.id if update.effective_user else None
    if not is_allowed(user_id):
        await update.message.reply_text("⛔️ Нет прав на публикацию через этого бота.")
        return

    msg = update.message

    try:
        if msg.text and not (msg.photo or msg.video or msg.document or msg.animation):
            await context.bot.send_message(
                chat_id=CHANNEL,
                text=msg.text,
                reply_markup=post_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            await msg.reply_text("✅ Опубликовано в канал.")
            return

        if msg.photo:
            await context.bot.send_photo(
                chat_id=CHANNEL,
                photo=msg.photo[-1].file_id,
                caption=msg.caption or "",
                reply_markup=post_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            await msg.reply_text("✅ Фото опубликовано.")
            return

        if msg.video:
            await context.bot.send_video(
                chat_id=CHANNEL,
                video=msg.video.file_id,
                caption=msg.caption or "",
                reply_markup=post_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            await msg.reply_text("✅ Видео опубликовано.")
            return

        if msg.animation:
            await context.bot.send_animation(
                chat_id=CHANNEL,
                animation=msg.animation.file_id,
                caption=msg.caption or "",
                reply_markup=post_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            await msg.reply_text("✅ GIF опубликован.")
            return

        if msg.document:
            await context.bot.send_document(
                chat_id=CHANNEL,
                document=msg.document.file_id,
                caption=msg.caption or "",
                reply_markup=post_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            await msg.reply_text("✅ Документ опубликован.")
            return

        await msg.reply_text("⚠️ Пришли текст/фото/видео/документ/гиф — этот тип пока не поддержан.")

    except Exception as e:
        await msg.reply_text(f"❌ Ошибка при публикации: {e}")


def main():
    if not TOKEN:
        raise RuntimeError("❌ Не задан BOT_TOKEN")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, publish))

    print("🤖 Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
