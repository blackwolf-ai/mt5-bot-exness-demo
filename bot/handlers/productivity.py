"""Reminders, notes, todos and everyday tools (calc, FX, weather, QR, world time)."""
from __future__ import annotations

import io
import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import qrcode
from telegram import Update
from telegram.ext import Application, ContextTypes

from bot.services import web
from bot.services.utils import parse_when, safe_calc

log = logging.getLogger(__name__)


# --- reminders --------------------------------------------------------------
async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    context.bot_data["db"].finish_reminder(data["id"])
    await context.bot.send_message(data["chat_id"], f"⏰ Reminder: {data['text']}")


def _schedule(app_or_ctx, reminder_id: int, chat_id: int, text: str, due: datetime) -> None:
    app_or_ctx.job_queue.run_once(_fire_reminder, when=due, name=f"reminder-{reminder_id}",
                                  data={"id": reminder_id, "chat_id": chat_id, "text": text})


def restore_reminders(app: Application) -> int:
    """Re-schedule reminders saved before a restart. Overdue ones fire right away."""
    count = 0
    now = datetime.now().astimezone()
    for r in app.bot_data["db"].pending_reminders():
        due = max(datetime.fromtimestamp(r["due_ts"]).astimezone(), now)
        _schedule(app, r["id"], r["chat_id"], r["text"], due)
        count += 1
    return count


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /remind 10m|2h|1d|1h30m|18:30 <text>")
        return
    tz = context.bot_data["settings"].timezone
    try:
        due = parse_when(context.args[0], tz)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    text = " ".join(context.args[1:])
    chat_id = update.effective_chat.id
    rid = context.bot_data["db"].add_reminder(chat_id, text, due.timestamp())
    _schedule(context, rid, chat_id, text, due)
    await update.message.reply_text(f"👍 Reminder #{rid} set for {due:%a %d %b %H:%M} ({tz})")


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tz = ZoneInfo(context.bot_data["settings"].timezone)
    rows = context.bot_data["db"].pending_reminders(update.effective_chat.id)
    text = "\n".join(f"#{r['id']} {datetime.fromtimestamp(r['due_ts'], tz):%d %b %H:%M} — {r['text']}"
                     for r in rows) or "No pending reminders."
    await update.effective_message.reply_text(text)


async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /cancel <reminder id>")
        return
    rid = int(context.args[0])
    if context.bot_data["db"].finish_reminder(rid, update.effective_chat.id):
        for job in context.job_queue.get_jobs_by_name(f"reminder-{rid}"):
            job.schedule_removal()
        await update.message.reply_text(f"Cancelled reminder #{rid}.")
    else:
        await update.message.reply_text("No such reminder.")


# --- notes & todos ----------------------------------------------------------
async def note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.message.reply_to_message
    text = " ".join(context.args) or ((replied.text or replied.caption or "") if replied else "")
    if not text:
        await update.message.reply_text("Usage: /note <text>  (or reply to a message with /note)")
        return
    nid = context.bot_data["db"].add_note(update.effective_user.id, text)
    await update.message.reply_text(f"📝 Saved note #{nid}")


async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = context.bot_data["db"].list_notes(update.effective_user.id)
    text = "\n\n".join(f"#{r['id']} {r['text']}" for r in rows) or "No notes yet."
    await update.effective_message.reply_text(text[-4000:])


async def del_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok = bool(context.args and context.args[0].isdigit()
              and context.bot_data["db"].delete_note(update.effective_user.id, int(context.args[0])))
    await update.message.reply_text("Deleted." if ok else "Usage: /delnote <id>")


async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /todo <task>")
        return
    tid = context.bot_data["db"].add_todo(update.effective_user.id, " ".join(context.args))
    await update.message.reply_text(f"➕ Todo #{tid} added")


async def list_todos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = context.bot_data["db"].list_todos(update.effective_user.id)
    text = "\n".join(f"{'✅' if r['done'] else '⬜'} #{r['id']} {r['text']}" for r in rows) or "No todos."
    await update.effective_message.reply_text(text[-4000:])


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok = bool(context.args and context.args[0].isdigit()
              and context.bot_data["db"].complete_todo(update.effective_user.id, int(context.args[0])))
    await update.message.reply_text("✅ Done!" if ok else "Usage: /done <id>")


# --- tools --------------------------------------------------------------------
async def calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    expr = " ".join(context.args)
    if not expr:
        await update.message.reply_text("Usage: /calc 2*(3+4)^2 / sqrt(16)")
        return
    try:
        result = safe_calc(expr)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError) as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    await update.message.reply_text(f"{expr} = {result:,.10g}" if isinstance(result, float) else f"{expr} = {result:,}")


async def convert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = [a for a in context.args if a.lower() != "to"]
    try:
        amount, base, quote = float(args[0]), args[1], args[2]
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /convert 100 USD INR")
        return
    try:
        await update.message.reply_text(await web.fx_convert(amount, base, quote))
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"Couldn't get the rate: {exc}")


async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city = " ".join(context.args)
    if not city:
        await update.message.reply_text("Usage: /weather <city>")
        return
    try:
        await update.message.reply_text(await web.weather(city))
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"Weather service error: {exc}")


async def qr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /qr <text or link>")
        return
    buf = io.BytesIO()
    qrcode.make(text).save(buf, format="PNG")
    buf.seek(0)
    await update.message.reply_photo(buf, caption=text[:200])


async def world_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    zones = context.args or [context.bot_data["settings"].timezone, "Europe/London", "America/New_York",
                             "Asia/Tokyo", "Australia/Sydney"]
    lines = []
    for z in zones[:8]:
        try:
            lines.append(f"{z}: {datetime.now(ZoneInfo(z)):%a %H:%M}")
        except (ZoneInfoNotFoundError, ValueError):
            lines.append(f"{z}: unknown zone (use Area/City, e.g. Asia/Dubai)")
    await update.message.reply_text("🕒 " + "\n".join(lines))
