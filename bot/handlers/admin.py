"""Health, logs, restart, laptop watchdogs (battery) and optional remote control."""
from __future__ import annotations

import asyncio
import io
import logging
import platform
import time

import psutil
from telegram import Update
from telegram.ext import ContextTypes

from bot.services.mt5_client import MT5Error
from bot.services.utils import human_duration, split_message

log = logging.getLogger(__name__)


def _battery_line() -> str:
    batt = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if batt is None:
        return "Battery: n/a (desktop/server)"
    plug = "🔌 charging" if batt.power_plugged else "🔋 ON BATTERY"
    return f"Battery: {batt.percent:.0f}% {plug}"


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bd = context.bot_data
    disk = psutil.disk_usage(str(bd["settings"].data_dir.resolve().anchor or "/"))
    mem = psutil.virtual_memory()
    cpu = await asyncio.to_thread(psutil.cpu_percent, 0.5)
    mt5 = bd["mt5"]
    if mt5.available:
        try:
            acc = await mt5.account()
            mt5_line = f"MT5: connected, equity {acc['equity']:,.2f} {acc['currency']}"
        except MT5Error as exc:
            mt5_line = f"MT5: ⚠️ {exc}"
    else:
        mt5_line = "MT5: not available on this machine"
    await update.effective_message.reply_text(
        f"🖥 {platform.node()} · {platform.system()} {platform.release()}\n"
        f"Bot uptime: {human_duration(time.time() - bd['started_at'])}\n"
        f"System uptime: {human_duration(time.time() - psutil.boot_time())}\n"
        f"CPU: {cpu:.0f}% · RAM: {mem.percent:.0f}% · Disk: {disk.percent:.0f}%\n"
        f"{_battery_line()}\n{mt5_line}\n"
        f"AI: {'on (' + bd['ai'].model + ')' if bd['ai'].enabled else 'off (no ANTHROPIC_API_KEY)'}")


async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = int(context.args[0]) if context.args and context.args[0].isdigit() else 40
    path = context.bot_data["settings"].data_dir / "bot.log"
    if not path.exists():
        await update.message.reply_text("No log file yet.")
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    for chunk in split_message("\n".join(lines)):
        await update.message.reply_text(chunk)


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("♻️ Restarting… (your supervisor/run script brings me back in a few seconds)")
    context.bot_data["restart_requested"] = True
    context.application.stop_running()


async def shell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.bot_data["settings"].enable_remote_control:
        await update.message.reply_text("Remote control is off. Set ENABLE_REMOTE_CONTROL=true to allow /sh.")
        return
    cmd = update.message.text.partition(" ")[2].strip()
    if not cmd:
        await update.message.reply_text("Usage: /sh <command>")
        return
    log.warning("Remote shell by %s: %s", update.effective_user.id, cmd)
    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        await update.message.reply_text("⏱ Timed out after 60s (killed).")
        return
    text = out.decode(errors="replace").strip() or "(no output)"
    for chunk in split_message(f"$ {cmd}\n[exit {proc.returncode}]\n{text}"[-12000:]):
        await update.message.reply_text(chunk)


async def screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.bot_data["settings"].enable_remote_control:
        await update.message.reply_text("Remote control is off. Set ENABLE_REMOTE_CONTROL=true to allow /screenshot.")
        return
    try:
        from PIL import ImageGrab
        img = await asyncio.to_thread(ImageGrab.grab)
    except Exception as exc:  # noqa: BLE001 - headless servers have no screen
        await update.message.reply_text(f"Screenshot not possible here: {exc}")
        return
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    await update.message.reply_document(buf, filename="screen.png")


# --- background jobs ---------------------------------------------------------
async def battery_watch_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Warn when the laptop is unplugged or low — the #1 way a laptop-hosted bot dies."""
    batt = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if batt is None:
        return
    state = context.bot_data.setdefault("battery_state", {"unplugged": False, "low": False})
    msgs = []
    if not batt.power_plugged and not state["unplugged"]:
        msgs.append(f"🔌 Laptop charger unplugged ({batt.percent:.0f}%). The bot stops when the battery dies.")
        state["unplugged"] = True
    elif batt.power_plugged and state["unplugged"]:
        msgs.append("🔌 Charger reconnected.")
        state.update(unplugged=False, low=False)
    if not batt.power_plugged and batt.percent <= 20 and not state["low"]:
        msgs.append(f"🪫 Battery low: {batt.percent:.0f}%! Plug in the laptop.")
        state["low"] = True
    for msg in msgs:
        for chat_id in context.bot_data["db"].owner_chat_ids():
            await context.bot.send_message(chat_id, msg)


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    bd = context.bot_data
    lines = [f"☀️ Daily report — bot up {human_duration(time.time() - bd['started_at'])}", _battery_line()]
    mt5 = bd["mt5"]
    if mt5.available:
        try:
            acc = await mt5.account()
            hist = await mt5.history(1)
            pos = await mt5.positions()
            lines += [f"Balance {acc['balance']:,.2f} · Equity {acc['equity']:,.2f} {acc['currency']}",
                      f"Open positions: {len(pos)} · Yesterday's P/L: {hist['profit']:+,.2f}"]
        except MT5Error as exc:
            lines.append(f"MT5: ⚠️ {exc}")
    pending = len(bd["db"].pending_reminders())
    lines.append(f"Pending reminders: {pending}")
    for chat_id in bd["db"].owner_chat_ids():
        await context.bot.send_message(chat_id, "\n".join(lines))
