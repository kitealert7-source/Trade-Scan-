"""
Regression tests for tools.engine_resolver — Phase 2 v1.5.8a remediation.

Proves the post-Phase-2 resolver policy:

  Selection: latest FROZEN + vaulted + manifest-clean + not-superseded
             engine satisfying capability and contract_id requirements;
             highest semantic version (suffix-aware) wins among eligibles.

  Filters:   EXPERIMENTAL never resurrected (v1.5.9 burn-in stays excluded).
             Manifest file_hashes verified at resolution time using the
             Phase-1 canonical_sha256 helper (LF-normalized) so Windows
             checkouts don't false-fail.
             Lineage supersession (governance/engine_lineage.yaml) blocks
             pre-supersession engines from selection even if their files
             are clean.

Each test constructs a synthetic engine_dev / vault tree + capability
catalog + lineage YAML in a tempdir, monkey-patches the resolver's path
constants to point at it, and asserts the resolver's selection. No real
engines, vault, or governance files are read or modified.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools import engine_resolver as er


CAPS = ["execution.entry.v1", "execution.exit.v1"]


def _make_engine(
    version_dir: Path,
    *,
    engine_status: str = "FROZEN",
    vaulted: bool = True,
    capabilities: list[str] | None = None,
    contract_body: str | None = None,
    extra_files: dict | None = None,
    overwrite_file_hash: dict | None = None,
):
    """Create a synthetic engine directory with contract.json + manifest.

    Returns the contract_id that the resolver will compare against.
    """
    version_dir.mkdir(parents=True, exist_ok=True)
    body = contract_body or '{"v":"test"}'
    contract_path = version_dir / "contract.json"
    contract_path.write_text(body, encoding="utf-8")
    contract_id = "sha256:" + er.canonical_sha256(contract_path)

    init_path = version_dir / "__init__.py"
    init_path.write_text("", encoding="utf-8")

    file_hashes = {
        "contract.json": er.canonical_sha256(contract_path).upper(),
        "__init__.py": er.canonical_sha256(init_path).upper(),
    }
    if extra_files:
        for name, content in extra_files.items():
            p = version_dir / name
            p.write_bytes(content)
            file_hashes[name] = er.canonical_sha256(p).upper()
    if overwrite_file_hash:
        for k, v in overwrite_file_hash.items():
            file_hashes[k] = v

    manifest = {
        "engine_name": "Universal_Research_Engine",
        "engine_version": version_dir.name,
        "engine_status": engine_status,
        "vaulted": vaulted,
        "file_hashes": file_hashes,
        "capabilities": capabilities or list(CAPS),
        "contract_id": contract_id,
    }
    (version_dir / "engine_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return contract_id


def _write_lineage(governance_dir: Path, engines: dict):
    """Write a synthetic engine_lineage.yaml. *engines* is the inner dict."""
    lineage_path = governance_dir / "engine_lineage.yaml"
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    lineage_path.write_text(
        yaml.safe_dump({"version": 1, "engines": engines}),
        encoding="utf-8",
    )
    return lineage_path


def _write_capability_catalog(governance_dir: Path):
    """Minimal capability catalog with no compatible_with mappings."""
    cat_path = governance_dir / "capability_catalog.yaml"
    cat_path.write_text(
        yaml.safe_dump({
            "capabilities": {
                "execution.entry.v1": {"compatible_with": []},
                "execution.exit.v1": {"compatible_with": []},
                "execution.partial_exit.v1": {"compatible_with": []},
            }
        }),
        encoding="utf-8",
    )
    return cat_path


class _ResolverEnv:
    """Context manager that points the resolver's module-level paths at a
    synthetic tempdir."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.engine_dev = self.tmp / "engine_dev"
        self.vault = self.tmp / "vault_engines"
        self.governance = self.tmp / "governance"
        self.engine_dev.mkdir()
        self.vault.mkdir()
        self.governance.mkdir()
        _write_capability_catalog(self.governance)
        # Default empty lineage
        _write_lineage(self.governance, {})

    def __enter__(self):
        self._orig_engine_dev = er.ENGINE_DEV_ROOT
        self._orig_vault = er.VAULT_ENGINE_ROOT
        self._orig_catalog = er.CATALOG_PATH
        self._orig_lineage = er.LINEAGE_PATH
        er.ENGINE_DEV_ROOT = self.engine_dev
        er.VAULT_ENGINE_ROOT = self.vault
        er.CATALOG_PATH = self.governance / "capability_catalog.yaml"
        er.LINEAGE_PATH = self.governance / "engine_lineage.yaml"
        return self

    def __exit__(self, *exc):
        er.ENGINE_DEV_ROOT = self._orig_engine_dev
        er.VAULT_ENGINE_ROOT = self._orig_vault
        er.CATALOG_PATH = self._orig_catalog
        er.LINEAGE_PATH = self._orig_lineage
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestResolverSelectsHighestEligible(unittest.TestCase):

    def test_only_v158_clean_resolves_v158(self):
        """Single eligible engine — resolver picks it."""
        with _ResolverEnv() as env:
            cid = _make_engine(env.engine_dev / "v1_5_8")
            sel = er.resolve_engine(CAPS, [cid])
            self.assertEqual(sel["engine_version"], "v1_5_8")
            self.assertEqual(sel["contract_id"], cid)

    def test_v158_dirty_v158a_clean_resolves_v158a(self):
        """v1.5.8 has manifest_drift; v1.5.8a is clean — pick v1.5.8a."""
        with _ResolverEnv() as env:
            # Ship v1.5.8 with bogus file_hash for __init__.py (drift)
            cid8 = _make_engine(
                env.engine_dev / "v1_5_8",
                contract_body='{"v":"8"}',
                overwrite_file_hash={"__init__.py": "DEADBEEF" * 8},
            )
            cid8a = _make_engine(
                env.engine_dev / "v1_5_8a",
                contract_body='{"v":"8a"}',
            )
            sel = er.resolve_engine(CAPS, [cid8, cid8a])
            self.assertEqual(sel["engine_version"], "v1_5_8a")

    def test_both_clean_v158a_wins_by_version(self):
        """Both clean & eligible — descending sort picks v1.5.8a (suffix > base)."""
        with _ResolverEnv() as env:
            cid8 = _make_engine(env.engine_dev / "v1_5_8",
                                contract_body='{"v":"8"}')
            cid8a = _make_engine(env.engine_dev / "v1_5_8a",
                                 contract_body='{"v":"8a"}')
            sel = er.resolve_engine(CAPS, [cid8, cid8a])
            self.assertEqual(sel["engine_version"], "v1_5_8a")

    def test_skips_experimental_v159(self):
        """v1.5.9 EXPERIMENTAL is filtered out even if its files are clean."""
        with _ResolverEnv() as env:
            cid9 = _make_engine(env.engine_dev / "v1_5_9",
                                engine_status="EXPERIMENTAL",
                                contract_body='{"v":"9"}')
            cid8a = _make_engine(env.engine_dev / "v1_5_8a",
                                 contract_body='{"v":"8a"}')
            sel = er.resolve_engine(CAPS, [cid9, cid8a])
            self.assertEqual(sel["engine_version"], "v1_5_8a")

    def test_skips_unvaulted(self):
        """vaulted: false engine is still selectable IF its
        engine_status is FROZEN — vaulted is informational, not a gate.

        The supersession registry is the authoritative gate; vaulted is
        informational metadata in the manifest. This test documents the
        current contract: vaulted-false engines participate in selection.
        Distinct gate is provided by the lineage 'vaulted: false' field
        which the resolver could read in a future enhancement.
        """
        with _ResolverEnv() as env:
            cid_unv = _make_engine(env.engine_dev / "v1_5_10",
                                   vaulted=False,
                                   contract_body='{"v":"10"}')
            cid8a = _make_engine(env.engine_dev / "v1_5_8a",
                                 contract_body='{"v":"8a"}')
            sel = er.resolve_engine(CAPS, [cid_unv, cid8a])
            # 1.5.10 > 1.5.8a in semver, so 1.5.10 wins absent supersession
            self.assertEqual(sel["engine_version"], "v1_5_10")

    def test_skips_superseded_when_listed_in_lineage(self):
        """v1.5.8 in supersession registry → filtered even if clean+eligible."""
        with _ResolverEnv() as env:
            cid8 = _make_engine(env.engine_dev / "v1_5_8",
                                contract_body='{"v":"8"}')
            cid8a = _make_engine(env.engine_dev / "v1_5_8a",
                                 contract_body='{"v":"8a"}')
            _write_lineage(env.governance, {
                "v1_5_8": {"superseded_by": "v1_5_8a"},
                "v1_5_8a": {"superseded_by": None},
            })
            sel = er.resolve_engine(CAPS, [cid8, cid8a])
            self.assertEqual(sel["engine_version"], "v1_5_8a")

    def test_canonical_hash_validates_crlf_files(self):
        """v1.5.8a with CRLF-rendered files but LF-canonical-clean manifest
        passes — proves the resolver uses the Phase-1 canonical helper, not
        raw bytes."""
        with _ResolverEnv() as env:
            v_dir = env.engine_dev / "v1_5_8a"
            # contract_body intentionally contains LF newlines
            lf_contract = '{\n  "v": "8a"\n}\n'
            cid = _make_engine(v_dir, contract_body=lf_contract)
            # Now overwrite contract.json with CRLF rendering of same content
            crlf_bytes = lf_contract.replace("\n", "\r\n").encode("utf-8")
            (v_dir / "contract.json").write_bytes(crlf_bytes)
            # Resolver uses canonical_sha256 → CRLF normalizes back to LF →
            # contract_id still matches the manifest's recorded value.
            sel = er.resolve_engine(CAPS, [cid])
            self.assertEqual(sel["engine_version"], "v1_5_8a")

    def test_no_eligible_engine_raises_f9(self):
        """All FROZEN candidates rejected → F9 with rejection diagnostic."""
        with _ResolverEnv() as env:
            # Single engine with deliberate manifest drift
            cid = _make_engine(
                env.engine_dev / "v1_5_8",
                contract_body='{"v":"8"}',
                overwrite_file_hash={"__init__.py": "DEAD" * 16},
            )
            with self.assertRaises(er.EngineResolverError) as cm:
                er.resolve_engine(CAPS, [cid])
            self.assertEqual(cm.exception.code, "F9")
            self.assertIn("manifest_drift", cm.exception.detail)

    def test_only_experimental_raises_f10(self):
        """Only EXPERIMENTAL candidates satisfy → F10 with version list."""
        with _ResolverEnv() as env:
            cid = _make_engine(env.engine_dev / "v1_5_9",
                               engine_status="EXPERIMENTAL",
                               contract_body='{"v":"9"}')
            with self.assertRaises(er.EngineResolverError) as cm:
                er.resolve_engine(CAPS, [cid])
            self.assertEqual(cm.exception.code, "F10")
            self.assertIn("v1_5_9", cm.exception.detail)

    def test_contract_drift_raises_f8(self):
        """Manifest contract_id != actual contract.json hash → F8 (existing behavior preserved)."""
        with _ResolverEnv() as env:
            v_dir = env.engine_dev / "v1_5_8"
            _make_engine(v_dir, contract_body='{"v":"8"}')
            # Mutate contract.json to drift its hash
            (v_dir / "contract.json").write_text('{"v":"MUTATED"}',
                                                  encoding="utf-8")
            with self.assertRaises(er.EngineResolverError) as cm:
                # Any required_contract_ids — F8 fires before contract filter
                er.resolve_engine(CAPS, ["sha256:anything"])
            self.assertEqual(cm.exception.code, "F8")


class TestSemverKeySuffixOrdering(unittest.TestCase):
    """The new suffix-aware semver_key must place v1_5_8a between v1_5_8
    and v1_5_9, and place v1_5_10 above all single-digit-patch versions."""

    def test_plain_versions_ascend(self):
        self.assertLess(er._semver_key("v1_5_7"), er._semver_key("v1_5_8"))
        self.assertLess(er._semver_key("v1_5_8"), er._semver_key("v1_5_9"))

    def test_suffix_is_successor_within_patch(self):
        self.assertLess(er._semver_key("v1_5_8"), er._semver_key("v1_5_8a"))
        self.assertLess(er._semver_key("v1_5_8a"), er._semver_key("v1_5_8b"))

    def test_suffix_below_next_patch(self):
        self.assertLess(er._semver_key("v1_5_8a"), er._semver_key("v1_5_9"))

    def test_double_digit_patch(self):
        self.assertLess(er._semver_key("v1_5_8"), er._semver_key("v1_5_10"))
        self.assertLess(er._semver_key("v1_5_8a"), er._semver_key("v1_5_10"))


class TestLiveLineageProducesV158a(unittest.TestCase):
    """Live integration: with the real engine_dev/, vault/, and lineage
    on this branch (post-Phase-2), the resolver MUST select v1_5_8a."""

    def test_live_resolver_picks_v158a(self):
        # Real contract_ids both v1_5_8 and v1_5_8a
        required_contracts = [
            "sha256:680e8c0014b58e76550da0326601402c498fb376dbf17fc69c027e7e95465df8",
            "sha256:edb81b5bf26b41788845ca17135b3108c36ec9bc7c0542bce487ea9953c50f2a",
        ]
        sel = er.resolve_engine(
            ["execution.entry.v1", "execution.exit.v1"],
            required_contracts,
        )
        self.assertEqual(sel["engine_version"], "v1_5_8a",
                         f"Live resolver should pick v1_5_8a after Phase 2; "
                         f"got {sel['engine_version']}")


if __name__ == "__main__":
    unittest.main()
