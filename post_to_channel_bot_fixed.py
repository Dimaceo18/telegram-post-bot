import os
import asyncio
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
CHANNEL = (os.getenv("CHANNEL") or "@your_channel").strip()  # e.g. @minskiyes
SUBSCRIBE_TO = (os.getenv("SUBSCRIBE_TO") or f"https://t.me/{CHANNEL.lstrip('@')}").strip()
SUGGEST_TO = (os.getenv("SUGGEST_TO") or "https://t.me/stridiv").strip()
ALLOWED_ADMINS_RAW = (os.getenv("ALLOWED_ADMINS") or "").strip()  # comma-separated numeric IDs
AUTOSIGN = (os.getenv("AUTOSIGN") or "").strip()  # e.g. "\n\n— @minsknews"
ALBUM_WAIT_SEC = float(os.getenv("ALBUM_WAIT_SEC") or "1.2")  # collect media_group items window

def _parse_admins(raw: str) -> set[int]:
    s: set[int] = set()
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
        [
            [
                InlineKeyboardButton("🚀 Опубликовать", callback_data=f"pub:{draft_id}"),
                InlineKeyboardButton("✖️ Отменить", callback_data=f"cancel:{draft_id}"),
            ]
        ]
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
    """
    album buffer per key f"{chat_id}:{media_group_id}"
    item:
      { "items": [Update], "task": asyncio.Task, "user_id": int }
    """
    if "album_buf" not in app.bot_data:
        app.bot_data["album_buf"] = {}
    return app.bot_data["album_buf"]

def _is_allowed(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    # If admins list is empty, allow all (simpler for you). Want strict? set ALLOWED_ADMINS.
    if not ALLOWED_ADMINS:
        return True
    return user_id in ALLOWED_ADMINS

def _safe_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )

def _apply_autosign(text: str) -> str:
    if not AUTOSIGN:
        return text
    t = text.rstrip()
    return f"{t}\n{AUTOSIGN}" if t else AUTOSIGN

# =======================
# Commands
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Пришли текст/фото/видео/документ — я сделаю предпросмотр и спрошу подтверждение.\n\n"
        "Команды:\n"
        "/myid — узнать свой Telegram ID\n"
        "/test — показать текущие настройки",
        disable_web_page_preview=True,
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(f"Ваш Telegram ID: {uid}")

async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
# Draft creation helpers
# =======================
def _new_draft_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    # simple increasing counter
    n = int(context.application.bot_data.get("draft_seq", 0)) + 1
    context.application.bot_data["draft_seq"] = n
    return str(n)

async def _send_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: Draft) -> str:
    """
    Sends a preview to user's chat and returns draft_id.
    """
    draft_id = _new_draft_id(context)
    _drafts(context.application)[draft_id] = draft

    caption = _apply_autosign(draft.text or "")
    if caption:
        caption = _safe_html(caption)

    # Album preview
    if draft.medias:
        # Put caption on first item only for albums
        medias = []
        for i, m in enumerate(draft.medias):
            # python-telegram-bot v20+ uses immutable InputMedia* objects,
            # so we create new ones instead of setting attributes.
            if i == 0 and caption:
                if isinstance(m, InputMediaPhoto):
                    nm = InputMediaPhoto(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaVideo):
                    nm = InputMediaVideo(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaDocument):
                    nm = InputMediaDocument(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaAudio):
                    nm = InputMediaAudio(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                else:
                    nm = m
            else:
                # no caption on the rest of the album
                if isinstance(m, InputMediaPhoto):
                    nm = InputMediaPhoto(media=m.media)
                elif isinstance(m, InputMediaVideo):
                    nm = InputMediaVideo(media=m.media)
                elif isinstance(m, InputMediaDocument):
                    nm = InputMediaDocument(media=m.media)
                elif isinstance(m, InputMediaAudio):
                    nm = InputMediaAudio(media=m.media)
                else:
                    nm = m
            medias.append(nm)

        await context.bot.send_media_group(chat_id=draft.chat_id, media=medias)
        await context.bot.send_message(
            chat_id=draft.chat_id,
            text="Предпросмотр готов. Публикуем?",
            reply_markup=confirm_keyboard(draft_id),
        )
        return draft_id

    # Text-only preview
    if update.message and update.message.text and not update.message.photo and not update.message.video and not update.message.document:
        await update.message.reply_text(
            f"🧾 Предпросмотр:\n\n{caption}" if caption else "🧾 Предпросмотр: (пусто)",
            parse_mode=ParseMode.HTML if caption else None,
            reply_markup=confirm_keyboard(draft_id),
            disable_web_page_preview=True,
        )
        return draft_id

    # Single media preview: just echo original message with caption applied as a new send
    msg = update.message
    if msg is None:
        await context.bot.send_message(chat_id=draft.chat_id, text="Не удалось сделать предпросмотр.")
        return draft_id

    if msg.photo:
        file_id = msg.photo[-1].file_id
        await context.bot.send_photo(
            chat_id=draft.chat_id,
            photo=file_id,
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

    # IMPORTANT: Telegram needs bot to be admin in the channel.
    # Channel should be set like "@minskiyes" (username), not t.me link.
    target = CHANNEL.strip()

    caption = _apply_autosign(draft.text or "")
    if caption:
        caption = _safe_html(caption)

    try:
        if draft.medias:
            medias = []
            for i, m in enumerate(draft.medias):
            # python-telegram-bot v20+ uses immutable InputMedia* objects,
            # so we create new ones instead of setting attributes.
            if i == 0 and caption:
                if isinstance(m, InputMediaPhoto):
                    nm = InputMediaPhoto(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaVideo):
                    nm = InputMediaVideo(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaDocument):
                    nm = InputMediaDocument(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaAudio):
                    nm = InputMediaAudio(media=m.media, caption=caption, parse_mode=ParseMode.HTML)
                else:
                    nm = m
            else:
                # no caption on the rest of the album
                if isinstance(m, InputMediaPhoto):
                    nm = InputMediaPhoto(media=m.media)
                elif isinstance(m, InputMediaVideo):
                    nm = InputMediaVideo(media=m.media)
                elif isinstance(m, InputMediaDocument):
                    nm = InputMediaDocument(media=m.media)
                elif isinstance(m, InputMediaAudio):
                    nm = InputMediaAudio(media=m.media)
                else:
                    nm = m
            medias.append(nm)
            await context.bot.send_media_group(chat_id=target, media=medias)
            # Send promo buttons as separate message (albums cannot attach reply_markup)
            await context.bot.send_message(chat_id=target, text=" ", reply_markup=promo_keyboard())
        else:
            # text-only
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

    except BadRequest as e:
        # Most common: Chat not found (wrong CHANNEL) or bot not admin
        raise e
    finally:
        # Remove draft after attempt
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

    text = update.message.text or ""
    draft = Draft(chat_id=update.effective_chat.id, user_id=update.effective_user.id, text=text)
    await _send_preview(update, context, draft)

async def handle_single_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if update.message.media_group_id:
        # handled by album collector
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
    """
    Collect media_group messages for a short time window, then create one preview with confirm buttons.
    """
    if not update.message or not update.message.media_group_id:
        return

    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        # avoid spamming on each item
        return

    key = f"{update.effective_chat.id}:{update.message.media_group_id}"
    buf = _album_buf(context.application)

    if key not in buf:
        buf[key] = {"items": [], "task": None, "user_id": update.effective_user.id}
    buf[key]["items"].append(update)

    # restart timer
    task = buf[key].get("task")
    if task and not task.done():
        task.cancel()

    async def finalize():
        await asyncio.sleep(ALBUM_WAIT_SEC)
        items = buf.get(key, {}).get("items", [])
        if not items:
            buf.pop(key, None)
            return

        # Sort items by message_id to keep order
        items = sorted(items, key=lambda u: u.message.message_id)

        caption = ""
        # Telegram puts caption only on one of messages (often first). We'll take first non-empty.
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
        await q.edit_message_text("⛔️ У вас нет доступа.")
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
        except BadRequest as e:
            # Most common reasons:
            # - CHANNEL incorrect (must be @username or numeric -100...)
            # - bot is not admin in channel
            # - bot cannot access channel (private without invite)
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=(
                    "❌ Ошибка публикации: Chat not found.\n\n"
                    "Проверь:\n"
                    "1) CHANNEL должен быть @username канала (например, @minskiyes), без ссылки.\n"
                    "2) Канал должен существовать именно с таким username.\n"
                    "3) Бот должен быть добавлен в админы канала.\n"
                    "4) Если канал приватный — добавь бота как участника/админа.\n"
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

    # Media group items must be handled before generic media handler
    app.add_handler(MessageHandler(filters.PHOTO & filters.UpdateType.MESSAGE, handle_single_media))
    app.add_handler(MessageHandler(filters.VIDEO & filters.UpdateType.MESSAGE, handle_single_media))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.UpdateType.MESSAGE, handle_single_media))

    # Text (exclude commands)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()