# Backtest date window (convention)

> Reference for [`/hypothesis-testing`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged.

The matched window follows the standard recent range: **single-asset** runs
`[2024-01-01 → first-available-bar (≈ 2024-01-02), latest-available-bar]`
(= `config/backtest_dates.py::resolve_dates(tf, stage="extended")`); **cointegration** stays
span-based — only cointegrated spans with `entry_date ≥ 2024-01-01`, each a separate test (a
fixed 2024→max window is rejected by `window_validity_gate`, which requires containment in a
cointegrated span — cf. [[feedback_test_window_must_match_signal_class]]). Reference and variant
share the identical window. *(Doc convention; tool auto-set is a pending change — see
[`/rerun-backtest`](../../rerun-backtest/SKILL.md) "Backtest date window".)*
