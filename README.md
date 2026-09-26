# mt5-bot-exness-demo — 24/7 Telegram assistant + MT5 trading bot

A private Telegram bot that only answers you. It has three parts:

- **AI assistant (Claude):** chat with memory, live web search, chart and photo analysis, PDF and file reading, translation, page summaries and market news.
- **MT5 / Exness trading:** account, positions, prices, buy/sell/close/modify with a confirm button, P/L, a lot-size calculator and price alerts.
- **Personal tools:** reminders, notes, todos, calculator, currency conversion, weather, QR codes and world clocks.

It also watches the machine it runs on (uptime, CPU, RAM and battery), sends a daily report and brings itself back after crashes.

## Commands

| Area | Commands |
|---|---|
| AI | just type · send photo/chart · send PDF/text file · `/ask` `/reset` `/translate` `/summarize <url>` `/news [topic]` |
| Trading | `/account` `/positions` `/price EURUSD` `/buy EURUSD 0.01 [sl] [tp]` `/sell …` `/close <ticket>` `/closeall` `/modify <ticket> <sl> <tp>` `/pnl [days]` `/lot <balance> <risk%> <sl_pips> [pip_value]` |
| Alerts | `/alert XAUUSD > 2400` `/alerts` `/delalert <id>` |
| Productivity | `/remind 10m\|2h\|1d\|18:30 <text>` `/reminders` `/cancel <id>` `/note` `/notes` `/delnote` `/todo` `/todos` `/done` |
| Tools | `/calc` `/convert 100 USD INR` `/weather Kochi` `/qr <text>` `/time [Area/City]` |
| System | `/menu` `/help` `/status` `/logs` `/restart` `/ping` `/id` · `/sh` `/screenshot` (off by default) |

## Setup (about 10 minutes)

1. **Create the bot.** In Telegram, open **@BotFather**, send `/newbot` and copy the token it gives you.
2. **Get a Claude API key** at <https://console.anthropic.com>. This step is optional; without a key the AI features are switched off.
3. **Configure.** Copy `.env.example` to `.env`, then fill in `TELEGRAM_BOT_TOKEN`, `OWNER_PHONE` (your number with the country code, e.g. `+91…`) and `ANTHROPIC_API_KEY`.
4. **Run it** using one of the options below. Then open your bot in Telegram, send `/start` and tap **Share my phone number**. If the number matches `OWNER_PHONE`, you're verified. Anyone else is blocked.

### Option A: your Windows laptop (full features, including MT5)

1. Install Python 3.11+ from python.org and tick "Add to PATH".
2. Install the **Exness MetaTrader 5** terminal, log into your demo account, and in *Tools → Options → Expert Advisors* enable **Algo Trading**.
3. Double-click `deploy\windows\run_bot.bat` once to test it. It creates `.venv` and installs everything.
4. To run it 24/7, open PowerShell in the repo folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\windows\install_autostart.ps1
   ```
   This starts the bot every time you sign in and restarts it if it dies. On the charger, the laptop never sleeps and closing the lid does nothing.
5. So the bot comes back after Windows Update reboots, turn on automatic sign-in (`netplwiz`, then untick "Users must enter a password"), or at least sign in after each reboot.

### Option B: Linux VPS or Docker (everything except MT5 trading)

```bash
cp .env.example .env    # fill it in
docker compose up -d --build     # or: ./run.sh   or the systemd unit in deploy/linux/
```

## Limits and how the bot handles them

| Limit | How the bot handles it |
|---|---|
| The MT5 Python API only works on **Windows** next to a running MT5 terminal | Trading runs on the Windows laptop or a Windows VPS. On Linux or Docker the bot still runs and explains that MT5 is unavailable. |
| A laptop isn't a server: it sleeps, loses power and gets updated | The autostart task, a restart loop, the no-sleep power plan, charger-unplugged and low-battery alerts, a "🟢 Bot online" message after every restart, and startup retries while Wi-Fi reconnects. For true 24/7 trading, a Windows VPS is the reliable upgrade (Exness offers a free VPS to eligible clients). |
| Bots can't log in with a phone number | The owner is verified once by sharing their Telegram contact. The bot checks that the contact belongs to the sender, so a forwarded contact card doesn't work. |
| Sending trades from a chat is risky | Every order and close needs a confirm button that expires in 60s. **Trading on LIVE accounts is blocked** unless `MT5_ALLOW_LIVE=true`, and there's a `MT5_MAX_LOT` cap. |
| Only one copy of the bot can poll Telegram at a time | Run it on one machine only. A second copy causes "Conflict" errors. |
| The Claude API doesn't take audio | Voice notes get a polite reply. Use text instead. |
| Remote shell and screenshots are powerful | They're off by default (`ENABLE_REMOTE_CONTROL=false`), owner-only and logged. |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

The tests cover the calculator sandbox, time parsing, lot sizing, the database, phone verification and the access gate. They also test the MT5 order logic (Exness symbol suffixes, fill mode, live-account block, lot cap) against a fake MT5 module, and check the shape of the Claude requests.

Layout: `bot/main.py` (wiring and jobs), `bot/handlers/*` (Telegram commands), `bot/services/*` (Claude, MT5, web APIs, helpers), `bot/db.py` (SQLite in `data/`), `deploy/` (Windows, Linux).
