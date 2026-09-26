"""Settings loaded from environment variables / a `.env` file."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_list(name: str) -> set[int]:
    raw = os.getenv(name, "")
    return {int(x) for x in re.split(r"[,\s]+", raw) if x.strip().lstrip("-").isdigit()}


def normalize_phone(phone: str | None) -> str:
    """Keep digits only, so '+91 95260-21998' and '919526021998' compare equal."""
    return re.sub(r"\D", "", phone or "")


@dataclass
class Settings:
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    owner_phone: str = field(default_factory=lambda: normalize_phone(os.getenv("OWNER_PHONE")))
    allowed_user_ids: set[int] = field(default_factory=lambda: _int_list("ALLOWED_USER_IDS"))

    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-opus-5"))
    claude_effort: str = field(default_factory=lambda: os.getenv("CLAUDE_EFFORT", "medium"))
    claude_web_search: bool = field(default_factory=lambda: _bool("CLAUDE_WEB_SEARCH", True))
    history_turns: int = field(default_factory=lambda: int(os.getenv("HISTORY_TURNS", "20")))

    mt5_enabled: bool = field(default_factory=lambda: _bool("MT5_ENABLED", True))
    mt5_login: int = field(default_factory=lambda: int(os.getenv("MT5_LOGIN", "0") or 0))
    mt5_password: str = field(default_factory=lambda: os.getenv("MT5_PASSWORD", ""))
    mt5_server: str = field(default_factory=lambda: os.getenv("MT5_SERVER", ""))
    mt5_path: str = field(default_factory=lambda: os.getenv("MT5_PATH", ""))
    mt5_symbol_suffix: str = field(default_factory=lambda: os.getenv("MT5_SYMBOL_SUFFIX", ""))
    mt5_allow_live: bool = field(default_factory=lambda: _bool("MT5_ALLOW_LIVE", False))
    mt5_max_lot: float = field(default_factory=lambda: float(os.getenv("MT5_MAX_LOT", "1.0")))

    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata"))
    daily_report_time: str = field(default_factory=lambda: os.getenv("DAILY_REPORT_TIME", "08:00"))
    alert_interval_sec: int = field(default_factory=lambda: int(os.getenv("ALERT_INTERVAL_SEC", "30")))
    battery_watch: bool = field(default_factory=lambda: _bool("BATTERY_WATCH", True))
    enable_remote_control: bool = field(default_factory=lambda: _bool("ENABLE_REMOTE_CONTROL", False))

    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "data")))

    def validate(self) -> list[str]:
        problems = []
        if not self.telegram_token:
            problems.append("TELEGRAM_BOT_TOKEN is missing (get one from @BotFather).")
        if not self.owner_phone and not self.allowed_user_ids:
            problems.append("Set OWNER_PHONE and/or ALLOWED_USER_IDS, otherwise nobody can use the bot.")
        if self.claude_effort not in {"low", "medium", "high", "xhigh", "max"}:
            problems.append("CLAUDE_EFFORT must be one of low/medium/high/xhigh/max.")
        return problems
