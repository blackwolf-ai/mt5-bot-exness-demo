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
| **Main risk** | A normal $5 gold swing = $10 = **10% of the account**. Stops must be capped in USD. The bot **skips** a trade when the ATR stop would cost more than `InpMaxLossPerTradeUSD` (default $6). It never forces a stop that is too tight. |
| **Margin** | Margin = 0.02 × 100 × price ÷ leverage. At 1:500 or higher this is a small part of $100. The bot runs `OrderCalcMargin` before each trade and skips the trade if it would use more than 50% of free margin. **Set account leverage to 1:500 or higher.** |
| **Spread** | Standard accounts have no commission; the cost is in the spread. The bot skips entries when the spread is above $0.50 (this happens around news and the daily rollover). |
| **Symbol name** | Exness Standard uses the `m` suffix (`XAUUSDm`). The bot accepts any symbol that contains `XAUUSD`. |
| **Stacking risk** | With a fixed lot, the only way to limit exposure is one position at a time. The bot enforces this. |
| **Weekend gaps** | Gold can gap over the weekend, past the stop. By default the bot closes any open trade on Friday at 20:00 server time. |
| **Uptime** | An EA runs only while MT5 is open. You need a PC that stays on or a Windows VPS (check whether you qualify for Exness's free VPS). |

---

## 2. Strategy

- **Trend filter (M15):** EMA 50 above EMA 200, price above EMA 50, and EMA 50 rising gives *uptrend only*. The mirror image gives *downtrend only*.
- **Entry (M5, closed bars only):**
  - Buy in an uptrend when RSI(14) crosses **up through 40** (the pullback has ended).
  - Sell in a downtrend when RSI(14) crosses **down through 60**.
- **Stop loss:** ATR(14, M5) × 1.5. It is at least $1.00 and above the broker's minimum stop distance. If it would cost more than $6, the trade is skipped.
- **Take profit:** 1.5 × the stop distance (1.5R).
- **Management:** at +1R the stop moves to breakeven +$0.10, then trails at ATR × 1.0.

## 3. Protection (all adjustable)

| Guard | Default |
|---|---|
| Max loss per trade | $6 |
| Daily loss limit (stop for the day) | $15 |
| Max losses in a row (stop for the day) | 3 |
| Max trades per day | 5 |
| Equity floor (no new trades below it) | $60 |
| Max spread | $0.50 |
| Trading hours (server time, Exness = GMT+0) | 07:00–20:00 Mon–Thu, until 18:00 Friday |
| Friday close of open trade | 20:00 |

At these defaults the worst normal day is about −$15 (−15%). A slippage or gap past the stop can make it worse.

---

## 4. Install and run

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

## 5. Honest risk note

No trading bot is guaranteed to make money. With $100 and a fixed 0.02 lot on gold, a few losing trades can take a large share of the account. Everything above is designed to limit that damage, but it can't remove it. Only trade money you can afford to lose.
