1. **ATR mean Reversion Strategy**



**Symbol: SPX500**

**Time Frame: -- Daily**

**Back Test period:**

**Start Date: 2015-01-01**

**End Date: 2026-01-31**



**ENTRY**

**Direction: Long Only**

**Highest High of Five past Bars - ATR**

**ATR: 10 period**



**EXIT**

**which ever come earlier**

1. **Close > previous high**
2. **5 Bar maximum holding period**

**Which ever come earlier**



**FILTERS**

**Volatility:**

**Direction: Market Regime Filter**



**VARIENTS**

**look back bars for calculating high**

**ATR period Back period 4 to 26 in step of 2**

**ATR multiplier for ATR .25 and 3 in steps of .25**

**Exit 3 to 15 bars in step of 1**



**Entry Conditions Variants**

**Z score of price deviation ( STD deviation and SMA are variables in it)**

**% Rank of Close to Close returns**









**Rule Bank**



**Trend Checking Rules**



1. Price above SMA, EMA or HMA of 200 period



2\. Trend Permission (Daily)

Uptrend (longs allowed only if ALL true):

Daily close > EMA(200)

EMA(200)\[0] − EMA(200)\[20] > 0

Downtrend (shorts allowed only if ALL true):

Daily close < EMA(200)

EMA(200)\[0] − EMA(200)\[20] < 0

If permission fails → NO TRADE



3\. linear regression line slope





**Entry Rules**



1. RSI Based

Long: RSI(2) average of (T-1, T-2) ≤ 25 AND Uptrend permission

Short: RSI(2) average of (T-1, T-2) ≥ 75 AND Downtrend permission



2\. 4 consecutive same-color daily candles (CANDLE\_COUNT = 4)





Exit (Authoritative)

Primary: Stop-and-Reverse after 4 same-color candles

Fail-safe: 500-pip hard stop



**Exit Rules**



\*\*Exit Logic (Precedence):\*\*

\- \*\*PRIMARY:\*\* RSI(2) > 75 or RSI(2) < 25 (exhaustion exit)

\- \*\*FALLBACK:\*\* Bars held >= 15 (timeout)

\- \*\*HARD STOP:\*\* 2% of entry price (fail-safe)

\- Take Profit: 3.0R fixed risk-reward ratio

\- Timeout:50-bar maximum holding period





**Time Out Based Exits**



1. Fixed number of Bars



2.Fixed number of Bars (Losers only):

Bars held ≥ 5 AND trade not in profit



3\. TREND FAILURE (winners):

Daily close crosses EMA(200) OR

EMA(200) slope flips sign



4\. HARD STOP:

Fixed stop = 2% of entry price (fail-safe)



**Risk Management**



\- Streak Cut 3: Halt trading after 3 consecutive losses (resumes next day)



**Filters**



1. Volatility Buckets Based on ATR percentile
2. Session Filters
