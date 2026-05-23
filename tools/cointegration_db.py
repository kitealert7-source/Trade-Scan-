"""cointegration_db.py — Phase 2: parquet → SQLite upsert + enrichment.

Reads coint_1d_latest.parquet, enriches each row with:
  * pvalue_rolling_median_5d — median of last 5 BEFORE-today snapshots
                                for this (pair_a, pair_b, lookback_days)
  * regime — hysteresis-aware classifier (spec §7), overwriting the
            bootstrap regime from parquet

then upserts into the cointegration_daily SQLite table.

Per COINTEGRATION_SCREENER_V1_SPEC.md §3, §5b, §7.

**Architectural rule** (enforced by code structure):
  parquet is the source of truth — base statistics (adf_pvalue,
  adf_statistic, half_life_days, hedge_ratio, current_zscore,
  sample_size, window_*) come from parquet unchanged.

  SQLite is the reporting sink — the two enrichment columns derive
  from SQLite's OWN prior history, not from re-computing anything.

Flow:
    parquet → DataFrame → enrich-per-row using SQLite history queries
            → upsert into cointegration_daily

API (mirrors tools/ledger_db.py):
    connect(db_path) -> sqlite3.Connection
    create_tables(conn)
    upsert_from_parquet(conn, parquet_path)        -> int (rows upserted)
    query_today(conn)                              -> pd.DataFrame
    query_history(conn, pair_a, pair_b, lookback_days, days=90) -> pd.DataFrame
    query_for_classifier(conn, pair_a, pair_b, lookback_days,
                         lookback=5, before_as_of=None)         -> list[float]

CLI:
    python tools/cointegration_db.py --upsert
    python tools/cointegration_db.py --query-today
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from config.path_authority import DATA_ROOT
from tools.cointegration_screen import PARQUET_PATH, SINGLES_PARQUET_PATH


# 2026-05-20 location move: SQLite was originally in
# TradeScan_State/cointegration/ (alongside MPS) but is conceptually a
# derived FX system factor, not pipeline run state. Moved alongside the
# parquet under DATA_ROOT/SYSTEM_FACTORS/FX_COINTEGRATION/ for backtest
# read convenience (one location for all cointegration artifacts,
# matching the FX_CORRELATION_MATRIX precedent).
SQLITE_DB = DATA_ROOT / "SYSTEM_FACTORS" / "FX_COINTEGRATION" / "cointegration.db"
TABLE_NAME = "cointegration_daily"
SINGLES_TABLE_NAME = "singles_daily"
TRIGGERS_TABLE_NAME = "cointegration_triggers"

# Trigger detection floor — any row where regime == 'cointegrated' AND
# |current_zscore| >= TRIGGER_Z_FLOOR is recorded as a screener "trigger
# event" in cointegration_triggers. The floor of 1.5 captures every
# threshold studied by the v2.1 event study ([1.5, 2.0, 2.5, 3.0]); the
# backtest report subsets by higher thresholds at read time.
TRIGGER_Z_FLOOR = 1.5

# Asset-class membership — mirrors the sets in cointegration_excel.py.
# Centralised here so the triggers table can stamp pair_class at write
# time without depending on the Excel module.
_FX_SYMBOLS = frozenset({
    "AUDUSD", "EURUSD", "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY",
    "AUDJPY", "AUDNZD", "CADJPY", "CHFJPY", "EURAUD", "EURGBP", "EURJPY",
    "GBPAUD", "GBPJPY", "GBPNZD", "NZDJPY",
})
_IDX_SYMBOLS = frozenset({
    "SPX500", "NAS100", "US30", "UK100", "FRA40", "ESP35", "EUSTX50",
    "GER40", "JPN225", "AUS200",
})
_CC_SYMBOLS = frozenset({"XAUUSD", "BTCUSD", "ETHUSD"})


def classify_pair(sym_a: str, sym_b: str) -> str:
    """Bucket a pair-pair into FX / IDX / CROSS."""
    a_fx = sym_a in _FX_SYMBOLS
    b_fx = sym_b in _FX_SYMBOLS
    a_idx = sym_a in _IDX_SYMBOLS
    b_idx = sym_b in _IDX_SYMBOLS
    if a_fx and b_fx:
        return "FX"
    if a_idx and b_idx:
        return "IDX"
    return "CROSS"

# Hysteresis classifier constants (spec §7).
P_COINTEGRATED = 0.05
P_BREAKING = 0.10
HYSTERESIS_LOOKBACK = 5         # last N snapshots
HYSTERESIS_MIN_COINT_COUNT = 4  # ≥ this many must agree
ROLLING_MEDIAN_LOOKBACK = 5

# Column order in SQLite (matches spec §5b schema declaration).
# `history_depth` added by spec amendment 2026-05-20 — number of prior
# snapshots actually used for THIS row's classification (0..HYSTERESIS_LOOKBACK).
# Operators must be able to see when a row is bootstrap-classified
# (history_depth < HYSTERESIS_LOOKBACK) vs hysteresis-classified.
DB_COLUMNS = [
    "as_of", "pair_a", "pair_b", "tf", "lookback_days",
    "window_start", "window_end", "sample_size",
    "adf_pvalue", "pvalue_rolling_median_5d", "history_depth", "adf_statistic",
    "half_life_days", "hedge_ratio", "beta_method", "test_method",
    "current_zscore", "regime",
    "data_version", "inserted_at",
]

# Singles table schema. `symbol` may be a direct broker symbol (AUDNZD) or a
# synthetic series tag (RATIO:BTCUSD/ETHUSD) — see tools/cointegration_screen
# .py::run_singles. Mirrors DB_COLUMNS layout minus pair_b / hedge_ratio /
# beta_method (single-series test has no OLS hedge ratio).
SINGLES_DB_COLUMNS = [
    "as_of", "symbol", "tf", "lookback_days",
    "window_start", "window_end", "sample_size",
    "adf_pvalue", "pvalue_rolling_median_5d", "history_depth", "adf_statistic",
    "half_life_days", "test_method",
    "current_zscore", "regime",
    "data_version", "inserted_at",
]


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------


def connect(db_path: Path | str = SQLITE_DB) -> sqlite3.Connection:
    """Open SQLite with WAL mode + Row factory."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    """Idempotent: CREATE IF NOT EXISTS for table + indexes (spec §5b)."""
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            as_of           TEXT    NOT NULL,
            pair_a          TEXT    NOT NULL,
            pair_b          TEXT    NOT NULL,
            tf              TEXT    NOT NULL,
            lookback_days   INTEGER NOT NULL,
            window_start    TEXT    NOT NULL,
            window_end      TEXT    NOT NULL,
            sample_size     INTEGER NOT NULL,
            adf_pvalue      REAL    NOT NULL,
            pvalue_rolling_median_5d REAL,
            history_depth   INTEGER NOT NULL DEFAULT 0,
            adf_statistic   REAL,
            half_life_days  REAL,
            hedge_ratio     REAL    NOT NULL,
            beta_method     TEXT    NOT NULL,
            test_method     TEXT    NOT NULL,
            current_zscore  REAL,
            regime          TEXT    NOT NULL,
            data_version    TEXT    NOT NULL,
            inserted_at     TEXT    NOT NULL,
            PRIMARY KEY (as_of, pair_a, pair_b, tf, lookback_days)
        );
        CREATE INDEX IF NOT EXISTS idx_coint_pair
            ON {TABLE_NAME} (pair_a, pair_b);
        CREATE INDEX IF NOT EXISTS idx_coint_regime
            ON {TABLE_NAME} (as_of, regime);
        CREATE INDEX IF NOT EXISTS idx_coint_history
            ON {TABLE_NAME} (pair_a, pair_b, lookback_days, as_of DESC);

        CREATE TABLE IF NOT EXISTS {SINGLES_TABLE_NAME} (
            as_of           TEXT    NOT NULL,
            symbol          TEXT    NOT NULL,
            tf              TEXT    NOT NULL,
            lookback_days   INTEGER NOT NULL,
            window_start    TEXT,
            window_end      TEXT,
            sample_size     INTEGER NOT NULL,
            adf_pvalue      REAL    NOT NULL,
            pvalue_rolling_median_5d REAL,
            history_depth   INTEGER NOT NULL DEFAULT 0,
            adf_statistic   REAL,
            half_life_days  REAL,
            test_method     TEXT    NOT NULL,
            current_zscore  REAL,
            regime          TEXT    NOT NULL,
            data_version    TEXT    NOT NULL,
            inserted_at     TEXT    NOT NULL,
            PRIMARY KEY (as_of, symbol, tf, lookback_days)
        );
        CREATE INDEX IF NOT EXISTS idx_singles_symbol
            ON {SINGLES_TABLE_NAME} (symbol);
        CREATE INDEX IF NOT EXISTS idx_singles_regime
            ON {SINGLES_TABLE_NAME} (as_of, regime);
        CREATE INDEX IF NOT EXISTS idx_singles_history
            ON {SINGLES_TABLE_NAME} (symbol, lookback_days, as_of DESC);

        -- Trigger ledger (added 2026-05-23) — explicit log of every
        -- screener event where regime == 'cointegrated' AND |z| >= 1.5
        -- (TRIGGER_Z_FLOOR). One row per (as_of, pair, lookback). The
        -- backtest replay tool reads this to enumerate "things the
        -- screener flagged in real time" without having to recompute
        -- from cointegration_daily on every backtest run.
        CREATE TABLE IF NOT EXISTS {TRIGGERS_TABLE_NAME} (
            as_of           TEXT    NOT NULL,
            pair_a          TEXT    NOT NULL,
            pair_b          TEXT    NOT NULL,
            tf              TEXT    NOT NULL,
            lookback_days   INTEGER NOT NULL,
            pair_class      TEXT    NOT NULL,    -- FX / IDX / CROSS
            direction       TEXT    NOT NULL,    -- LONG_SPREAD (z<0) or SHORT_SPREAD (z>0)
            z_at_trigger    REAL    NOT NULL,    -- signed z at trigger time
            z_floor         REAL    NOT NULL,    -- TRIGGER_Z_FLOOR at write time (for audit)
            beta_at_trigger REAL,
            hl_at_trigger   REAL,
            regime_at_trigger TEXT  NOT NULL,
            adf_pvalue_at_trigger REAL NOT NULL,
            inserted_at     TEXT    NOT NULL,
            PRIMARY KEY (as_of, pair_a, pair_b, tf, lookback_days)
        );
        CREATE INDEX IF NOT EXISTS idx_trigger_pair
            ON {TRIGGERS_TABLE_NAME} (pair_a, pair_b);
        CREATE INDEX IF NOT EXISTS idx_trigger_class_date
            ON {TRIGGERS_TABLE_NAME} (pair_class, as_of DESC);
        CREATE INDEX IF NOT EXISTS idx_trigger_z
            ON {TRIGGERS_TABLE_NAME} (as_of, z_at_trigger);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# History queries — used by the enrichment step + by Excel render (Phase 3)
# ---------------------------------------------------------------------------


def query_for_classifier(conn: sqlite3.Connection,
                         pair_a: str, pair_b: str, lookback_days: int,
                         *,
                         lookback: int = HYSTERESIS_LOOKBACK,
                         before_as_of: str | None = None,
                         ) -> list[float]:
    """Return list of `adf_pvalue` values from the last `lookback`
    snapshots STRICTLY BEFORE `before_as_of` for this pair-window.

    Ordered MOST RECENT FIRST. Used both for the hysteresis classifier
    and the rolling-median enrichment.

    `before_as_of` defaults to the maximum as_of in the table
    (i.e. "before today's row" when called during enrichment).
    """
    if before_as_of is None:
        row = conn.execute(
            f"SELECT MAX(as_of) AS m FROM {TABLE_NAME}"
        ).fetchone()
        before_as_of = row["m"] if row and row["m"] else "0000-00-00"

    rows = conn.execute(
        f"""
        SELECT adf_pvalue FROM {TABLE_NAME}
        WHERE pair_a = ? AND pair_b = ? AND lookback_days = ?
              AND as_of < ?
        ORDER BY as_of DESC
        LIMIT ?
        """,
        (pair_a, pair_b, int(lookback_days), before_as_of, int(lookback)),
    ).fetchall()
    return [float(r["adf_pvalue"]) for r in rows]


def query_today(conn: sqlite3.Connection) -> pd.DataFrame:
    """All rows for the most recent as_of in the table."""
    row = conn.execute(
        f"SELECT MAX(as_of) AS m FROM {TABLE_NAME}"
    ).fetchone()
    if not row or not row["m"]:
        return pd.DataFrame(columns=DB_COLUMNS)
    as_of = row["m"]
    return pd.read_sql_query(
        f"SELECT * FROM {TABLE_NAME} WHERE as_of = ? ORDER BY pair_a, pair_b, lookback_days",
        conn, params=(as_of,),
    )


def query_history(conn: sqlite3.Connection,
                  pair_a: str, pair_b: str, lookback_days: int,
                  *, days: int = 90) -> pd.DataFrame:
    """Last `days` snapshots for a specific pair-window, oldest first."""
    return pd.read_sql_query(
        f"""
        SELECT * FROM {TABLE_NAME}
        WHERE pair_a = ? AND pair_b = ? AND lookback_days = ?
        ORDER BY as_of DESC
        LIMIT ?
        """,
        conn,
        params=(pair_a, pair_b, int(lookback_days), int(days)),
    ).sort_values("as_of").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


def classify_regime(current_pvalue: float, prior_pvalues: list[float]) -> str:
    """Hysteresis-aware regime classifier (spec §7).

    `prior_pvalues` = at most HYSTERESIS_LOOKBACK most-recent values
                      strictly BEFORE this snapshot.

    Bootstrap exception: if fewer than HYSTERESIS_LOOKBACK priors,
    classify on current_pvalue alone.
    """
    if len(prior_pvalues) < HYSTERESIS_LOOKBACK:
        # Bootstrap path (insufficient history).
        if current_pvalue < P_COINTEGRATED:
            return "cointegrated"
        if current_pvalue < P_BREAKING:
            return "breaking"
        return "broken"

    coint_prior_count = sum(1 for p in prior_pvalues if p < P_COINTEGRATED)
    above_breaking_prior_count = sum(1 for p in prior_pvalues if p >= P_BREAKING)

    # broken: ≥ 0.10 dominates
    if current_pvalue >= P_BREAKING:
        return "broken"

    # cointegrated: < 0.05 AND ≥ 4 of last 5 priors also < 0.05
    if (current_pvalue < P_COINTEGRATED
            and coint_prior_count >= HYSTERESIS_MIN_COINT_COUNT):
        return "cointegrated"

    # breaking: catches:
    #   * current in [0.05, 0.10)
    #   * current < 0.05 but priors don't agree (last 5 all ≥ 0.10)
    return "breaking"


def compute_rolling_median(prior_pvalues: list[float]) -> float | None:
    """Median of up to ROLLING_MEDIAN_LOOKBACK prior p-values.

    Returns None if no priors (NaN in SQLite). Observability only —
    NOT consumed by the classifier in v1 (spec §14 item 4).
    """
    if not prior_pvalues:
        return None
    sample = prior_pvalues[:ROLLING_MEDIAN_LOOKBACK]
    return float(statistics.median(sample))


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def upsert_from_parquet(conn: sqlite3.Connection,
                        parquet_path: Path | str = PARQUET_PATH) -> int:
    """Read parquet, enrich with history-aware columns, upsert.

    Returns rows upserted. ON CONFLICT REPLACE — re-running for the
    same as_of overwrites the previous insert cleanly.
    """
    parquet_path = Path(parquet_path)
    if not parquet_path.is_file():
        raise FileNotFoundError(f"parquet not found: {parquet_path}")

    df = pd.read_parquet(parquet_path)
    if df.empty:
        return 0

    # Derive as_of from window_end (just the date, since this is a
    # daily screener). Same as_of for all rows in a single snapshot.
    df = df.copy()
    df["window_end_dt"] = pd.to_datetime(df["window_end"], errors="coerce")
    # If window_end is NaT (placeholder row), fall back to generated_at.
    df["window_end_dt"] = df["window_end_dt"].fillna(
        pd.to_datetime(df["generated_at"]))
    df["as_of"] = df["window_end_dt"].dt.strftime("%Y-%m-%d")

    inserted_at = datetime.now(timezone.utc).isoformat()
    rows_to_insert: list[tuple] = []

    for _, r in df.iterrows():
        # Pull the prior history for this pair-window STRICTLY BEFORE
        # this row's as_of. By querying with `before_as_of=as_of` we
        # naturally exclude any prior re-run of TODAY's snapshot.
        prior = query_for_classifier(
            conn,
            r["pair_a"], r["pair_b"], int(r["lookback_days"]),
            lookback=HYSTERESIS_LOOKBACK,
            before_as_of=r["as_of"],
        )

        # Enrich.
        regime_hysteresis = classify_regime(float(r["adf_pvalue"]), prior)
        rolling_median = compute_rolling_median(prior)
        history_depth = len(prior)  # 0..HYSTERESIS_LOOKBACK; <5 = bootstrap

        rows_to_insert.append((
            r["as_of"],
            r["pair_a"], r["pair_b"],
            r["tf"], int(r["lookback_days"]),
            _to_iso_or_null(r["window_start"]),
            _to_iso_or_null(r["window_end"]),
            int(r["sample_size"]),
            float(r["adf_pvalue"]),
            rolling_median,                # may be None on early bars
            history_depth,                 # NEW: bootstrap visibility
            _float_or_none(r["adf_statistic"]),
            _float_or_none(r["half_life_days"]),
            float(r["hedge_ratio"]) if pd.notna(r["hedge_ratio"]) else 0.0,
            r["beta_method"],
            r["test_method"],
            _float_or_none(r["current_zscore"]),
            regime_hysteresis,
            r["data_version"],
            inserted_at,
        ))

    placeholders = ", ".join(["?"] * len(DB_COLUMNS))
    columns = ", ".join(DB_COLUMNS)
    conn.executemany(
        f"INSERT OR REPLACE INTO {TABLE_NAME} ({columns}) VALUES ({placeholders})",
        rows_to_insert,
    )
    conn.commit()

    # Trigger ledger population — runs AFTER the pair-pair upsert above
    # so the rows we just wrote are the source. Idempotent: re-running
    # the same as_of just refreshes the existing trigger rows (same PK).
    _upsert_triggers_from_rows(conn, rows_to_insert)

    return len(rows_to_insert)


# ---------------------------------------------------------------------------
# Trigger ledger
# ---------------------------------------------------------------------------


def _upsert_triggers_from_rows(conn: sqlite3.Connection,
                                 rows: list[tuple]) -> int:
    """Scan a batch of just-upserted cointegration_daily rows for trigger
    events and insert into cointegration_triggers.

    A trigger event = regime == 'cointegrated' AND |current_zscore| >=
    TRIGGER_Z_FLOOR. The signed z determines direction:
        z < 0 → LONG_SPREAD  (spread below mean, expect rise back)
        z > 0 → SHORT_SPREAD (spread above mean, expect fall back)

    Rows come in the same tuple shape as the cointegration_daily upsert,
    in DB_COLUMNS order — see upsert_from_parquet above.
    """
    # Column indices in the rows tuples (matches DB_COLUMNS order)
    IDX_AS_OF       = DB_COLUMNS.index("as_of")
    IDX_PAIR_A      = DB_COLUMNS.index("pair_a")
    IDX_PAIR_B      = DB_COLUMNS.index("pair_b")
    IDX_TF          = DB_COLUMNS.index("tf")
    IDX_LB          = DB_COLUMNS.index("lookback_days")
    IDX_ADF_P       = DB_COLUMNS.index("adf_pvalue")
    IDX_HL          = DB_COLUMNS.index("half_life_days")
    IDX_HEDGE       = DB_COLUMNS.index("hedge_ratio")
    IDX_Z           = DB_COLUMNS.index("current_zscore")
    IDX_REGIME      = DB_COLUMNS.index("regime")
    IDX_INSERTED_AT = DB_COLUMNS.index("inserted_at")

    triggers: list[tuple] = []
    for r in rows:
        regime = r[IDX_REGIME]
        z = r[IDX_Z]
        if regime != "cointegrated":
            continue
        if z is None:
            continue
        if abs(z) < TRIGGER_Z_FLOOR:
            continue
        pa, pb = r[IDX_PAIR_A], r[IDX_PAIR_B]
        triggers.append((
            r[IDX_AS_OF],
            pa, pb,
            r[IDX_TF], r[IDX_LB],
            classify_pair(pa, pb),
            "SHORT_SPREAD" if z > 0 else "LONG_SPREAD",
            float(z),
            float(TRIGGER_Z_FLOOR),
            float(r[IDX_HEDGE]) if r[IDX_HEDGE] is not None else None,
            float(r[IDX_HL]) if r[IDX_HL] is not None else None,
            regime,
            float(r[IDX_ADF_P]),
            r[IDX_INSERTED_AT],
        ))

    if not triggers:
        return 0

    conn.executemany(f"""
        INSERT OR REPLACE INTO {TRIGGERS_TABLE_NAME} (
            as_of, pair_a, pair_b, tf, lookback_days, pair_class,
            direction, z_at_trigger, z_floor, beta_at_trigger,
            hl_at_trigger, regime_at_trigger, adf_pvalue_at_trigger,
            inserted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, triggers)
    conn.commit()
    return len(triggers)


def rebuild_triggers_from_history(conn: sqlite3.Connection) -> int:
    """One-shot rebuild of cointegration_triggers from the full
    cointegration_daily table. Useful after backfilling historical
    as_ofs that pre-date the trigger ledger's introduction.

    Truncates the existing triggers table first to avoid stale rows
    surviving from a previous run with different TRIGGER_Z_FLOOR.
    """
    conn.execute(f"DELETE FROM {TRIGGERS_TABLE_NAME}")
    conn.commit()

    rows = conn.execute(f"""
        SELECT {', '.join(DB_COLUMNS)} FROM {TABLE_NAME}
        WHERE regime = 'cointegrated'
          AND ABS(current_zscore) >= ?
        ORDER BY as_of, pair_a, pair_b, lookback_days
    """, (TRIGGER_Z_FLOOR,)).fetchall()

    # sqlite3.Row → tuple in DB_COLUMNS order
    row_tuples = [tuple(r) for r in rows]
    n = _upsert_triggers_from_rows(conn, row_tuples)
    return n


def _to_iso_or_null(v) -> str | None:
    if pd.isna(v):
        return None
    if isinstance(v, str):
        return v
    return pd.Timestamp(v).isoformat()


def _float_or_none(v) -> float | None:
    if pd.isna(v):
        return None
    return float(v)


# ---------------------------------------------------------------------------
# Singles upsert + queries
# ---------------------------------------------------------------------------


def query_singles_for_classifier(
    conn: sqlite3.Connection, symbol: str, lookback_days: int,
    *, lookback: int = HYSTERESIS_LOOKBACK, before_as_of: str | None = None,
) -> list[float]:
    """Singles analog of query_for_classifier — last N prior p-values."""
    if before_as_of is None:
        row = conn.execute(
            f"SELECT MAX(as_of) AS m FROM {SINGLES_TABLE_NAME}"
        ).fetchone()
        before_as_of = row["m"] if row and row["m"] else "0000-00-00"
    rows = conn.execute(
        f"""
        SELECT adf_pvalue FROM {SINGLES_TABLE_NAME}
        WHERE symbol = ? AND lookback_days = ? AND as_of < ?
        ORDER BY as_of DESC
        LIMIT ?
        """,
        (symbol, int(lookback_days), before_as_of, int(lookback)),
    ).fetchall()
    return [float(r["adf_pvalue"]) for r in rows]


def query_singles_today(conn: sqlite3.Connection) -> pd.DataFrame:
    row = conn.execute(
        f"SELECT MAX(as_of) AS m FROM {SINGLES_TABLE_NAME}"
    ).fetchone()
    if not row or not row["m"]:
        return pd.DataFrame(columns=SINGLES_DB_COLUMNS)
    return pd.read_sql_query(
        f"SELECT * FROM {SINGLES_TABLE_NAME} "
        f"WHERE as_of = ? ORDER BY symbol, lookback_days",
        conn, params=(row["m"],),
    )


def upsert_singles_from_parquet(
    conn: sqlite3.Connection,
    parquet_path: Path | str = SINGLES_PARQUET_PATH,
) -> int:
    """Read singles parquet, enrich with history, upsert. Returns rows count."""
    parquet_path = Path(parquet_path)
    if not parquet_path.is_file():
        raise FileNotFoundError(f"singles parquet not found: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    if df.empty:
        return 0

    df = df.copy()
    df["window_end_dt"] = pd.to_datetime(df["window_end"], errors="coerce")
    df["window_end_dt"] = df["window_end_dt"].fillna(
        pd.to_datetime(df["generated_at"]))
    df["as_of"] = df["window_end_dt"].dt.strftime("%Y-%m-%d")

    inserted_at = datetime.now(timezone.utc).isoformat()
    rows_to_insert: list[tuple] = []
    for _, r in df.iterrows():
        prior = query_singles_for_classifier(
            conn, r["symbol"], int(r["lookback_days"]),
            lookback=HYSTERESIS_LOOKBACK, before_as_of=r["as_of"],
        )
        regime_hysteresis = classify_regime(float(r["adf_pvalue"]), prior)
        rolling_median = compute_rolling_median(prior)
        history_depth = len(prior)
        rows_to_insert.append((
            r["as_of"],
            r["symbol"],
            r["tf"], int(r["lookback_days"]),
            _to_iso_or_null(r["window_start"]),
            _to_iso_or_null(r["window_end"]),
            int(r["sample_size"]),
            float(r["adf_pvalue"]),
            rolling_median,
            history_depth,
            _float_or_none(r["adf_statistic"]),
            _float_or_none(r["half_life_days"]),
            "adf",  # test_method — fixed for singles
            _float_or_none(r["current_zscore"]),
            regime_hysteresis,
            r["data_version"],
            inserted_at,
        ))
    placeholders = ", ".join(["?"] * len(SINGLES_DB_COLUMNS))
    columns = ", ".join(SINGLES_DB_COLUMNS)
    conn.executemany(
        f"INSERT OR REPLACE INTO {SINGLES_TABLE_NAME} ({columns}) VALUES ({placeholders})",
        rows_to_insert,
    )
    conn.commit()
    return len(rows_to_insert)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cointegration screener — Phase 2 parquet → SQLite."
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--upsert", action="store_true",
                   help="Read coint_1d_latest.parquet, enrich, upsert into SQLite.")
    g.add_argument("--query-today", action="store_true",
                   help="Print today's snapshot from SQLite.")
    p.add_argument("--db", type=str, default=str(SQLITE_DB),
                   help=f"SQLite path (default: {SQLITE_DB})")
    p.add_argument("--parquet", type=str, default=str(PARQUET_PATH),
                   help=f"Parquet path (default: {PARQUET_PATH})")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    conn = connect(args.db)
    try:
        create_tables(conn)
        if args.upsert:
            n = upsert_from_parquet(conn, args.parquet)
            print(f"[cointegration_db] upserted {n} pair-pair rows")
            # Singles parquet is optional — if present, upsert it too.
            if Path(SINGLES_PARQUET_PATH).is_file():
                n_s = upsert_singles_from_parquet(conn, SINGLES_PARQUET_PATH)
                print(f"[cointegration_db] upserted {n_s} singles rows")
            # quick regime summary
            df_today = query_today(conn)
            if not df_today.empty:
                counts = df_today.groupby(["lookback_days", "regime"]).size().unstack(fill_value=0)
                print(f"[cointegration_db] today's pair-pair regime counts:\n{counts}")
            df_singles = query_singles_today(conn)
            if not df_singles.empty:
                s_counts = df_singles.groupby(["lookback_days", "regime"]).size().unstack(fill_value=0)
                print(f"[cointegration_db] today's singles regime counts:\n{s_counts}")
        elif args.query_today:
            df = query_today(conn)
            print(df.to_string(index=False))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
