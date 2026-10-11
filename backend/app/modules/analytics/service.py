"""Builds analytics responses from the database. The only place aggregate financial figures are produced."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import Account
from app.modules.analytics import metrics as mx
from app.modules.instruments.rules import market_local_time
from app.modules.journal.models import Tag, TradeTag
from app.modules.playbooks.models import Playbook
from app.modules.trades.filters import TradeFilters, apply_filters, base_query

EXCURSION_NOTE = (
    "MAE/MFE come from historical 1-minute bid/ask candles (forex via Dukascopy). They are computed when a trade's "
    "chart is opened or when excursions are refreshed; trades without market data are left out of the averages."
)


def load(db: Session, user_id: UUID, f: TradeFilters, currency: str | None) -> tuple[list[mx.TradeRow], dict]:
    closed_f = replace(f, status="closed")
    rows = db.execute(apply_filters(base_query(), user_id, closed_f)).all()
    open_count = len(db.execute(apply_filters(base_query(), user_id, replace(f, status="open"))).all())

    ccys = Counter(t.currency for t, _ in rows)
    if currency is None:
        currency = ccys.most_common(1)[0][0] if ccys else "USD"
    excluded = sum(c for k, c in ccys.items() if k != currency)
    rows = [(t, i) for t, i in rows if t.currency == currency]

    ids = [t.id for t, _ in rows]
    mistakes: dict[UUID, list[str]] = defaultdict(list)
    if ids:
        for tid, name in db.execute(
            select(TradeTag.trade_id, Tag.name)
            .join(Tag, Tag.id == TradeTag.tag_id)
            .where(TradeTag.trade_id.in_(ids), Tag.category == "mistake")
        ):
            mistakes[tid].append(name)
    pb_ids = {t.playbook_id for t, _ in rows if t.playbook_id}
    pbs = {p.id: p.name for p in db.scalars(select(Playbook).where(Playbook.id.in_(pb_ids)))} if pb_ids else {}
    out = [
        mx.TradeRow(
            id=t.id,
            account_id=t.account_id,
            symbol=i.symbol,
            asset_class=i.asset_class,
            direction=t.direction,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
            session_date=t.session_date,
            entry_session=t.entry_session,
            entry_hour=market_local_time(t.opened_at, i.asset_class).hour,
            gross_pnl=t.gross_pnl,
            fees=t.fees,
            net_pnl=t.net_pnl,
            holding_seconds=t.holding_seconds or 0,
            initial_risk=t.initial_risk,
            r_multiple=t.r_multiple,
            mae=t.mae,
            mfe=t.mfe,
            playbook_id=t.playbook_id,
            playbook_name=pbs.get(t.playbook_id),
            followed_plan=t.followed_plan,
            mistake_tags=tuple(sorted(mistakes.get(t.id, []))),
        )  # fmt: skip
        for t, i in rows
    ]
    accounts_q = select(Account).where(Account.user_id == user_id)
    if f.account_ids:
        accounts_q = accounts_q.where(Account.id.in_(f.account_ids))
    accounts = list(db.scalars(accounts_q))
    meta = {
        "currency": currency,
        "currencies_available": sorted(ccys),
        "excluded_other_currency_trades": excluded,
        "open_trades": open_count,
        "accounts": accounts,
        "includes_demo_data": any(a.is_demo for a in accounts if not f.account_ids or a.id in f.account_ids),
    }
    return out, meta


def dashboard(db: Session, user_id: UUID, f: TradeFilters, currency: str | None) -> dict:
    trades, meta = load(db, user_id, f, currency)
    accounts: list[Account] = meta.pop("accounts")
    s = mx.summary(trades)
    curve, dd = mx.equity_curve(trades)
    days = mx.daily(trades)
    warnings = []
    if meta["excluded_other_currency_trades"]:
        warnings.append(
            f"{meta['excluded_other_currency_trades']} closed trades in other currencies are excluded; "
            f"choose a currency to see them. Amounts are never converted."
        )
    if 0 < s["closed_trades"] < mx.SMALL_SAMPLE:
        warnings.append(f"Small sample: {s['closed_trades']} closed trades. Treat ratios as unreliable.")
    if meta["open_trades"]:
        warnings.append(f"{meta['open_trades']} open trades are excluded from performance metrics.")
    starting = [a.starting_balance for a in accounts]
    if accounts and all(b is not None for b in starting) and dd["max_drawdown"] is not None:
        base = sum(starting)  # type: ignore[arg-type]
        dd["max_drawdown_pct_of_starting_balance"] = mx.ratio(dd["max_drawdown"], base) if base else None
    return {
        "filters": f.as_dict(),
        **meta,
        "warnings": warnings,
        "summary": {**s, **dd, **mx.streaks(trades), **mx.day_stats(days)},
        "equity_curve": curve,
        "daily": days,
        "distribution": mx.distribution(trades),
        "r_distribution": mx.r_distribution(trades),
        "by_symbol": sorted(mx.group(trades, lambda t: t.symbol), key=lambda g: g["net_pnl"], reverse=True),
        "by_playbook": mx.group(
            trades,
            lambda t: t.playbook_id,
            label=lambda k: next((t.playbook_name for t in trades if t.playbook_id == k), None) or "No playbook",
        ),  # fmt: skip
        "by_hour": mx.group(
            trades, lambda t: t.entry_hour, label=lambda h: f"{h:02d}:00", order=list(range(24))
        ),  # fmt: skip
        "by_weekday": mx.group(
            trades, lambda t: t.session_date.weekday(), label=lambda d: mx.WEEKDAYS[d], order=list(range(7))
        ),
        "by_direction": mx.group(trades, lambda t: t.direction, order=["long", "short"]),
        "by_session": mx.group(trades, lambda t: t.entry_session, order=["regular", "extended"]),
        "costs": mx.costs(trades),
        "risk": mx.risk_adherence(
            trades,
            {a.id: a.max_risk_per_trade for a in accounts},
            {a.id: a.daily_loss_limit for a in accounts},
        ),
        "excursions": {**mx.excursion_summary(trades), "note": EXCURSION_NOTE},
    }


def calendar(db: Session, user_id: UUID, f: TradeFilters, month: date, currency: str | None) -> dict:
    start = month.replace(day=1)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    from datetime import timedelta

    mf = replace(f, date_from=start, date_to=end - timedelta(days=1))
    trades, meta = load(db, user_id, mf, currency)
    meta.pop("accounts")
    days = mx.daily(trades)
    weeks: dict[int, list[dict]] = defaultdict(list)
    for d in days:
        weeks[d["date"].isocalendar()[1]].append(d)
    from decimal import Decimal

    week_rows = [
        {"iso_week": w, "net_pnl": mx.m(sum((d["net_pnl"] for d in ds), Decimal(0))),
         "trades": sum(d["trades"] for d in ds), "days": len(ds)}
        for w, ds in sorted(weeks.items())
    ]  # fmt: skip
    return {
        "month": start.isoformat()[:7],
        "filters": mf.as_dict(),
        **meta,
        "days": days,
        "weeks": week_rows,
        "summary": {**mx.day_stats(days), "net_pnl": mx.m(sum((d["net_pnl"] for d in days), Decimal(0)))},
    }
