"""Refresh-awareness of the directive uniqueness guard (cointegration pilot).

`verify_directive_uniqueness_guard` rejects re-running an already-executed
directive_id -- EXCEPT when `refresh=True` (an explicitly-declared,
identity-preserving refresh). Then the uniqueness check is skipped so a new
run_id is produced for the SAME directive identity (no __E### variant). Only
tools/refresh_cointegration.py passes refresh=True, and it first validates the
target is a cointegration directive.
"""
import pytest

from tools.run_pipeline import verify_directive_uniqueness_guard
from tools.orchestration.pipeline_errors import PipelineExecutionError


@pytest.fixture
def registry_with_d1(monkeypatch):
    """Pretend directive 'D1' has already executed (one registry entry)."""
    import tools.run_pipeline as rp
    monkeypatch.setattr(rp, "_load_registry",
                        lambda: {"run_abc": {"directive_id": "D1"}})


def test_guard_rejects_existing_directive(registry_with_d1):
    with pytest.raises(PipelineExecutionError, match="already executed"):
        verify_directive_uniqueness_guard("D1")


def test_guard_refresh_allows_existing_directive(registry_with_d1):
    # refresh=True => declared identity-preserving refresh => no raise.
    assert verify_directive_uniqueness_guard("D1", refresh=True) is None


def test_guard_allows_unseen_directive(registry_with_d1):
    # A directive absent from the registry is fine regardless of refresh.
    assert verify_directive_uniqueness_guard("D2") is None
    assert verify_directive_uniqueness_guard("D2", refresh=True) is None
