"""Aggregate performance metrics. Pure functions over closed trades; Decimal only.

Every formula here is documented in docs/metrics.md. Conventions:

* Only **closed** trades enter performance metrics. Open trades are counted separately.
* "P&L" means **net** realized P&L (gross minus commissions and fees) unless a field says gross.
* Outcome: win if net > 0, loss if net < 0, breakeven if net == 0.
* Ratios with a zero denominator are ``None`` (never 0 and never infinity); the response carries a reason.
* Deposits and withdrawals never enter any metric here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from statistics import median
from uuid import UUID

from app.core.money import ZERO
from app.modules.analytics.formulas import outcome

RATIO_Q = Decimal("0.0001")
MONEY_Q = Decimal("0.01")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SMALL_SAMPLE = 30


@dataclass(frozen=True)
class TradeRow:
    id: UUID
    account_id: UUID
    symbol: str
    asset_class: str
    direction: str
    opened_at: datetime
    closed_at: datetime
    session_date: date
    entry_session: str
    entry_hour: int  # hour of entry in the instrument's market timezone
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    holding_seconds: int
    initial_risk: Decimal | None = None
    r_multiple: Decimal | None = None
    playbook_id: UUID | None = None
    playbook_name: str | None = None
    followed_plan: bool | None = None
    mistake_tags: tuple[str, ...] = field(default_factory=tuple)


def m(v: Decimal | None) -> Decimal | None:
    return None if v is None else v.quantize(MONEY_Q)


def ratio(num: Decimal, den: Decimal) -> Decimal | None:
    return None if den == 0 else (num / den).quantize(RATIO_Q)


def ordered(trades: Iterable[TradeRow]) -> list[TradeRow]:
    return sorted(trades, key=lambda t: (t.closed_at, t.opened_at, str(t.id)))


def summary(trades: list[TradeRow]) -> dict:
    n = len(trades)
    nets = [t.net_pnl for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    breakevens = n - len(wins) - len(losses)
    sum_w = sum(wins, ZERO)
    sum_l = sum(losses, ZERO)
    net = sum(nets, ZERO)
    gross = sum((t.gross_pnl for t in trades), ZERO)
    fees = sum((t.fees for t in trades), ZERO)
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    return {
        "closed_trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": breakevens,
        "gross_pnl": m(gross),
        "fees": m(fees),
        "net_pnl": m(net),
        "win_rate": ratio(Decimal(len(wins)), Decimal(len(wins) + len(losses))),
        "profit_factor": ratio(sum_w, -sum_l),
        "profit_factor_note": "no losing trades" if not losses and wins else None,
        "expectancy": m(net / n) if n else None,
        "avg_win": m(sum_w / len(wins)) if wins else None,
        "avg_loss": m(sum_l / len(losses)) if losses else None,
        "win_loss_ratio": ratio(sum_w / len(wins), -sum_l / len(losses)) if wins and losses else None,
        "largest_win": m(max(wins)) if wins else None,
        "largest_loss": m(min(losses)) if losses else None,
        "median_trade": m(Decimal(median(nets))) if nets else None,
        "avg_r": (sum(rs, ZERO) / len(rs)).quantize(RATIO_Q) if rs else None,
        "total_r": sum(rs, ZERO).quantize(RATIO_Q) if rs else None,
        "trades_with_r": len(rs),
        "avg_holding_seconds": int(sum(t.holding_seconds for t in trades) / n) if n else None,
    }


def equity_curve(trades: list[TradeRow]) -> tuple[list[dict], dict]:
    """Cumulative net P&L after each closed trade, starting at 0, plus drawdown statistics.

    Max drawdown = largest decline from a running peak of cumulative net P&L (the peak starts at 0).
    """
    cum = ZERO
    peak = ZERO
    max_dd = ZERO
    peak_at: datetime | None = None
    dd_start: datetime | None = None
    dd_end: datetime | None = None
    points = []
    for t in ordered(trades):
        cum += t.net_pnl
        if cum > peak:
            peak = cum
            peak_at = t.closed_at
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
            dd_start, dd_end = peak_at, t.closed_at
        points.append(
            {
                "trade_id": t.id,
                "closed_at": t.closed_at,
                "symbol": t.symbol,
                "net_pnl": m(t.net_pnl),
                "cumulative": m(cum),
                "drawdown": m(-dd),
            }  # fmt: skip
        )
    return points, {"max_drawdown": m(max_dd), "max_drawdown_start": dd_start, "max_drawdown_end": dd_end}


def streaks(trades: list[TradeRow]) -> dict:
    """Longest runs of consecutive wins and losses by close order. A breakeven trade ends both runs."""
    best_w = best_l = cur_w = cur_l = 0
    for t in ordered(trades):
        o = outcome(t.net_pnl)
        cur_w = cur_w + 1 if o == "win" else 0
        cur_l = cur_l + 1 if o == "loss" else 0
        best_w, best_l = max(best_w, cur_w), max(best_l, cur_l)
    current = 0
    for t in reversed(ordered(trades)):
        o = outcome(t.net_pnl)
        if o == "breakeven":
            break
        if current == 0:
            current = 1 if o == "win" else -1
        elif (current > 0) == (o == "win"):
            current += 1 if current > 0 else -1
        else:
            break
    return {"max_consecutive_wins": best_w, "max_consecutive_losses": best_l, "current_streak": current}


def daily(trades: list[TradeRow]) -> list[dict]:
    """Net P&L per trading session date (the exit's session date in the market's timezone)."""
    by: dict[date, list[TradeRow]] = defaultdict(list)
    for t in trades:
        by[t.session_date].append(t)
    out = []
    cum = ZERO
    for d in sorted(by):
        ts = by[d]
        net = sum((t.net_pnl for t in ts), ZERO)
        cum += net
        out.append(
            {
                "date": d,
                "net_pnl": m(net),
                "gross_pnl": m(sum((t.gross_pnl for t in ts), ZERO)),
                "fees": m(sum((t.fees for t in ts), ZERO)),
                "trades": len(ts),
                "wins": sum(1 for t in ts if t.net_pnl > 0),
                "losses": sum(1 for t in ts if t.net_pnl < 0),
                "cumulative": m(cum),
            }  # fmt: skip
        )
    return out


def day_stats(days: list[dict]) -> dict:
    n = len(days)
    profitable = sum(1 for d in days if d["net_pnl"] > 0)
    losing = sum(1 for d in days if d["net_pnl"] < 0)
    nets = [d["net_pnl"] for d in days]
    return {
        "trading_days": n,
        "profitable_days": profitable,
        "losing_days": losing,
        "day_win_rate": ratio(Decimal(profitable), Decimal(n)),
        "avg_daily_pnl": m(sum(nets, ZERO) / n) if n else None,
        "best_day": m(max(nets)) if nets else None,
        "worst_day": m(min(nets)) if nets else None,
    }


def group(trades: list[TradeRow], key: Callable[[TradeRow], object], label: Callable[[object], str] | None = None,
          order: list | None = None) -> list[dict]:  # fmt: skip
    by: dict[object, list[TradeRow]] = defaultdict(list)
    for t in trades:
        by[key(t)].append(t)
    keys = [k for k in order if k in by] if order else sorted(by, key=lambda k: (k is None, str(k)))
    out = []
    for k in keys:
        s = summary(by[k])
        out.append(
            {
                "key": None if k is None else str(k),
                "label": label(k) if label else str(k),
                "trades": s["closed_trades"],
                "net_pnl": s["net_pnl"],
                "gross_pnl": s["gross_pnl"],
                "fees": s["fees"],
                "wins": s["wins"],
                "losses": s["losses"],
                "win_rate": s["win_rate"],
                "profit_factor": s["profit_factor"],
                "expectancy": s["expectancy"],
                "avg_r": s["avg_r"],
            }  # fmt: skip
        )
    return out


def distribution(trades: list[TradeRow], buckets: int = 12) -> dict:
    """Histogram of per-trade net P&L in equal-width buckets between the min and max outcome."""
    if not trades:
        return {"bucket_width": None, "buckets": []}
    nets = [t.net_pnl for t in trades]
    lo, hi = min(nets), max(nets)
    if lo == hi:
        return {"bucket_width": None, "buckets": [{"from": m(lo), "to": m(hi), "count": len(nets),
                                                   "wins": sum(1 for x in nets if x > 0)}]}  # fmt: skip
    width = (hi - lo) / buckets
    counts = [0] * buckets
    wins = [0] * buckets
    for x in nets:
        i = min(int((x - lo) / width), buckets - 1)
        counts[i] += 1
        wins[i] += 1 if x > 0 else 0
    return {
        "bucket_width": m(width),
        "buckets": [
            {"from": m(lo + width * i), "to": m(lo + width * (i + 1)), "count": counts[i], "wins": wins[i]}
            for i in range(buckets)
        ],
    }


def r_distribution(trades: list[TradeRow]) -> list[dict]:
    edges = [Decimal(x) for x in ("-3", "-2", "-1", "0", "1", "2", "3")]
    labels = ["< -3R", "-3R to -2R", "-2R to -1R", "-1R to 0R", "0R to 1R", "1R to 2R", "2R to 3R", ">= 3R"]
    counts = [0] * len(labels)
    for t in trades:
        if t.r_multiple is None:
            continue
        i = sum(1 for e in edges if t.r_multiple >= e)
        counts[i] += 1
    return [{"label": lbl, "count": c} for lbl, c in zip(labels, counts, strict=True)]


def costs(trades: list[TradeRow]) -> dict:
    """Trading-cost analysis. fees_pct_of_gross_profit = total fees / sum of positive gross P&L."""
    fees = sum((t.fees for t in trades), ZERO)
    gross_profit = sum((t.gross_pnl for t in trades if t.gross_pnl > 0), ZERO)
    flipped = [t for t in trades if t.gross_pnl > 0 and t.net_pnl <= 0]
    return {
        "total_fees": m(fees),
        "avg_fees_per_trade": m(fees / len(trades)) if trades else None,
        "fees_pct_of_gross_profit": ratio(fees, gross_profit),
        "trades_turned_negative_by_costs": len(flipped),
        "net_without_costs": m(sum((t.gross_pnl for t in trades), ZERO)),
    }


def risk_adherence(trades: list[TradeRow], max_risk: dict[UUID, Decimal | None],
                   daily_limit: dict[UUID, Decimal | None]) -> dict:  # fmt: skip
    """Facts about planned risk and stated plan adherence. Plan adherence is the trader's own judgement
    (followed_plan); it is reported separately from profitability and never inferred from P&L."""
    with_risk = [t for t in trades if t.initial_risk is not None]
    over_limit = [
        t for t in with_risk if max_risk.get(t.account_id) is not None and t.initial_risk > max_risk[t.account_id]
    ]
    beyond_stop = [t for t in trades if t.r_multiple is not None and t.r_multiple < -1]
    per_day: dict[tuple[UUID, date], Decimal] = defaultdict(lambda: ZERO)
    for t in trades:
        per_day[(t.account_id, t.session_date)] += t.net_pnl
    day_breaches = [
        {"account_id": a, "date": d, "net_pnl": m(v), "limit": m(daily_limit[a])}
        for (a, d), v in sorted(per_day.items(), key=lambda kv: kv[0][1])
        if daily_limit.get(a) is not None and v < -daily_limit[a]
    ]

    def bucket(flag):
        ts = [t for t in trades if t.followed_plan is flag]
        return {"trades": len(ts), "net_pnl": m(sum((t.net_pnl for t in ts), ZERO)),
                "win_rate": summary(ts)["win_rate"]}  # fmt: skip

    mistakes: dict[str, list[TradeRow]] = defaultdict(list)
    for t in trades:
        for name in t.mistake_tags:
            mistakes[name].append(t)
    return {
        "trades_with_planned_risk": len(with_risk),
        "planned_risk_coverage": ratio(Decimal(len(with_risk)), Decimal(len(trades))),
        "risk_limit_violations": [
            {
                "trade_id": t.id,
                "symbol": t.symbol,
                "initial_risk": m(t.initial_risk),
                "limit": m(max_risk[t.account_id]),
            }
            for t in over_limit
        ],  # fmt: skip
        "losses_beyond_planned_risk": [
            {"trade_id": t.id, "symbol": t.symbol, "r_multiple": t.r_multiple, "net_pnl": m(t.net_pnl)}
            for t in beyond_stop
        ],
        "daily_loss_limit_breaches": day_breaches,
        "plan_adherence": {"followed": bucket(True), "not_followed": bucket(False), "unrated": bucket(None)},
        "mistakes": sorted(
            [
                {"tag": k, "trades": len(v), "net_pnl": m(sum((t.net_pnl for t in v), ZERO))}
                for k, v in mistakes.items()
            ],
            key=lambda x: x["net_pnl"],
        ),
        "note": "Plan adherence is self-reported per trade; it is not inferred from profitability.",
    }
