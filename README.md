# mt5-bot-exness-demo

**XAUUSD_Exness_Bot**: an MT5 Expert Advisor (trading bot) for an **Exness Standard** account.

| Requirement | How the bot handles it |
|---|---|
| Platform: MT5, Exness Standard | Native MQL5 EA, runs inside the Exness MT5 terminal |
| Capital: 100 USD | All risk limits are set in USD for a 100 USD account |
| Symbol: XAU/USD only | Refuses to start on any chart that is not XAUUSD (Exness Standard name: `XAUUSDm`) |
| Lot: min 0.02, max 0.02 | Every order is exactly **0.02**. The bot checks this against the broker's min, max and step, and won't start if 0.02 isn't allowed. It holds **one position at a time**. |

File: [`MQL5/Experts/XAUUSD_Exness_Bot.mq5`](MQL5/Experts/XAUUSD_Exness_Bot.mq5)

---

## 1. Feasibility check (done before building)

| Check | Result |
|---|---|
| **P/L per $1 gold move at 0.02 lot** | Contract = 100 oz, so 0.02 lot = 2 oz. **$1 move = $2** (2% of a $100 account). |
| **Real gold volatility (checked Sep 2026, gold ≈ $4,320)** | Median 5-minute ATR in trading hours is **$4.76**, so a 1×ATR stop costs **≈ $9.50 per trade**. v1.0 capped the loss at $6 with a 1.5×ATR stop and would have placed **zero trades**. v1.1 uses a 1×ATR stop capped at **$10** and still skips trades when gold is wilder than that. |
| **Main risk** | Each losing trade costs about 10% of the account. The bot stops for the day after 2 losses in a row or when another full loss would break the $20 daily limit. |
| **Margin** | Margin = 0.02 × 100 × price ÷ leverage: about $43 at 1:200, $17 at 1:500, $4 at 1:2000 (gold at $4,320). At 1:500 or higher this is a small part of $100. The bot runs `OrderCalcMargin` before each trade and skips the trade if it would use more than 50% of free margin. **Set account leverage to 1:500 or higher.** |
| **Spread** | Standard accounts have no commission; the cost is in the spread. The bot skips entries when the spread is above $0.50 (this happens around news and the daily rollover). |
| **Symbol name** | Exness Standard uses the `m` suffix (`XAUUSDm`). The bot accepts any symbol that contains `XAUUSD`. |
| **Stacking risk** | With a fixed lot, the only way to limit exposure is one position at a time. The bot enforces this. |
| **Weekend gaps** | Gold can gap over the weekend, past the stop. By default the bot closes any open trade on Friday at 20:00 server time. |
| **Uptime** | An EA runs only while MT5 is open. You need a PC that stays on or a Windows VPS (check whether you qualify for Exness's free VPS). |

---

## 2. Strategy

- **Trend filter (M15):** EMA 50 above EMA 200, price above EMA 50, and EMA 50 rising gives *uptrend only*. The mirror image gives *downtrend only*.
- **Entry (M5, closed bars only).** Choose one with the `Entry signal` input:
  - **RSI pullback** (default): buy when RSI(14) crosses up through 40; sell when it crosses down through 60.
  - **EMA pullback:** the close crosses back over EMA(20) in the trend direction.
  - **Donchian breakout:** the close breaks the high or low of the last 20 M15 bars in the trend direction.
- **Stop loss:** ATR(14, M5) × 1.0. It is at least $1.00 and above the broker's minimum stop distance. If it would cost more than $10, the trade is skipped.
- **Take profit:** 1.5 × the stop distance (1.5R).
- **Management:** at +1R the stop moves to breakeven +$0.10, then trails at ATR × 1.0.

## 3. Protection (all adjustable)

| Guard | Default |
|---|---|
| **Real-account lock**: no new trades on a real account until `Allow trading on a REAL account` = true | on |
| Max loss per trade | $10 |
| Daily loss limit (a new trade is allowed only if a full loss still fits) | $20 |
| Max losses in a row (stop for the day) | 2 |
| Max trades per day | 3 |
| High-impact USD news filter (±30 min; uses MT5's economic calendar, which is not available in the Strategy Tester) | on |
| Equity floor (no new trades below it) | $60 |
| Max spread | $0.50 |
| Trading hours (server time, Exness = GMT+0) | 07:00–20:00 Mon–Thu, until 18:00 Friday |
| Friday close of open trade | 20:00 |

At these defaults the worst normal day is about −$20 (−20%). A slippage or gap past the stop can make it worse.

---

## 3b. Backtest check (read this before going live)

`research/gold_backtest.py` replays the bot's rules on 60 days of 5-minute gold data (17 Jul – 25 Sep 2026, $0.30 spread, pessimistic fills). "Profit factor" is money won ÷ money lost (above 1 means profitable). Results at the v1.1 defaults:

| Entry signal | Trades | Win rate | Net | Profit factor | Max drawdown |
|---|---|---|---|---|---|
| RSI pullback | 43 | 28% | −$128 | 0.48 | $155 |
| EMA pullback | 82 | 37% | −$97 | 0.77 | $137 |
| Donchian breakout | 41 | 41% | +$3 | 1.02 | $77 (+$50 in the first half, −$46 in the second) |

**None of the three entry signals showed a reliable edge.** Even with zero spread, the RSI pullback still lost. The $60 equity floor would have stopped the bot after about $40 of losses. That's why v1.1 blocks real-account trading by default. 60 days is a short sample and futures data isn't Exness spot, so the right next step is a **multi-year run in the MT5 Strategy Tester on Exness real ticks** for each entry mode. Unlock the real account only if a mode is profitable over years, not weeks.

---

## 4. Changes in v1.1

- **Fixed: bot never traded.** The stop settings didn't fit 2026 gold volatility (see above).
- **Fixed: missed signals.** If indicator data was still loading on the first tick of a bar, v1.0 dropped that bar's signal. v1.1 retries. It also waits up to 120 s for a wide spread or a news block to clear, where v1.0 skipped the signal.
- **Fixed: daily limit could be overshot.** v1.0 could open a trade that would break the daily loss limit if it hit its stop. v1.1 opens a trade only if a full loss still fits inside the limit.
- **Fixed: breakeven/trailing distance.** It was worked out from the take-profit, so entry slippage threw it off. The real initial risk is now saved per position and survives an MT5 restart.
- **Added:** requote retry (up to 3 tries), news filter, real-account lock, and 3 selectable entry signals.
- **Faster backtests:** the daily stats are recalculated only after a trade, not on every tick.
- **Startup:** the bot no longer refuses to start when the tick value isn't loaded yet right after MT5 opens.

## 5. Install and run

1. Download **MT5 from your Exness Personal Area** and log in to your **Standard** account (start with the **demo** account).
2. In MT5, open **File → Open Data Folder**, then go to `MQL5/Experts/`. Copy `XAUUSD_Exness_Bot.mq5` there.
3. Open it in **MetaEditor** (F4) and press **Compile** (F7). It should show `0 errors`.
4. In MT5, open an **XAUUSDm** chart (any timeframe; the bot uses M5 and M15 internally).
5. Drag **XAUUSD_Exness_Bot** from Navigator → Expert Advisors onto the chart. Tick **Allow Algo Trading**.
6. Turn on the **Algo Trading** button in the toolbar. The chart shows a status panel.

### Test before going live (recommended order)
1. **Strategy Tester** (Ctrl+R): Expert = XAUUSD_Exness_Bot, Symbol = XAUUSDm, Modelling = *Every tick based on real ticks*, Deposit = 100 USD, Leverage = your account's. Test at least 6–12 months.
2. **Exness demo account** for 2–4 weeks.
3. Go live on the $100 Standard account only after both of these look acceptable.

---

## 6. Honest risk note

No trading bot is guaranteed to make money. With $100 and a fixed 0.02 lot on gold, a few losing trades can take a large share of the account. Everything above is designed to limit that damage, but it can't remove it. Only trade money you can afford to lose.
