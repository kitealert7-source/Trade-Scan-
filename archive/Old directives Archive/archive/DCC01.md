**DCC01 — DAILY CLOSE**

TEST PARAMETERS

ASSET- ETHUSD

BROKER- OCTAFX
BROKER FEED - OCTAFX
TIME FRAME -DAILY
DIRECTON - BOTH LONG AND SHORT
Start Date: 2020-01-01

End Date: 2025-12-31

LOT SIZE -MINIMUM AS PER BROKER SPECS





**Regime Detection**

Price > EMA  20 period





**Entry**

Daily Close Based
Long Entry:

If C\[t-1] > C\[t-2] AND C\[t-1] > EMA20\[t-1]

→ Enter LONG at O\[t]



**Short Entry:**

If C\[t-1] < C\[t-2] AND C\[t-1] < EMA20\[t-1]

→ Enter SHORT at O\[t]





**Exit Logic**



Exit all positions at C\[t]





