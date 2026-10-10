from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.instruments.models import Instrument
from app.modules.instruments.rules import InstrumentSpec, infer_spec


def get_or_create(db: Session, spec: InstrumentSpec) -> Instrument:
    """Instruments are shared reference data; concurrent creators converge via ON CONFLICT."""
    existing = db.scalar(
        select(Instrument).where(Instrument.symbol == spec.symbol, Instrument.asset_class == spec.asset_class)
    )
    if existing:
        return existing
    db.execute(
        insert(Instrument)
        .values(
            symbol=spec.symbol,
            asset_class=spec.asset_class,
            currency=spec.currency,
            multiplier=spec.multiplier,
            tick_size=spec.tick_size,
            root_symbol=spec.root_symbol,
            underlying=spec.underlying,
            expiry=spec.expiry,
            strike=spec.strike,
            option_type=spec.option_type,
        )  # fmt: skip
        .on_conflict_do_nothing(index_elements=["symbol", "asset_class"])
    )
    inst = db.scalar(
        select(Instrument).where(Instrument.symbol == spec.symbol, Instrument.asset_class == spec.asset_class)
    )
    assert inst is not None
    return inst


def resolve(db: Session, symbol: str, asset_class: str | None = None, currency: str | None = None,
            multiplier: Decimal | None = None) -> Instrument:  # fmt: skip
    return get_or_create(db, infer_spec(symbol, asset_class, currency, multiplier))
