"""Central definitions of every per-trade financial formula. Aggregate metrics live in metrics.py.

See docs/metrics.md for the written definitions; tests/test_metrics.py hold the regression fixtures.
"""

from decimal import Decimal

from app.core.money import ZERO, q8

R_Q = Decimal("0.0001")


def initial_risk(
    *,
    direction: str,
    entry_avg_price: Decimal,
    planned_stop_price: Decimal | None,
    peak_qty: Decimal,
    multiplier: Decimal,
    planned_risk_amount: Decimal | None,
) -> Decimal | None:
    """Initial planned risk in account currency.

    1. If the user entered an explicit risk amount, that amount is used.
    2. Otherwise risk = |entry_avg_price - planned_stop_price| * peak_qty * multiplier, provided the stop is on
       the losing side of the entry (below for longs, above for shorts).
    3. Otherwise risk is unknown (None). Unknown risk is never treated as zero.
    """
    if planned_risk_amount is not None:
        return q8(planned_risk_amount) if planned_risk_amount > 0 else None
    if planned_stop_price is None:
        return None
    per_unit = entry_avg_price - planned_stop_price if direction == "long" else planned_stop_price - entry_avg_price
    if per_unit <= 0:
        return None
    return q8(per_unit * peak_qty * multiplier)


def r_multiple(net_pnl: Decimal, risk: Decimal | None, status: str) -> Decimal | None:
    """R-multiple = net realized P&L / initial planned risk, for closed trades with known positive risk."""
    if status != "closed" or risk is None or risk <= ZERO:
        return None
    return (net_pnl / risk).quantize(R_Q)


def outcome(net_pnl: Decimal) -> str:
    """Win if net P&L > 0, loss if < 0, breakeven if exactly 0."""
    if net_pnl > 0:
        return "win"
    if net_pnl < 0:
        return "loss"
    return "breakeven"
