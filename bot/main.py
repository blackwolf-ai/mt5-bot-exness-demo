"""Entry point: `python -m bot.main`."""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, time as dtime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.error import InvalidToken
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, Defaults, MessageHandler,
                          TypeHandler, filters)

from bot.config import Settings
from bot.db import DB
from bot.handlers import admin, ai, core, productivity, trading
from bot.services.ai import AIClient
from bot.services.mt5_client import MT5Client

log = logging.getLogger("bot")


def setup_logging(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(settings.data_dir / "bot.log", maxBytes=2_000_000, backupCount=5,
                                       encoding="utf-8")
    console = logging.StreamHandler(sys.stdout)
    for h in (file_handler, console):
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console])
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every poll, and URLs contain the token


async def post_init(app: Application) -> None:
    await core.set_commands(app)
    restored = productivity.restore_reminders(app)
    log.info("Bot started as @%s; restored %d reminders", app.bot.username, restored)
    for chat_id in app.bot_data["db"].owner_chat_ids():
        try:
            await app.bot.send_message(chat_id, f"🟢 Bot online ({datetime.now():%d %b %H:%M}).")
        except Exception:  # noqa: BLE001 - e.g. owner blocked the bot
            log.warning("Could not send startup notice to %s", chat_id)


async def post_shutdown(app: Application) -> None:
    app.bot_data["mt5"].shutdown()


def register_handlers(app: Application) -> None:
    app.add_handler(TypeHandler(Update, core.auth_gate), group=-1)

    commands = {
        "start": core.start, "help": core.help_cmd, "menu": core.menu, "id": core.my_id, "ping": core.ping,
        "ask": ai.ask, "reset": ai.reset, "translate": ai.translate, "summarize": ai.summarize, "news": ai.news,
        "account": trading.account, "positions": trading.positions, "price": trading.price,
        "buy": trading.buy, "sell": trading.sell, "close": trading.close, "closeall": trading.close_all,
        "modify": trading.modify, "pnl": trading.pnl, "lot": trading.lot,
        "alert": trading.add_alert, "alerts": trading.list_alerts, "delalert": trading.del_alert,
        "remind": productivity.remind, "reminders": productivity.list_reminders,
        "cancel": productivity.cancel_reminder, "note": productivity.note, "notes": productivity.list_notes,
        "delnote": productivity.del_note, "todo": productivity.todo, "todos": productivity.list_todos,
        "done": productivity.done, "calc": productivity.calc, "convert": productivity.convert,
        "weather": productivity.weather, "qr": productivity.qr, "time": productivity.world_time,
        "status": admin.status, "logs": admin.logs, "restart": admin.restart,
        "sh": admin.shell, "screenshot": admin.screenshot,
    }
    for name, fn in commands.items():
        app.add_handler(CommandHandler(name, fn, filters=~filters.UpdateType.EDITED))

    app.add_handler(CallbackQueryHandler(core.menu_callback, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(trading.order_callback, pattern=r"^(ok|no):"))
    app.add_handler(CallbackQueryHandler(trading.close_callback, pattern=r"^cl:\d+$"))
    app.add_handler(CallbackQueryHandler(trading.close_confirm_callback, pattern=r"^cx:\d+$"))
    app.add_handler(CallbackQueryHandler(trading.close_all_callback, pattern=r"^ca:"))

    app.add_handler(MessageHandler(filters.CONTACT, core.on_contact))
    app.add_handler(MessageHandler(filters.PHOTO, ai.on_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, ai.on_document))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, ai.on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, ai.on_text))

    app.add_error_handler(core.error_handler)


def schedule_jobs(app: Application, settings: Settings) -> None:
    jq = app.job_queue
    jq.run_repeating(trading.check_alerts_job, interval=settings.alert_interval_sec, first=15, name="alerts")
    if settings.battery_watch:
        jq.run_repeating(admin.battery_watch_job, interval=120, first=30, name="battery")
    hour, minute = (int(x) for x in settings.daily_report_time.split(":"))
    jq.run_daily(admin.daily_report_job, time=dtime(hour, minute, tzinfo=ZoneInfo(settings.timezone)),
                 name="daily-report")


def build_app(settings: Settings) -> Application:
    app = (Application.builder()
           .token(settings.telegram_token)
           .defaults(Defaults(tzinfo=ZoneInfo(settings.timezone)))
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .build())
    app.bot_data.update(
        settings=settings,
        db=DB(settings.data_dir / "bot.sqlite3"),
        ai=AIClient(settings.anthropic_api_key, settings.claude_model, settings.claude_effort,
                    settings.claude_web_search),
        mt5=MT5Client(settings),
        started_at=time.time(),
    )
    register_handlers(app)
    schedule_jobs(app, settings)
    return app


def main() -> int:
    settings = Settings()
    setup_logging(settings)
    problems = settings.validate()
    if problems:
        for p in problems:
            log.error(p)
        return 2
    app = build_app(settings)
    # bootstrap_retries=-1: keep retrying if the laptop boots before Wi-Fi is up.
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES, bootstrap_retries=-1)
    except InvalidToken:
        log.error("Telegram rejected TELEGRAM_BOT_TOKEN. Copy it again from @BotFather.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
