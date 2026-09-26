"""Thin async wrapper over the MetaTrader5 Python package.

The MetaTrader5 package only works on Windows next to a running MT5 terminal.
Everywhere else `available` is False and trading commands explain why.
All MT5 calls are blocking and not thread-safe, so they run one at a time in a worker thread.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import ModuleType

log = logging.getLogger(__name__)


class MT5Error(RuntimeError):
    pass


@dataclass
class OrderResult:
    ok: bool
    message: str
    ticket: int | None = None


def _load_module() -> ModuleType | None:
    try:
        import MetaTrader5 as mt5  # type: ignore
        return mt5
    except ImportError:
        return None


class MT5Client:
    MAGIC = 26092026

    def __init__(self, settings, module: ModuleType | None = None):
        self.s = settings
        self.mt5 = module if module is not None else (_load_module() if settings.mt5_enabled else None)
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def available(self) -> bool:
        return self.mt5 is not None

    def unavailable_reason(self) -> str:
        if not self.s.mt5_enabled:
            return "MT5 is disabled (MT5_ENABLED=false)."
        return ("MT5 isn't available here. It needs Windows with the MetaTrader 5 terminal installed "
                "and `pip install MetaTrader5`. Run the bot on your Windows laptop or a Windows VPS.")

    # --- connection -------------------------------------------------------
    def _ensure(self) -> None:
        mt5 = self.mt5
        if mt5 is None:
            raise MT5Error(self.unavailable_reason())
        if self._connected and mt5.terminal_info() is not None:
            return
        kwargs = {}
        if self.s.mt5_path:
            kwargs["path"] = self.s.mt5_path
        if self.s.mt5_login:
            kwargs.update(login=self.s.mt5_login, password=self.s.mt5_password, server=self.s.mt5_server)
        if not mt5.initialize(**kwargs):
            self._connected = False
            raise MT5Error(f"MT5 initialize failed: {mt5.last_error()}")
        self._connected = True

    async def _run(self, fn, *args):
        async with self._lock:
            return await asyncio.to_thread(self._call, fn, *args)

    def _call(self, fn, *args):
        self._ensure()
        return fn(*args)

    def shutdown(self) -> None:
        if self.mt5 is not None and self._connected:
            self.mt5.shutdown()
            self._connected = False

    # --- helpers ----------------------------------------------------------
    def _resolve_symbol(self, symbol: str) -> str:
        mt5 = self.mt5
        base = symbol.strip()
        candidates = [base, base.upper()]
        for suffix in filter(None, [self.s.mt5_symbol_suffix, "m", "c", ".a"]):
            candidates += [base + suffix, base.upper() + suffix]
        for cand in dict.fromkeys(candidates):
            info = mt5.symbol_info(cand)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(cand, True)
                return cand
        raise MT5Error(f"Symbol '{symbol}' not found at this broker.")

    def _filling_mode(self, info) -> int:
        mt5 = self.mt5
        flags = getattr(info, "filling_mode", 0)
        if flags & 1:  # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        if flags & 2:  # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _is_demo(self) -> bool:
        acc = self.mt5.account_info()
        return acc is not None and acc.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO

    def _check_trading_allowed(self, volume: float) -> None:
        if not self._is_demo() and not self.s.mt5_allow_live:
            raise MT5Error("This is a LIVE account. Trading from Telegram is blocked unless MT5_ALLOW_LIVE=true.")
        if volume <= 0 or volume > self.s.mt5_max_lot:
            raise MT5Error(f"Lot size must be between 0 and MT5_MAX_LOT ({self.s.mt5_max_lot}).")

    def _send(self, request: dict) -> OrderResult:
        result = self.mt5.order_send(request)
        if result is None:
            return OrderResult(False, f"order_send failed: {self.mt5.last_error()}")
        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            return OrderResult(False, f"Rejected (retcode {result.retcode}): {result.comment}")
        return OrderResult(True, f"Done at {result.price}", ticket=result.order)

    # --- sync implementations (run in worker thread) ----------------------
    def _account(self) -> dict:
        acc = self.mt5.account_info()
        if acc is None:
            raise MT5Error(f"account_info failed: {self.mt5.last_error()}")
        return {
            "login": acc.login, "server": acc.server, "currency": acc.currency,
            "balance": acc.balance, "equity": acc.equity, "margin": acc.margin,
            "free_margin": acc.margin_free, "margin_level": acc.margin_level,
            "profit": acc.profit, "leverage": acc.leverage, "demo": self._is_demo(),
        }

    def _positions(self) -> list[dict]:
        rows = self.mt5.positions_get() or ()
        return [{
            "ticket": p.ticket, "symbol": p.symbol,
            "type": "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL",
            "volume": p.volume, "open": p.price_open, "current": p.price_current,
            "sl": p.sl, "tp": p.tp, "profit": p.profit,
        } for p in rows]

    def _price(self, symbol: str) -> dict:
        sym = self._resolve_symbol(symbol)
        tick = self.mt5.symbol_info_tick(sym)
        if tick is None:
            raise MT5Error(f"No price for {sym}.")
        info = self.mt5.symbol_info(sym)
        spread = round((tick.ask - tick.bid) / info.point) if info and info.point else None
        return {"symbol": sym, "bid": tick.bid, "ask": tick.ask, "spread_points": spread,
                "time": datetime.fromtimestamp(tick.time, tz=timezone.utc)}

    def build_market_order(self, side: str, symbol: str, volume: float, sl: float = 0.0, tp: float = 0.0) -> dict:
        mt5 = self.mt5
        sym = self._resolve_symbol(symbol)
        info = mt5.symbol_info(sym)
        tick = mt5.symbol_info_tick(sym)
        if info is None or tick is None:
            raise MT5Error(f"No market data for {sym}.")
        is_buy = side.lower() == "buy"
        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if is_buy else tick.bid,
            "sl": float(sl or 0.0),
            "tp": float(tp or 0.0),
            "deviation": 20,
            "magic": self.MAGIC,
            "comment": "telegram-bot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(info),
        }

    def _market_order(self, side: str, symbol: str, volume: float, sl: float, tp: float) -> OrderResult:
        self._check_trading_allowed(volume)
        return self._send(self.build_market_order(side, symbol, volume, sl, tp))

    def _close(self, ticket: int) -> OrderResult:
        mt5 = self.mt5
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            raise MT5Error(f"No open position #{ticket}.")
        p = pos[0]
        self._check_trading_allowed(p.volume)
        tick = mt5.symbol_info_tick(p.symbol)
        is_buy = p.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position": p.ticket, "price": tick.bid if is_buy else tick.ask,
            "deviation": 20, "magic": self.MAGIC, "comment": "telegram-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(mt5.symbol_info(p.symbol)),
        }
        return self._send(request)

    def _close_all(self) -> list[tuple[int, OrderResult]]:
        return [(p["ticket"], self._close(p["ticket"])) for p in self._positions()]

    def _modify(self, ticket: int, sl: float, tp: float) -> OrderResult:
        mt5 = self.mt5
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            raise MT5Error(f"No open position #{ticket}.")
        self._check_trading_allowed(pos[0].volume)
        return self._send({"action": mt5.TRADE_ACTION_SLTP, "symbol": pos[0].symbol,
                           "position": ticket, "sl": float(sl), "tp": float(tp)})

    def _history(self, days: int) -> dict:
        end = datetime.now(timezone.utc) + timedelta(hours=1)
        start = end - timedelta(days=days)
        deals = self.mt5.history_deals_get(start, end) or ()
        closing = [d for d in deals if d.entry in (self.mt5.DEAL_ENTRY_OUT, self.mt5.DEAL_ENTRY_INOUT)]
        profit = sum(d.profit + d.commission + d.swap for d in closing)
        wins = sum(1 for d in closing if d.profit > 0)
        return {"trades": len(closing), "wins": wins, "profit": profit}

    # --- async API -----------------------------------------------------------
    async def account(self) -> dict:
        return await self._run(self._account)

    async def positions(self) -> list[dict]:
        return await self._run(self._positions)

    async def price(self, symbol: str) -> dict:
        return await self._run(self._price, symbol)

    async def market_order(self, side: str, symbol: str, volume: float, sl: float = 0.0, tp: float = 0.0) -> OrderResult:
        return await self._run(self._market_order, side, symbol, volume, sl, tp)

    async def close(self, ticket: int) -> OrderResult:
        return await self._run(self._close, ticket)

    async def close_all(self) -> list[tuple[int, OrderResult]]:
        return await self._run(self._close_all)

    async def modify(self, ticket: int, sl: float, tp: float) -> OrderResult:
        return await self._run(self._modify, ticket, sl, tp)

    async def history(self, days: int = 1) -> dict:
        return await self._run(self._history, days)
