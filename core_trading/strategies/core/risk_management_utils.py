"""Risk management utility functions."""

import numpy as np


def calculate_position_size(
    account_balance: float,
    risk_percentage: float,
    stop_loss_price: float,
    entry_price: float,
) -> float:
    """Calculate position size based on account balance and risk percentage."""
    risk_amount = account_balance * (risk_percentage / 100)
    risk_per_share = abs(entry_price - stop_loss_price)
    if risk_per_share <= 0:
        return 0
    return risk_amount / risk_per_share


def chandelier_exit(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: float,
    period: int = 22,
    multiplier: float = 3.0,
) -> tuple:
    """Calculate the Chandelier Exit trailing stop-loss."""
    long_stop = np.max(high[-period:]) - atr * multiplier
    short_stop = np.min(low[-period:]) + atr * multiplier
    return long_stop, short_stop


def calculate_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> float:
    """Calculate Average True Range."""
    if len(close) < 2:
        return 0.0
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    return float(np.mean(tr[-period:])) if len(tr) >= period else float(np.mean(tr))


def calculate_var(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Calculate Value at Risk using historical method."""
    if len(returns) == 0:
        return 0.0
    return float(np.percentile(returns, (1 - confidence) * 100))


def max_drawdown(equity_curve: np.ndarray) -> float:
    """Calculate maximum drawdown from equity curve."""
    if len(equity_curve) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - peak) / peak
    return float(np.min(drawdown))
