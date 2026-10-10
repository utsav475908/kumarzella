"""Decimal-safe arithmetic helpers. Accounting values never use binary floating point."""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, getcontext

getcontext().prec = 38

ZERO = Decimal("0")
STORE_Q = Decimal("0.00000001")  # 8 dp, matches NUMERIC(24, 8) columns
CENT = Decimal("0.01")


def D(value) -> Decimal:  # noqa: N802
    """Convert to Decimal without passing through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # Floats are only accepted via their shortest repr, never their binary expansion.
        return Decimal(repr(value))
    if value is None:
        raise InvalidOperation("None is not a number")
    return Decimal(str(value).strip().replace(",", ""))


def q8(value: Decimal) -> Decimal:
    return value.quantize(STORE_Q, rounding=ROUND_HALF_EVEN)


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def split_proportionally(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split `total` by weights at 8dp so the parts sum exactly to `total` (remainder goes to the last part)."""
    if not weights:
        return []
    wsum = sum(weights, ZERO)
    if wsum == 0:
        return [ZERO for _ in weights[:-1]] + [total]
    parts = [q8(total * w / wsum) for w in weights[:-1]]
    parts.append(total - sum(parts, ZERO))
    return parts
