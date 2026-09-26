"""Access control, onboarding (phone verification), help/menu and error reporting."""
from __future__ import annotations

import logging
import time
import traceback

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, Update)
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.config import normalize_phone
from bot.services.utils import human_duration, split_message

log = logging.getLogger(__name__)

HELP_TEXT = """Here's everything I can do:

🤖 AI assistant (Claude)
• just type — chat with memory + live web search
• send a photo / chart — I analyse it (add a caption as your question)
• send a PDF or text file — I summarise / answer about it
• /ask <q> · /reset (forget chat) · /translate <lang> <text>
• /summarize <url> · /news [topic]

📈 Trading (MT5 / Exness)
• /account · /positions · /price EURUSD
• /buy EURUSD 0.01 [sl] [tp] · /sell … (asks to confirm)
• /close <ticket> · /closeall · /modify <ticket> <sl> <tp>
• /pnl [days] · /lot <balance> <risk%> <sl_pips> [pip_value]
• /alert XAUUSD > 2400 · /alerts · /delalert <id>

⏰ Productivity
• /remind 10m|2h|1d|18:30 <text> · /reminders · /cancel <id>
• /note <text> · /notes · /delnote <id>
• /todo <text> · /todos · /done <id>

🧰 Tools
• /calc 2*(3+4)^2 · /convert 100 USD INR · /weather Kochi
• /qr <text> · /time [Area/City]

🖥 Bot & laptop
• /status (uptime, CPU, RAM, battery) · /logs · /restart · /id · /ping
• /sh <cmd> · /screenshot (only if ENABLE_REMOTE_CONTROL=true)"""

COMMANDS = [
    ("menu", "Main menu"), ("help", "All commands"), ("ask", "Ask the AI"), ("reset", "Forget AI chat"),
    ("account", "MT5 account"), ("positions", "Open positions"), ("price", "Symbol price"),
    ("buy", "Market buy"), ("sell", "Market sell"), ("close", "Close position"), ("closeall", "Close all"),
    ("pnl", "Realised P/L"), ("lot", "Position size calc"), ("alert", "Price alert"), ("alerts", "List alerts"),
    ("remind", "Set reminder"), ("reminders", "List reminders"), ("note", "Save note"), ("notes", "List notes"),
    ("todo", "Add todo"), ("todos", "List todos"), ("calc", "Calculator"), ("convert", "Currency convert"),
    ("weather", "Weather"), ("news", "Latest news"), ("summarize", "Summarise a URL"),
    ("translate", "Translate"), ("qr", "Make QR code"), ("time", "World time"), ("status", "Bot/laptop status"),
]


def is_authorized(context: ContextTypes.DEFAULT_TYPE, user_id: int | None) -> bool:
    if user_id is None:
        return False
    settings = context.bot_data["settings"]
    return user_id in settings.allowed_user_ids or context.bot_data["db"].is_verified(user_id)


def _contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("📱 Share my phone number to verify", request_contact=True)]],
                               resize_keyboard=True, one_time_keyboard=True)


async def auth_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs before every handler. Strangers only get the verification flow."""
    user = update.effective_user
    if user is None:  # channel posts and other anonymous updates are never processed
        raise ApplicationHandlerStop
    if is_authorized(context, user.id):
        return
    msg = update.effective_message
    if msg is not None and (msg.contact is not None or (msg.text or "").startswith("/start")):
        return  # let the verification handlers run
    if update.callback_query:
        await update.callback_query.answer("Not authorised.", show_alert=True)
    elif msg is not None and update.effective_chat and update.effective_chat.type == "private":
        await msg.reply_text("🔒 This is a private bot. Tap /start to verify.")
    log.warning("Blocked update from user %s (%s)", user.id, user.username)
    raise ApplicationHandlerStop


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_authorized(context, user.id):
        await update.message.reply_text(f"Hi {user.first_name}! 👋 I'm online 24/7.",
                                        reply_markup=ReplyKeyboardRemove())
        await menu(update, context)
        return
    if not context.bot_data["settings"].owner_phone:
        await update.message.reply_text(f"🔒 Private bot. Your user id is {user.id}; "
                                        "ask the owner to add it to ALLOWED_USER_IDS.")
        return
    await update.message.reply_text(
        "🔒 Private bot. Verify that you're the owner by sharing your Telegram phone number.",
        reply_markup=_contact_keyboard())


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg, user = update.message, update.effective_user
    settings, db = context.bot_data["settings"], context.bot_data["db"]
    contact = msg.contact
    # Must be the sender's *own* contact, not a forwarded card of someone else.
    if contact.user_id != user.id:
        await msg.reply_text("Please share your own number using the button.", reply_markup=_contact_keyboard())
        return
    if settings.owner_phone and normalize_phone(contact.phone_number) == settings.owner_phone:
        db.verify_user(user.id, msg.chat_id, normalize_phone(contact.phone_number), user.full_name)
        log.info("Owner verified: user %s", user.id)
        await msg.reply_text("✅ Verified. Welcome, boss!", reply_markup=ReplyKeyboardRemove())
        await menu(update, context)
    else:
        log.warning("Failed verification by user %s", user.id)
        await msg.reply_text("❌ That number isn't authorised for this bot.", reply_markup=ReplyKeyboardRemove())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


def _menu_markup() -> InlineKeyboardMarkup:
    rows = [
        [("💼 Account", "m:account"), ("📊 Positions", "m:positions")],
        [("💰 P/L today", "m:pnl"), ("🔔 Alerts", "m:alerts")],
        [("⏰ Reminders", "m:reminders"), ("📝 Notes", "m:notes")],
        [("✅ Todos", "m:todos"), ("🖥 Status", "m:status")],
        [("📰 Market news", "m:news"), ("❓ Help", "m:help")],
    ]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("What do you need?", reply_markup=_menu_markup())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.handlers import admin, ai, productivity, trading  # avoid import cycle

    query = update.callback_query
    await query.answer()
    context.args = []
    target = {
        "account": trading.account, "positions": trading.positions, "pnl": trading.pnl,
        "alerts": trading.list_alerts, "reminders": productivity.list_reminders,
        "notes": productivity.list_notes, "todos": productivity.list_todos,
        "status": admin.status, "news": ai.news, "help": help_cmd,
    }.get(query.data.split(":", 1)[1])
    if target:
        await target(update, context)


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"User id: {update.effective_user.id}\nChat id: {update.effective_chat.id}")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uptime = human_duration(time.time() - context.bot_data["started_at"])
    await update.effective_message.reply_text(f"🏓 pong — up {uptime}")


async def set_commands(application) -> None:
    await application.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled error", exc_info=context.error)
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    text = f"⚠️ Error: {context.error}\n\n{tb[-3000:]}"
    for chat_id in context.bot_data["db"].owner_chat_ids():
        try:
            for chunk in split_message(text):
                await context.bot.send_message(chat_id, chunk)
        except Exception:  # never let error reporting crash the bot
            log.exception("Could not deliver error report")
