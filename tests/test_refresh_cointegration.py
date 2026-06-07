"""Tests for tools/refresh_cointegration.py -- identity-preserving cointegration
refresh entrypoint: window-mode current|recorded, cointegration-only scope,
identity preservation (no __E### / name change), and the debt-marked rerun-auth
reuse. Screener + ledger are mocked (no DB)."""
import argparse
import textwrap

import pytest
import yaml

from tools import refresh_cointegration as rc

_DID = "90_PORT_CADJPYUSDCHF_15M_COINTREV_V3_L30_GP_ZCRS__E260312"

_COINT = textwrap.dedent(f"""\
    test:
      name: {_DID}
      family: PORT
      strategy: {_DID}
      version: 1
      signal_version: 1
      broker: OctaFx
      timeframe: 15m
      start_date: '2026-03-12'
      end_date: '2026-06-04'
      research_mode: true
    symbols:
      - CADJPY
      - USDCHF
    basket:
      basket_id: CADJPYUSDCHF
      legs:
        - symbol: CADJPY
          lot: 0.01
          direction: long
        - symbol: USDCHF
          lot: 0.01
          direction: short
      cointegration_join:
        lookback_days: 252
      recycle_rule:
        name: pine_ratio_zrev_v1_zcross
        version: 1
""")

_NON_COINT = textwrap.dedent("""\
    test:
      name: 15_MR_FX_1H_PINBAR_S01_V1_P00
      family: MR
      strategy: 15_MR_FX_1H_PINBAR_S01_V1_P00
      start_date: '2024-01-02'
      end_date: '2026-03-20'
    symbols:
      - USDJPY
    basket: {}
""")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    droot = tmp_path / "backtest_directives"
    inbox, completed = droot / "INBOX", droot / "completed"
    inbox.mkdir(parents=True)
    completed.mkdir(parents=True)
    monkeypatch.setattr(rc, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rc, "DIRECTIVES_ROOT", droot)
    monkeypatch.setattr(rc, "INBOX_DIR", inbox)
    monkeypatch.setattr(rc, "_SEARCH_DIRS", (inbox, completed))
    monkeypatch.setattr(rc, "_prior_run_id", lambda did: "PRIORRUN01")
    (completed / f"{_DID}.txt").write_text(_COINT, encoding="utf-8")
    return {"inbox": inbox, "completed": completed}


def test_is_cointegration_detection():
    assert rc._is_cointegration(yaml.safe_load(_COINT)) is True
    assert rc._is_cointegration(yaml.safe_load(_NON_COINT)) is False


def _dry_args(window_mode="current", category="ENGINE"):
    return argparse.Namespace(
        directive_id=_DID, category=category,
        reason="capture broker_spec provenance for promotion",
        window_mode=window_mode, dry_run=True)


def test_recorded_mode_keeps_window_and_identity(sandbox):
    assert rc.cmd_refresh(_dry_args(window_mode="recorded")) == 0
    data = yaml.safe_load(_COINT)
    out = rc._build_refresh_directive(data, _DID, "ENGINE", "x" * 30, "recorded", "PRIORRUN01")
    assert out["test"]["start_date"] == "2026-03-12"
    assert out["test"]["end_date"] == "2026-06-04"          # unchanged
    assert out["test"]["rerun_of"] == "PRIORRUN01"
    assert out["test"]["repeat_override_reason"].startswith("[COINT-REFRESH:ENGINE@")
    assert "mode=recorded" in out["test"]["repeat_override_reason"]
    assert len(out["test"]["repeat_override_reason"]) >= 50
    # identity preserved -- no __E### rotation
    assert out["test"]["name"] == _DID
    assert out["test"]["strategy"] == _DID


def test_current_mode_rederives_window_only(sandbox, monkeypatch):
    monkeypatch.setattr(rc, "_current_span", lambda pa, pb, lb: ("2026-03-12", "2026-06-05"))
    data = yaml.safe_load(_COINT)
    out = rc._build_refresh_directive(data, _DID, "DATA_FRESH", "extend to current span", "current", "PRIORRUN01")
    assert out["test"]["end_date"] == "2026-06-05"          # re-derived to current
    assert "mode=current" in out["test"]["repeat_override_reason"]
    assert out["test"]["name"] == _DID                      # identity unchanged despite window change


def test_refuses_non_cointegration_directive(sandbox):
    (sandbox["completed"] / "15_MR_FX_1H_PINBAR_S01_V1_P00.txt").write_text(_NON_COINT, encoding="utf-8")
    args = argparse.Namespace(
        directive_id="15_MR_FX_1H_PINBAR_S01_V1_P00", category="ENGINE",
        reason="should be refused -- not a cointegration directive",
        window_mode="recorded", dry_run=True)
    assert rc.cmd_refresh(args) == 1


def test_dry_run_writes_nothing(sandbox):
    rc.cmd_refresh(_dry_args(window_mode="recorded"))
    assert not any(sandbox["inbox"].iterdir())
