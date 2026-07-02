"""Tests for tools/rerun_backtest.py prepare subcommand.

Two failure modes hit 2026-05-24 when re-running basket directives:

  1. signal_version written at the YAML root collided with test.signal_version
     at the test->root mirror in pipeline_utils (KEY COLLISION). Also tripped
     canonicalization (UNKNOWN_STRUCTURE).
  2. Same-stem reruns refused by verify_directive_uniqueness_guard
     (run_pipeline.py:483) because directive_id was already in the registry.

The fix (Option B) is symmetric for basket + non-basket: always bump
test.signal_version, always rotate the __E### suffix on filename + test.name.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import pytest
import yaml

from tools import rerun_backtest


# Source directive shapes — match the conventions in backtest_directives/completed/.

_NON_BASKET_DIRECTIVE = textwrap.dedent("""\
    test:
      name: {name}
      family: MR
      strategy: {strategy}
      version: 1
      signal_version: 1
      broker: OctaFx
      timeframe: 1h
      start_date: '2024-01-02'
      end_date: '2026-03-20'
      research_mode: true
      description: 'Non-basket fixture'

    symbols:
      - USDJPY

    indicators:
      - indicators.volatility.atr

    execution_rules:
      pyramiding: false
      entry_when_flat_only: true
      reset_on_exit: false
      entry_logic:
        type: pinbar
      exit_logic:
        type: time_exit
        time_exit_bars: 10
      stop_loss:
        type: atr_multiple
        atr_multiplier: 2.0

    order_placement:
      type: market
      execution_timing: next_bar_open

    trade_management:
      direction: both
      reentry:
        allowed: true
      session_reset: utc_day
""")


_BASKET_DIRECTIVE = textwrap.dedent("""\
    test:
      name: {name}
      family: PORT
      strategy: {strategy}
      version: 1
      signal_version: 1
      broker: OctaFx
      timeframe: 1d
      start_date: '2017-01-01'
      end_date: '2026-05-22'
      research_mode: true
      description: 'Basket fixture'

    symbols:
      - CHFJPY
      - UK100

    indicators:
      - indicators.volatility.atr

    execution_rules:
      pyramiding: false
      entry_when_flat_only: true
      reset_on_exit: false
      entry_logic:
        type: pine_zrev_reversal_proposal
      exit_logic:
        type: basket_recycle_rule
      stop_loss:
        type: atr_multiple
        atr_multiplier: 100000.0

    order_placement:
      type: market
      execution_timing: next_bar_open

    trade_management:
      direction: basket_mixed
      reentry:
        allowed: true
      session_reset: none

    position_management:
      lots: 0.01

    basket:
      basket_id: CHFJPYUK100
      legs:
        - symbol: CHFJPY
          lot: 0.01
          direction: long
        - symbol: UK100
          lot: 0.01
          direction: short
      initial_stake_usd: 1000.0
      harvest_threshold_usd: 1000000.0
      recycle_rule:
        name: pine_ratio_zrev_v1
        version: 1
        params:
          n_window: 100
""")


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect rerun_backtest directory globals into tmp_path."""
    directives_root = tmp_path / "backtest_directives"
    inbox = directives_root / "INBOX"
    completed = directives_root / "completed"
    active_backup = directives_root / "active_backup"
    active = directives_root / "active"
    archive = directives_root / "archive"
    audit_log = tmp_path / "outputs" / "logs" / "rerun_audit.jsonl"

    for d in (inbox, completed, active_backup, active, archive, audit_log.parent):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(rerun_backtest, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rerun_backtest, "DIRECTIVES_ROOT", directives_root)
    monkeypatch.setattr(rerun_backtest, "INBOX_DIR", inbox)
    monkeypatch.setattr(rerun_backtest, "_SEARCH_DIRS",
                        (completed, active_backup, active, archive))
    monkeypatch.setattr(rerun_backtest, "AUDIT_LOG_PATH", audit_log)
    # Isolate from the real ledger: by default these tests exercise the
    # mtime-scan fallback. The resolve_baseline-first path (F1) and the
    # basket-sheet path (F1b) both query the live ledger.db, so they are
    # neutralized here and covered explicitly in their own tests (which
    # re-patch _resolve_source_via_baseline / _query_basket_sheets_current).
    monkeypatch.setattr(rerun_backtest, "_resolve_source_via_baseline",
                        lambda handle: None)
    monkeypatch.setattr(rerun_backtest, "_query_basket_sheets_current",
                        lambda handle: [])

    return {
        "root": tmp_path,
        "directives_root": directives_root,
        "inbox": inbox,
        "completed": completed,
        "active_backup": active_backup,
        "active": active,
        "archive": archive,
    }


def _seed(dir_: Path, name: str, body: str) -> Path:
    p = dir_ / f"{name}.txt"
    p.write_text(body, encoding="utf-8")
    return p


def _prepare(target: str, *, category: str, reason: str,
             end_date: str | None = None, dry_run: bool = False,
             force: bool = False) -> int:
    return rerun_backtest.cmd_prepare(argparse.Namespace(
        target=target,
        category=category,
        reason=reason,
        end_date=end_date,
        dry_run=dry_run,
        force=force,
    ))


# ── Suffix helpers ─────────────────────────────────────────────────────────

def test_strip_e_suffix_removes_trailing_e_block():
    assert rerun_backtest._strip_e_suffix("90_PORT_X__E002") == "90_PORT_X"
    assert rerun_backtest._strip_e_suffix("90_PORT_X") == "90_PORT_X"
    # 2- and 4-digit forms are NOT recognized — only __E### (3 digits).
    assert rerun_backtest._strip_e_suffix("90_PORT_X__E12") == "90_PORT_X__E12"
    assert rerun_backtest._strip_e_suffix("90_PORT_X__E1234") == "90_PORT_X__E1234"


def test_next_e_index_starts_at_one_when_only_base_exists(sandbox):
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))
    assert rerun_backtest._next_e_index(base) == 1


def test_next_e_index_skips_used_suffixes(sandbox):
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))
    _seed(sandbox["completed"], f"{base}__E001", _NON_BASKET_DIRECTIVE.format(
        name=f"{base}__E001", strategy=base))
    _seed(sandbox["completed"], f"{base}__E002", _NON_BASKET_DIRECTIVE.format(
        name=f"{base}__E002", strategy=base))
    assert rerun_backtest._next_e_index(base) == 3


def test_next_e_index_fills_gap(sandbox):
    """Gaps in the E sequence are filled — the next index is the smallest free."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))
    _seed(sandbox["completed"], f"{base}__E003", _NON_BASKET_DIRECTIVE.format(
        name=f"{base}__E003", strategy=base))
    assert rerun_backtest._next_e_index(base) == 1


def test_next_e_index_scans_inbox_too(sandbox):
    """A pending rerun in INBOX must be respected when picking the next suffix."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))
    _seed(sandbox["inbox"], f"{base}__E001", _NON_BASKET_DIRECTIVE.format(
        name=f"{base}__E001", strategy=base))
    assert rerun_backtest._next_e_index(base) == 2


def test_next_e_index_ignores_unrelated_prefix_collisions(sandbox):
    """A different strategy that shares a prefix must not bleed into the count."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    sibling = f"{base}_NOT_THIS_ONE"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))
    _seed(sandbox["completed"], sibling, _NON_BASKET_DIRECTIVE.format(name=sibling, strategy=sibling))
    _seed(sandbox["completed"], f"{sibling}__E001", _NON_BASKET_DIRECTIVE.format(
        name=f"{sibling}__E001", strategy=sibling))
    # sibling's __E001 is irrelevant to base's count.
    assert rerun_backtest._next_e_index(base) == 1


# ── canonical base stem (per-symbol ledger suffix) ─────────────────────────

_PER_SYMBOL_BASE = "69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00"


def test_canonical_base_stem_reduces_per_symbol_and_suffix():
    """The ledger stores per-symbol runs with a trailing _<SYMBOL> and reruns
    add __E### — in either order. Every polluted form must reduce to the base
    stem, which parse_strategy_name accepts with an empty symbol_suffix."""
    from config.asset_classification import parse_strategy_name

    for polluted in (
        _PER_SYMBOL_BASE,                          # already clean
        f"{_PER_SYMBOL_BASE}_SPX500",              # per-symbol suffix
        f"{_PER_SYMBOL_BASE}__E001",               # trailing rerun tag
        f"{_PER_SYMBOL_BASE}__E001_SPX500",        # tag THEN symbol (the 2026-07-02 shape)
        f"{_PER_SYMBOL_BASE}_SPX500__E003",        # symbol THEN tag
        f"{_PER_SYMBOL_BASE}__E001__E002",         # doubled tag
    ):
        got = rerun_backtest._canonical_base_stem(polluted)
        assert got == _PER_SYMBOL_BASE, f"{polluted!r} -> {got!r}"
        p = parse_strategy_name(got)
        assert p is not None and not p.get("symbol_suffix")
        assert p["model"] == "RSIPULL"


def test_canonical_base_stem_is_idempotent():
    """Operator-requested fixed-point invariant (2026-07-02): applying the
    reduction twice equals applying it once. This is the guard that catches
    future suffix explosions (__E001 -> __E001__E002 -> ...)."""
    for name in (
        _PER_SYMBOL_BASE,
        f"{_PER_SYMBOL_BASE}__E001",
        f"{_PER_SYMBOL_BASE}__E001__E002",
        f"{_PER_SYMBOL_BASE}_SPX500",
        f"{_PER_SYMBOL_BASE}__E001_SPX500",
        f"{_PER_SYMBOL_BASE}_SPX500__E003",
        "90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100",       # basket passthrough
        "90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100__E002",  # basket + tag
    ):
        once = rerun_backtest._canonical_base_stem(name)
        twice = rerun_backtest._canonical_base_stem(once)
        assert twice == once, f"not idempotent: {name!r} -> {once!r} -> {twice!r}"


def test_canonical_base_stem_basket_passthrough():
    """Non-conforming basket ids don't parse; the helper falls back to
    stripping a trailing __E### only, leaving the base id otherwise intact."""
    basket = "90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100"
    assert rerun_backtest._canonical_base_stem(basket) == basket
    assert rerun_backtest._canonical_base_stem(f"{basket}__E002") == basket


# ── prepare: non-basket regression ─────────────────────────────────────────

def test_non_basket_signal_rerun(sandbox):
    """SIGNAL category on a non-basket directive bumps test.signal_version
    inside test:, never at root, and rotates the __E### suffix."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))

    rc = _prepare(base, category="SIGNAL",
                  reason="Added new liquidity-sweep filter to the entry logic")
    assert rc == 0

    out = sandbox["inbox"] / f"{base}__E001.txt"
    assert out.exists(), f"expected {out} to exist"
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert "signal_version" not in parsed, \
        f"root-level signal_version must not be written; got {parsed.get('signal_version')!r}"
    assert parsed["test"]["signal_version"] == 2
    assert parsed["test"]["strategy"] == base  # base stem preserved
    assert parsed["test"]["name"] == f"{base}__E001"
    override = parsed["test"]["repeat_override_reason"]
    assert override.startswith("[RERUN:SIGNAL@")
    assert len(override.strip()) >= 50


# ── prepare: basket regression (the 2026-05-24 bug) ────────────────────────

def test_basket_signal_rerun_no_root_collision(sandbox):
    """Regression for 2026-05-24: basket directives have signal_version inside
    test: and a top-level basket: block. The old tool wrote signal_version at
    the root, causing KEY COLLISION at the test->root mirror in pipeline_utils
    and UNKNOWN_STRUCTURE at canonicalization."""
    base = "90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100"
    _seed(sandbox["completed"], base, _BASKET_DIRECTIVE.format(name=base, strategy=base))

    rc = _prepare(base, category="SIGNAL",
                  reason="Fixed leg_direction_flip bug; output sign was inverted on SHORT cycles")
    assert rc == 0

    out = sandbox["inbox"] / f"{base}__E001.txt"
    assert out.exists()
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))

    # Regression: no root-level signal_version.
    assert "signal_version" not in parsed
    # Bumped in test:.
    assert parsed["test"]["signal_version"] == 2
    # basket: block preserved untouched.
    assert "basket" in parsed
    assert parsed["basket"]["basket_id"] == "CHFJPYUK100"
    assert len(parsed["basket"]["legs"]) == 2
    # Suffix rotation.
    assert parsed["test"]["name"] == f"{base}__E001"
    assert parsed["test"]["strategy"] == base


def test_basket_bug_fix_override_lands_in_test_block(sandbox):
    """BUG_FIX bumps signal_version and writes repeat_override_reason inside
    test: (not at root)."""
    base = "90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100"
    _seed(sandbox["completed"], base, _BASKET_DIRECTIVE.format(name=base, strategy=base))

    rc = _prepare(base, category="BUG_FIX",
                  reason="Prior result inverted sign on SHORT cycles; arithmetic confirmed wrong")
    assert rc == 0

    out = sandbox["inbox"] / f"{base}__E001.txt"
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert parsed["test"]["signal_version"] == 2
    assert "repeat_override_reason" in parsed["test"]
    assert "repeat_override_reason" not in parsed
    assert "[RERUN:BUG_FIX@" in parsed["test"]["repeat_override_reason"]


# ── prepare: suffix-rotation behaviors ─────────────────────────────────────

def test_data_fresh_rotates_suffix_without_sv_bump(sandbox):
    """DATA_FRESH does not bump signal_version, but DOES rotate the suffix —
    uniqueness guard at run_pipeline.py:483 fires regardless of category."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))

    rc = _prepare(base, category="DATA_FRESH",
                  reason="More than 6 weeks of new bars available; baseline stale")
    assert rc == 0

    out = sandbox["inbox"] / f"{base}__E001.txt"
    assert out.exists()
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))

    assert parsed["test"]["signal_version"] == 1  # unchanged
    assert "signal_version" not in parsed  # no stray root key
    assert parsed["test"]["name"] == f"{base}__E001"


def test_target_with_suffix_produces_next_e_not_nested(sandbox):
    """If the user passes 'X__E002' as target, the output is 'X__E003.txt',
    NOT 'X__E002__E003.txt' — test.strategy is the base stem."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))
    _seed(sandbox["completed"], f"{base}__E001",
          _NON_BASKET_DIRECTIVE.format(name=f"{base}__E001", strategy=base))
    _seed(sandbox["completed"], f"{base}__E002",
          _NON_BASKET_DIRECTIVE.format(name=f"{base}__E002", strategy=base))

    rc = _prepare(f"{base}__E002", category="SIGNAL",
                  reason="Indicator update for follow-on test, signal logic adjusted")
    assert rc == 0

    out = sandbox["inbox"] / f"{base}__E003.txt"
    assert out.exists(), "expected single-level __E003 suffix, not nested"
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert parsed["test"]["strategy"] == base
    assert parsed["test"]["name"] == f"{base}__E003"


def test_per_symbol_ledger_name_yields_canonical_stem(sandbox):
    """Regression 2026-07-02: master_filter stores per-symbol runs with an
    appended _<SYMBOL>. prepare must anchor test.strategy on the capsule's
    canonical base stem, not the polluted ledger name — otherwise (a) the
    classifier parses an empty model token and cross-matches an unrelated
    family, and (b) rotation doubles the suffix (..._SPX500__E001 fails the
    namespace gate)."""
    from config.asset_classification import parse_strategy_name

    base = "69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00"
    ledger = f"{base}_SPX500"
    # Source directive filed under the per-symbol ledger name, but its
    # test.strategy is the canonical base (how per-symbol capsules are written).
    _seed(sandbox["completed"], ledger,
          _NON_BASKET_DIRECTIVE.format(name=ledger, strategy=base))

    rc = _prepare(ledger, category="SIGNAL",
                  reason="Monetary-repair rerun of the SPX500 per-symbol clone")
    assert rc == 0

    out = sandbox["inbox"] / f"{base}__E001.txt"
    assert out.exists(), (
        f"expected canonical {base}__E001.txt; INBOX has "
        f"{[p.name for p in sandbox['inbox'].iterdir()]}")
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert parsed["test"]["strategy"] == base           # NOT ..._P00_SPX500
    assert parsed["test"]["name"] == f"{base}__E001"     # single suffix, no _SPX500
    # The prepared stem parses with a real model token (fixes phantom SIGNAL).
    p = parse_strategy_name(parsed["test"]["strategy"])
    assert p is not None and p["model"] == "RSIPULL" and not p["symbol_suffix"]


def test_per_symbol_fallback_when_capsule_strategy_absent(sandbox):
    """When the source capsule has no test.strategy (legacy directive), the
    canonical stem is derived from the ledger name by peeling the _<SYMBOL>
    suffix rather than trusting the polluted handle."""
    base = "69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00"
    ledger = f"{base}_SPX500"
    body = _NON_BASKET_DIRECTIVE.format(name=ledger, strategy=base)
    body = "\n".join(
        ln for ln in body.splitlines() if not ln.strip().startswith("strategy:")
    ) + "\n"
    _seed(sandbox["completed"], ledger, body)

    rc = _prepare(ledger, category="DATA_FRESH",
                  reason="Capsule missing test.strategy; stem must come from ledger name")
    assert rc == 0
    out = sandbox["inbox"] / f"{base}__E001.txt"
    assert out.exists()
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert parsed["test"]["strategy"] == base
    assert parsed["test"]["name"] == f"{base}__E001"


def test_prepare_round_trip_stem_is_stable(sandbox):
    """Operator invariant (2026-07-02): feed a prepared rerun directive back
    into prepare — the stem must stay canonical across generations (no suffix
    explosion), while the __E### advances E001 -> E002."""
    base = "69_MR_IDX_1D_RSIPULL_REGFILT_S01_V1_P00"
    ledger = f"{base}_SPX500"
    _seed(sandbox["completed"], ledger,
          _NON_BASKET_DIRECTIVE.format(name=ledger, strategy=base))

    # Gen 1: rerun the per-symbol ledger name.
    assert _prepare(ledger, category="SIGNAL",
                    reason="Gen-1 monetary-repair rerun of SPX500 clone") == 0
    gen1 = sandbox["inbox"] / f"{base}__E001.txt"
    assert gen1.exists()
    g1 = yaml.safe_load(gen1.read_text(encoding="utf-8"))
    assert g1["test"]["strategy"] == base
    assert g1["test"]["name"] == f"{base}__E001"

    # Publish gen1 into completed/ so it is a discoverable source, then rerun
    # ITS name. The stem must remain canonical; the suffix advances to E002.
    (sandbox["completed"] / f"{base}__E001.txt").write_text(
        gen1.read_text(encoding="utf-8"), encoding="utf-8")
    assert _prepare(f"{base}__E001", category="SIGNAL",
                    reason="Gen-2 follow-on rerun; stem must remain canonical") == 0
    gen2 = sandbox["inbox"] / f"{base}__E002.txt"
    assert gen2.exists(), (
        f"expected {base}__E002.txt (stable stem); INBOX has "
        f"{[p.name for p in sandbox['inbox'].iterdir()]}")
    g2 = yaml.safe_load(gen2.read_text(encoding="utf-8"))
    assert g2["test"]["strategy"] == base             # stem stable across gens
    assert g2["test"]["name"] == f"{base}__E002"       # single suffix, advanced


def test_legacy_root_signal_version_defensively_stripped(sandbox):
    """If the source directive has a stray root-level signal_version (from an
    older bad-prepare invocation), the tool strips it and uses test.signal_version
    as the source of truth."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    body = _NON_BASKET_DIRECTIVE.format(name=base, strategy=base)
    body = body.rstrip() + "\n\nsignal_version: 7\n"  # stray root key
    _seed(sandbox["completed"], base, body)

    rc = _prepare(base, category="SIGNAL",
                  reason="Indicator threshold tightened; signal definition altered")
    assert rc == 0

    parsed = yaml.safe_load((sandbox["inbox"] / f"{base}__E001.txt").read_text(encoding="utf-8"))
    assert "signal_version" not in parsed  # root key stripped
    # test.signal_version was 1; bumped to 2. The stray root=7 is ignored when
    # test value exists (only used as fallback when test had no SV at all).
    assert parsed["test"]["signal_version"] == 2


# ── prepare: resolve_baseline source resolution (F1) ───────────────────────

def test_prepare_prefers_resolve_baseline_seed_over_mtime(sandbox, monkeypatch):
    """F1: prepare must clone the resolve_baseline (is_current) seed, not the
    most-recent-mtime file in completed/. The completed/ decoy carries a
    distinct signal_version so we can prove which source was actually used."""
    base = "90_PORT_CHFJPYUK100_1D_COINTREV_V3_L100"
    # Decoy the mtime scan would pick (SV=5 → would bump to 6).
    decoy = _BASKET_DIRECTIVE.format(name=base, strategy=base).replace(
        "signal_version: 1", "signal_version: 5")
    _seed(sandbox["completed"], base, decoy)
    # Authentic is_current seed (e.g. runs/<id>/directive.txt) with SV=1.
    seed_dir = sandbox["root"] / "runs" / "abc123def456abc123def456"
    seed_dir.mkdir(parents=True, exist_ok=True)
    seed_path = seed_dir / "directive.txt"
    seed_path.write_text(_BASKET_DIRECTIVE.format(name=base, strategy=base),
                         encoding="utf-8")

    # Override the fixture's None-stub: pin the resolver to the authentic seed.
    monkeypatch.setattr(
        rerun_backtest, "_resolve_source_via_baseline",
        lambda handle: (seed_path, "abc123def456abc123def456"),
    )

    rc = _prepare(base, category="SIGNAL",
                  reason="Resolver-seed regression — must clone is_current, not mtime")
    assert rc == 0
    parsed = yaml.safe_load(
        (sandbox["inbox"] / f"{base}__E001.txt").read_text(encoding="utf-8"))
    # Came from the resolver seed (SV 1 → bumped to 2), NOT the decoy (5 → 6).
    assert parsed["test"]["signal_version"] == 2
    # The resolved run_id is captured as provenance for a bare-name target.
    assert parsed["test"]["rerun_of"] == "abc123def456abc123def456"
    assert "origin=abc123def456abc123def456" in parsed["test"]["repeat_override_reason"]


def test_prepare_falls_back_to_mtime_when_resolver_returns_none(sandbox):
    """When resolve_baseline can't pin a seed (fixture stub returns None), the
    legacy mtime scan still resolves the source — zero regression."""
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))

    rc = _prepare(base, category="DATA_FRESH",
                  reason="Resolver absent; mtime fallback must still find the directive")
    assert rc == 0
    out = sandbox["inbox"] / f"{base}__E001.txt"
    assert out.exists()
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))
    # No originating run_id (bare-name target, resolver returned None) → breadcrumb absent.
    assert "rerun_of" not in parsed["test"]
    assert "origin=directive-clone" in parsed["test"]["repeat_override_reason"]


# ── prepare: basket-sheet source resolution (F1b) ──────────────────────────

def test_prepare_resolves_basket_via_sheet(sandbox, monkeypatch):
    """F1b: a COINTREV / basket directive (absent from master_filter) resolves
    to its is_current seed through the basket sheets, not the mtime scan. The
    completed/ decoy carries a distinct signal_version to prove the source."""
    base = "90_PORT_GBPAUDUSDCHF_15M_COINTREV_V3_L30_GP_ZCRS_CXN1_Z25"
    # Decoy the mtime scan would pick (SV=9).
    decoy = _BASKET_DIRECTIVE.format(name=base, strategy=base).replace(
        "signal_version: 1", "signal_version: 9")
    _seed(sandbox["completed"], base, decoy)
    # Authentic is_current seed inside the capsule (backtests_path/DIRECTIVE_SOURCE.txt).
    capsule = sandbox["root"] / "backtests" / f"{base}_GBPAUDUSDCHF"
    capsule.mkdir(parents=True, exist_ok=True)
    (capsule / "DIRECTIVE_SOURCE.txt").write_text(
        _BASKET_DIRECTIVE.format(name=base, strategy=base), encoding="utf-8")
    # Basket-sheet lookup returns the is_current row pointing at the capsule.
    monkeypatch.setattr(
        rerun_backtest, "_query_basket_sheets_current",
        lambda handle: [{"run_id": "feeddeadbeef0123feeddead",
                         "directive_id": base,
                         "backtests_path": str(capsule)}],
    )

    rc = _prepare(base, category="ENGINE",
                  reason="Engine-bump rerun of cointegration basket; confirm is_current seed")
    assert rc == 0
    parsed = yaml.safe_load(
        (sandbox["inbox"] / f"{base}__E001.txt").read_text(encoding="utf-8"))
    # From the capsule seed (ENGINE does not bump SV; capsule SV=1), NOT the decoy (9).
    assert parsed["test"]["signal_version"] == 1
    # Provenance captured from the basket-sheet run_id.
    assert parsed["test"]["rerun_of"] == "feeddeadbeef0123feeddead"
    assert "origin=feeddeadbeef0123feeddead" in parsed["test"]["repeat_override_reason"]


def test_resolve_target_basket_run_id_via_sheet(monkeypatch):
    """A basket run_id (absent from master_filter) resolves to its directive_id
    through the basket sheets, instead of raising."""
    class _FakeCursor:
        def fetchone(self):
            return None  # not in master_filter

    class _FakeConn:
        def execute(self, *a, **k):
            return _FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(rerun_backtest, "_connect", lambda: _FakeConn())
    monkeypatch.setattr(
        rerun_backtest, "_query_basket_sheets_current",
        lambda handle: [{"run_id": handle,
                         "directive_id": "90_PORT_GBPAUDUSDCHF_15M_COINTREV_V3_L30"}],
    )

    strat, rid = rerun_backtest._resolve_target("feeddeadbeef0123feeddead")
    assert strat == "90_PORT_GBPAUDUSDCHF_15M_COINTREV_V3_L30"
    assert rid == "feeddeadbeef0123feeddead"


# ── prepare: dry-run ───────────────────────────────────────────────────────

def test_dry_run_writes_nothing(sandbox):
    base = "15_MR_FX_1H_PINBAR_S01_V1_P00"
    _seed(sandbox["completed"], base, _NON_BASKET_DIRECTIVE.format(name=base, strategy=base))

    rc = _prepare(base, category="SIGNAL",
                  reason="Dry-run check — should leave INBOX empty",
                  dry_run=True)
    assert rc == 0
    assert not any(sandbox["inbox"].iterdir()), "INBOX must stay empty in dry-run"


if __name__ == "__main__":
    import subprocess
    import sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
