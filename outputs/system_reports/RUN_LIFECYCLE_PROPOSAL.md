# Run Lifecycle & Directory Structure Architecture

**Goal:** Create a directory structure that scales to 10k+ runs while keeping storage minimal, cleanup safe, and the operator workspace lean (≤150 rows).

The core principle: **Separate disposable runs from preserved research assets using explicit physical boundaries and a unified, machine-readable JSON registry. Treat runs as immutable libraries and portfolios as programs that link them.**

---

## Status Update (2026-03-12)

This proposal is **partially implemented**:
- Implemented: run planning + persistent run registry in orchestration (`run_planner.py`, `run_registry.py`).
- Implemented: worker-claim model (`PLANNED -> RUNNING -> COMPLETE/FAILED`) with resume-safe requeue behavior.
- Not fully implemented: global single registry at `runs/run_registry.json` and full directory-tier model (`sandbox/candidate/portfolio`) are still conceptual; current runtime uses directive-scoped registry (`runs/<DIRECTIVE_ID>/run_registry.json`).
- Not implemented: fully decoupled default where core pipeline always stops before portfolio stage.

---

## 1. The Authoritative Ledger: `run_registry.json`

To prevent parsing fragile Excel sheets during system-critical operations like cleanup, **Excel sheets are treated strictly as operator workspace views, not authoritative state.** 

The single source of truth for the lifecycle of every run is a machine-readable JSON registry located at `runs/run_registry.json`.

**Schema Requirements for `run_registry.json`:**
Each entry must store at minimum:
- `run_id`
- `tier` (`sandbox`, `candidate`, `portfolio`)
- Basic metadata (timestamp, directive, asset)

**Example Entry:**
```json
{
  "R042": {
    "tier": "sandbox",
    "timestamp": "2026-03-12T10:00:00Z",
    "directive": "DIR_01",
    "asset": "EURUSD"
  },
  "R055": {
    "tier": "candidate"
  },
  "R081": {
    "tier": "portfolio"
  }
}
```

---

## 2. Core Immutability Rule

To mathematically guarantee portfolio reproducibility, the following rules are strictly enforced natively by the registry architecture:

1. **Run Artifacts are Immutable**: Once a multi-asset directive deposits an individual run into `runs/<run_id>/`, the contents of that directory are locked. They may not be modified.
2. **Run IDs are Never Reused**: A `run_id` represents a globally unique, mathematical execution point in time. It is never recycled for a new test or overwritten with new results. 
   *(Overwriting results or reusing an ID would transparently and invisibly corrupt all portfolios referencing it.)*

---

## 3. Recommended Directory Layout & Decoupled Pipeline

The pipeline is explicitly decoupled: **execution stops completely after generating individual asset runs.** Portfolio evaluation is a separate, explicit step that consumes selected `run_ids`.

```text
project_root/

runs/                         ← ephemeral runs (sandbox)
    R042/
    R055/
    R081/
    run_registry.json         ← AUTHORITATIVE LIFECYCLE LEDGER

candidates/                   ← promoted research runs (protected boundary)
    R055/

strategies/                   ← explicitly generated portfolio snapshots
    P001/
        portfolio_composition.json  ← strictly references `run_ids`

backtests/                    ← operational views (NOT AUTHORITATIVE)
    Strategy_Master_Filter.xlsx     ← UI View generated from registry (capped ~150 rows)
    Strategy_Candidates.xlsx        ← UI View of promoted rows
    Master_Portfolio_Sheet.xlsx     ← UI View of portfolios
```

---

## 4. Startup Reconciliation Sweep (The Integrity Gate)

To guarantee that the filesystem and registry never drift out of sync, a startup reconciliation sweep `reconcile_registry()` executes at the beginning of *every* pipeline start. 

**Reconciliation Rules:**
1. **Unregistered Artifacts (Filesystem > Registry):**  
   If a folder like `runs/R099/` is present but missing from `run_registry.json`, it is auto-healed and marked in the registry with `tier: "sandbox"`.
   *(Why: Catches aborted runs or manual copies and safely schedules them for normal cleanup).*
2. **Missing Artifacts (Registry > Filesystem):**  
   If the registry expects `runs/R021/` but the folder is missing from disk, the registry entry is updated to `"tier": "invalid"`.
   *(Why: Accidental physical deletion is caught immediately without crashing downstream tools unexpectedly).*
3. **Broken Dependency Constraint:**  
   If a portfolio snapshot (`strategies/P001/portfolio_composition.json`) references a `run_id` (e.g., `R044`), but the `run_id` is `"tier": "invalid"` (missing folder), the reconciliation sweep **raises a hard error** and aborts the pipeline startup.
   *(Why: Prevents the pipeline from running on top of a fundamentally corrupted mathematical baseline).*

---

## 5. The Lifecycle Flow (Sandbox → Candidate → Portfolio)

### Phase 1: Generation & The Sandbox
- **Action:** The pipeline runs a multi-asset directive. **It stops after generating individual runs.**
- **Artifacts:** Land in `runs/`. 
- **Registry Update:** New runs are logged as `"tier": "sandbox"` in `run_registry.json`.
- **Operator View:** Displayed in `Strategy_Master_Filter.xlsx`. Operator reviews these rows.

### Phase 2: Programmatic Promotion (The Internal Research Asset)
- **Action:** Manual Excel manipulation (cut/paste) is prohibited to prevent state drift and registry inconsistency. Instead, the operator executes a programmatic command: e.g., `promote_run(run_id)`.
- **Registry Update:** The command updates the master entry in `run_registry.json` to `"tier": "candidate"`. It handles explicitly migrating the folder to `candidates/` (if implemented that way).
- **Operator View:** The Excel UI views are subsequently refreshed from the underlying state of the registry. The promoted row safely moves to `Strategy_Candidates.xlsx` and exits the sandbox.

### Phase 3: Explicit Portfolio Evaluation (Runs as Libraries)
- **Action:** The operator explicitly invokes the portfolio evaluator, passing in a list of `run_ids`.
- **Behavior:** The portfolio snapshot is built in `strategies/P00x/`. **Run artifacts are exactly immutable and are NEVER copied or modified.** The portfolio `portfolio_composition.json` simply references them by ID.
- **Registry Update:** Referenced `run_ids` are mapped to `"tier": "portfolio"` in the registry.

---

## 6. Extremely Safe Cleanup Rule

Because runs are immutable and highly referenced, the cleanup script (`tools/cleanup_reconciler.py`) ignores Excel entirely and relies exclusively on `run_registry.json` and the startup reconciliation sweep.

**Deterministic Safety Rule:**
Delete a `runs/<run_id>/` folder if and only if:
1. `registry[run_id].tier == "sandbox"` 
2. **AND** the `run_id` is not referenced by any active portfolio.

**Boundaries:**
The cleanup script **NEVER** touches the `candidates/` or `strategies/` directories.

---

## 7. Scalability Outlook

By enforcing absolute immutability, programmatic registry updates via `promote_run`, and decoupling operator UIs from definitive storage validity, this architecture scales effortlessly to 10k+ historical runs:
- Unpromoted runs are effortlessly GC'd (Garbage Collected) by reading a simple machine map. 
- A single run (e.g., `R042`) can be efficiently referenced by `Portfolio_A`, `Portfolio_B`, and `Portfolio_C`.
- **Storage cost:** 1 copy. Storage overlap drops to zero. 
- You cannot overwrite `R042` or reuse its ID for a new test because it would corrupt three distinct downstream portfolios.
- If an operator accidentally scrambles the Excel UIs, zero data is lost. The UIs are deterministically rebuilt from the central `run_registry.json`.
