# Governance & Reproducibility Audit Report

**Mode:** Read-only — no code changes
**Date:** 2026-02-20

---

## Risk Summary Table

| # | Risk | Severity | Impact |
|---|---|---|---|
| 1 | Documentation authority mismatch — `Trade_Scan_invariants.md` referenced but does not exist under that name | **MEDIUM** | Governance hierarchy broken for new contributors |
| 2 | `os.system()` in `governance/preflight.py:83` — silent exit code masking, shell injection surface | **HIGH** | Integrity check can be silently bypassed |
| 3 | Zero dependency management files in repo | **HIGH** | Clean-machine reproducibility impossible |
| 4 | Encoding / mojibake in source files | **LOW** | No mojibake detected in audited files; cosmetic only if introduced |

---

## 1. Documentation Authority Mismatch

### Evidence

**`governance/README.md` lines 8 and 63** reference:

```
Trade_Scan_invariants.md
```

**Actual file on disk:**

```
governance/SOP/trade_scan_invariants_state_gated.md
```

- `Trade_Scan_invariants.md` does **not exist** anywhere in the repository (confirmed via `find_by_name("invariant*")` — zero hits outside `governance/SOP/`).
- The root `README.md` does **not** reference invariants at all (12 lines, no governance links).
- No alias, symlink, or redirect file exists.

### Impact: **MEDIUM**

- A contributor following the governance README would look for `Trade_Scan_invariants.md` and find nothing.
- The actual invariants file (`trade_scan_invariants_state_gated.md`) is discoverable only by browsing `governance/SOP/`.
- No runtime impact — this is a documentation-only mismatch.

### Minimal Correction Proposal

**Option A (preferred):** Update `governance/README.md` lines 8 and 63 to reference the actual filename:

```diff
-  `Trade_Scan_invariants.md`
+  `trade_scan_invariants_state_gated.md`
```

**Option B:** Rename `governance/SOP/trade_scan_invariants_state_gated.md` → `governance/SOP/Trade_Scan_invariants.md` and update any internal cross-references.

Option A is lower-risk (single file change, no rename propagation).

---

## 2. Preflight Uses `os.system()` — Integrity Invocation Audit

### Target

[preflight.py](file:///c:/Users/faraw/Documents/Trade_Scan/governance/preflight.py) — lines 78–89

### Exact Code

```python
if skip_vault_check:
    cmd = f"python {integrity_check} --mode workspace"   # line 79
else:
    cmd = f"python {integrity_check} --mode strict"       # line 81

exit_code = os.system(cmd)                                 # line 83
if exit_code != 0:
    return ("BLOCK_EXECUTION", "Engine integrity check FAILED.", None)
```

### Risk Analysis

| Check | Result |
|---|---|
| Shell injection possible? | **YES** — `integrity_check` is derived from `PROJECT_ROOT / "tools" / "verify_engine_integrity.py"`. If `PROJECT_ROOT` contains spaces or special characters (e.g. `C:\Users\John Doe\...`), the command breaks silently. If a path component contained `;` or `&&`, arbitrary commands could execute. |
| Exit code checked? | **Partially** — `os.system()` returns the raw OS exit status, NOT the process exit code on Windows. On Windows, `os.system()` returns the value from the `system()` C runtime call, which may differ from the subprocess exit code. On POSIX, the return value is a 16-bit waitpid result — `exit_code != 0` works but is not robust. |
| Output captured? | **NO** — stdout/stderr from the integrity check are printed to console but not captured or logged. A failure message is lost if the orchestrator redirects output. |
| Failure logged structurally? | **NO** — only a return tuple `("BLOCK_EXECUTION", ...)` is emitted. No audit log, no structured JSON, no failure detail preserved. |
| Can integrity check be silently bypassed? | **YES** — a concrete scenario: if the path to `integrity_check` contains a space, `os.system()` splits the command at the space, runs a different binary, which succeeds (exit 0), and the integrity check is never actually executed. The pipeline proceeds. |

### Severity: **HIGH**

### Concrete Failure Scenario

```
PROJECT_ROOT = C:\Users\My User\Documents\Trade_Scan
cmd = "python C:\Users\My User\Documents\Trade_Scan\tools\verify_engine_integrity.py --mode workspace"
```

`os.system(cmd)` passes this to the shell. The unquoted space breaks argument parsing. The shell attempts to run `python C:\Users\My` with arguments `User\Documents\...`. This may fail with a non-zero exit code (blocking execution) or may silently succeed if a binary named `My` exists on `PATH` — bypassing the integrity check entirely.

### Minimal Safe Replacement Recommendation

```python
import subprocess

result = subprocess.run(
    [sys.executable, str(integrity_check), "--mode",
     "workspace" if skip_vault_check else "strict"],
    capture_output=True, text=True
)
if result.returncode != 0:
    return (
        "BLOCK_EXECUTION",
        f"Engine integrity check FAILED:\n{result.stderr}",
        None
    )
```

**Why:**

- `subprocess.run([...])` — no shell, no injection, no path-splitting
- `sys.executable` — uses the exact Python interpreter running the pipeline (not relying on `PATH`)
- `capture_output=True` — stderr preserved for structured logging
- `result.returncode` — correct cross-platform exit code

---

## 3. Dependency Management Audit

### File Search Results

| File | Present? |
|---|---|
| `requirements.txt` | ❌ |
| `requirements-dev.txt` | ❌ |
| `pyproject.toml` | ❌ |
| `Pipfile` | ❌ |
| `Pipfile.lock` | ❌ |
| `setup.py` | ❌ |
| `environment.yml` | ❌ |

**Zero dependency management files exist in the repository.**

### External Dependencies Discovered (top-level imports across `tools/`)

| Package | PyPI Name | Used In (count) |
|---|---|---|
| `pandas` | `pandas` | 20+ files |
| `numpy` | `numpy` | 12+ files |
| `yaml` | `PyYAML` | 4 files (`pipeline_utils.py`, `run_stage1.py`, `directive_utils.py`, `fix_broker_specs.py`) |
| `openpyxl` | `openpyxl` | 3 files (`format_excel_artifact.py`, `safe_append_excel.py`, `verify_formatting.py`) |
| `matplotlib` | `matplotlib` | 2 files (`portfolio_evaluator.py`) |

### Are versions pinned anywhere?

**No.** No version constraints exist in any file, comment, or documentation.

### Would a clean machine reproduce runs deterministically?

**No.** Without version pinning:

- `pandas` 2.x vs 1.x has breaking API changes (e.g. `append()` removed)
- `numpy` 2.x changes default dtypes
- `PyYAML` versions differ in `safe_load()` behavior
- Non-deterministic results are possible from version differences alone

### Severity: **HIGH**

### Minimal Stabilization Proposal

**Step 1:** Generate `requirements.txt` from current working environment:

```bash
pip freeze > requirements.txt
```

**Step 2:** Curate to top-level deps only:

```
pandas==2.2.3
numpy==1.26.4
PyYAML==6.0.2
openpyxl==3.1.5
matplotlib==3.9.3
```

**Step 3 (optional):** Add `python_requires` constraint via `pyproject.toml`:

```toml
[project]
requires-python = ">=3.11,<3.13"
```

No lockfile needed for this project scope. A simple `requirements.txt` with pinned versions is sufficient.

---

## 4. Encoding / Mojibake Audit

### Scan Results

| File | Encoding | Mojibake? |
|---|---|---|
| `README.md` | UTF-8 ✅ | None |
| `tools/run_pipeline.py` | UTF-8 ✅ | None |
| `tools/verify_engine_integrity.py` | UTF-8 ✅ | None |
| `governance/preflight.py` | UTF-8 ✅ | None |
| `tools/pipeline_utils.py` | UTF-8 ✅ | None |

### Analysis

- All five audited files are valid UTF-8 with no BOM.
- No mojibake patterns (`â€"`, `â†'`, `â€œ`, `â€‹`, `ï»¿`) detected.
- `pipeline_utils.py` now contains UTF-8 arrow characters (`→`) in comments (added during this session's patches). These are valid UTF-8 but caused a `cp1252` decode error when read without explicit `encoding='utf-8'` on Windows.

### Risk Assessment

- **Source files:** Clean. No mojibake.
- **Emitted artifacts:** JSON output uses `json.dumps()` which handles Unicode correctly. CSV output uses `pandas.to_csv()` which defaults to UTF-8. No artifact contamination risk.
- **Windows console:** The `→` characters in comments could render as `?` in `cp1252` terminals, but this is cosmetic (comments only, not user-facing output).

### Severity: **LOW**

### Minimal Correction Strategy

1. Replace `→` in source comments with ASCII `->` if Windows console rendering matters
2. Add `# -*- coding: utf-8 -*-` headers to files containing non-ASCII (optional, Python 3 defaults to UTF-8)
3. No CI check needed — no active contamination found

---

## Summary of Recommendations

| # | Fix | Effort | Priority |
|---|---|---|---|
| 1 | Update `governance/README.md` to reference actual invariants filename | 1 line | Medium |
| 2 | Replace `os.system()` with `subprocess.run([...])` in `governance/preflight.py` | 5 lines | **High** |
| 3 | Create `requirements.txt` with pinned versions | 1 file | **High** |
| 4 | ASCII-ify `→` in comments (optional) | Cosmetic | Low |

---

**End of audit. No code was modified.**
