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
    await update.message.rep
