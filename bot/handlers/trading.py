"""MT5 trading commands, position sizing and price alerts."""
from __future__ import annotations

import logging
import secrets
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.services.mt5_client import MT5Error
from bot.services.utils import lot_size

log = logging.getLogger(__name__)
CONFIRM_TTL = 60  # seconds a trade confirmation button stays valid


def _num(value: str) -> float:
    return float(value.replace(",", "."))


async def _guard(update: Update, context) -> bool:
    mt5 = context.bot_data["mt5"]
    if not mt5.available:
        await update.effective_message.reply_text(mt5.unavailable_reason())
        return False
    return True


async def account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    try:
        a = await context.bot_data["mt5"].account()
    except MT5Error as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return
    kind = "DEMO" if a["demo"] else "⚠️ LIVE"
    await update.effective_message.reply_text(
        f"💼 {a['login']} @ {a['server']} ({kind})\n"
        f"Balance: {a['balance']:,.2f} {a['currency']}\n"
        f"Equity: {a['equity']:,.2f}\nFloating P/L: {a['profit']:+,.2f}\n"
        f"Margin: {a['margin']:,.2f} · Free: {a['free_margin']:,.2f}\n"
        f"Margin level: {a['margin_level']:,.0f}% · Leverage 1:{a['leverage']}")


async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    try:
        rows = await context.bot_data["mt5"].positions()
    except MT5Error as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return
    if not rows:
        await update.effective_message.reply_text("No open positions.")
        return
    total = sum(p["profit"] for p in rows)
    lines = [f"#{p['ticket']} {p['type']} {p['volume']} {p['symbol']} @ {p['open']} → {p['current']}  "
             f"{p['profit']:+.2f}" + (f"  SL {p['sl']}" if p["sl"] else "") + (f"  TP {p['tp']}" if p["tp"] else "")
             for p in rows]
    buttons = [[InlineKeyboardButton(f"Close #{p['ticket']}", callback_data=f"cl:{p['ticket']}")] for p in rows[:10]]
    await update.effective_message.reply_text("\n".join(lines) + f"\n\nTotal: {total:+.2f}",
                                              reply_markup=InlineKeyboardMarkup(buttons))


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /price EURUSD")
        return
    if not await _guard(update, context):
        return
    out = []
    for sym in context.args[:5]:
        try:
            p = await context.bot_data["mt5"].price(sym)
            out.append(f"{p['symbol']}: bid {p['bid']} / ask {p['ask']} (spread {p['spread_points']} pts)")
        except MT5Error as exc:
            out.append(f"{sym}: {exc}")
    await update.message.reply_text("\n".join(out))


async def _order(update: Update, context: ContextTypes.DEFAULT_TYPE, side: str) -> None:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(f"Usage: /{side} SYMBOL LOTS [SL] [TP]\ne.g. /{side} EURUSD 0.01 1.0800 1.0950")
        return
    try:
        symbol, volume = args[0], _num(args[1])
        sl = _num(args[2]) if len(args) > 2 else 0.0
        tp = _num(args[3]) if len(args) > 3 else 0.0
    except ValueError:
        await update.message.reply_text("Lots, SL and TP must be numbers.")
        return
    if not await _guard(update, context):
        return
    token = secrets.token_hex(4)
    context.user_data.setdefault("pending", {})[token] = {
        "side": side, "symbol": symbol, "volume": volume, "sl": sl, "tp": tp, "ts": time.time()}
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm", callback_data=f"ok:{token}"),
                                InlineKeyboardButton("❌ Cancel", callback_data=f"no:{token}")]])
    await update.message.reply_text(
        f"{side.upper()} {volume} {symbol.upper()}" + (f"  SL {sl}" if sl else "") + (f"  TP {tp}" if tp else "")
        + f"\nConfirm within {CONFIRM_TTL}s.", reply_markup=kb)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _order(update, context, "buy")


async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _order(update, context, "sell")


async def order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, token = query.data.split(":", 1)
    order = context.user_data.get("pending", {}).pop(token, None)
    await query.answer()
    if order is None:
        await query.edit_message_text("This order was already handled.")
        return
    if action == "no":
        await query.edit_message_text("Cancelled.")
        return
    if time.time() - order["ts"] > CONFIRM_TTL:
        await query.edit_message_text("⌛ Confirmation expired — send the order again.")
        return
    try:
        res = await context.bot_data["mt5"].market_order(order["side"], order["symbol"], order["volume"],
                                                         order["sl"], order["tp"])
    except MT5Error as exc:
        await query.edit_message_text(f"❌ {exc}")
        return
    log.info("Order %s -> %s", order, res)
    await query.edit_message_text(("✅ " if res.ok else "❌ ") + f"{order['side'].upper()} {order['volume']} "
                                  f"{order['symbol'].upper()}: {res.message}"
                                  + (f" (ticket {res.ticket})" if res.ticket else ""))


async def close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    ticket = int(query.data.split(":", 1)[1])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Yes, close #{ticket}", callback_data=f"cx:{ticket}"),
                                InlineKeyboardButton("❌ No", callback_data="cx:0")]])
    await query.message.reply_text(f"Close position #{ticket}?", reply_markup=kb)


async def close_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    ticket = int(query.data.split(":", 1)[1])
    if not ticket:
        await query.edit_message_text("Kept open.")
        return
    try:
        res = await context.bot_data["mt5"].close(ticket)
    except MT5Error as exc:
        await query.edit_message_text(f"❌ {exc}")
        return
    await query.edit_message_text(("✅ Closed " if res.ok else "❌ ") + f"#{ticket}: {res.message}")


async def close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /close <ticket>  (see /positions)")
        return
    if not await _guard(update, context):
        return
    ticket = int(context.args[0])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✅ Yes, close #{ticket}", callback_data=f"cx:{ticket}"),
                                InlineKeyboardButton("❌ No", callback_data="cx:0")]])
    await update.message.reply_text(f"Close position #{ticket}?", reply_markup=kb)


async def close_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔥 Yes, close ALL", callback_data="ca:yes"),
                                InlineKeyboardButton("❌ No", callback_data="ca:no")]])
    await update.message.reply_text("Close ALL open positions?", reply_markup=kb)


async def close_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data != "ca:yes":
        await query.edit_message_text("Nothing closed.")
        return
    try:
        results = await context.bot_data["mt5"].close_all()
    except MT5Error as exc:
        await query.edit_message_text(f"❌ {exc}")
        return
    lines = [("✅" if r.ok else "❌") + f" #{t}: {r.message}" for t, r in results] or ["No open positions."]
    await query.edit_message_text("\n".join(lines))


async def modify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 3 or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /modify <ticket> <sl> <tp>   (use 0 to remove)")
        return
    if not await _guard(update, context):
        return
    try:
        res = await context.bot_data["mt5"].modify(int(context.args[0]), _num(context.args[1]), _num(context.args[2]))
    except (MT5Error, ValueError) as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    await update.message.reply_text(("✅ " if res.ok else "❌ ") + res.message)


async def pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    days = int(context.args[0]) if context.args and context.args[0].isdigit() else 1
    try:
        h = await context.bot_data["mt5"].history(days)
    except MT5Error as exc:
        await update.effective_message.reply_text(f"❌ {exc}")
        return
    rate = f"{h['wins'] / h['trades'] * 100:.0f}%" if h["trades"] else "n/a"
    await update.effective_message.reply_text(
        f"📅 Last {days} day(s): {h['trades']} closed trades, win rate {rate}\nNet P/L: {h['profit']:+,.2f}")


async def lot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        balance, risk, sl_pips = (_num(x.rstrip("%")) for x in context.args[:3])
        pip_value = _num(context.args[3]) if len(context.args) > 3 else 10.0
        lots = lot_size(balance, risk, sl_pips, pip_value)
    except (ValueError, IndexError):
        await update.message.reply_text(
            "Usage: /lot <balance> <risk%> <sl_pips> [pip_value_per_lot=10]\n"
            "e.g. /lot 1000 1 20  → lots risking 1% with a 20-pip stop\n"
            "(pip value ≈ 10 for XXX/USD pairs on a USD account; gold/indices differ)")
        return
    await update.message.reply_text(
        f"📐 Risk {balance * risk / 100:,.2f} ({risk}%) over {sl_pips} pips\n→ {lots:.2f} lots"
        + ("\n⚠️ Below the 0.01 minimum — widen risk or tighten the stop." if lots < 0.01 else ""))


# --- price alerts -----------------------------------------------------------
async def add_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) != 3 or args[1] not in {">", "<", ">=", "<="}:
        await update.message.reply_text("Usage: /alert SYMBOL > PRICE   or   /alert SYMBOL < PRICE")
        return
    try:
        level = _num(args[2])
    except ValueError:
        await update.message.reply_text("Price must be a number.")
        return
    if not await _guard(update, context):
        return
    op = args[1][0]
    alert_id = context.bot_data["db"].add_alert(update.effective_chat.id, args[0].upper(), op, level)
    await update.message.reply_text(f"🔔 Alert #{alert_id}: {args[0].upper()} {op} {level}")


async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rows = context.bot_data["db"].active_alerts(update.effective_chat.id)
    text = "\n".join(f"#{r['id']} {r['symbol']} {r['op']} {r['price']}" for r in rows) or "No active alerts."
    await update.effective_message.reply_text(text)


async def del_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /delalert <id>")
        return
    ok = context.bot_data["db"].deactivate_alert(int(context.args[0]), update.effective_chat.id)
    await update.message.reply_text("Deleted." if ok else "No such alert.")


async def check_alerts_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    mt5, db = context.bot_data["mt5"], context.bot_data["db"]
    if not mt5.available:
        return
    for row in db.active_alerts():
        try:
            p = await mt5.price(row["symbol"])
        except MT5Error as exc:
            log.warning("Alert #%s price check failed: %s", row["id"], exc)
            continue
        mid = (p["bid"] + p["ask"]) / 2
        hit = mid >= row["price"] if row["op"] == ">" else mid <= row["price"]
        if hit:
            db.deactivate_alert(row["id"])
            await context.bot.send_message(
                row["chat_id"], f"🚨 {p['symbol']} is {mid:.5g} ({row['op']} {row['price']}) — alert #{row['id']}")
