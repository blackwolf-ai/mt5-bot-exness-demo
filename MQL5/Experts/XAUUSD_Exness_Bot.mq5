//+------------------------------------------------------------------+
//|                                          XAUUSD_Exness_Bot.mq5   |
//|        Gold-only EA for Exness MT5 Standard, fixed 0.02 lot      |
//|                                   https://cfdtradertools.store   |
//+------------------------------------------------------------------+
#property copyright   "CFD Trader Tools"
#property link        "https://cfdtradertools.store"
#property version     "1.00"
#property description "XAUUSD only. Fixed 0.02 lot. Built for a ~100 USD Exness Standard account."
#property description "Trend (EMA 50/200 on M15) + RSI pullback entry on M5, ATR stop capped in USD."
#property description "Daily loss limit, consecutive-loss stop, equity floor, spread & session filters."

#include <Trade\Trade.mqh>

//--- Lot (the user requirement: min 0.02 = max 0.02)
input group "=== Lot (fixed) ==="
input double          InpLot                  = 0.02;   // Lot size (fixed: min = max = 0.02)

//--- Strategy
input group "=== Strategy ==="
input ENUM_TIMEFRAMES InpTrendTF              = PERIOD_M15; // Trend timeframe
input int             InpFastEMA              = 50;     // Trend fast EMA
input int             InpSlowEMA              = 200;    // Trend slow EMA
input ENUM_TIMEFRAMES InpEntryTF              = PERIOD_M5;  // Entry timeframe
input int             InpRSIPeriod            = 14;     // Entry RSI period
input double          InpRSIBuyLevel          = 40.0;   // Buy when RSI crosses UP through this (pullback over)
input double          InpRSISellLevel         = 60.0;   // Sell when RSI crosses DOWN through this
input int             InpATRPeriod            = 14;     // ATR period (entry TF)
input double          InpATRSLMult            = 1.5;    // Stop loss = ATR x this
input double          InpRR                   = 1.5;    // Take profit = SL distance x this

//--- Risk (all in account currency, USD)
input group "=== Risk (USD) ==="
input double          InpMaxLossPerTradeUSD   = 6.0;    // Max loss per trade (skip trade if ATR stop needs more)
input double          InpMinSLPrice           = 1.0;    // Min SL distance in gold price ($)
input double          InpMaxDailyLossUSD      = 15.0;   // Stop trading for the day after this loss
input double          InpDailyTargetUSD       = 0.0;    // Stop for the day after this profit (0 = off)
input int             InpMaxTradesPerDay      = 5;      // Max new trades per day
input int             InpMaxConsecLosses      = 3;      // Stop for the day after N losses in a row
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

//--- Misc
input group "=== Misc ==="
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
datetime gLastEntryBar = 0;
string   gStatus  = "";

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
   if(InpFastEMA >= InpSlowEMA || InpRR <= 0.0 || InpATRSLMult <= 0.0 ||
      InpMaxLossPerTradeUSD <= 0.0 || InpStartHour < 0 || InpEndHour > 24 || InpStartHour >= InpEndHour)
     {
      Alert("XAUUSD_Exness_Bot: invalid inputs (check EMA periods, RR, ATR mult, hours, max loss)");
      return INIT_PARAMETERS_INCORRECT;
     }

   double vpp = ValuePerPriceUnit();
   if(vpp <= 0.0)
     {
      Alert("XAUUSD_Exness_Bot: could not read tick value for ", _Symbol);
      return INIT_FAILED;
     }
   if(InpMinSLPrice * vpp > InpMaxLossPerTradeUSD)
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
   if(hFastEMA == INVALID_HANDLE || hSlowEMA == INVALID_HANDLE || hRSI == INVALID_HANDLE || hATR == INVALID_HANDLE)
     {
      Alert("XAUUSD_Exness_Bot: failed to create indicators");
      return INIT_FAILED;
     }

   //--- 5) Trade object
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetDeviationInPoints((ulong)MathMax(1.0, MathRound(InpMaxSlippagePrice / _Point)));
   trade.SetMarginMode();

   PrintFormat("XAUUSD_Exness_Bot started on %s | lot %.2f | $1 gold move = %.2f %s | max SL = %.2f price",
               _Symbol, gLot, vpp, AccountInfoString(ACCOUNT_CURRENCY), InpMaxLossPerTradeUSD / vpp);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(hFastEMA != INVALID_HANDLE) IndicatorRelease(hFastEMA);
   if(hSlowEMA != INVALID_HANDLE) IndicatorRelease(hSlowEMA);
   if(hRSI     != INVALID_HANDLE) IndicatorRelease(hRSI);
   if(hATR     != INVALID_HANDLE) IndicatorRelease(hATR);
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

   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   t.hour = 0; t.min = 0; t.sec = 0;
   datetime dayStart = StructToTime(t);

   if(!HistorySelect(dayStart, TimeCurrent() + 60))
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
//| Returns +1 buy, -1 sell, 0 none. Uses closed bars only.          |
//+------------------------------------------------------------------+
int Signal(double &atr)
  {
   double fast[], slow[], rsi[], atrBuf[];
   if(!GetBuffer(hFastEMA, 0, 1, 3, fast) || !GetBuffer(hSlowEMA, 0, 1, 1, slow) ||
      !GetBuffer(hRSI, 0, 1, 2, rsi)      || !GetBuffer(hATR, 0, 1, 1, atrBuf))
      return 0;

   atr = atrBuf[0];
   double trendClose = iClose(_Symbol, InpTrendTF, 1);
   if(trendClose <= 0.0 || atr <= 0.0)
      return 0;

   // fast[0] = last closed trend bar, fast[2] = two bars before it
   bool upTrend   = fast[0] > slow[0] && trendClose > fast[0] && fast[0] > fast[2];
   bool downTrend = fast[0] < slow[0] && trendClose < fast[0] && fast[0] < fast[2];

   // rsi[0] = last closed entry bar, rsi[1] = the bar before
   bool rsiBuy  = rsi[1] < InpRSIBuyLevel  && rsi[0] >= InpRSIBuyLevel;
   bool rsiSell = rsi[1] > InpRSISellLevel && rsi[0] <= InpRSISellLevel;

   if(upTrend && rsiBuy)
      return 1;
   if(downTrend && rsiSell)
      return -1;
   return 0;
  }

//+------------------------------------------------------------------+
void TryOpen(const int dir, const double atr)
  {
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;

   double spread = tick.ask - tick.bid;
   if(spread > InpMaxSpreadPrice)
     {
      gStatus = StringFormat("Signal skipped: spread %.2f > %.2f", spread, InpMaxSpreadPrice);
      Print(gStatus);
      return;
     }

   double vpp = ValuePerPriceUnit();
   if(vpp <= 0.0)
      return;

   double maxSL    = InpMaxLossPerTradeUSD / vpp;
   double stopsMin = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point + spread;
   double slDist   = MathMax(atr * InpATRSLMult, MathMax(InpMinSLPrice, stopsMin));

   if(slDist > maxSL)
     {
      gStatus = StringFormat("Signal skipped: needed SL %.2f (=%.2f USD) > max loss %.2f USD",
                             slDist, slDist * vpp, InpMaxLossPerTradeUSD);
      Print(gStatus);
      return;
     }

   double price = (dir > 0) ? tick.ask : tick.bid;
   double sl    = NormalizePrice((dir > 0) ? price - slDist : price + slDist);
   double tp    = NormalizePrice((dir > 0) ? price + slDist * InpRR : price - slDist * InpRR);

   ENUM_ORDER_TYPE type = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double margin = 0.0;
   if(!OrderCalcMargin(type, _Symbol, gLot, price, margin))
     {
      Print("OrderCalcMargin failed: ", GetLastError());
      return;
     }
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(margin > freeMargin * InpMaxMarginUsePct / 100.0)
     {
      gStatus = StringFormat("Signal skipped: margin %.2f > %.0f%% of free margin %.2f",
                             margin, InpMaxMarginUsePct, freeMargin);
      Print(gStatus);
      return;
     }

   bool ok = (dir > 0) ? trade.Buy(gLot, _Symbol, price, sl, tp, "XAU bot buy")
                       : trade.Sell(gLot, _Symbol, price, sl, tp, "XAU bot sell");
   if(ok && (trade.ResultRetcode() == TRADE_RETCODE_DONE || trade.ResultRetcode() == TRADE_RETCODE_PLACED))
     {
      gStatus = StringFormat("%s %.2f @ %.2f SL %.2f TP %.2f (risk %.2f USD)",
                             dir > 0 ? "BUY" : "SELL", gLot, trade.ResultPrice(), sl, tp, slDist * vpp);
      Print(gStatus);
     }
   else
     {
      gStatus = StringFormat("Order failed: %u %s", trade.ResultRetcode(), trade.ResultRetcodeDescription());
      Print(gStatus);
     }
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
      return;
     }

   // R = initial risk distance. TP is never moved, so recover R from it.
   double R = (curTP > 0.0) ? MathAbs(curTP - open) / InpRR : 0.0;
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
              "Spread %.2f (max %.2f)  Session %s\n"
              "%s",
              _Symbol, gLot,
              AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
              AccountInfoDouble(ACCOUNT_MARGIN_FREE),
              pnl, InpMaxDailyLossUSD, entries, InpMaxTradesPerDay, streak, InpMaxConsecLosses,
              spread, InpMaxSpreadPrice, InSession() ? "OPEN" : "closed",
              gStatus));
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   ulong ticket = OurPositionTicket();
   if(ticket != 0)
      ManagePosition(ticket);

   //--- act once per closed entry-TF bar
   datetime barTime = iTime(_Symbol, InpEntryTF, 0);
   bool newBar = (barTime != 0 && barTime != gLastEntryBar);

   double pnl = 0.0;
   int    entries = 0, streak = 0;
   TodayStats(pnl, entries, streak);
   UpdatePanel(pnl, entries, streak);

   if(!newBar)
      return;
   gLastEntryBar = barTime;

   if(ticket != 0 || OurPositionTicket() != 0)
      return;                                      // one position at a time

   //--- account guards
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
     { gStatus = "Algo Trading is disabled"; return; }
   if(AccountInfoDouble(ACCOUNT_EQUITY) < InpMinEquityUSD)
     { gStatus = "Equity below floor - trading paused"; return; }
   if(pnl <= -InpMaxDailyLossUSD)
     { gStatus = "Daily loss limit hit - done for today"; return; }
   if(InpDailyTargetUSD > 0.0 && pnl >= InpDailyTargetUSD)
     { gStatus = "Daily profit target hit - done for today"; return; }
   if(entries >= InpMaxTradesPerDay)
     { gStatus = "Max trades for today reached"; return; }
   if(InpMaxConsecLosses > 0 && streak >= InpMaxConsecLosses)
     { gStatus = "Too many losses in a row - done for today"; return; }
   if(!InSession())
     { gStatus = "Outside trading session"; return; }

   double atr = 0.0;
   int dir = Signal(atr);
   if(dir == 0)
     {
      gStatus = "Waiting for signal";
      return;
     }
   TryOpen(dir, atr);
  }
//+------------------------------------------------------------------+
