"""AI features: free chat, /ask, photos, documents, translate, summarise, news."""
from __future__ import annotations

import logging
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.services import web
from bot.services.ai import friendly_error
from bot.services.utils import split_message

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram Bot API download limit
TEXT_EXTENSIONS = (".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html", ".xml", ".yaml", ".yml", ".mq5", ".mqh")


async def _reply_long(update: Update, text: str) -> None:
    for chunk in split_message(text):
        await update.effective_message.reply_text(chunk, disable_web_page_preview=True)


async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)


async def _chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    ai, db, settings = context.bot_data["ai"], context.bot_data["db"], context.bot_data["settings"]
    chat_id = update.effective_chat.id
    await _typing(update, context)
    try:
        reply = await ai.chat(db.get_history(chat_id, settings.history_turns * 2), text)
    except Exception as exc:  # noqa: BLE001 - shown to the user in plain words
        await update.effective_message.reply_text(friendly_error(exc))
        return
    db.add_history(chat_id, "user", text)
    db.add_history(chat_id, "assistant", reply)
    await _reply_long(update, reply)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _chat(update, context, update.message.text)


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /ask <question>")
        return
    await _chat(update, context, " ".join(context.args))


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.bot_data["db"].clear_history(update.effective_chat.id)
    await update.message.reply_text("🧹 Conversation memory cleared.")


async def _one_shot(update, context, instruction: str, text: str, web_search: bool = False) -> None:
    await _typing(update, context)
    try:
        reply = await context.bot_data["ai"].one_shot(instruction, text, web=web_search)
    except Exception as exc:  # noqa: BLE001
        await update.effective_message.reply_text(friendly_error(exc))
        return
    await _reply_long(update, reply)


async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.message.reply_to_message
    if context.args and replied and (replied.text or replied.caption):
        lang, text = " ".join(context.args), replied.text or replied.caption
    elif len(context.args) >= 2:
        lang, text = context.args[0], " ".join(context.args[1:])
    else:
        await update.message.reply_text("Usage: /translate <language> <text>\n(or reply to a message with /translate <language>)")
        return
    await _one_shot(update, context, f"Translate the following into {lang}. Reply with the translation only.", text)


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].startswith(("http://", "https://")):
        await update.message.reply_text("Usage: /summarize <https://url>")
        return
    url = context.args[0]
    try:
        page = await web.fetch_text(url)
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"Couldn't fetch that page: {exc}")
        return
    await _one_shot(update, context, f"Summarise this web page ({url}) in 5-8 bullet points, "
                                     "then one line on why it matters for a trader if relevant.", page)


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = " ".join(context.args) if context.args else "forex, gold and major indices"
    await _one_shot(update, context,
                    "Search the web and give me today's most important market-moving news and upcoming "
                    "high-impact economic events. Short bullets with sources.", f"Topic: {topic}", web_search=True)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    photo = update.message.photo[-1]  # largest size
    await _typing(update, context)
    data = bytes(await (await photo.get_file()).download_as_bytearray())
    try:
        reply = await context.bot_data["ai"].describe_image(data, "image/jpeg", update.message.caption or "")
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(friendly_error(exc))
        return
    await _reply_long(update, reply)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    if doc.file_size and doc.file_size > MAX_FILE_BYTES:
        await update.message.reply_text("That file is over Telegram's 20 MB bot download limit.")
        return
    name = (doc.file_name or "file").lower()
    mime = doc.mime_type or ""
    data = bytes(await (await doc.get_file()).download_as_bytearray())

    # Keep a copy of everything the owner sends.
    inbox = context.bot_data["settings"].data_dir / "files"
    inbox.mkdir(parents=True, exist_ok=True)
    safe_name = Path(doc.file_name or doc.file_unique_id).name  # no path traversal
    (inbox / safe_name).write_bytes(data)

    prompt = update.message.caption or ""
    ai = context.bot_data["ai"]
    await _typing(update, context)
    try:
        if mime == "application/pdf" or name.endswith(".pdf"):
            reply = await ai.analyse_pdf(data, prompt)
        elif mime.startswith("image/") and mime in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            reply = await ai.describe_image(data, mime, prompt)
        elif mime.startswith("text/") or name.endswith(TEXT_EXTENSIONS):
            text = data.decode("utf-8", errors="replace")
            reply = await ai.one_shot(prompt or "Summarise this file and point out anything important.",
                                      f"File: {doc.file_name}\n\n{text}")
        else:
            await update.message.reply_text(f"💾 Saved {doc.file_name}. I can analyse PDFs, images and text files.")
            return
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(friendly_error(exc))
        return
    await _reply_long(update, reply)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🎙 Voice notes aren't supported yet (the Claude API doesn't take audio). "
                                    "Please type your message, or use Telegram's built-in transcription.")
