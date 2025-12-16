import os
import asyncio
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =======================
# ENV / SETTINGS
# =======================
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL") or "@your_channel").strip()
SUBSCRIBE_TO = (os.getenv("SUBSCRIBE_TO") or f"https://t.me/{CHANNEL.lstrip('@')}").strip()
SUGGEST_TO = (os.getenv("SUGGEST_TO") or "https://t.me/stridiv").strip()
ALLOWED_ADMINS_RAW = (os.getenv("ALLOWED_ADMINS") or "").strip()
AUTOSIGN = (os.getenv("AUTOSIGN") or "").strip()
ALBUM_WAIT_SEC = float(os.getenv("ALBUM_WAIT_SEC") or "1.2")

def _parse_admins(raw: str) -> set[int]:
    s = set()
    if raw:
        for x in raw.split(","):
            x = x.strip()
            if x.isdigit():
                s.add(int(x))
    return s

ALLOWED_ADMINS = _parse_admins(ALLOWED_ADMINS_RAW)

# =======================
# TEXT AUTOFORMAT
# =======================
def _normalize_text(t: str) -> str:
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def _smart_cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s

def autoformat_news(raw: str) -> str:
    raw = _normalize_text(raw)
    if not raw:
        return raw

    lines = raw.split("\n")
    first = lines[0].strip()
    rest = _normalize_text("\n".join(lines[1:])) if len(lines) > 1 else ""

    title, body = "", ""

    if 5 <= len(first) <= 90 and rest:
        title = _smart_cap(first)
        body = _smart_cap(rest)
    else:
        body = _smart_cap(raw)

    out = ""
    if title:
        out += f"<b>{title}</b>\n\n{body}"
    else:
        out += body

    if out and out[-1] not in ".!?":
        out += "."
    out += "\n\n<i>Подробности уточняются.</i>"

    return out

def _apply_autosign(text: str) -> str:
    if not AUTOSIGN:
        return text
    return f"{text.rstrip()}\n{AUTOSIGN}"

def _safe_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# =======================
# UI
# =======================
def promo_kb():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подписаться на канал", url=SUBSCRIBE_TO)],
            [InlineKeyboardButton("✉️ Предложить новость", url=SUGGEST_TO)],
        ]
    )

def confirm_kb(draft_id: str):
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🚀 Опубликовать", callback_data=f"pub:{draft_id}"),
            InlineKeyboardButton("✖️ Отменить", callback_data=f"cancel:{draft_id}"),
            InlineKeyboardButton("✨ Автоформат / Как есть", callback_data=f"toggle:{draft_id}")
        ]]
    )

# =======================
# DATA
# =======================
@dataclass
class Draft:
    chat_id: int
    user_id: int
    raw_text: str = ""
    formatted_text: str = ""
    use_formatted: bool = True
    medias: List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]] = field(default_factory=list)

def allowed(uid: Optional[int]) -> bool:
    if not ALLOWED_ADMINS:
        return True
    return uid in ALLOWED_ADMINS

# =======================
# HANDLERS
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Пришли пост — я сделаю предпросмотр.\n"
        "Будет выбор: опубликовать / отменить / автоформат."
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш ID: {update.effective_user.id}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user.id):
        return
    raw = update.message.text or ""
    formatted = autoformat_news(raw)
    draft = Draft(update.effective_chat.id, update.effective_user.id, raw, formatted, True)
    did = str(len(context.application.bot_data.get("drafts", {})) + 1)
    context.application.bot_data.setdefault("drafts", {})[did] = draft

    preview = _apply_autosign(formatted)
    await update.message.reply_text(
        _safe_html(preview),
        parse_mode=ParseMode.HTML,
        reply_markup=confirm_kb(did),
        disable_web_page_preview=True,
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    drafts = context.application.bot_data.get("drafts", {})

    if ":" not in data:
        return

    action, did = data.split(":", 1)
    d = drafts.get(did)

    if not d:
        await q.edit_message_text("Черновик не найден.")
        return

    if action == "toggle":
        d.use_formatted = not d.use_formatted
        text = d.formatted_text if d.use_formatted else d.raw_text
        preview = _apply_autosign(text)
        await q.edit_message_text(
            _safe_html(preview),
            parse_mode=ParseMode.HTML,
            reply_markup=confirm_kb(did),
            disable_web_page_preview=True,
        )
        return

    if action == "cancel":
        drafts.pop(did, None)
        await q.edit_message_text("❌ Отменено.")
        return

    if action == "pub":
        text = d.formatted_text if d.use_formatted else d.raw_text
        text = _apply_autosign(text)
        try:
            await context.bot.send_message(
                chat_id=CHANNEL,
                text=_safe_html(text),
                parse_mode=ParseMode.HTML,
                reply_markup=promo_kb(),
                disable_web_page_preview=True,
            )
            await q.edit_message_text("✅ Опубликовано.")
        except BadRequest:
            await q.edit_message_text("❌ Ошибка публикации. Проверь CHANNEL и права бота.")
        drafts.pop(did, None)

# =======================
# MAIN
# =======================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling()

if __name__ == "__main__":
    main()
