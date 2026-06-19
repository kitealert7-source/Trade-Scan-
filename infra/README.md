# infra/ — version-controlled operational scripts

Canonical, version-controlled copies of host ops scripts that otherwise live
**untracked** in `C:\Users\faraw\Documents\` and are **not** in any repo. Tracking
them here means they survive a disk failure (git history **and** the NAS mirror,
since `Trade_Scan` is repo #1 in the backup set).

## backup_repos.ps1 / run_backup_repos.bat — NAS disaster-recovery backup

**LIVE copy (what actually runs):** `C:\Users\faraw\Documents\backup_repos.ps1`,
launched by the Windows scheduled task **`TradeScan NAS Backup`** every 6h. The copy
here is the **canonical source of truth** — if the two diverge, this one wins; sync
the live copy from here.

**What it does:** robocopy `/MIR` mirror of 7 folders (Trade_Scan, TradeScan_State,
TS_Execution, DATA_INGRESS, Anti_Gravity_DATA_ROOT, DRY_RUN_VAULT, TS_Obsidian_Vault)
to `\\FARAWAYTOURISM\faraway\Trade_Scan_Backup`.

**Hardening folded in (2026-06-19):**
- `/B` backup mode + scheduled task `RunLevel=Highest` → SeBackupPrivilege to read
  past the `Deny INTERACTIVE` ACE on `MASTER_DATA`.
- `/XD … "$SRC\Trade_Scan\data_root"` → do **not** follow the `data_root` junction
  into `Anti_Gravity_DATA_ROOT` (already its own backup entry; was double-copying 7.4GB).
  A global `/XJ` is deliberately avoided — it would also skip TradeScan_State's
  `runs\<id> → sandbox\<id>` junctions and `/MIR` would purge them from the backup.
- `/XF … *.db-shm *.db-wal *.db-journal` → skip live-SQLite lock sidecars (held open by
  the screener / basket regime reads of `cointegration.db`) that caused robocopy
  `ERROR 32` and a false "finished WITH ERRORS".

**Authentication:** relies on a **persistent** Windows credential for the NAS, stored
via `cmdkey /add:FARAWAYTOURISM /user:SANTOSH /pass:<…>`. This MUST be persistent (not
session-scoped) — a session-scoped credential is dropped on reboot, which is exactly
what silently broke the backup for ~24h on 2026-06-18→19 (robocopy `ERROR 1326`).

## Restore procedure (after a disk rebuild)
1. Copy `backup_repos.ps1` + `run_backup_repos.bat` back to `C:\Users\faraw\Documents\`
   **preserving the UTF-8 BOM** (PS 5.1 reads a BOM-less file as Windows-1252).
2. Re-store the persistent NAS credential with `cmdkey` (see above).
3. Re-register the `TradeScan NAS Backup` scheduled task (RunLevel=Highest, every 6h)
   pointing at the live `Documents\backup_repos.ps1`.

## Change discipline
Edit here, then copy to the live `Documents\` path (or vice-versa) — keep them in sync
and keep the BOM. Not a pipeline tool; intentionally **outside** `tools/` so it isn't
subject to the `tools_manifest.json` gate.
