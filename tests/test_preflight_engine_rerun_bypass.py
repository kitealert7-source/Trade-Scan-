"""Lock the first-exec EXPERIMENT_DISCIPLINE ENGINE-rerun bypass (governance/preflight.py).

CHECK 6.5's first-execution guard normally forces a V2 version bump when strategy.py
mtime is newer than the directive's first recorded run. A *declared* ENGINE / cost-model
revalidation re-run (test.repeat_override_reason carrying the ``[RERUN:ENGINE ...]`` marker
that ``rerun_backtest.py prepare --category ENGINE`` injects) is exempted -- the directive
is byte-identical, only the engine changed; content integrity stays enforced by the
approval marker + CHECK 6.75.

The exemption decision is made by ``_directive_declares_engine_rerun()``. These tests lock
its scoping, which maps directly to the run_preflight outcomes:

    declared ENGINE rerun  -> True   => first-exec guard ALLOWED to pass (no V2 bump)
    fresh research         -> False  => guard fires (ADMISSION_GATE)
    SIGNAL/PARAMETER/
    BUG_FIX/DATA_FRESH     -> False  => still disciplined (DATA_FRESH has its own bypass)

A full run_preflight integration test is intentionally avoided: it is brittle to the
evolving provisioning flow (see the @skip on test_provision_only_integration). Testing the
predicate at its decision point is the robust, maintainable lock.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from governance.preflight import _directive_declares_engine_rerun  # noqa: E402

_DIRECTIVE = """test:
  name: 99_REV_EURUSD_1D_PINBAR_S01_V1_P00
  strategy: 99_REV_EURUSD_1D_PINBAR_S01_V1_P00
  broker: OctaFx
  timeframe: 1d
  start_date: '2024-01-02'
  end_date: '2026-06-24'
{override}symbols:
- EURUSD
indicators:
- indicators.momentum.rsi
"""


def _write(tmp_path, override_line):
    p = tmp_path / "directive.txt"
    p.write_text(_DIRECTIVE.format(override=override_line), encoding="utf-8")
    return p


def _override(category):
    return (f"  repeat_override_reason: '[RERUN:{category}@2026-06-24 "
            f"origin=abc strategy=99_REV_EURUSD_1D_PINBAR_S01_V1_P00] reason text here'\n")


def test_declared_engine_rerun_bypasses(tmp_path):
    # ENGINE rerun -> bypass (first-exec guard ALLOWED, no V2 bump)
    assert _directive_declares_engine_rerun(_write(tmp_path, _override("ENGINE"))) is True


def test_fresh_research_does_not_bypass(tmp_path):
    # No override marker (fresh research) -> guard fires (ADMISSION_GATE)
    assert _directive_declares_engine_rerun(_write(tmp_path, "")) is False


def test_signal_rerun_stays_disciplined(tmp_path):
    # SIGNAL = real code change -> NOT exempt (ADMISSION_GATE)
    assert _directive_declares_engine_rerun(_write(tmp_path, _override("SIGNAL"))) is False


def test_other_categories_do_not_bypass(tmp_path):
    # PARAMETER / BUG_FIX / DATA_FRESH must not trigger the ENGINE-only bypass.
    for cat in ("PARAMETER", "BUG_FIX", "DATA_FRESH"):
        assert _directive_declares_engine_rerun(_write(tmp_path, _override(cat))) is False, cat


def test_missing_or_unparseable_directive_is_failsafe_false(tmp_path):
    # Fail-safe: any read/parse error -> False (enforce the guard, never silently bypass).
    assert _directive_declares_engine_rerun(tmp_path / "does_not_exist.txt") is False
