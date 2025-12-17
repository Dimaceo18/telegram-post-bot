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
    Message,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Conflict, Forbidden
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

# IMPORTANT:
# CHANNEL can be:
#   1) "@username" (public channel username)
#   2) numeric channel id like "-1001234567890"  (most reliable)
CHANNEL = (os.getenv("CHANNEL") or "").strip()

SUBSCRIBE_TO = (os.getenv("SUBSCRIBE_TO") or "").strip()
SUGGEST_TO = (os.getenv("SUGGEST_TO") or "https://t.me/stridiv").strip()

# comma-separated numeric IDs (e.g. "5314321592,123")
ALLOWED_ADMINS_RAW = (os.getenv("ALLOWED_ADMINS") or "").strip()

# Autotext appended to the end of every post (can be empty)
AUTOSIGN = (os.getenv("AUTOSIGN") or "").strip()

# How long to collect album items (seconds)
ALBUM_WAIT_SEC = float(os.getenv("ALBUM_WAIT_SEC") or "1.2")

# Send debug logs into Telegram chat (true/false)
LOG_TO_TG = (os.getenv("LOG_TO_TG") or "true").strip().lower() in ("1", "true", "yes", "on")
# Optional: fixed chat id to receive logs (if empty -> logs go to the chat where command/message came from)
LOG_CHAT_ID = (os.getenv("LOG_CHAT_ID") or "").strip()


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


def _is_allowed(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    # If admins list is empty, allow all (easy mode)
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
    t = (text or "").rstrip()
    if not t:
        return AUTOSIGN
    # ensure autosign starts on new line
    if AUTOSIGN.startswith("\n"):
        return f"{t}{AUTOSIGN}"
    return f"{t}\n{AUTOSIGN}"


def _resolved_channel(context: ContextTypes.DEFAULT_TYPE) -> str:
    # allow temporary override via /setchannel (stored in bot_data)
    override = (context.application.bot_data.get("override_channel") or "").strip()
    return override or CHANNEL


async def _log(context: ContextTypes.DEFAULT_TYPE, text: str, update: Optional[Update] = None) -> None:
    if not LOG_TO_TG:
        return
    try:
        chat_id: Optional[int] = None
        if LOG_CHAT_ID and LOG_CHAT_ID.lstrip("-").isdigit():
            chat_id = int(LOG_CHAT_ID)
        elif update and update.effective_chat:
            chat_id = update.effective_chat.id
        if chat_id is None:
            return
        await context.bot.send_message(chat_id=chat_id, text=f"🧩 LOG:\n{text}")
    except Exception:
        # never crash because of logging
        return


# =======================
# UI
# =======================
def promo_keyboard() -> InlineKeyboardMarkup:
    rows = []
    if SUBSCRIBE_TO:
        rows.append([InlineKeyboardButton("✅ Подписаться на канал", url=SUBSCRIBE_TO)])
    if SUGGEST_TO:
        rows.append([InlineKeyboardButton("✉️ Предложить новость", url=SUGGEST_TO)])
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([])


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
    chat_id: int          # where preview lives (user chat)
    user_id: int
    text: str = ""
    medias: List[Union[InputMediaPhoto, InputMediaVideo, InputMediaDocument]] = field(default_factory=list)


def _drafts(app: Application) -> Dict[str, Draft]:
    if "drafts" not in app.bot_data:
        app.bot_data["drafts"] = {}
    return app.bot_data["drafts"]


def _album_buf(app: Application) -> Dict[str, dict]:
    if "album_buf" not in app.bot_data:
        app.bot_data["album_buf"] = {}
    return app.bot_data["album_buf"]


def _new_draft_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    n = int(context.application.bot_data.get("draft_seq", 0)) + 1
    context.application.bot_data["draft_seq"] = n
    return str(n)


# =======================
# Commands
# =======================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Пришли текст/фото/видео/документ или альбом — я сделаю предпросмотр и спрошу подтверждение.\n\n"
        "Команды:\n"
        "/myid — узнать свой Telegram ID\n"
        "/test — показать текущие настройки\n"
        "/checkchannel — проверить доступ к каналу\n"
        "/getchannelid — получить numeric ID канала (нужно переслать боту пост из канала)\n"
        "/setchannel <@username или -100...> — временно поменять канал (до рестарта)\n",
        disable_web_page_preview=True,
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(f"Ваш Telegram ID: {uid}")


async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target = _resolved_channel(context)
    await update.message.reply_text(
        "⚙️ Настройки:\n"
        f"CHANNEL: {target or '(не задан)'}\n"
        f"SUBSCRIBE_TO: {SUBSCRIBE_TO or '(нет)'}\n"
        f"SUGGEST_TO: {SUGGEST_TO or '(нет)'}\n"
        f"ALLOWED_ADMINS: {ALLOWED_ADMINS_RAW or '(пусто = разрешены все)'}\n"
        f"AUTOSIGN: {AUTOSIGN or '(нет)'}\n"
        f"LOG_TO_TG: {LOG_TO_TG}\n",
        disable_web_page_preview=True,
    )


async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    if not context.args:
        await update.message.reply_text("Используй: /setchannel @username  или  /setchannel -1001234567890")
        return

    ch = context.args[0].strip()
    context.application.bot_data["override_channel"] = ch
    await update.message.reply_text(f"✅ Временно установлен CHANNEL = {ch}\n(после рестарта Render вернётся значение из Environment Variables)")
    await _log(context, f"override_channel set to {ch}", update)


async def getchannelid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Самый надежный способ:
    1) Добавь бота в админы канала
    2) Перешли боту любое сообщение из канала (Forward)
    3) Напиши /getchannelid
    """
    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    # We try to inspect the replied-to or last forwarded message
    msg: Optional[Message] = update.message
    ref: Optional[Message] = msg.reply_to_message if msg else None

    candidate = ref or msg
    fchat = getattr(candidate, "forward_from_chat", None)

    if not fchat:
        await update.message.reply_text(
            "❗️Сначала перешли (Forward) боту любое сообщение из нужного канала.\n"
            "Потом ответь на пересланное сообщение командой /getchannelid",
            disable_web_page_preview=True,
        )
        return

    await update.message.reply_text(
        f"✅ Канал: {fchat.title}\n"
        f"username: @{fchat.username}" if getattr(fchat, "username", None) else f"✅ Канал: {fchat.title}\nusername: (нет)\n"
        f"id: {fchat.id}\n\n"
        f"👉 Поставь в Render → Environment Variables:\nCHANNEL = {fchat.id}\n"
    )


async def checkchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("⛔️ У вас нет доступа.")
        return

    target = _resolved_channel(context)
    if not target:
        await update.message.reply_text("❌ CHANNEL не задан. Укажи в Render → Environment Variables.")
        return

    try:
        chat = await context.bot.get_chat(target)
        await update.message.reply_text(
            f"✅ Доступ есть.\n"
            f"title: {chat.title}\n"
            f"type: {chat.type}\n"
            f"id: {chat.id}\n"
            f"username: @{chat.username}" if getattr(chat, "username", None) else f"✅ Доступ есть.\n"
            f"title: {chat.title}\n"
            f"type: {chat.type}\n"
            f"id: {chat.id}\n"
            f"username: (нет)\n"
        )
    except Forbidden as e:
        await update.message.reply_text(
            "❌ Нет доступа (Forbidden).\n"
            "Обычно это значит: бот НЕ добавлен в канал, или канал приватный и бота не добавили.\n"
        )
        await _log(context, f"checkchannel Forbidden: {e}", update)
    except BadRequest as e:
        await update.message.reply_text(
            "❌ Chat not found / BadRequest.\n"
            "Это значит: CHANNEL указан неверно (ошибка в @username или неверный -100... id).\n"
        )
        await _log(context, f"checkchannel BadRequest: {e}\nCHANNEL={target}", update)


# =======================
# Preview builder
# =======================
async def _send_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: Draft) -> str:
    draft_id = _new_draft_id(context)
    _drafts(context.application)[draft_id] = draft

    caption = _apply_autosign(draft.text or "")
    caption_html = _safe_html(caption) if caption else ""

    # Album preview
    if draft.medias:
        medias = []
        for i, m in enumerate(draft.medias):
            if i == 0 and caption_html:
                if isinstance(m, InputMediaPhoto):
                    nm = InputMediaPhoto(media=m.media, caption=caption_html, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaVideo):
                    nm = InputMediaVideo(media=m.media, caption=caption_html, parse_mode=ParseMode.HTML)
                elif isinstance(m, InputMediaDocument):
                    nm = InputMediaDocument(media=m.media, caption=caption_html, parse_mode=ParseMode.HTML)
                else:
                    nm = m
            else:
                if isinstance(m, InputMediaPhoto):
                    nm = InputMediaPhoto(media=m.media)
                elif isinstance(m, InputMediaVideo):
                    nm = InputMediaVideo(media=m.media)
                elif isinstance(m, InputMediaDocument):
                    nm = InputMediaDocument(media=m.media)
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
    if update.message and update.message.text and not (update.message.photo or update.message.video or update.message.document):
        text = f"🧾 Предпросмотр:\n\n{caption_html}" if caption_html else "🧾 Предпросмотр: (пусто)"
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML if caption_html else None,
            reply_markup=confirm_keyboard(draft_id),
            disable_web_page_preview=True,
        )
        return draft_id

    # Single media preview (send new media with caption and buttons)
    msg = update.message
    if not msg:
        await context.bot.send_message(chat_id=draft.chat_id, text="Не удалось сделать предпросмотр.")
        return draft_id

    if msg.photo:
        await context.bot.send_photo(
            chat_id=draft.chat_id,
            photo=msg.photo[-1].file_id,
            caption=caption_html or None,
            parse_mode=ParseMode.HTML if caption_html else None,
            reply_markup=confirm_keyboard(draft_id),
        )
        return draft_id

    if msg.video:
        await context.bot.send_video(
            chat_id=draft.chat_id,
            video=msg.video.file_id,
            caption=caption_html or None,
            parse_mode=ParseMode.HTML if caption_html else None,
            reply_markup=confirm_keyboard(draft_id),
        )
        return draft_id

    if msg.document:
        await context.bot.send_document(
            chat_id=draft.chat_id,
            document=msg.document.file_id,
            caption=caption_html or None,
            parse_mode=ParseMode.HTML if caption_html else None,
            reply_markup=confirm_keyboard(draft_id),
        )
        return draft_id

    await context.bot.send_message(chat_id=draft.chat_id, text="Неизвестный тип сообщения для предпросмотра.")
    return draft_id


# =======================
# Publish
# =======================
async def _publish_draft(context: ContextTypes.DEFAULT_TYPE, draft_id: str, update: Optional[Update] = None) -> None:
    drafts = _drafts(context.application)
    draft = drafts.get(draft_id)
    if not draft:
        return

    target = _resolved_channel(context).strip()
    if not target:
        raise BadRequest("CHANNEL not set")

    caption = _apply_autosign(draft.text or "")
    caption_html = _safe_html(caption) if caption else ""

    await _log(context, f"Publishing to {target}\ncaption_len={len(caption_html)}\nmedias={len(draft.medias)}", update)

    try:
        if draft.medias:
            medias = []
            for i, m in enumerate(draft.medias):
                if i == 0 and caption_html:
                    if isinstance(m, InputMediaPhoto):
                        nm = InputMediaPhoto(media=m.media, caption=caption_html, parse_mode=ParseMode.HTML)
                    elif isinstance(m, InputMediaVideo):
                        nm = InputMediaVideo(media=m.media, caption=caption_html, parse_mode=ParseMode.HTML)
                    elif isinstance(m, InputMediaDocument):
                        nm = InputMediaDocument(media=m.media, caption=caption_html, parse_mode=ParseMode.HTML)
                    else:
                        nm = m
                else:
                    if isinstance(m, InputMediaPhoto):
                        nm = InputMediaPhoto(media=m.media)
                    elif isinstance(m, InputMediaVideo):
                        nm = InputMediaVideo(media=m.media)
                    elif isinstance(m, InputMediaDocument):
                        nm = InputMediaDocument(media=m.media)
                    else:
                        nm = m
                medias.append(nm)

            await context.bot.send_media_group(chat_id=target, media=medias)
            # albums can't have reply_markup -> send buttons as separate message
            if SUBSCRIBE_TO or SUGGEST_TO:
                await context.bot.send_message(chat_id=target, text=" ", reply_markup=promo_keyboard())
            return

        # text-only
        await context.bot.send_message(
            chat_id=target,
            text=caption_html or " ",
            parse_mode=ParseMode.HTML if caption_html else None,
            reply_markup=promo_keyboard() if (SUBSCRIBE_TO or SUGGEST_TO) else None,
            disable_web_page_preview=True,
        )

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


async def handle_single_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if update.message.media_group_id:
        await handle_album_item(update, context)
        return

    if not _is_allowed(update.effective_user.id if update.effective_user else None):
        return

    caption = update.message.caption or ""
    draft = Draft(chat_id=update.effective_chat.id, user_id=update.effective_user.id, text=caption)

    m = update.message
    if m.photo:
        draft.medias = [InputMediaPhoto(media=m.photo[-1].file_id)]
    elif m.video:
        draft.medias = [InputMediaVideo(media=m.video.file_id)]
    elif m.document:
        draft.medias = [InputMediaDocument(media=m.document.file_id)]
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
        buf[key] = {"items": [], "task": None, "user_id": update.effective_user.id}
    buf[key]["items"].append(update)

    task = buf[key].get("task")
    if task and not task.done():
        task.cancel()

    async def finalize():
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
            await _publish_draft(context, draft_id, update=update)
            await context.bot.send_message(chat_id=q.message.chat_id, text="✅ Опубликовано.")
        except Conflict:
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="❌ Conflict: запущены ДВА экземпляра бота (polling). Останови один деплой/инстанс в Render.",
            )
        except Forbidden:
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text="❌ Forbidden: бот не имеет доступа к каналу. Добавь бота в канал и выдай права на публикацию.",
            )
        except BadRequest as e:
            target = _resolved_channel(context)
            await context.bot.send_message(
                chat_id=q.message.chat_id,
                text=(
                    f"❌ Ошибка публикации: {e}\n\n"
                    "Что проверить:\n"
                    f"1) CHANNEL сейчас = {target}\n"
                    "2) Самый надежный вариант: numeric id канала вида -100xxxxxxxxxx\n"
                    "3) /checkchannel должен показывать ✅ Доступ есть\n"
                ),
            )
            await _log(context, f"Publish BadRequest: {e}\nCHANNEL={target}", update)
        return


# =======================
# Main
# =======================
def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("❌ Не задан BOT_TOKEN")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("test", test))
    app.add_handler(CommandHandler("setchannel", setchannel))
    app.add_handler(CommandHandler("getchannelid", getchannelid))
    app.add_handler(CommandHandler("checkchannel", checkchannel))

    app.add_handler(CallbackQueryHandler(on_callback))

    # Album items must be processed before generic handlers
    app.add_handler(MessageHandler(filters.PHOTO, handle_single_media))
    app.add_handler(MessageHandler(filters.VIDEO, handle_single_media))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_single_media))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
