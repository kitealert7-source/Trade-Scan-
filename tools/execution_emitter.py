"""
Execution Results Emitter — Stage-1 Implementation (SOP-Aligned)
Governed by: EMITTER_DESIGN_SPEC.md, SOP_OUTPUT, SOP_TESTING
"""

import csv
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional


class EmissionResult(Enum):
    SUCCESS = "SUCCESS"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    WRITE_FAILED = "WRITE_FAILED"
    FOLDER_EXISTS = "FOLDER_EXISTS"


@dataclass
class TradeRecord:
    # strategy_name retained for denormalization: enables standalone CSV interpretation without metadata join
    strategy_name: str
    parent_trade_id: int
    sequence_index: int
    entry_timestamp: str
    exit_timestamp: str
    direction: int
    entry_price: float
    exit_price: float
    net_pnl: float
    bars_held: Optional[int] = None
    atr_entry: Optional[float] = None
    position_units: Optional[float] = None
    notional_usd: Optional[float] = None
    mfe_price: Optional[float] = None
    mae_price: Optional[float] = None
    mfe_r: Optional[float] = None
    mae_r: Optional[float] = None


@dataclass
class StandardMetrics:
    net_pnl_usd: float
    win_rate: float
    profit_factor: float
    trade_count: int


@dataclass
class RiskMetrics:
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    return_dd_ratio: Optional[float] = None


@dataclass
class YearwiseRecord:
    year: int
    net_pnl_usd: float
    trade_count: int
    win_rate: float
    max_drawdown_pct: Optional[float] = None


@dataclass
class GlossaryEntry:
    metric_key: str
    full_name: str
    definition: str
    unit: str


@dataclass
class RunMetadata:
    run_id: str
    strategy_name: str
    symbol: str
    timeframe: str
    date_range_start: str
    date_range_end: str
    execution_timestamp_utc: str
    engine_name: str
    engine_version: str
    directive_hash: str
    engine_hash: str
    data_fingerprint: str
    schema_version: str
    broker: Optional[str] = None
    reference_capital_usd: Optional[float] = None
    position_sizing_basis: Optional[str] = None


REQUIRED_TRADE_FIELDS = [
    "strategy_name",
    "parent_trade_id",
    "sequence_index",
    "entry_timestamp",
    "exit_timestamp",
    "direction",
    "entry_price",
    "exit_price",
    "net_pnl",
]

REQUIRED_METADATA_FIELDS = [
    "run_id",
    "strategy_name",
    "symbol",
    "timeframe",
    "date_range_start",
    "date_range_end",
    "execution_timestamp_utc",
    "engine_name",
    "engine_version",
    "directive_hash",
    "engine_hash",
    "data_fingerprint",
    "schema_version",
]


def _validate_iso8601(timestamp: str) -> bool:
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def _validate_decimal_range(value: float) -> bool:
    return 0.0 <= value <= 1.0


def _validate_trade(trade: TradeRecord) -> bool:
    for field in REQUIRED_TRADE_FIELDS:
        if getattr(trade, field, None) is None:
            return False
    if not isinstance(trade.parent_trade_id, int):
        return False
    if not isinstance(trade.sequence_index, int):
        return False
    if trade.direction not in (1, -1):
        return False
    if not isinstance(trade.entry_price, (int, float)):
        return False
    if not isinstance(trade.exit_price, (int, float)):
        return False
    if not isinstance(trade.net_pnl, (int, float)):
        return False
    if not _validate_iso8601(trade.entry_timestamp):
        return False
    if not _validate_iso8601(trade.exit_timestamp):
        return False
    return True


def _validate_metadata(metadata: RunMetadata) -> bool:
    for field in REQUIRED_METADATA_FIELDS:
        if getattr(metadata, field, None) is None:
            return False
        if getattr(metadata, field) == "":
            return False
    if not _validate_iso8601(metadata.date_range_start):
        return False
    if not _validate_iso8601(metadata.date_range_end):
        return False
    if not _validate_iso8601(metadata.execution_timestamp_utc):
        return False
    return True


def _validate_standard_metrics(metrics: StandardMetrics) -> bool:
    if not isinstance(metrics.net_pnl_usd, (int, float)):
        return False
    if not isinstance(metrics.win_rate, (int, float)):
        return False
    if not _validate_decimal_range(metrics.win_rate):
        return False
    if not isinstance(metrics.profit_factor, (int, float)):
        return False
    if not isinstance(metrics.trade_count, int):
        return False
    return True


def _validate_risk_metrics(metrics: RiskMetrics) -> bool:
    if not isinstance(metrics.max_drawdown_usd, (int, float)):
        return False
    if not isinstance(metrics.max_drawdown_pct, (int, float)):
        return False
    if not _validate_decimal_range(metrics.max_drawdown_pct):
        return False
    return True


def _validate_yearwise_record(record: YearwiseRecord) -> bool:
    if not isinstance(record.year, int):
        return False
    if not isinstance(record.net_pnl_usd, (int, float)):
        return False
    if not isinstance(record.trade_count, int):
        return False
    if not isinstance(record.win_rate, (int, float)):
        return False
    if not _validate_decimal_range(record.win_rate):
        return False
    if record.max_drawdown_pct is not None:
        if not _validate_decimal_range(record.max_drawdown_pct):
            return False
    return True


def _validate_glossary_entry(entry: GlossaryEntry) -> bool:
    if not entry.metric_key or not isinstance(entry.metric_key, str):
        return False
    if not entry.full_name or not isinstance(entry.full_name, str):
        return False
    if not entry.definition or not isinstance(entry.definition, str):
        return False
    if not entry.unit or not isinstance(entry.unit, str):
        return False
    return True


def _validate_inputs(
    trades: List[TradeRecord],
    standard_metrics: StandardMetrics,
    risk_metrics: RiskMetrics,
    yearwise_metrics: List[YearwiseRecord],
    metrics_glossary: List[GlossaryEntry],
    metadata: RunMetadata,
    directive_content: str,
    directive_filename: str,
) -> bool:
    if not trades:
        return False
    if not standard_metrics:
        return False
    if not risk_metrics:
        return False
    if not yearwise_metrics:
        return False
    if not metrics_glossary:
        return False
    if not metadata:
        return False
    if not directive_content or not isinstance(directive_content, str):
        return False
    if not directive_filename or not isinstance(directive_filename, str):
        return False
    # Decimal semantics (0.0-1.0): enforced on percentage fields in table validators.
    if not _validate_metadata(metadata):
        return False
    if not _validate_standard_metrics(standard_metrics):
        return False
    if not _validate_risk_metrics(risk_metrics):
        return False
    for trade in trades:
        if not _validate_trade(trade):
            return False
    for record in yearwise_metrics:
        if not _validate_yearwise_record(record):
            return False
    for entry in metrics_glossary:
        if not _validate_glossary_entry(entry):
            return False
    return True


def _write_tradelevel_csv(trades: List[TradeRecord], filepath: Path) -> None:
    fieldnames = [
        "strategy_name",
        "parent_trade_id",
        "sequence_index",
        "entry_timestamp",
        "exit_timestamp",
        "direction",
        "entry_price",
        "exit_price",
        "net_pnl",
        "bars_held",
        "atr_entry",
        "position_units",
        "notional_usd",
        "mfe_price",
        "mae_price",
        "mfe_r",
        "mae_r",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            row = {
                "strategy_name": trade.strategy_name,
                "parent_trade_id": trade.parent_trade_id,
                "sequence_index": trade.sequence_index,
                "entry_timestamp": trade.entry_timestamp,
                "exit_timestamp": trade.exit_timestamp,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "net_pnl": round(trade.net_pnl, 2),
                "bars_held": trade.bars_held if trade.bars_held is not None else "",
                "atr_entry": round(trade.atr_entry, 4) if trade.atr_entry is not None else "",
                "position_units": round(trade.position_units, 4) if trade.position_units is not None else "",
                "notional_usd": round(trade.notional_usd, 2) if trade.notional_usd is not None else "",
                "mfe_price": round(trade.mfe_price, 4) if trade.mfe_price is not None else "",
                "mae_price": round(trade.mae_price, 4) if trade.mae_price is not None else "",
                "mfe_r": round(trade.mfe_r, 4) if trade.mfe_r is not None else "",
                "mae_r": round(trade.mae_r, 4) if trade.mae_r is not None else "",
            }
            writer.writerow(row)


def _write_standard_csv(metrics: StandardMetrics, filepath: Path) -> None:
    fieldnames = ["net_pnl_usd", "win_rate", "profit_factor", "trade_count"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "net_pnl_usd": round(metrics.net_pnl_usd, 2),
            "win_rate": round(metrics.win_rate, 4),
            "profit_factor": round(metrics.profit_factor, 2),
            "trade_count": metrics.trade_count,
        })


def _write_risk_csv(metrics: RiskMetrics, filepath: Path) -> None:
    fieldnames = ["max_drawdown_usd", "max_drawdown_pct", "sharpe_ratio", "sortino_ratio", "return_dd_ratio"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "max_drawdown_usd": round(metrics.max_drawdown_usd, 2),
            "max_drawdown_pct": round(metrics.max_drawdown_pct, 4),
            "sharpe_ratio": round(metrics.sharpe_ratio, 2) if metrics.sharpe_ratio is not None else "",
            "sortino_ratio": round(metrics.sortino_ratio, 2) if metrics.sortino_ratio is not None else "",
            "return_dd_ratio": round(metrics.return_dd_ratio, 2) if metrics.return_dd_ratio is not None else "",
        })


def _write_yearwise_csv(records: List[YearwiseRecord], filepath: Path) -> None:
    fieldnames = ["year", "net_pnl_usd", "trade_count", "win_rate", "max_drawdown_pct"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "year": record.year,
                "net_pnl_usd": round(record.net_pnl_usd, 2),
                "trade_count": record.trade_count,
                "win_rate": round(record.win_rate, 4),
                "max_drawdown_pct": round(record.max_drawdown_pct, 4) if record.max_drawdown_pct is not None else "",
            })


def _write_glossary_csv(entries: List[GlossaryEntry], filepath: Path) -> None:
    fieldnames = ["metric_key", "full_name", "definition", "unit"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow({
                "metric_key": entry.metric_key,
                "full_name": entry.full_name,
                "definition": entry.definition,
                "unit": entry.unit,
            })


def _write_metadata_json(metadata: RunMetadata, filepath: Path) -> None:
    data = {
        "run_id": metadata.run_id,
        "strategy_name": metadata.strategy_name,
        "symbol": metadata.symbol,
        "timeframe": metadata.timeframe,
        "date_range": {
            "start": metadata.date_range_start,
            "end": metadata.date_range_end,
        },
        "execution_timestamp_utc": metadata.execution_timestamp_utc,
        "engine_name": metadata.engine_name,
        "engine_version": metadata.engine_version,
        "directive_hash": metadata.directive_hash,
        "engine_hash": metadata.engine_hash,
        "data_fingerprint": metadata.data_fingerprint,
        "schema_version": metadata.schema_version,
        "broker": metadata.broker,
        "reference_capital_usd": metadata.reference_capital_usd,
        "position_sizing_basis": metadata.position_sizing_basis,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _write_directive_copy(directive_content: str, filepath: Path) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(directive_content)


def emit_results(
    trades: List[TradeRecord],
    standard_metrics: StandardMetrics,
    risk_metrics: RiskMetrics,
    yearwise_metrics: List[YearwiseRecord],
    metrics_glossary: List[GlossaryEntry],
    metadata: RunMetadata,
    directive_content: str,
    directive_filename: str,
    backtests_root: Path = Path("backtests"),
) -> EmissionResult:
    if not _validate_inputs(
        trades,
        standard_metrics,
        risk_metrics,
        yearwise_metrics,
        metrics_glossary,
        metadata,
        directive_content,
        directive_filename,
    ):
        return EmissionResult.VALIDATION_FAILED

    strategy_folder = backtests_root / metadata.strategy_name

    if strategy_folder.exists():
        return EmissionResult.FOLDER_EXISTS

    staging_id = uuid.uuid4().hex[:8]
    staging_folder = backtests_root / f".staging_{metadata.strategy_name}_{staging_id}"

    try:
        staging_folder.mkdir(parents=True, exist_ok=False)
        execution_dir = staging_folder / "execution"
        metadata_dir = staging_folder / "metadata"
        execution_dir.mkdir()
        metadata_dir.mkdir()

        _write_tradelevel_csv(trades, execution_dir / "results_tradelevel.csv")
        _write_standard_csv(standard_metrics, execution_dir / "results_standard.csv")
        _write_risk_csv(risk_metrics, execution_dir / "results_risk.csv")
        _write_yearwise_csv(yearwise_metrics, execution_dir / "results_yearwise.csv")
        _write_glossary_csv(metrics_glossary, execution_dir / "metrics_glossary.csv")
        _write_metadata_json(metadata, metadata_dir / "run_metadata.json")
        _write_directive_copy(directive_content, staging_folder / directive_filename)

        if strategy_folder.exists():
            shutil.rmtree(staging_folder, ignore_errors=True)
            return EmissionResult.FOLDER_EXISTS

        staging_folder.rename(strategy_folder)

        return EmissionResult.SUCCESS

    except Exception as _exc:
        if staging_folder.exists():
            shutil.rmtree(staging_folder, ignore_errors=True)
        return EmissionResult.WRITE_FAILED
