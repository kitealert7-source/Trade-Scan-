# Demo — Extended News Policy Section

Strategy: `63_BRK_IDX_30M_ATRBRK_S13_V2_P00_NAS100` (ATRBRK breakout on NAS100 30M)
Calendar: `data_root/EXTERNAL_DATA/NEWS_CALENDAR/RESEARCH/` (live, daily-updated, ForexFactory source)

## A. Legacy contract (default kwargs — byte-stable with existing reports)

---

## News Policy Impact

### Portfolio Impact

| Policy | Trades | Net PnL | PF | Win % | Max DD |
|--------|--------|---------|-----|-------|--------|
| Baseline | 1214 | $1,337.60 | 1.22 | 35.1% | $354.05 |
| No-Entry | 1203 | $1,342.26 | 1.23 | 35.0% | $354.05 |
| Go-Flat | 1203 | $1,064.21 | 1.19 | 36.2% | $413.82 |

### Per-Symbol News Sensitivity

| Symbol | Trades (News) | PF (News) | PF (Outside) | Impact |
|--------|--------------|-----------|--------------|--------|
| NAS100 | 305 | 4.83 | 0.56 | Helps |

### News vs Non-News Performance (Aggregate)

| Segment | Trades | Net PnL | PF | Avg R |
|---------|--------|---------|-----|-------|
| News Window | 305 | $3,545.37 | 4.83 | +0.287 |
| Outside | 909 | $-2,207.77 | 0.56 | -0.073 |

- News PF: 4.83 vs Outside PF: 0.56
- Most affected: NAS100 (helps)

> Note: Go-Flat assumes no entries during news windows; trades entering within windows are excluded.


## B. Extended research view — symmetric ±15 min, High-impact, all metrics

---

## News Policy Impact

### Portfolio Impact

| Policy | Trades | Net PnL | PF | Win % | Max DD |
|--------|--------|---------|-----|-------|--------|
| Baseline | 1214 | $1,337.60 | 1.22 | 35.1% | $354.05 |
| No-Entry | 1203 | $1,342.26 | 1.23 | 35.0% | $354.05 |
| Go-Flat | 1203 | $1,064.21 | 1.19 | 36.2% | $413.82 |

### Per-Symbol News Sensitivity

| Symbol | Trades (News) | PF (News) | PF (Outside) | Impact |
|--------|--------------|-----------|--------------|--------|
| NAS100 | 305 | 4.83 | 0.56 | Helps |

### News vs Non-News Performance (Aggregate)

| Segment | Trades | Net PnL | PF | Avg R |
|---------|--------|---------|-----|-------|
| News Window | 305 | $3,545.37 | 4.83 | +0.287 |
| Outside | 909 | $-2,207.77 | 0.56 | -0.073 |

- News PF: 4.83 vs Outside PF: 0.56
- Most affected: NAS100 (helps)

> Note: Go-Flat assumes no entries during news windows; trades entering within windows are excluded.

---

### Extended News Research

_Pre-window: 15min · Post-window: 15min · Impact filter: High_

### News Pre vs Post-Event Split

| Bucket | Trades | Net PnL | PF | Avg R |
|--------|--------|---------|-----|-------|
| Pre-event only | 2 | $25.94 | 5.07 | +0.655 |
| Post-event only | 8 | $26.77 | 2.67 | +0.072 |
| Overlap (straddles event) | 295 | $3,492.66 | 4.86 | +0.290 |
| Outside (no news) | 909 | $-2,207.77 | 0.56 | -0.073 |

### Per-Impact Breakdown

| Impact Tag | Trades | Net PnL | PF | Expectancy |
|------------|--------|---------|-----|------------|
| High | 305 | $3,545.37 | 4.83 | $11.62 |

### Per-Currency Breakdown

| Currency Tag | Trades | Net PnL | PF | Expectancy |
|--------------|--------|---------|-----|------------|
| USD | 305 | $3,545.37 | 4.83 | $11.62 |

### News-Subset Robustness Metrics

| Metric | News Subset |
|--------|-------------|
| Trades | 305 |
| Net PnL | $3,545.37 |
| PF | 4.83 |
| Top-5 Concentration | 17.9% of news Net PnL |
| PF after top-5% wins removed | 3.73 |
| Longest Flat Period (news subset) | 97 days |
| Edge Ratio (news, MFE/MAE) | 3.90 |

**News-Subset Yearwise**

| Year | Trades | Net PnL | PF |
|------|--------|---------|-----|
| 2024 | 116 | $1,179.70 | 5.38 |
| 2025 | 148 | $1,689.98 | 4.32 |
| 2026 | 41 | $675.69 | 5.57 |


## C. Asymmetric window — 30 min pre, 90 min post (Architecture A1 substrate)

---

## News Policy Impact

### Portfolio Impact

| Policy | Trades | Net PnL | PF | Win % | Max DD |
|--------|--------|---------|-----|-------|--------|
| Baseline | 1214 | $1,337.60 | 1.22 | 35.1% | $354.05 |
| No-Entry | 1179 | $1,473.35 | 1.26 | 35.5% | $354.05 |
| Go-Flat | 1179 | $1,155.77 | 1.21 | 36.5% | $416.39 |

### Per-Symbol News Sensitivity

| Symbol | Trades (News) | PF (News) | PF (Outside) | Impact |
|--------|--------------|-----------|--------------|--------|
| NAS100 | 318 | 4.35 | 0.58 | Helps |

### News vs Non-News Performance (Aggregate)

| Segment | Trades | Net PnL | PF | Avg R |
|---------|--------|---------|-----|-------|
| News Window | 318 | $3,443.39 | 4.35 | +0.267 |
| Outside | 896 | $-2,105.79 | 0.58 | -0.071 |

- News PF: 4.35 vs Outside PF: 0.58
- Most affected: NAS100 (helps)

> Note: Go-Flat assumes no entries during news windows; trades entering within windows are excluded.

---

### Extended News Research

_Pre-window: 30min · Post-window: 90min · Impact filter: High_

### News Pre vs Post-Event Split

| Bucket | Trades | Net PnL | PF | Avg R |
|--------|--------|---------|-----|-------|
| Pre-event only | 3 | $15.88 | 1.97 | +0.317 |
| Post-event only | 20 | $-65.15 | 0.40 | -0.087 |
| Overlap (straddles event) | 295 | $3,492.66 | 4.86 | +0.290 |
| Outside (no news) | 896 | $-2,105.79 | 0.58 | -0.071 |

### Per-Impact Breakdown

| Impact Tag | Trades | Net PnL | PF | Expectancy |
|------------|--------|---------|-----|------------|
| High | 318 | $3,443.39 | 4.35 | $10.83 |

### Per-Currency Breakdown

| Currency Tag | Trades | Net PnL | PF | Expectancy |
|--------------|--------|---------|-----|------------|
| USD | 318 | $3,443.39 | 4.35 | $10.83 |

### News-Subset Robustness Metrics

| Metric | News Subset |
|--------|-------------|
| Trades | 318 |
| Net PnL | $3,443.39 |
| PF | 4.35 |
| Top-5 Concentration | 18.4% of news Net PnL |
| PF after top-5% wins removed | 3.36 |
| Longest Flat Period (news subset) | 97 days |
| Edge Ratio (news, MFE/MAE) | 3.69 |

**News-Subset Yearwise**

| Year | Trades | Net PnL | PF |
|------|--------|---------|-----|
| 2024 | 121 | $1,161.39 | 5.03 |
| 2025 | 156 | $1,606.31 | 3.71 |
| 2026 | 41 | $675.69 | 5.57 |


## D. Impact sweep — High vs High+Medium vs Medium

---

## News Policy Impact

### Portfolio Impact

| Policy | Trades | Net PnL | PF | Win % | Max DD |
|--------|--------|---------|-----|-------|--------|
| Baseline | 1214 | $1,337.60 | 1.22 | 35.1% | $354.05 |
| No-Entry | 1203 | $1,342.26 | 1.23 | 35.0% | $354.05 |
| Go-Flat | 1203 | $1,064.21 | 1.19 | 36.2% | $413.82 |

### Per-Symbol News Sensitivity

| Symbol | Trades (News) | PF (News) | PF (Outside) | Impact |
|--------|--------------|-----------|--------------|--------|
| NAS100 | 305 | 4.83 | 0.56 | Helps |

### News vs Non-News Performance (Aggregate)

| Segment | Trades | Net PnL | PF | Avg R |
|---------|--------|---------|-----|-------|
| News Window | 305 | $3,545.37 | 4.83 | +0.287 |
| Outside | 909 | $-2,207.77 | 0.56 | -0.073 |

- News PF: 4.83 vs Outside PF: 0.56
- Most affected: NAS100 (helps)

> Note: Go-Flat assumes no entries during news windows; trades entering within windows are excluded.

### Impact Sweep — News vs Outside by Filter

| Impact Filter | News Trades | News PF | Outside Trades | Outside PF |
|---------------|-------------|---------|----------------|------------|
| High | 305 | 4.83 | 909 | 0.56 |
| High+Medium | 406 | 4.11 | 808 | 0.42 |
| Medium | 282 | 4.98 | 932 | 0.59 |
