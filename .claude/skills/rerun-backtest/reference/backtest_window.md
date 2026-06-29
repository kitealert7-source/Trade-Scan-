# Backtest date window — rerun convention

> Reference for [`/rerun-backtest`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged. **Note:** the execution-critical *gap-/window-sensitive `--end-date` pinning* warning stays in the main skill's **Common Pitfalls** — it is not reference material.

A rerun runs on the standard recent window, derived from data availability — **not** blindly
from the source directive's original dates:

- **Single-asset:** `start_date` = **2024-01-01**, or the first available bar on/after it (in
  practice **2024-01-02** — 2024-01-01 is a market holiday, no FX bars); `end_date` = the
  **latest available bar** (`min(latest_date)` across the directive's symbols, from
  `data_root/MASTER_DATA/freshness_index.json`). This is exactly what
  `config/backtest_dates.py::resolve_dates(tf, stage="extended")` /
  `governance/preflight.py::resolve_data_range()` already return.
- **Cointegration / basket:** the window is **not** a single 2024→max range — each test is one
  pre-computed cointegrated **span**. Re-run only the spans whose entry falls **within
  [2024-01-01, max]** (drop any with `entry_date < 2024-01-01`); each in-range span stays a
  **separate test** on its own `[entry_date, exit_date]` window. A fixed 2024→max window would
  be **rejected by `window_validity_gate.py`** (the window must be contained in one cointegrated
  span — see [[feedback_test_window_must_match_signal_class]]).

> **Tool support pending — apply by hand for now.** `prepare` today sets `end_date = today` and
> never sets `start_date` (`rerun_backtest.py:474-479`). Auto-setting the single-asset
> `[2024-01-02, max]` window and filtering cointegration spans to the range are **pending tool
> changes** (out of the current skills-only scope). Until they land, set the window per this
> convention when forming / reviewing the rerun directive.
