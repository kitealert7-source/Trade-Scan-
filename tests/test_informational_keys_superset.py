"""Guardrail: INFORMATIONAL_KEYS must be a superset of NON_SIGNATURE_KEYS.

Why this test exists
--------------------
Two independent lists classify directive keys as "meta, not behavior":

  * tools/directive_schema.py::NON_SIGNATURE_KEYS
      Keys excluded from the strategy signature hash. Anything identity-,
      audit-, or envelope-shaped lives here.

  * governance/semantic_coverage_checker.py::INFORMATIONAL_KEYS
      Keys excluded from the Stage-0.55 coverage check. Anything that
      strategy.py is NOT expected to reference lives here.

These lists have different authoring histories but the same intent at the
boundary: if a key is non-signature, it is also non-behavioral. The coverage
checker must therefore ignore every key the signature ignores, otherwise
audit/envelope fields (e.g. `repeat_override_reason`) spuriously fail the
coverage gate.

Historical bite
---------------
Phase 1 added `repeat_override_reason` to NON_SIGNATURE_KEYS but the
parallel update to INFORMATIONAL_KEYS was missed. Any directive that
exercised the idea-gate override hard-failed Stage 0.55 with a
SEMANTIC_COVERAGE_FAILURE on the override field itself. This test makes
that class of drift impossible going forward.
"""

from __future__ import annotations

from tools.directive_schema import NON_SIGNATURE_KEYS
from governance.semantic_coverage_checker import INFORMATIONAL_KEYS


def test_informational_keys_is_superset_of_non_signature_keys():
    missing = set(NON_SIGNATURE_KEYS) - set(INFORMATIONAL_KEYS)
    assert not missing, (
        "INFORMATIONAL_KEYS must be a superset of NON_SIGNATURE_KEYS. "
        f"Keys excluded from the signature but still demanded by the "
        f"coverage checker: {sorted(missing)}.\n\n"
        "Fix: add the missing key(s) to INFORMATIONAL_KEYS in "
        "governance/semantic_coverage_checker.py."
    )


if __name__ == "__main__":
    import subprocess
    import sys
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
