import os
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== НАСТРОЙКИ ==================

TOKEN = os.getenv("BOT_TOKEN")

# Публичный канал, куда публикуем
CHANNEL = os.getenv("CHANNEL", "@your_channel")

# Кнопка "Предложить новость"
SUGGEST_TO = "https://t.me/stridiv"

# Кнопка "Подписаться на канал"
SUBSCRIBE_TO = os.getenv(
    "SUBSCRIBE_TO",
    f"https://t.me/{CHANNEL.lstrip('@')}"
)

# Кто может публиковать (через запятую)
# Пример: 123456789,987654321
ALLOWED_ADMINS = set()
raw_admins = os.getenv("ALLOWED_ADMINS", "")
if raw_admins:
    for uid in raw_admins.split(","):
        uid = uid.strip()
        if uid.isdigit():
            ALLOWED_ADMINS.add(int(uid))


# ================== КНОПКИ ==================

def post_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Подписаться на канал",
                    url=SUBSCRIBE_TO
                ),
                InlineKeyboardButton(
                    "✉️ Предложить новость",
                    url=SUGGEST_TO
                ),
            ]
        ]
    )


# ================== ПРОВЕРКИ ==================

def is_allowed(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    return not ALLOWED_ADMINS or user_id in ALLOWED_ADMINS


# ================== КОМАНДЫ ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Пришли мне текст, фото или видео — я опубликую это в канале "
        "с кнопками «Подписаться» и «Предложить новость».\n\n"
        "Команды:\n"
        "/myid — узнать свой Telegram ID\n"
        "/test — проверить настройки"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 Ваш Telegram ID: {update.effective_user.id}"
    )


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⚙️ Текущие настройки:\n\n"
        f"CHANNEL: {CHANNEL}\n"
        f"SUBSCRIBE_TO: {SUBSCRIBE_TO}\n"
        f"SUGGEST_TO: {SUGGEST_TO}\n"
        f"ALLOWED_ADMINS: {', '.join(map(str, ALLOWED_ADMINS)) or 'не задано'}"
    )


# ================== ПУБЛИКАЦИЯ ==================

async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user_id = update.effective_user.id if update.effective_user else None
    if not is_allowed(user_id):
        await update.message.reply_text("⛔ У вас нет прав на публикацию.")
        return

    msg = update.message

    # ТЕКСТ
    if msg.text and not any([msg.photo, msg.video, msg.document, msg.animation]):
        await context.bot.send_message(
            chat_id=CHANNEL,
            text=msg.text,
            reply_markup=post_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        await msg.reply_text("✅ Пост опубликован.")
        return

    # ФОТО
    if msg.photo:
        await context.bot.send_photo(
            chat_id=CHANNEL,
            photo=msg.photo[-1].file_id,
            caption=msg.caption,
            reply_markup=post_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        await msg.reply_text("✅ Фото опубликовано.")
        return

    # ВИДЕО
    if msg.video:
        await context.bot.send_video(
            chat_id=CHANNEL,
            video=msg.video.file_id,
            caption=msg.caption,
            reply_markup=post_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        await msg.reply_text("✅ Видео опубликовано.")
        return

    # GIF
    if msg.animation:
        await context.bot.send_animation(
            chat_id=CHANNEL,
            animation=msg.animation.file_id,
            caption=msg.caption,
            reply_markup=post_keyboard(),
        )
        await msg.reply_text("✅ GIF опубликован.")
        return

    # ДОКУМЕНТ
    if msg.document:
        await context.bot.send_document(
            chat_id=CHANNEL,
            document=msg.document.file_id,
            caption=msg.caption,
            reply_markup=post_keyboard(),
        )
        await msg.reply_text("✅ Документ опубликован.")
        return

    await msg.reply_text("⚠️ Этот тип сообщения пока не поддерживается.")


# ================== ЗАПУСК ==================

def main():
    if not TOKEN:
        raise RuntimeError("❌ Не задан BOT_TOKEN")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, publish))

    print("🤖 Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
