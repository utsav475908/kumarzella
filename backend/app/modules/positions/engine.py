"""Position accounting engine: reconstructs trades from fills. Pure, deterministic, Decimal-only.

Definitions
-----------
* A **trade** is one position lifecycle: it opens when the position leaves zero and closes when the
  position returns to zero. One CSV row is never assumed to be one trade.
* A fill that crosses through zero (a **reversal**) is split: the part that flattens the position closes
  the current trade, and the remainder opens a new trade in the opposite direction. Costs are split
  pro rata by quantity.
* Realized P&L of a closed trade is exact and policy independent:
      long:  (exit_value - entry_value) * multiplier
      short: (entry_value - exit_value) * multiplier
  where *_value = sum(price * quantity) over the entry or exit side fills.
* For a trade that is still open, realized P&L of the partial exits depends on the accounting policy:
  ``average_cost`` (default) or ``fifo``. Unrealized P&L is not computed here (it needs a mark price).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.core.money import ZERO, q8, split_proportionally

PRICE_Q = Decimal("0.0000000001")


@dataclass(frozen=True)
class Fill:
    id: str
    side: str  # "buy" | "sell"
    quantity: Decimal  # > 0
    price: Decimal
    costs: Decimal  # commission + fees, >= 0
    executed_at: datetime
    sequence: int = 0
    source: str = "import"

    @property
    def signed_qty(self) -> Decimal:
        return self.quantity if self.side == "buy" else -self.quantity


@dataclass
class Allocation:
    execution_id: str
    role: str  # open | add | reduce | close
    quantity: Decimal
    fees: Decimal
    realized_pnl: Decimal
    position_after: Decimal  # signed


@dataclass
class ReconstructedTrade:
    anchor_execution_id: str
    anchor_leg: int
    direction: str
    opened_at: datetime
    closed_at: datetime | None = None
    allocations: list[Allocation] = field(default_factory=list)
    entry_qty: Decimal = ZERO
    exit_qty: Decimal = ZERO
    entry_value: Decimal = ZERO
    exit_value: Decimal = ZERO
    peak_qty: Decimal = ZERO
    open_qty: Decimal = ZERO
    gross_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    sources: set[str] = field(default_factory=set)

    @property
    def status(self) -> str:
        return "closed" if self.closed_at is not None else "open"

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.fees

    @property
    def entry_avg_price(self) -> Decimal:
        return (self.entry_value / self.entry_qty).quantize(PRICE_Q)

    @property
    def exit_avg_price(self) -> Decimal | None:
        return (self.exit_value / self.exit_qty).quantize(PRICE_Q) if self.exit_qty else None

    @property
    def holding_seconds(self) -> int | None:
        if self.closed_at is None:
            return None
        return int((self.closed_at - self.opened_at).total_seconds())

    @property
    def origin(self) -> str:
        if self.sources == {"manual"}:
            return "manual"
        if "manual" in self.sources:
            return "mixed"
        return "imported"


@dataclass
class ReconstructionResult:
    trades: list[ReconstructedTrade]
    position: Decimal  # final signed quantity
    avg_cost: Decimal | None  # average cost of the open position, if any


def sort_fills(fills: list[Fill]) -> list[Fill]:
    return sorted(fills, key=lambda f: (f.executed_at, f.sequence, f.id))


class _Book:
    """Tracks cost basis of the open position for partial-exit realized P&L."""

    def __init__(self, policy: str):
        if policy not in ("average_cost", "fifo"):
            raise ValueError(f"Unknown accounting policy {policy!r}")
        self.policy = policy
        self.lots: deque[list[Decimal]] = deque()  # [qty, price]  (fifo)
        self.qty = ZERO  # absolute
        self.basis = ZERO  # total cost basis (price * qty), absolute

    def add(self, qty: Decimal, price: Decimal) -> None:
        self.qty += qty
        self.basis += qty * price
        self.lots.append([qty, price])

    def remove(self, qty: Decimal) -> Decimal:
        """Remove `qty` from the book and return the cost basis removed."""
        if qty == self.qty:
            removed = self.basis
            self.lots.clear()
        elif self.policy == "average_cost":
            removed = self.basis * qty / self.qty
            # keep lots consistent for avg cost (single synthetic lot)
            remaining = self.qty - qty
            self.lots = deque([[remaining, (self.basis - removed) / remaining]])
        else:
            removed = ZERO
            left = qty
            while left > 0:
                lot = self.lots[0]
                take = min(lot[0], left)
                removed += take * lot[1]
                lot[0] -= take
                left -= take
                if lot[0] == 0:
                    self.lots.popleft()
        self.qty -= qty
        self.basis -= removed
        return removed

    @property
    def avg_cost(self) -> Decimal | None:
        return (self.basis / self.qty).quantize(PRICE_Q) if self.qty else None


def reconstruct(fills: list[Fill], multiplier: Decimal, policy: str = "average_cost") -> ReconstructionResult:
    trades: list[ReconstructedTrade] = []
    pos = ZERO
    current: ReconstructedTrade | None = None
    book = _Book(policy)

    for f in sort_fills(fills):
        if f.quantity <= 0:
            raise ValueError(f"Fill {f.id} has non-positive quantity")
        signed = f.signed_qty

        # Split into a closing part and an opening part.
        if pos == 0 or (pos > 0) == (signed > 0):
            close_qty, open_qty = ZERO, f.quantity
        else:
            close_qty = min(f.quantity, abs(pos))
            open_qty = f.quantity - close_qty
        weights = [w for w in (close_qty, open_qty) if w > 0]
        cost_parts = split_proportionally(f.costs, weights)
        close_cost = cost_parts[0] if close_qty > 0 else ZERO
        open_cost = cost_parts[-1] if open_qty > 0 else ZERO

        if close_qty > 0:
            assert current is not None
            direction_sign = Decimal(1) if current.direction == "long" else Decimal(-1)
            removed_basis = book.remove(close_qty)
            pos += signed if open_qty == 0 else (-pos)
            current.exit_qty += close_qty
            current.exit_value += close_qty * f.price
            current.fees += close_cost
            current.sources.add(f.source)
            closing = pos == 0
            if closing:
                # Exact, policy-independent realized P&L for the whole round trip.
                total = q8(direction_sign * (current.exit_value - current.entry_value) * multiplier)
                realized = total - sum((a.realized_pnl for a in current.allocations), ZERO)
                current.gross_pnl = total
                current.closed_at = f.executed_at
                current.open_qty = ZERO
            else:
                realized = q8(direction_sign * (close_qty * f.price - removed_basis) * multiplier)
                current.gross_pnl += realized
                current.open_qty = abs(pos)
            current.allocations.append(
                Allocation(f.id, "close" if closing else "reduce", close_qty, close_cost, realized, pos)
            )
            if closing:
                trades.append(current)
                current = None

        if open_qty > 0:
            leg = 1 if close_qty > 0 else 0
            open_signed = open_qty if signed > 0 else -open_qty
            if current is None:
                current = ReconstructedTrade(
                    anchor_execution_id=f.id,
                    anchor_leg=leg,
                    direction="long" if open_signed > 0 else "short",
                    opened_at=f.executed_at,
                )
                role = "open"
            else:
                role = "add"
            pos += open_signed
            book.add(open_qty, f.price)
            current.entry_qty += open_qty
            current.entry_value += open_qty * f.price
            current.fees += open_cost
            current.peak_qty = max(current.peak_qty, abs(pos))
            current.open_qty = abs(pos)
            current.sources.add(f.source)
            current.allocations.append(Allocation(f.id, role, open_qty, open_cost, ZERO, pos))

    if current is not None:
        trades.append(current)
    return ReconstructionResult(trades=trades, position=pos, avg_cost=book.avg_cost)
