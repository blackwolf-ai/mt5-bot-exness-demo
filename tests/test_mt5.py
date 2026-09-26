"""MT5 client logic against a fake MetaTrader5 module (the real one is Windows-only)."""
from types import SimpleNamespace

import pytest

from bot.config import Settings
from bot.services.mt5_client import MT5Client, MT5Error


class FakeMT5:
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    TRADE_RETCODE_DONE = 10009
    DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT = 1, 2

    def __init__(self, trade_mode=0):
        self.trade_mode = trade_mode
        self.sent = []

    def initialize(self, **kw): return True
    def terminal_info(self): return object()
    def last_error(self): return (0, "ok")
    def shutdown(self): pass
    def symbol_select(self, s, v): return True

    def symbol_info(self, s):
        if s != "EURUSDm":
            return None
        return SimpleNamespace(visible=True, filling_mode=2, point=0.00001)

    def symbol_info_tick(self, s):
        return SimpleNamespace(bid=1.1000, ask=1.1002, time=0)

    def account_info(self):
        return SimpleNamespace(trade_mode=self.trade_mode, login=1, server="Exness-MT5Trial", currency="USD",
                               balance=1000, equity=1000, margin=0, margin_free=1000, margin_level=0,
                               profit=0, leverage=200)

    def order_send(self, req):
        self.sent.append(req)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, price=req["price"], order=42, comment="done")


def client(trade_mode=0, **overrides):
    s = Settings()
    s.mt5_symbol_suffix, s.mt5_allow_live, s.mt5_max_lot = "", False, 1.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return MT5Client(s, module=FakeMT5(trade_mode))


async def test_buy_resolves_exness_suffix_and_uses_ioc():
    c = client()
    res = await c.market_order("buy", "eurusd", 0.01, 1.09, 1.12)
    req = c.mt5.sent[0]
    assert res.ok and res.ticket == 42
    assert req["symbol"] == "EURUSDm" and req["price"] == 1.1002 and req["type_filling"] == FakeMT5.ORDER_FILLING_IOC


async def test_live_account_blocked_by_default():
    c = client(trade_mode=FakeMT5.ACCOUNT_TRADE_MODE_REAL)
    with pytest.raises(MT5Error, match="LIVE"):
        await c.market_order("sell", "EURUSD", 0.01)
    assert c.mt5.sent == []


async def test_max_lot_enforced():
    with pytest.raises(MT5Error, match="MT5_MAX_LOT"):
        await client().market_order("buy", "EURUSD", 5)


async def test_unknown_symbol():
    with pytest.raises(MT5Error, match="not found"):
        await client().price("NOPE")


def test_unavailable_without_module():
    s = Settings()
    s.mt5_enabled = False
    assert not MT5Client(s).available
