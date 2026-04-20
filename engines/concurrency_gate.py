# concurrency_gate.py — Portfolio-level open-position cap enforcement
#
# Imported by TS_Execution/src/execution_adapter.py at dispatch time.
# If `concurrency_cap` is not set in portfolio.yaml exec_config, the caller
# skips the gate entirely (cap=None path), so these functions are only reached
# when an explicit integer cap is configured.
#
# API:
#   validate_cap(raw)  → None | int   (raises ValueError on bad config)
#   admit(positions, cap) → bool      (True = allow dispatch)


def validate_cap(raw) -> int | None:
    """Validate and normalise the concurrency_cap exec_config value.

    Args:
        raw: value from exec_config.get("concurrency_cap") — may be None,
             an int, or a misconfigured type.

    Returns:
        None  — unlimited (no cap enforced)
        int≥1 — maximum number of simultaneously open positions allowed

    Raises:
        ValueError — if raw is 0, negative, or a non-integer non-None value.
    """
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(f"concurrency_cap must be a positive integer or null, got {raw!r}")
    if raw < 1:
        raise ValueError(f"concurrency_cap must be >= 1, got {raw}")
    return raw


def admit(open_positions: list, cap: int) -> bool:
    """Return True if opening another position is within the cap.

    Args:
        open_positions: list of MT5 position objects already open for this
                        strategy (filtered by magic number by the caller).
        cap:            maximum allowed open positions (validated int >= 1).

    Returns:
        True  — fewer than `cap` positions open; dispatch is allowed.
        False — at or above cap; caller should skip and log SKIP_CONCURRENCY_CAP.
    """
    return len(open_positions) < cap
