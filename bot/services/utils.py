"""Pure helpers: safe calculator, time parsing, position sizing, message splitting."""
from __future__ import annotations

import ast
import math
import operator
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TELEGRAM_LIMIT = 4096

_BIN_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    name: getattr(math, name)
    for name in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "log2",
                 "exp", "floor", "ceil", "factorial", "radians", "degrees")
}
_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max})
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_calc(expr: str) -> float:
    """Evaluate arithmetic without `eval`. Raises ValueError on anything else."""
    expr = expr.replace("^", "**").replace("×", "*").replace("÷", "/")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("exponent too large")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCS and not node.keywords):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("unsupported expression")

    if len(expr) > 200:
        raise ValueError("expression too long")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid expression") from exc
    return ev(tree)


_DUR_RE = re.compile(r"(\d+)\s*([smhdw])")
_DUR_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_when(token: str, tz: str, now: datetime | None = None) -> datetime:
    """'10m', '1h30m', '2d' -> now + delta; 'HH:MM' -> next occurrence in `tz`."""
    zone = ZoneInfo(tz)
    now = now.astimezone(zone) if now else datetime.now(zone)
    token = token.strip().lower()
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", token)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("invalid time")
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return due if due > now else due + timedelta(days=1)
    if not re.fullmatch(r"(\d+\s*[smhdw]\s*)+", token):
        raise ValueError("use e.g. 10m, 2h, 1d, 1h30m or HH:MM")
    seconds = sum(int(n) * _DUR_UNITS[u] for n, u in _DUR_RE.findall(token))
    if seconds <= 0:
        raise ValueError("duration must be positive")
    return now + timedelta(seconds=seconds)


def lot_size(balance: float, risk_pct: float, sl_pips: float, pip_value_per_lot: float = 10.0) -> float:
    """Lots so that hitting the stop loses `risk_pct` % of `balance`.

    pip_value_per_lot is the account-currency value of one pip for 1.00 lot
    (10 for most XXX/USD pairs on a USD account).
    """
    if balance <= 0 or risk_pct <= 0 or sl_pips <= 0 or pip_value_per_lot <= 0:
        raise ValueError("all values must be positive")
    risk_money = balance * risk_pct / 100
    return math.floor(risk_money / (sl_pips * pip_value_per_lot) * 100) / 100


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split long text on paragraph/line boundaries to fit Telegram's message limit."""
    text = text or "(empty)"
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = [f"{v}{u}" for v, u in ((days, "d"), (hours, "h"), (minutes, "m")) if v]
    return " ".join(parts) or f"{secs}s"
