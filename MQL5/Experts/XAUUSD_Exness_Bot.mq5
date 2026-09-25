//+------------------------------------------------------------------+
//|                                          XAUUSD_Exness_Bot.mq5   |
//|        Gold-only EA for Exness MT5 Standard, fixed 0.02 lot      |
//|                                   https://cfdtradertools.store   |
//+------------------------------------------------------------------+
#property copyright   "CFD Trader Tools"
#property link        "https://cfdtradertools.store"
#property version     "1.10"
#property description "XAUUSD only. Fixed 0.02 lot. Built for a ~100 USD Exness Standard account."
#property description "Trend filter (EMA 50/200 on M15) + selectable M5 entry, ATR stop capped in USD."
#property description "Daily loss limit, consecutive-loss stop, equity floor, spread & session filters."

#include <Trade\Trade.mqh>

//--- Lot (the user requirement: min 0.02 = max 0.02)
input group "=== Lot (fixed) ==="
input double          InpLot                  = 0.02;   // Lot size (fixed: min = max = 0.02)

//--- Strategy
enum ENUM_ENTRY_MODE
  {
   ENTRY_RSI_PULLBACK = 0,  // RSI pullback (RSI crosses back through level)
   ENTRY_EMA_PULLBACK = 1,  // EMA pullback (close crosses back over entry EMA)
   ENTRY_DONCHIAN     = 2   // Donchian breakout (close breaks trend-TF channel)
  };

input group "=== Strategy ==="
input ENUM_ENTRY_MODE InpEntryMode            = ENTRY_RSI_PULLBACK; // Entry signal
input ENUM_TIMEFRAMES InpTrendTF              = PERIOD_M15; // Trend timeframe
input int             InpFastEMA              = 50;     // Trend fast EMA
input int             InpSlowEMA              = 200;    // Trend slow EMA
input ENUM_TIMEFRAMES InpEntryTF              = PERIOD_M5;  // Entry timeframe
input int             InpRSIPeriod            = 14;     // Entry RSI period
input double          InpRSIBuyLevel          = 40.0;   // Buy when RSI crosses UP through this (pullback over)
input double          InpRSISellLevel         = 60.0;   // Sell when RSI crosses DOWN through this
input int             InpEntryEMA             = 20;     // EMA pullback: entry EMA period
input int             InpDonchianBars         = 20;     // Donchian: channel length (trend TF bars)
input int             InpATRPeriod            = 14;     // ATR period (entry TF)
input double          InpATRSLMult            = 1.0;    // Stop loss = ATR x this
input double          InpRR                   = 1.5;    // Take profit = SL distance x this

//--- Risk (all in account currency, USD)
input group "=== Risk (USD) ==="
input double          InpMaxLossPerTradeUSD   = 10.0;   // Max loss per trade (skip trade if ATR stop needs more)
input double          InpMinSLPrice           = 1.0;    // Min SL distance in gold price ($)
input double          InpMaxDailyLossUSD      = 20.0;   // Daily loss limit (a new trade must fit inside it)
input double          InpDailyTargetUSD       = 0.0;    // Stop for the day after this profit (0 = off)
input int             InpMaxTradesPerDay      = 3;      // Max new trades per day
input int             InpMaxConsecLosses      = 2;      // Stop for the day after N losses in a row
input double          InpMinEquityUSD         = 60.0;   // Never open trades below this equity
input double          InpMaxSpreadPrice       = 0.50;   // Max spread in gold price ($)
input double          InpMaxMarginUsePct      = 50.0;   // Max % of free margin one trade may use

//--- Trade management
input group "=== Trade management ==="
input double          InpBreakEvenAtR         = 1.0;    // Move SL to breakeven at this many R (0 = off)
input double          InpBELockPrice          = 0.10;   // Profit locked at breakeven ($ price)
input bool            InpUseTrailing          = true;   // Trail SL after breakeven
input double          InpTrailATRMult         = 1.0;    // Trailing distance = ATR x this

//--- Sessions (server time; Exness server time = GMT+0)
input group "=== Session (server time, Exness = GMT+0) ==="
input int             InpStartHour            = 7;      // Start hour (London open)
input int             InpEndHour              = 20;     // End hour (no new trades from this hour)
input int             InpFridayEndHour        = 18;     // Friday: no new trades from this hour
input int             InpFridayCloseHour      = 20;     // Friday: close open trade at this hour (-1 = off)

//--- News (MT5 economic calendar; live/demo only, the Strategy Tester has no calendar)
input group "=== News filter ==="
input bool            InpUseNewsFilter        = true;   // Block entries around high-impact USD news
input int             InpNewsMinutesBefore    = 30;     // Minutes before the event
input int             InpNewsMinutesAfter     = 30;     // Minutes after the event

//--- Misc
input group "=== Misc ==="
input bool            InpAllowRealAccount     = false;  // Allow trading on a REAL account (false = demo/tester only)
input int             InpEntryWindowSec       = 120;    // Seconds after a bar opens to retry a blocked entry
input ulong           InpMagic                = 20260925; // Magic number
input double          InpMaxSlippagePrice     = 0.30;   // Max slippage ($ price)
input bool            InpShowPanel            = true;   // Show info panel on chart

//--- globals
CTrade   trade;
int      hFastEMA = INVALID_HANDLE;
int      hSlowEMA = INVALID_HANDLE;
int      hRSI     = INVALID_HANDLE;
int      hATR     = INVALID_HANDLE;
double   gLot     = 0.0;
int      hEntryEMA = INVALID_HANDLE;
datetime gLastEntryBar = 0;
bool     gBarDone = false;
string   gStatus  = "";
string   gGVPrefix = "";
double   gPendingR = 0.0;          // initial risk distance of the order just sent
//--- cached daily stats (recomputed only after trades / day change)
bool     gStatsDirty = true;
datetime gStatsDay = 0;
double   gDayPnl = 0.0;
int      gDayEntries = 0;
int      gDayStreak = 0;
//--- cached news check
datetime gNewsCheckedAt = 0;
bool     gNewsBlock = false;
string   gNewsName = "";

//+------------------------------------------------------------------+
//| Money value of a 1.0 move in price for gLot                      |
//+------------------------------------------------------------------+
double ValuePerPriceUnit()
  {
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tickValue <= 0.0)
      tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0.0 || tickSize <= 0.0)
      return 0.0;
   return tickValue / tickSize * gLot;
  }

//+------------------------------------------------------------------+
double NormalizePrice(const double price)
  {
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0.0)
      return NormalizeDouble(price, _Digits);
   return NormalizeDouble(MathRound(price / tickSize) * tickSize, _Digits);
  }

//+------------------------------------------------------------------+
bool GetBuffer(const int handle, const int buffer, const int start, const int count, double &out[])
  {
   ArraySetAsSeries(out, true);
   return CopyBuffer(handle, buffer, start, count, out) == count;
  }

//+------------------------------------------------------------------+
bool IsRealAccount()
  {
   return AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL &&
          !MQLInfoInteger(MQL_TESTER);
  }

//+------------------------------------------------------------------+
datetime DayStart(const datetime when)
  {
   MqlDateTime t;
   TimeToStruct(when, t);
   t.hour = 0; t.min = 0; t.sec = 0;
   return StructToTime(t);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   //--- 1) Gold only
   if(StringFind(_Symbol, "XAUUSD") < 0)
     {
      Alert("XAUUSD_Exness_Bot: attach me to an XAUUSD chart (Exness Standard = XAUUSDm). Current: ", _Symbol);
      return INIT_PARAMETERS_INCORRECT;
     }

   //--- 2) Fixed 0.02 lot, validated against broker limits
   double vMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vMax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(vStep <= 0.0)
      vStep = 0.01;
   gLot = NormalizeDouble(MathRound(InpLot / vStep) * vStep, 2);
   if(gLot < vMin || gLot > vMax || MathAbs(gLot - InpLot) > 1e-8)
     {
      Alert(StringFormat("XAUUSD_Exness_Bot: lot %.2f not allowed (min %.2f, max %.2f, step %.2f)",
                         InpLot, vMin, vMax, vStep));
      return INIT_PARAMETERS_INCORRECT;
     }

   //--- 3) Parameter sanity
   if(InpFastEMA >= InpSlowEMA || InpRR <= 0.0 || InpATRSLMult <= 0.0 || InpDonchianBars < 2 || InpEntryEMA < 2 ||
      InpMaxLossPerTradeUSD <= 0.0 || InpStartHour < 0 || InpEndHour > 24 || InpStartHour >= InpEndHour)
     {
      Alert("XAUUSD_Exness_Bot: invalid inputs (check EMA periods, RR, ATR mult, hours, max loss)");
      return INIT_PARAMETERS_INCORRECT;
     }

   // tick value can be 0 for a moment right after terminal start; TryOpen re-checks it
   double vpp = ValuePerPriceUnit();
   if(vpp <= 0.0)
      Print("Warning: tick value not available yet for ", _Symbol, " - will retry before trading");
   else if(InpMinSLPrice * vpp > InpMaxLossPerTradeUSD)
     {
      Alert(StringFormat("XAUUSD_Exness_Bot: min SL %.2f costs %.2f USD at %.2f lot, above max loss %.2f USD",
                         InpMinSLPrice, InpMinSLPrice * vpp, gLot, InpMaxLossPerTradeUSD));
      return INIT_PARAMETERS_INCORRECT;
     }

   if(AccountInfoString(ACCOUNT_CURRENCY) != "USD")
      Print("Warning: account currency is ", AccountInfoString(ACCOUNT_CURRENCY),
            " - USD risk inputs are treated as that currency.");

   //--- 4) Indicators
   hFastEMA = iMA(_Symbol, InpTrendTF, InpFastEMA, 0, MODE_EMA, PRICE_CLOSE);
   hSlowEMA = iMA(_Symbol, InpTrendTF, InpSlowEMA, 0, MODE_EMA, PRICE_CLOSE);
   hRSI     = iRSI(_Symbol, InpEntryTF, InpRSIPeriod, PRICE_CLOSE);
   hATR     = iATR(_Symbol, InpEntryTF, InpATRPeriod);
   hEntryEMA = iMA(_Symbol, InpEntryTF, InpEntryEMA, 0, MODE_EMA, PRICE_CLOSE);
   if(hFastEMA == INVALID_HANDLE || hSlowEMA == INVALID_HANDLE || hRSI == INVALID_HANDLE ||
      hATR == INVALID_HANDLE || hEntryEMA == INVALID_HANDLE)
     {
      Alert("XAUUSD_Exness_Bot: failed to create indicators");
      return INIT_FAILED;
     }

   //--- 5) Trade object
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints((ulong)MathMax(1.0, MathRound(InpMaxSlippagePrice / _Point)));
   trade.SetMarginMode();

   gGVPrefix = StringFormat("XAUBOT_%I64u_R_", InpMagic);
   gStatsDirty = true;

   if(vpp > 0.0)
      PrintFormat("XAUUSD_Exness_Bot started on %s | lot %.2f | $1 gold move = %.2f %s | max SL = %.2f price",
                  _Symbol, gLot, vpp, AccountInfoString(ACCOUNT_CURRENCY), InpMaxLossPerTradeUSD / vpp);
   if(IsRealAccount() && !InpAllowRealAccount)
      Alert("XAUUSD_Exness_Bot: REAL account detected - new trades are blocked until you set "
            "'Allow trading on a REAL account' = true (test on demo first).");
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(hFastEMA != INVALID_HANDLE) IndicatorRelease(hFastEMA);
   if(hSlowEMA != INVALID_HANDLE) IndicatorRelease(hSlowEMA);
   if(hRSI     != INVALID_HANDLE) IndicatorRelease(hRSI);
   if(hATR     != INVALID_HANDLE) IndicatorRelease(hATR);
   if(hEntryEMA != INVALID_HANDLE) IndicatorRelease(hEntryEMA);
   Comment("");
  }

//+------------------------------------------------------------------+
//| Our open position ticket (0 if none)                             |
//+------------------------------------------------------------------+
ulong OurPositionTicket()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return ticket;
     }
   return 0;
  }

//+------------------------------------------------------------------+
//| Today's stats for this EA: realised P/L, entries, losing streak  |
//+------------------------------------------------------------------+
void TodayStats(double &pnl, int &entries, int &consecLosses)
  {
   pnl = 0.0;
   entries = 0;
   consecLosses = 0;

   if(!HistorySelect(DayStart(TimeCurrent()), TimeCurrent() + 60))
      return;

   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)   // oldest -> newest
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol ||
         (ulong)HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic)
         continue;

      double net = HistoryDealGetDouble(deal, DEAL_PROFIT) +
                   HistoryDealGetDouble(deal, DEAL_SWAP) +
                   HistoryDealGetDouble(deal, DEAL_COMMISSION);
      pnl += net;

      long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry == DEAL_ENTRY_IN)
         entries++;
      else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY || entry == DEAL_ENTRY_INOUT)
        {
         if(net < 0.0)
            consecLosses++;
         else
            consecLosses = 0;
        }
     }
  }

//+------------------------------------------------------------------+
//| Recompute daily stats only when a deal happened or the day rolled |
//+------------------------------------------------------------------+
void RefreshStats()
  {
   datetime today = DayStart(TimeCurrent());
   if(today != gStatsDay)
     {
      gStatsDay = today;
      gStatsDirty = true;
     }
   if(!gStatsDirty)
      return;
   TodayStats(gDayPnl, gDayEntries, gDayStreak);
   gStatsDirty = false;
  }

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
      gStatsDirty = true;
  }

//+------------------------------------------------------------------+
//| True if a high-impact USD event is within the news window.       |
//| Calendar times are trade-server times. Checked once a minute.    |
//+------------------------------------------------------------------+
bool NewsBlocked()
  {
   if(!InpUseNewsFilter || MQLInfoInteger(MQL_TESTER))
      return false;
   datetime now = TimeTradeServer();
   if(now - gNewsCheckedAt < 60)
      return gNewsBlock;
   gNewsCheckedAt = now;
   gNewsBlock = false;
   gNewsName = "";

   MqlCalendarValue values[];
   int n = CalendarValueHistory(values, now - InpNewsMinutesAfter * 60, now + InpNewsMinutesBefore * 60, NULL, "USD");
   for(int i = 0; i < n; i++)
     {
      MqlCalendarEvent ev;
      if(CalendarEventById(values[i].event_id, ev) && ev.importance == CALENDAR_IMPORTANCE_HIGH)
        {
         gNewsBlock = true;
         gNewsName = ev.name;
         break;
        }
     }
   return gNewsBlock;
  }

//+------------------------------------------------------------------+
bool InSession()
  {
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   if(t.day_of_week == 0 || t.day_of_week == 6)
      return false;
   if(t.day_of_week == 5 && t.hour >= InpFridayEndHour)
      return false;
   return t.hour >= InpStartHour && t.hour < InpEndHour;
  }

//+------------------------------------------------------------------+
//| Returns +1 buy, -1 sell, 0 none, SIGNAL_NOT_READY if data is not  |
//| loaded yet (retry on the next tick). Uses closed bars only.      |
//+------------------------------------------------------------------+
#define SIGNAL_NOT_READY 99

int Signal(double &atr)
  {
   double fast[], slow[], atrBuf[];
   if(!GetBuffer(hFastEMA, 0, 1, 3, fast) || !GetBuffer(hSlowEMA, 0, 1, 1, slow) ||
      !GetBuffer(hATR, 0, 1, 1, atrBuf))
      return SIGNAL_NOT_READY;

   atr = atrBuf[0];
   double trendClose = iClose(_Symbol, InpTrendTF, 1);
   if(trendClose <= 0.0 || atr <= 0.0)
      return SIGNAL_NOT_READY;

   // fast[0] = last closed trend bar, fast[2] = two bars before it
   bool upTrend   = fast[0] > slow[0] && trendClose > fast[0] && fast[0] > fast[2];
   bool downTrend = fast[0] < slow[0] && trendClose < fast[0] && fast[0] < fast[2];

   if(!upTrend && !downTrend)
      return 0;

   bool buy = false, sell = false;
   if(InpEntryMode == ENTRY_RSI_PULLBACK)
     {
      double rsi[];
      if(!GetBuffer(hRSI, 0, 1, 2, rsi))
         return SIGNAL_NOT_READY;
      // rsi[0] = last closed entry bar, rsi[1] = the bar before
      buy  = rsi[1] < InpRSIBuyLevel  && rsi[0] >= InpRSIBuyLevel;
      sell = rsi[1] > InpRSISellLevel && rsi[0] <= InpRSISellLevel;
     }
   else
     {
      double c1 = iClose(_Symbol, InpEntryTF, 1);
      double c2 = iClose(_Symbol, InpEntryTF, 2);
      if(c1 <= 0.0 || c2 <= 0.0)
         return SIGNAL_NOT_READY;

      if(InpEntryMode == ENTRY_EMA_PULLBACK)
        {
         double ema[];
         if(!GetBuffer(hEntryEMA, 0, 1, 2, ema))
            return SIGNAL_NOT_READY;
         // close crosses back over the entry EMA in the trend direction
         buy  = c2 <= ema[1] && c1 > ema[0];
         sell = c2 >= ema[1] && c1 < ema[0];
        }
      else // ENTRY_DONCHIAN
        {
         int hi = iHighest(_Symbol, InpTrendTF, MODE_HIGH, InpDonchianBars, 1);
         int lo = iLowest(_Symbol, InpTrendTF, MODE_LOW, InpDonchianBars, 1);
         if(hi < 0 || lo < 0)
            return SIGNAL_NOT_READY;
         double chHigh = iHigh(_Symbol, InpTrendTF, hi);
         double chLow  = iLow(_Symbol, InpTrendTF, lo);
         // entry-TF close crosses outside the channel of closed trend-TF bars
         buy  = c2 <= chHigh && c1 > chHigh;
         sell = c2 >= chLow  && c1 < chLow;
        }
     }

   if(upTrend && buy)
      return 1;
   if(downTrend && sell)
      return -1;
   return 0;
  }

//+------------------------------------------------------------------+
//| Returns true when this bar's signal is finished with (order sent  |
//| or signal rejected for good), false to retry on a later tick.    |
//+------------------------------------------------------------------+
bool TryOpen(const int dir, const double atr)
  {
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return false;

   double spread = tick.ask - tick.bid;
   if(spread > InpMaxSpreadPrice)
     {
      gStatus = StringFormat("Signal waiting: spread %.2f > %.2f", spread, InpMaxSpreadPrice);
      return false;
     }

   double vpp = ValuePerPriceUnit();
   if(vpp <= 0.0)
      return false;

   double maxSL    = InpMaxLossPerTradeUSD / vpp;
   double stopsMin = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point + spread;
   double slDist   = MathMax(atr * InpATRSLMult, MathMax(InpMinSLPrice, stopsMin));

   if(slDist > maxSL)
     {
      gStatus = StringFormat("Signal skipped: needed SL %.2f (=%.2f USD) > max loss %.2f USD",
                             slDist, slDist * vpp, InpMaxLossPerTradeUSD);
      Print(gStatus);
      return true;
     }

   ENUM_ORDER_TYPE type = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double margin = 0.0;
   if(!OrderCalcMargin(type, _Symbol, gLot, (dir > 0) ? tick.ask : tick.bid, margin))
     {
      Print("OrderCalcMargin failed: ", GetLastError());
      return false;
     }
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(margin > freeMargin * InpMaxMarginUsePct / 100.0)
     {
      gStatus = StringFormat("Signal skipped: margin %.2f > %.0f%% of free margin %.2f",
                             margin, InpMaxMarginUsePct, freeMargin);
      Print(gStatus);
      return true;
     }

   //--- send; on requote / price change refresh the price and retry (max 3 tries)
   for(int attempt = 0; attempt < 3; attempt++)
     {
      if(attempt > 0 && !SymbolInfoTick(_Symbol, tick))
         return false;
      double price = (dir > 0) ? tick.ask : tick.bid;
      double sl    = NormalizePrice((dir > 0) ? price - slDist : price + slDist);
      double tp    = NormalizePrice((dir > 0) ? price + slDist * InpRR : price - slDist * InpRR);

      bool ok = (dir > 0) ? trade.Buy(gLot, _Symbol, price, sl, tp, "XAU bot buy")
                          : trade.Sell(gLot, _Symbol, price, sl, tp, "XAU bot sell");
      uint rc = trade.ResultRetcode();
      if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
        {
         gPendingR = slDist;
         gStatus = StringFormat("%s %.2f @ %.2f SL %.2f TP %.2f (risk %.2f USD)",
                                dir > 0 ? "BUY" : "SELL", gLot, trade.ResultPrice(), sl, tp, slDist * vpp);
         Print(gStatus);
         return true;
        }
      gStatus = StringFormat("Order failed: %u %s", rc, trade.ResultRetcodeDescription());
      Print(gStatus);
      if(rc != TRADE_RETCODE_REQUOTE && rc != TRADE_RETCODE_PRICE_CHANGED && rc != TRADE_RETCODE_PRICE_OFF)
         return true;   // not a price problem - don't hammer the server this bar
     }
   return true;
  }

//+------------------------------------------------------------------+
//| Breakeven + ATR trailing for our open position                   |
//+------------------------------------------------------------------+
void ManagePosition(const ulong ticket)
  {
   if(!PositionSelectByTicket(ticket))
      return;

   long   type   = PositionGetInteger(POSITION_TYPE);
   double open   = PositionGetDouble(POSITION_PRICE_OPEN);
   double curSL  = PositionGetDouble(POSITION_SL);
   double curTP  = PositionGetDouble(POSITION_TP);

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   //--- Friday close to avoid weekend gap risk on a small account
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   if(InpFridayCloseHour >= 0 && t.day_of_week == 5 && t.hour >= InpFridayCloseHour)
     {
      if(trade.PositionClose(ticket))
         Print("Friday close: position closed to avoid weekend gap");
      else
         gStatus = StringFormat("Friday close failed: %u %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
      return;
     }

   // R = initial risk distance, kept in a terminal global variable so it survives
   // restarts and entry slippage. Fallback: TP is never moved, so recover R from it.
   string gv = gGVPrefix + (string)ticket;
   if(!GlobalVariableCheck(gv) && gPendingR > 0.0)
     {
      GlobalVariableSet(gv, gPendingR);
      gPendingR = 0.0;
     }
   double R = GlobalVariableCheck(gv) ? GlobalVariableGet(gv)
                                      : ((curTP > 0.0) ? MathAbs(curTP - open) / InpRR : 0.0);
   if(R <= 0.0)
      return;

   bool   isBuy    = (type == POSITION_TYPE_BUY);
   double mktPrice = isBuy ? tick.bid : tick.ask;
   double profit   = isBuy ? mktPrice - open : open - mktPrice;
   double minGap   = MathMax((double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL),
                             (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * _Point;
   double newSL    = curSL;

   //--- breakeven
   if(InpBreakEvenAtR > 0.0 && profit >= R * InpBreakEvenAtR)
     {
      double be = NormalizePrice(isBuy ? open + InpBELockPrice : open - InpBELockPrice);
      if(isBuy  && (curSL == 0.0 || be > newSL)) newSL = be;
      if(!isBuy && (curSL == 0.0 || be < newSL)) newSL = be;
     }

   //--- trailing (only once past breakeven)
   bool pastBE = isBuy ? (newSL >= open) : (newSL > 0.0 && newSL <= open);
   if(InpUseTrailing && pastBE)
     {
      double atr[];
      if(GetBuffer(hATR, 0, 1, 1, atr) && atr[0] > 0.0)
        {
         double trail = NormalizePrice(isBuy ? mktPrice - atr[0] * InpTrailATRMult
                                             : mktPrice + atr[0] * InpTrailATRMult);
         if(isBuy  && trail > newSL) newSL = trail;
         if(!isBuy && trail < newSL) newSL = trail;
        }
     }

   // only move in our favour, by at least one tick, and respect broker distance
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   bool improves = isBuy ? (newSL > curSL + tickSize) : (curSL == 0.0 || newSL < curSL - tickSize);
   bool legal    = isBuy ? (mktPrice - newSL > minGap) : (newSL - mktPrice > minGap);
   if(improves && legal)
     {
      if(trade.PositionModify(ticket, newSL, curTP))
         PrintFormat("SL moved %.2f -> %.2f", curSL, newSL);
     }
  }

//+------------------------------------------------------------------+
void UpdatePanel(const double pnl, const int entries, const int streak)
  {
   if(!InpShowPanel)
      return;
   double spread = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   Comment(StringFormat(
              "XAUUSD Exness Bot  |  %s  |  lot %.2f\n"
              "Balance %.2f  Equity %.2f  Free margin %.2f\n"
              "Today P/L %.2f (limit -%.2f)  Trades %d/%d  Loss streak %d/%d\n"
              "Spread %.2f (max %.2f)  Session %s  News %s  Mode %s\n"
              "%s",
              _Symbol, gLot,
              AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
              AccountInfoDouble(ACCOUNT_MARGIN_FREE),
              pnl, InpMaxDailyLossUSD, entries, InpMaxTradesPerDay, streak, InpMaxConsecLosses,
              spread, InpMaxSpreadPrice, InSession() ? "OPEN" : "closed",
              gNewsBlock ? ("BLOCK: " + gNewsName) : "clear", EnumToString(InpEntryMode),
              gStatus));
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   ulong ticket = OurPositionTicket();
   if(ticket != 0)
      ManagePosition(ticket);
   else if(GlobalVariablesTotal() > 0)
      GlobalVariablesDeleteAll(gGVPrefix);       // no open position -> drop stale R values

   RefreshStats();
   UpdatePanel(gDayPnl, gDayEntries, gDayStreak);

   //--- one entry decision per entry-TF bar; blocked entries retry within the window
   datetime barTime = iTime(_Symbol, InpEntryTF, 0);
   if(barTime == 0)
      return;
   if(barTime != gLastEntryBar)
     {
      gLastEntryBar = barTime;
      gBarDone = false;
     }
   if(gBarDone)
      return;
   if(TimeCurrent() - barTime > InpEntryWindowSec)
     {
      gBarDone = true;   // too late in the bar - wait for the next one
      return;
     }

   if(ticket != 0 || OurPositionTicket() != 0)
     { gBarDone = true; return; }                  // one position at a time

   //--- account guards (fixed for this bar)
   if(IsRealAccount() && !InpAllowRealAccount)
     { gStatus = "REAL account: trading blocked (see inputs)"; gBarDone = true; return; }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
     { gStatus = "Algo Trading is disabled"; return; }
   if(AccountInfoDouble(ACCOUNT_EQUITY) < InpMinEquityUSD)
     { gStatus = "Equity below floor - trading paused"; gBarDone = true; return; }
   if(gDayPnl - InpMaxLossPerTradeUSD < -InpMaxDailyLossUSD)
     { gStatus = "Daily loss budget used - done for today"; gBarDone = true; return; }
   if(InpDailyTargetUSD > 0.0 && gDayPnl >= InpDailyTargetUSD)
     { gStatus = "Daily profit target hit - done for today"; gBarDone = true; return; }
   if(gDayEntries >= InpMaxTradesPerDay)
     { gStatus = "Max trades for today reached"; gBarDone = true; return; }
   if(InpMaxConsecLosses > 0 && gDayStreak >= InpMaxConsecLosses)
     { gStatus = "Too many losses in a row - done for today"; gBarDone = true; return; }
   if(!InSession())
     { gStatus = "Outside trading session"; gBarDone = true; return; }

   double atr = 0.0;
   int dir = Signal(atr);
   if(dir == SIGNAL_NOT_READY)
      return;                                      // data still loading - retry next tick
   if(dir == 0)
     {
      gStatus = "Waiting for signal";
      gBarDone = true;
      return;
     }

   //--- blockers that can clear within the bar: retry on the next tick
   if(NewsBlocked())
     { gStatus = "Signal waiting: high-impact USD news (" + gNewsName + ")"; return; }

   gBarDone = TryOpen(dir, atr);
  }
//+------------------------------------------------------------------+
