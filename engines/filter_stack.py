class FilterStack:
    def __init__(self, signature: dict):
        self.signature = signature or {}

    def allow_trade(self, row) -> bool:
        if not self._check_volatility(row):
            return False
        if not self._check_trend(row):
            return False
        return True

    def _check_volatility(self, row) -> bool:
        cfg = self.signature.get("volatility_filter", {})
        if not cfg.get("enabled", False):
            return True
        return row.get("regime") == cfg.get("required_regime")

    def _check_trend(self, row) -> bool:
        cfg = self.signature.get("trend_filter", {})
        if not cfg.get("enabled", False):
            return True
        return row.get("trend_regime") == cfg.get("required_regime")
