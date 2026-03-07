"""
infra/finance/finance_thresholds.py — Configurable detection thresholds.

All values are read from environment variables at import time.
No hardcoded business constants.
Defaults are conservative but overridable.
"""
from __future__ import annotations

import os


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Liquidity
# ---------------------------------------------------------------------------

# Minimum available balance before triggering critical liquidity signal
MIN_LIQUIDITY_THRESHOLD: float = _float_env("MIN_LIQUIDITY_THRESHOLD", 500.0)

# ---------------------------------------------------------------------------
# Drop detection
# ---------------------------------------------------------------------------

# Maximum allowed percentage drop within the observation window
MAX_DROP_PERCENT: float = _float_env("MAX_DROP_PERCENT", 30.0)

# Observation window for drop detection (hours)
DROP_WINDOW_HOURS: int = _int_env("DROP_WINDOW_HOURS", 24)

# ---------------------------------------------------------------------------
# Outflow spike detection
# ---------------------------------------------------------------------------

# If total outflow in the snapshot exceeds this multiple of the mean,
# flag it as an outflow spike.
MAX_OUTFLOW_SPIKE: float = _float_env("MAX_OUTFLOW_SPIKE", 3.0)

# Minimum number of recent transactions required to compute spike baseline
OUTFLOW_SPIKE_MIN_SAMPLES: int = _int_env("OUTFLOW_SPIKE_MIN_SAMPLES", 3)


def reload() -> None:
    """
    Re-read environment variables into module-level constants.
    Useful in tests that patch env vars after import.
    """
    global MIN_LIQUIDITY_THRESHOLD, MAX_DROP_PERCENT, DROP_WINDOW_HOURS
    global MAX_OUTFLOW_SPIKE, OUTFLOW_SPIKE_MIN_SAMPLES

    MIN_LIQUIDITY_THRESHOLD  = _float_env("MIN_LIQUIDITY_THRESHOLD", 500.0)
    MAX_DROP_PERCENT         = _float_env("MAX_DROP_PERCENT", 30.0)
    DROP_WINDOW_HOURS        = _int_env("DROP_WINDOW_HOURS", 24)
    MAX_OUTFLOW_SPIKE        = _float_env("MAX_OUTFLOW_SPIKE", 3.0)
    OUTFLOW_SPIKE_MIN_SAMPLES = _int_env("OUTFLOW_SPIKE_MIN_SAMPLES", 3)
