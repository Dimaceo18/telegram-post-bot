import os
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Set

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
CHANNEL = (os.getenv("CHANNEL") or "@your_channel").strip()  # e.g. @minskiyes
SUBSCRIBE_TO = (os.getenv("SUBSCRIBE_TO") or f"https://t.me/{CHANNEL.lstrip('@')}").strip()
SUGGEST_TO = (os.getenv("SUGGEST_TO") or "https://t.me/stridiv").strip()
ALLOWED_ADMINS_RAW = (os.getenv("ALLOWED_ADMINS") or "").strip()  # comma-separated numeric IDs
AUTOSIGN = (os.getenv("AUTOSIGN") or "").strip()  # e.g. "\n\n— @minsknews"
ALBUM_WAIT_SEC = float(os.getenv("ALBUM_WAIT_SEC") or "1.2")  # collect media_group items window

def _parse_admins(raw: str) -> Set[int]:
    s: Set[int] = set()
    if not raw:
        return s
    for x in raw.split(","):
        x = x.strip()
        if x.isdigit():
            s.add(int(x))
    return s

ALLOWED_ADMINS = _parse_admins(ALLOWED_ADMINS_RAW)

# =======================
# UI
# =======================
def promo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Подписаться на канал", url=SUBSCRIBE_TO)],
            [InlineKeyboardButton("✉️ Предложить новость", url=SUGGEST_TO)],
        ]
    )

def confirm_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🚀 Опубликовать", callback_data=f"pub:{draft_id}"),
            InlineKeyboardButton("✖️ Отменить", callback_data=f"cancel:{draft_id}"),
        ]]
    )

# =======================
# Drafts / Album buffer
# =======================
@dataclass
class Draft:
    chat_id: int
    user_id: int
    text: str = ""
    parse_mode: Optional[str] = ParseMode.HTML
    medias: List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]] = field(default_factory=list)

def _drafts(app: Application) -> Dict[str, Draft]:
    if "drafts" not in app.bot_data:
        app.bot_data["drafts"] = {}
    return app.bot_data["drafts"]

def _album_buf(app: Application) -> Dict[str, dict]:
    if "album_buf" not in app.bot_data:
        app.bot_data["album_buf"] = {}
    return app.bot_data["album_buf"]

def _is_allowed(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    # If admins list is empty, allow all.
    return (not ALLOWED_ADMINS) or (user_id in ALLOWED_ADMINS)

def _safe_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _apply_autosign(text: str) -> str:
    if not AUTOSIGN:
        return text
    t = text.rstrip()
    return f"{t}\n{AUTOSIGN}" if t else AUTOSIGN

# =======================
# Commands
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "👋 Привет! Пришли текст/фото/видео/документ — я сделаю предпросмотр и спрошу подтверждение.\n\n"
        "Команды:\n"
        "/myid — узнать свой Telegram ID\n"
        "/test — показать текущие настройки",
        disable_web_page_preview=True,
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    uid = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(f"Ваш Telegram ID: {uid}")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "⚙️ Настройки:\n"
        f"CHANNEL: {CHANNEL}\n"
        f"SUBSCRIBE_TO: {SUBSCRIBE_TO}\n"
        f"SUGGEST_TO: {SUGGEST_TO}\n"
        f"ALLOWED_ADMINS: {ALLOWED_ADMINS_RAW or '(пусто = разрешены все)'}\n"
        f"AUTOSIGN: {AUTOSIGN or '(нет)'}\n",
        disable_web_page_preview=True,
    )

# =======================
# Draft helpers
# =======================
def _new_draft_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    n = int(context.application.bot_data.get("draft_seq", 0)) + 1
    context.application.bot_data["draft_seq"] = n
    return str(n)

def _build_album_media(draft: Draft) -> List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]]:
    caption = _apply_autosign(draft.text or "")
    caption = _safe_html(caption) if caption else ""

    medias: List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]] = []
    for i, m in enumerate(draft.medias):
        if isinstance(m, InputMediaPhoto):
            medias.append(InputMediaPhoto(media=m.media, caption=caption if (i == 0 and caption) else None,
                                          parse_mode=ParseMode.HTML if (i == 0 and caption) else None))
        elif isinstance(m, InputMediaVideo):
            medias.append(InputMediaVideo(media=m.media, caption=caption if (i == 0 and caption) else None,
                                          parse_mode=ParseMode.HTML if (i == 0 and caption) else None))
        elif isinstance(m, InputMediaDocument):
            medias.append(InputMediaDocument(media=m.media, caption=caption if (i == 0 and caption) else None,
                                             parse_mode=ParseMode.HTML if (i == 0 and caption) else None))
        else:
            medias.append(m)
    return medias

async def _send_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: Draft) -> str:
    draft_id = _new_draft_id(context)
    _drafts(context.application)[draft_id] = draft

    caption = _apply_autosign(draft.text or "")
    caption = _safe_html(caption) if caption else ""

    # Album preview
    if draft.medias:
        medias = _build_album_media(draft)
        await context.bot.send_media_group(chat_id=draft.chat_id, media=medias)
        await context.bot.send_message(
            chat_id=draft.chat_id,
            text="Предпросмотр готов. Публикуем?",
            reply_markup=confirm_keyboard(draft_id),
        )
        return draft_id

    # Text-only preview
    if update.message and update.message.text and not (update.message.photo or update.message.video or update.message.document):
        await update.message.reply_text(
            f"🧾 Предпросмотр:\n\n{caption}" if caption else "🧾 Предпросмотр: (пусто)",
            parse_mode=ParseMode.HTML if caption else None,
            reply_markup=confirm_keyboard(draft_id),
            disable_web_page_preview=True,
        )
        return draft_id

    # Single media preview
    msg = update.message
    if not msg:
        await context.bot.send_message(chat_id=draft.chat_id, text="Не удалось сделать предпросмотр.")
        return draft_id

    if msg.photo:
        await context.bot.send_photo(
            chat_id=draft.chat_id,
            photo=msg.photo[-1].file_id,
            caption=caption or None,
            parse_mode=ParseMode.HTML if caption else None,
        )
    elif msg.video:
        await context.bot.send_video(
            chat_id=draft.chat_id,
            video=msg.video.file_id,
            caption=caption or None,
            parse_mode=ParseMode.HTML if caption else None,
        )
    elif msg.document:
        await context.bot.send_document(
            chat_id=draft.chat_id,
            document=msg.document.file_id,
            caption=caption or None,
            parse_mode=ParseMode.HTML if caption else None,
        )
    else:
        await context.bot.send_message(chat_id=draft.chat_id, text="Неизвестный тип сообщения для предпросмотра.")

    await context.bot.send_message(
        chat_id=draft.chat_id,
        text="Предпросмотр готов. Публикуем?",
        reply_markup=confirm_keyboard(draft_id),
    )
    return draft_id

# =======================
# Publish
# =======================
async def _publish_draft(context: ContextTypes.DEFAULT_TYPE, draft_id: str) -> None:
    drafts = _drafts(context.application)
    draft = drafts.get(draft_id)
    if not draft:
        return

    target = CHANNEL.strip()  # must be @username or -100xxxxxxxxxx

    try:
        if draft.medias:
            medias = _build_album_media(draft)
            await context.bot.send_media_group(chat_id=target, media=medias)
            # albums cannot have reply_markup; send buttons separately
            await context.bot.send_message(chat_id=target, text=" ", reply_markup=promo_keyboard())
        else:
            caption = _apply_autosign(draft.text or "")
            caption = _safe_html(caption) if caption else ""
            if caption:
                await context.bot.send_message(
                    chat_id=target,
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=promo_keyboard(),
                    disable_web_page_preview=True,
                )
            else:
                await context.bot.send_message(chat_id=target, text=" ", reply_markup=promo_keyboard())
    finally:
        drafts.pop(draft_id, None)

# =======================
# Handlers
# =======================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return
    draft = Draft(chat_id=update.effective_chat.id, user_id=update.effective_user.id, text=update.message.text or "")
    await _send_preview(update, context, draft)

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    # albums
    if update.message.media_group_id:
        await handle_album_item(update, context)
        return

    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    caption = update.message.caption or ""
    draft = Draft(chat_id=update.effective_chat.id, user_id=update.effective_user.id, text=caption)

    msg = update.message
    if msg.photo:
        draft.medias = [InputMediaPhoto(media=msg.photo[-1].file_id)]
    elif msg.video:
        draft.medias = [InputMediaVideo(media=msg.video.file_id)]
    elif msg.document:
        draft.medias = [InputMediaDocument(media=msg.document.file_id)]
    else:
        await update.message.reply_text("Не понял тип файла.")
        return

    await _send_preview(update, context, draft)

async def handle_album_item(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.media_group_id:
        return
    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        return

    key = f"{update.effective_chat.id}:{update.message.media_group_id}"
    buf = _album_buf(context.application)

    if key not in buf:
        buf[key] = {"items": [], "task": None}
    buf[key]["items"].append(update)

    task = buf[key].get("task")
    if task and not task.done():
        task.cancel()

    async def finalize() -> None:
        await asyncio.sleep(ALBUM_WAIT_SEC)
        items = buf.get(key, {}).get("items", [])
        if not items:
            buf.pop(key, None)
            return

        items = sorted(items, key=lambda u: u.message.message_id)

        caption = ""
        for u in items:
            if u.message.caption:
                caption = u.message.caption
                break

        medias: List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]] = []
        for u in items:
            m = u.message
            if m.photo:
                medias.append(InputMediaPhoto(media=m.photo[-1].file_id))
            elif m.video:
                medias.append(InputMediaVideo(media=m.video.file_id))
            elif m.document:
                medias.append(InputMediaDocument(media=m.document.file_id))

        draft = Draft(chat_id=update.effective_chat.id, user_id=update.effective_user.id, text=caption, medias=medias)
        await _send_preview(items[-1], context, draft)
        buf.pop(key, None)

    buf[key]["task"] = asyncio.create_task(finalize())

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id if q.from_user else None
    if not _is_allowed(user_id):
        try:
            await q.edit_message_text("⛔️ У вас нет доступа.")
        except Exception:
            pass
        return

    data = q.data or ""
    if data.startswith("cancel:"):
        draft_id = data.split(":", 1)[1]
        _drafts(context.application).pop(draft_id, None)
        try:
            await q.edit_message_text("✖️ Отменено.")
        except Exception:
            pass
        return

    if data.startswith("pub:"):
        draft_id = data.split(":", 1)[1]
        try:
            await q.edit_message_text("🚀 Публикую…")
        except Exception:
            pass

        try:
            await _publish_draft(context, draft_id)
            await context.bot.send_message(chat_id=q.message.chat_id, text="✅ Опубликовано.")
        except BadRequest:
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=(
                    "❌ Ошибка публикации: Chat not found.\n\n"
                    "Проверь:\n"
                    "1) CHANNEL должен быть @username канала (без ссылки).\n"
                    "2) username канала написан точно (у тебя было minskiyes vs minskIyes).\n"
                    "3) Бот добавлен в админы канала.\n"
                    "4) Если канал приватный — добавь бота в канал.\n"
                ),
            )
        return

# =======================
# Main
# =======================
def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("❌ Не задан BOT_TOKEN")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CallbackQueryHandler(on_callback))

    # media (album items are handled inside handle_media)
    app.add_handler(MessageHandler(filters.PHOTO, handle_media))
    app.add_handler(MessageHandler(filters.VIDEO, handle_media))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_media))

    # text (exclude commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
