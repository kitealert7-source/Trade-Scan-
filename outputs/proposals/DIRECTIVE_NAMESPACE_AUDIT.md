# Audit: Directive Generation & Namespace Governance

This report audits the directive creation lifecycle and classifies the namespace gate failure modes into auto-fixable and manual intervention categories.

## 1. Directive Generation Audit

Directives are currently generated via three primary channels:

| Channel | Method | Guardrails |
| :--- | :--- | :--- |
| **Manual** | Direct creation in `backtest_directives/active/`. | None (Relies on pre-execution gate). |
| **Scripted (Sweep)** | `generate_sweep_08.py` and similar variant producers. | Templates follow canonical naming. |
| **Migration** | `convert_promoted_directives.py` (via orchestration). | Semantic inference + Registry lookup. |

### Current Generation Weakness
Manual creation often results in "Identity Mismatch" (filename != `test.strategy`) or token typos, while scripted generation is stable but rigid.

---

## 2. Namespace Gate Failures by Type

The `namespace_gate.py` (Stage -0.30) enforces strict pattern matching.

### Category A: Structural Identity
*   **`NAMESPACE_IDENTITY_MISSING`**: Required keys (filename, `test.name`, `test.strategy`) are missing.
*   **`NAMESPACE_IDENTITY_MISMATCH`**: Inconsistency between the filename and internal metadata.

### Category B: Pattern & Normalization
*   **`NAMESPACE_PATTERN_INVALID`**: Regex failure (wrong number of underscores, misplaced parts).
*   **`NAMESPACE_ALIAS_FORBIDDEN`**: Using a mapped alias (e.g., `H1`) instead of the canonical token (`1H`).

### Category C: Semantic & Registry
*   **`NAMESPACE_TOKEN_INVALID`**: Token not found in `token_dictionary.yaml`.
*   **`IDEA_ID_UNREGISTERED`**: The 2-digit Idea ID has no entry in `idea_registry.yaml`.
*   **`IDEA_FAMILY_MISMATCH`**: The Family code in the name contradicts the Idea's registration.
*   **`IDEA_METADATA_MISSING`**: The Idea exists but lacks required Classification/Regime/Role tags.

---

## 3. Classification of Auto-Fixable Failures

Based on current infrastructure capabilities (Canonicalizer + Converter), we can classify failures:

### ✅ HIGH (Auto-Fixable)
*   **Identity Syncing**: Forced alignment of `test.strategy` and `test.name` to the filename.
*   **Alias Normalization**: Automatic replacement of `H1` -> `1H`, `M15` -> `15M` using the dictionary.
*   **Casing Guard**: Forcing tokens to uppercase.
*   **Structure Padding**: Adding missing `V1` or `P00` if the rest of the pattern is intact.

### ⚠️ MEDIUM (Decision Required)
*   **Identity Collision**: When the filename is valid but internal `test.strategy` belongs to another valid (existing) file.
*   **Inferred Family**: If the Family is missing but Indicators clearly point to `MR` or `PA`.

### ❌ LOW (Manual Only)
*   **New Idea Onboarding**: Creating a new ID (e.g., `99`) requires defining its objective.
*   **Registry Corruption**: Fixing mismatched families requires confirming the original intent of the Idea ID.
*   **Missing Core Tokens**: If the Symbol or Timeframe is missing from the name, the script cannot guess the intended data source.
