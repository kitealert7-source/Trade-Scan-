"""Phase 4 - new_pass.py --clone-asset tests.

Uses monkeypatch to redirect tools.new_pass module-level directory globals
into a tmp sandbox so no real repo state is touched.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from tools import new_pass


_DIRECTIVE = textwrap.dedent("""\
    test:
      name: {name}
      family: STR
      strategy: {name}
      version: 1
      broker: OctaFx
      timeframe: 1h
      start_date: '2024-01-02'
      end_date: '2026-03-20'
      research_mode: true
      signal_version: 1

    symbols:
      - USDJPY

    indicators:
      - indicators.volatility.atr
      - indicators.structure.choch
""")

_STRATEGY = textwrap.dedent("""\
    # strategy: {name}
    from indicators.volatility.atr import atr
    from indicators.structure.choch import choch

    def check_entry(ctx):
        return None

    # --- STRATEGY SIGNATURE START ---
    STRATEGY_SIGNATURE = {{
        "signal_version": 1,
        "strategy": "{name}"
    }}
    # --- STRATEGY SIGNATURE END ---
""")


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect new_pass directory globals into tmp_path, but KEEP PROJECT_ROOT
    pointing at the real repo so that (a) config.asset_classification resolves
    and (b) the parity check hashes real indicator modules. Synthetic strategies
    here import real `indicators.volatility.atr` / `indicators.structure.choch`
    paths, so hashing the real modules is correct and does not pollute
    sys.modules with a sandbox copy.
    """
    strat_dir = tmp_path / "strategies"
    inbox = tmp_path / "backtest_directives" / "INBOX"
    completed = tmp_path / "backtest_directives" / "completed"
    active_backup = tmp_path / "backtest_directives" / "active_backup"
    sweep_reg = tmp_path / "governance" / "namespace" / "sweep_registry.yaml"
    for d in (strat_dir, inbox, completed, active_backup, sweep_reg.parent):
        d.mkdir(parents=True, exist_ok=True)
    sweep_reg.write_text("families: {}\n", encoding="utf-8")

    # Seed a source strategy (idea 50, FX/USDJPY, CHOCH_v1).
    src_name = "50_STR_FX_1H_CHOCH_S01_V1_P00"
    (strat_dir / src_name).mkdir(parents=True, exist_ok=True)
    (strat_dir / src_name / "strategy.py").write_text(
        _STRATEGY.format(name=src_name), encoding="utf-8"
    )
    (completed / f"{src_name}.txt").write_text(
        _DIRECTIVE.format(name=src_name), encoding="utf-8"
    )

    # Redirect directory globals ONLY — leave PROJECT_ROOT at the real repo.
    monkeypatch.setattr(new_pass, "STRATEGIES_DIR", strat_dir)
    monkeypatch.setattr(new_pass, "INBOX_DIR", inbox)
    monkeypatch.setattr(new_pass, "COMPLETED_DIR", completed)
    monkeypatch.setattr(new_pass, "ACTIVE_BACKUP_DIR", active_backup)
    monkeypatch.setattr(new_pass, "SWEEP_REGISTRY", sweep_reg)

    return {
        "root": new_pass.PROJECT_ROOT,
        "strat_dir": strat_dir,
        "inbox": inbox,
        "completed": completed,
        "src_name": src_name,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_clone_to_btc_creates_new_idea_and_strategy(sandbox):
    new_pass.clone_asset(sandbox["src_name"], "BTCUSD", new_idea="52")

    new_name = "52_STR_BTC_1H_CHOCH_S01_V1_P00"
    new_dir = sandbox["strat_dir"] / new_name
    new_directive = sandbox["inbox"] / f"{new_name}.txt"

    assert new_dir.exists()
    assert (new_dir / "strategy.py").exists()
    assert new_directive.exists()

    # Symbol in the new directive was replaced.
    parsed = yaml.safe_load(new_directive.read_text(encoding="utf-8"))
    assert parsed["symbols"] == ["BTCUSD"]
    # signal_version preserved.
    assert int(parsed["test"]["signal_version"]) == 1
    # Name fields updated.
    assert parsed["test"]["strategy"] == new_name

    # The cloned strategy.py has name replaced.
    code = (new_dir / "strategy.py").read_text(encoding="utf-8")
    assert new_name in code
    assert sandbox["src_name"] not in code


def test_clone_indicator_hash_parity(sandbox):
    new_pass.clone_asset(sandbox["src_name"], "BTCUSD", new_idea="52")

    import re
    from tools.indicator_hasher import aggregate_indicator_hash

    src_code = (sandbox["strat_dir"] / sandbox["src_name"] / "strategy.py").read_text(
        encoding="utf-8"
    )
    new_code = (
        sandbox["strat_dir"] / "52_STR_BTC_1H_CHOCH_S01_V1_P00" / "strategy.py"
    ).read_text(encoding="utf-8")

    ind_re = re.compile(r"from\s+(indicators\.[A-Za-z0-9_.]+)\s+import", re.MULTILINE)
    src_mods = sorted(set(ind_re.findall(src_code)))
    new_mods = sorted(set(ind_re.findall(new_code)))
    assert src_mods == new_mods, (src_mods, new_mods)

    src_hash, _ = aggregate_indicator_hash(src_mods, project_root=sandbox["root"])
    new_hash, _ = aggregate_indicator_hash(new_mods, project_root=sandbox["root"])
    assert src_hash == new_hash


def test_clone_refuses_to_clobber(sandbox):
    new_pass.clone_asset(sandbox["src_name"], "BTCUSD", new_idea="52")
    with pytest.raises(FileExistsError):
        new_pass.clone_asset(sandbox["src_name"], "BTCUSD", new_idea="52")


def test_clone_auto_idea_picks_free_slot(sandbox):
    new_pass.clone_asset(sandbox["src_name"], "BTCUSD")  # no --idea given
    # Source was idea 50 (already occupied); auto picks next free 2-digit id.
    # Source directory populates only 50 as a seeded idea, so expect 51.
    assert (sandbox["strat_dir"] / "51_STR_BTC_1H_CHOCH_S01_V1_P00").exists()


def test_clone_unknown_symbol_raises(sandbox):
    with pytest.raises(RuntimeError, match="Cannot classify symbol"):
        new_pass.clone_asset(sandbox["src_name"], "NOTASYMBOL", new_idea="52")


def test_clone_rejects_bad_idea_format(sandbox):
    with pytest.raises(ValueError):
        new_pass.clone_asset(sandbox["src_name"], "BTCUSD", new_idea="3")   # 1-digit
    with pytest.raises(ValueError):
        new_pass.clone_asset(sandbox["src_name"], "BTCUSD", new_idea="abc")


def test_clone_rejects_bad_source_name(sandbox):
    with pytest.raises(ValueError, match="does not match"):
        new_pass.clone_asset("nonsense_name", "BTCUSD", new_idea="52")


if __name__ == "__main__":
    import subprocess, sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
