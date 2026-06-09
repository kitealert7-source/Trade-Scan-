# Hard time-stop on deployable ZCRS — decision record (2026-06-09)

**Question:** Given the current canonical pipeline, does adding a hard time-stop
improve deployable ZCRS performance?

**Decision: NO. Decision-grade testing demonstrated no benefit on the 252-window
deployable universe.** The `max_bars_in_trade` param is retained default-off for
future research but is NOT adopted.

## Method (canonical, no shortcuts)
- New optional `max_bars_in_trade` param on `PineRatioZRevRule` (force-liquidate
  after N bars in position, `LIQUIDATE_TIMESTOP`, then flat → next ±z_entry cross
  re-enters natively). Default 0 = canonical no-op.
- **140 full `run_pipeline` backtests** = 20 deployable pairs × 7 variants
  (max_bars 0/12/16/20/24/28/32 bars = baseline/3/4/5/6/7/8h), run 16-way parallel.
- **252-window canonical directives** (the deployed config), one source per pair.
- Proper artifacts for every run: `TradeScan_State/backtests/…_MB{N}__…` folders,
  run-registry entries, and **MPS Cointegration rows** — reproducible / promotable.
- Frozen baseline = the re-run **MB0** (max_bars=0), validated to reproduce the
  prior run exactly before the sweep.

## Result — AGGREGATE (median Ret/DD across 20 pairs; net summed)
| stop | hrs | med Ret/DD | sum net% | med win |
|---|---|---|---|---|
| **0 (baseline)** | — | **1.62** | **224.2** | 66.2 |
| 12 | 3h | 1.28 | 186.1 | 62.1 |
| 16 | 4h | 1.17 | 186.2 | 63.5 |
| 20 | 5h | 1.27 | 194.7 | 65.6 |
| 24 | 6h | 1.33 | 216.0 | 65.9 |
| 28 | 7h | 1.40 | 217.5 | 66.0 |
| 32 | 8h | 1.52 | 218.2 | 66.1 |

## Result — PAIRS IMPROVED vs baseline /20
| stop | hrs | Ret/DD > base | net > base |
|---|---|---|---|
| 12 | 3h | 6 | 6 |
| 16 | 4h | 5 | 5 |
| 20 | 5h | 6 | 6 |
| 24 | 6h | 8 | 7 |
| 28 | 7h | 7 | 7 |
| 32 | 8h | 5 | 5 |

## Findings
- **Every** time-stop variant lowered median Ret/DD below the no-stop baseline (1.62);
  the closest (8h, 1.52) helps only by binding least. No peak above baseline.
- Every variant reduced total net return (224% → 186–218%) and win rate.
- **No variant improved a majority of pairs** on Ret/DD — best is 6h at 8/20 (40%).
- Mechanism: the cointegration screen + the zcross exit already manage the risk a
  time-stop targets; a hard stop forces exits at the mean-reversion trough, trading
  away return without a risk-adjusted gain.

## Notes
- A faster engine-direct preview (in-memory, mixed windows) reached the same verdict
  (no robust improvement); this canonical 252-window run is the authoritative record
  and is cleaner (uniformly mildly harmful).
- Authoritative artifacts: MPS Cointegration tab (`_MB{N}` rows) + per-run folders
  `TradeScan_State/backtests/…_MB{N}__…` (results_basket / tradelevel / per_bar) +
  run-registry entries. (Local preview CSV + in-memory harness are not tracked.)
- An earlier per-leg "expectancy cliff" analysis was invalid (evaluated individual
  legs as directional trades; the strategy only trades spreads) and is superseded.
