from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot.config import normalize_phone
from bot.services.utils import human_duration, lot_size, parse_when, safe_calc, split_message


def test_calc_basic():
    assert safe_calc("2*(3+4)^2") == 98
    assert safe_calc("sqrt(16) + pi - pi") == 4


@pytest.mark.parametrize("expr", ["__import__('os')", "open('x')", "2**100000", "a+1", "(lambda: 1)()"])
def test_calc_rejects_unsafe(expr):
    with pytest.raises(ValueError):
        safe_calc(expr)


def test_parse_when_durations():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert (parse_when("1h30m", "Asia/Kolkata", now) - now).total_seconds() == 5400
    assert (parse_when("2d", "Asia/Kolkata", now) - now).days == 2


def test_parse_when_clock_rolls_to_tomorrow():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert parse_when("18:30", "Asia/Kolkata", now).day == 1
    assert parse_when("09:00", "Asia/Kolkata", now).day == 2


@pytest.mark.parametrize("bad", ["soon", "25:00", "0m", "10x"])
def test_parse_when_rejects(bad):
    with pytest.raises(ValueError):
        parse_when(bad, "UTC")


def test_lot_size():
    assert lot_size(1000, 1, 20) == 0.05          # $10 risk / (20 pips * $10)
    assert lot_size(10000, 2, 50, 10) == 0.4
    with pytest.raises(ValueError):
        lot_size(1000, 0, 20)


def test_split_message():
    text = ("a" * 3000 + "\n\n") * 3
    parts = split_message(text)
    assert all(len(p) <= 4096 for p in parts) and len(parts) == 3


def test_phone_normalize():
    assert normalize_phone("+91 95260-21998") == normalize_phone("919526021998")


def test_human_duration():
    assert human_duration(90061) == "1d 1h 1m"
