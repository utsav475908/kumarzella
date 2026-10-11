"""Deterministic order simulator for manual backtesting. Pure functions: no database, no clock, no randomness.

The simulator walks 1-minute bid and ask candles in time order. The rules (also in docs/backtesting.md):

* Buys fill against the ask, sells against the bid. Slippage (a fixed price amount) is applied against the trader
  on market and stop fills. Limit fills never slip.
* An order is placed at the replay cursor and can first fill in the minute that starts at the cursor.
* Market order: fills at the open of its first minute.
* Buy limit L: fills when ask low <= L, at min(L, ask open). Sell limit L: bid high >= L, at max(L, bid open).
* Buy stop S: triggers when ask high >= S, fills at max(S, ask open) + slippage.
  Sell stop S: bid low <= S, fills at min(S, bid open) - slippage.
* Orders are filled whole. There are no partial fills: candle data has no depth.
* Stop-loss and take-profit attached to an entry become reduce-only, one-cancels-the-other orders when the entry fills.
* Inside one minute the order of the high and the low is unknown. Orders whose level was already crossed at the open
  fill first, in placement order. When two or more other orders trigger in the same minute, a stop-loss is assumed
  to fill first (the conservative assumption) and every fill from that minute is marked ambiguous.
* In the minute an entry fills mid-bar, its stop-loss can fill (conservatively, marked ambiguous) but its
  take-profit cannot: the take-profit waits for the next minute. If the entry filled at the open, both are live in
  that minute because the rest of the minute happened after the entry.
* Reduce-only orders are cancelled when the position they protect is closed or reversed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from app.modules.marketdata.providers.base import Bar

SIM_VERSION = "sim-1"
KINDS = ("entry", "stop_loss", "take_profit")
MINUTE = timedelta(minutes=1)
LOT = Decimal(100000)
CENT = Decimal("0.01")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Config:
    commission_per_100k: Decimal  # per side, in the quote currency
    slippage: Decimal  # price units

    def commission(self, qty: Decimal) -> Decimal:
        return (qty / LOT * self.commission_per_100k).quantize(CENT, ROUND_HALF_EVEN)


@dataclass(frozen=True)
class Order:
    key: str  # stable id: the order's own id, or "<parent key>:stop_loss" / ":take_profit"
    seq: int
    kind: str  # entry | stop_loss | take_profit
    side: str  # buy | sell
    type: str  # market | limit | stop
    quantity: Decimal
    price: Decimal | None  # limit or stop level
    active_from: datetime
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    parent: str | None = None
    root_seq: int = 0  # the entry's seq for protective orders, so ordering never depends on when they were made

    @property
    def reduce_only(self) -> bool:
        return self.kind != "entry"

    @property
    def rank(self) -> tuple[int, int]:
        return (self.root_seq or self.seq, KINDS.index(self.kind))


@dataclass(frozen=True)
class Fill:
    order_key: str
    ts: datetime
    side: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    slippage: Decimal
    ambiguous: bool = False
    reason: str = ""


@dataclass(frozen=True)
class Cancel:
    order_key: str
    ts: datetime
    reason: str


@dataclass
class State:
    position: Decimal = ZERO
    pending: list[Order] = field(default_factory=list)
    next_seq: int = 1


@dataclass
class Events:
    fills: list[Fill] = field(default_factory=list)
    cancels: list[Cancel] = field(default_factory=list)
    created: list[Order] = field(default_factory=list)  # protective orders made when an entry filled


def signed(side: str, qty: Decimal) -> Decimal:
    return qty if side == "buy" else -qty


def _trigger(o: Order, bid: Bar, ask: Bar, opn: tuple[Decimal, Decimal] | None = None) -> tuple[Decimal, bool] | None:
    """(fill price before slippage, crossed at the open) or None. `opn` overrides the (bid, ask) open: used for
    protective orders evaluated in the minute their entry filled, from the entry price onwards."""
    b_open, a_open = opn if opn else (bid.open, ask.open)
    p = o.price
    assert p is not None
    if o.type == "limit":
        if o.side == "buy":
            return (min(p, a_open), a_open <= p) if ask.low <= p or a_open <= p else None
        return (max(p, b_open), b_open >= p) if bid.high >= p or b_open >= p else None
    if o.side == "buy":
        return (max(p, a_open), a_open >= p) if ask.high >= p or a_open >= p else None
    return (min(p, b_open), b_open <= p) if bid.low <= p or b_open <= p else None


def _priority(o: Order) -> tuple[int, tuple[int, int]]:
    return (0 if o.kind == "stop_loss" else 1, o.rank)


class _Minute:
    def __init__(self, state: State, cfg: Config, bid: Bar, ask: Bar, ev: Events):
        self.s, self.cfg, self.bid, self.ask, self.ev = state, cfg, bid, ask, ev

    def fill(self, o: Order, price: Decimal, ambiguous: bool, reason: str) -> Decimal:
        qty = o.quantity
        if o.reduce_only:
            qty = min(qty, abs(self.s.position))
        slip = self.cfg.slippage if o.type in ("market", "stop") else ZERO
        px = price + slip if o.side == "buy" else price - slip
        self.ev.fills.append(
            Fill(o.key, self.bid.ts, o.side, qty, px, self.cfg.commission(qty), slip, ambiguous, reason)
        )
        self.s.position += signed(o.side, qty)
        self.s.pending = [p for p in self.s.pending if p.key != o.key]
        if o.parent:  # one-cancels-the-other
            self.cancel(lambda p: p.parent == o.parent, "the other side of the bracket filled")
        self.cancel(lambda p: p.reduce_only and (self.s.position == 0 or signed(p.side, Decimal(1)) * self.s.position > 0),
                    "position closed or reversed")  # fmt: skip
        return px

    def cancel(self, pred, reason: str) -> None:
        for p in [p for p in self.s.pending if pred(p)]:
            self.ev.cancels.append(Cancel(p.key, self.bid.ts, reason))
        self.s.pending = [p for p in self.s.pending if not pred(p)]

    def bracket(self, o: Order, entry_px: Decimal, at_open: bool) -> None:
        nxt = self.bid.ts + MINUTE
        exit_side = "sell" if o.side == "buy" else "buy"
        kids = []
        for kind, level, typ in (("stop_loss", o.stop_loss, "stop"), ("take_profit", o.take_profit, "limit")):
            if level is None:
                continue
            kid = Order(f"{o.key}:{kind}", self.s.next_seq, kind, exit_side, typ, o.quantity, level, nxt,
                        parent=o.key, root_seq=o.seq)  # fmt: skip
            self.s.next_seq += 1
            kids.append(kid)
            self.ev.created.append(kid)
        self.s.pending.extend(kids)
        # Same-minute check, from the entry price onwards. A mid-bar entry only lets its stop fill (conservatively).
        opn = (entry_px, entry_px)
        live = [k for k in kids if at_open or k.kind == "stop_loss"]
        hits = [(k, t) for k in live if (t := _trigger(k, self.bid, self.ask, opn))]
        if not hits:
            return
        k, (px, _) = sorted(hits, key=lambda h: _priority(h[0]))[0]
        ambiguous = len(hits) > 1 or not at_open
        why = ("stop and target both touched in the entry minute; stop assumed first" if len(hits) > 1
               else "touched in the entry minute; order inside the minute unknown, assumed hit" if not at_open
               else "")  # fmt: skip
        self.fill(k, px, ambiguous, why)

    def run(self) -> None:
        ts = self.bid.ts
        for o in sorted(
            [o for o in self.s.pending if o.type == "market" and o.active_from <= ts], key=lambda o: o.rank
        ):
            if o not in self.s.pending:
                continue
            px = self.ask.open if o.side == "buy" else self.bid.open
            filled = self.fill(o, px, False, "")
            if o.kind == "entry":
                self.bracket(o, filled, at_open=True)
        resting = [o for o in self.s.pending if o.type != "market" and o.active_from <= ts]
        hits = [(o, t) for o in resting if (t := _trigger(o, self.bid, self.ask))]
        at_open = sorted([h for h in hits if h[1][1]], key=lambda h: h[0].rank)
        intrabar = sorted([h for h in hits if not h[1][1]], key=lambda h: _priority(h[0]))
        ambiguous = len(intrabar) > 1
        for o, (px, opened) in at_open + intrabar:
            if o not in self.s.pending:  # cancelled by an earlier fill this minute (bracket or reversal)
                continue
            why = "" if opened or not ambiguous else "several orders triggered in one minute; order inside it unknown"
            filled = self.fill(o, px, ambiguous and not opened, why)
            if o.kind == "entry":
                self.bracket(o, filled, at_open=opened)


def step(state: State, cfg: Config, bid: Bar, ask: Bar) -> Events:
    """Process one minute. Mutates `state`; returns what happened."""
    assert bid.ts == ask.ts
    ev = Events()
    _Minute(state, cfg, bid, ask, ev).run()
    return ev


def pair_minutes(bid: list[Bar], ask: list[Bar]) -> list[tuple[Bar, Bar]]:
    """Minutes that have both a bid and an ask candle. A minute missing either side is not tradable."""
    asks = {a.ts: a for a in ask}
    return [(b, asks[b.ts]) for b in bid if b.ts in asks]


def flatten(state: State, cfg: Config, last_bid: Bar, last_ask: Bar, ts: datetime, key: str) -> Fill | None:
    """Close the position at the last revealed close, with slippage, when a session is finished."""
    if state.position == 0:
        return None
    side = "sell" if state.position > 0 else "buy"
    qty = abs(state.position)
    px = last_bid.close - cfg.slippage if side == "sell" else last_ask.close + cfg.slippage
    state.position = ZERO
    state.pending = []
    return Fill(
        key,
        ts,
        side,
        qty,
        px,
        cfg.commission(qty),
        cfg.slippage,
        False,
        "closed at the last close when the session was finished",
    )


@dataclass(frozen=True)
class LoggedOrder:
    """An order as the trader placed it, for re-running a session from scratch."""

    order: Order
    placed_at: datetime
    cancelled_at: datetime | None = None


def rerun(cfg: Config, orders: list[LoggedOrder], child_cancels: dict[str, datetime], minutes: list[tuple[Bar, Bar]],
          finish: tuple[datetime, str] | None = None) -> list[Fill]:  # fmt: skip
    """Replays a whole session from its order log. Used to prove a stored session is reproducible."""
    s = State(next_seq=max((o.order.seq for o in orders), default=0) + 1)
    fills: list[Fill] = []
    todo = sorted(orders, key=lambda o: (o.placed_at, o.order.rank))
    for bid, ask in minutes:
        while todo and todo[0].placed_at <= bid.ts:
            s.pending.append(todo.pop(0).order)
        dead = {o.order.key for o in orders if o.cancelled_at and o.cancelled_at <= bid.ts}
        dead |= {k for k, at in child_cancels.items() if at <= bid.ts}
        s.pending = [o for o in s.pending if o.key not in dead]
        ev = step(s, cfg, bid, ask)
        fills.extend(ev.fills)
    if finish and minutes:
        ts, key = finish
        f = flatten(s, cfg, minutes[-1][0], minutes[-1][1], ts, key)
        if f:
            fills.append(f)
    return fills
