"""Create a clearly labelled DEMO user and account with SYNTHETIC executions.

    python -m scripts.seed_demo            # demo@example.com / demo-password-1

The data is randomly generated from a fixed seed. It is not real broker data or market history, and the
account is flagged is_demo so the UI shows a banner wherever it appears.
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

import app.models  # noqa: F401  (register every table)
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.accounts.models import Account
from app.modules.auth.models import User
from app.modules.executions.models import Execution
from app.modules.instruments import service as instruments
from app.modules.journal.models import Tag, TradeTag
from app.modules.playbooks.models import Playbook
from app.modules.trades.models import Trade
from app.modules.trades.reconstruction import rebuild_account
from app.modules.trades.service import manual_fingerprint

EMAIL = "demo@example.com"
SYMBOLS = [("AAPL", "stock", Decimal("190")), ("NVDA", "stock", Decimal("850")), ("ESM4", "future", Decimal("5200")),
           ("TSLA", "stock", Decimal("180")), ("SPY", "etf", Decimal("520"))]  # fmt: skip


def main() -> None:
    rng = random.Random(42)  # noqa: S311  (deterministic synthetic data, not security)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == EMAIL))
        if user is None:
            user = User(email=EMAIL, password_hash=hash_password("demo-password-1"), display_name="Demo Trader")
            db.add(user)
            db.flush()
        acct = db.scalar(select(Account).where(Account.user_id == user.id, Account.name == "Demo (synthetic)"))
        if acct is not None:
            print("Demo data already present.")
            return
        acct = Account(user_id=user.id, name="Demo (synthetic)", account_type="demo", is_demo=True, broker="Synthetic",
                       starting_balance=Decimal(25000), max_risk_per_trade=Decimal(300), daily_loss_limit=Decimal(1000))  # fmt: skip
        db.add(acct)
        db.flush()
        pbs = [
            Playbook(user_id=user.id, name=n) for n in ("Opening range breakout", "VWAP pullback", "Trend continuation")
        ]
        tags = [Tag(user_id=user.id, name=n, category=c) for n, c in
                (("FOMO", "mistake"), ("Moved stop", "mistake"), ("A+ setup", "setup"), ("Tired", "emotion"))]  # fmt: skip
        db.add_all(pbs + tags)
        db.flush()

        day = datetime(2024, 1, 2, 14, 35, tzinfo=UTC)
        meta: list[tuple] = []
        for _ in range(60):
            day += timedelta(days=1 if day.weekday() < 4 else 3)
            for _k in range(rng.randint(1, 3)):
                sym, ac, px = rng.choice(SYMBOLS)
                inst = instruments.resolve(db, sym, ac)
                qty = Decimal(rng.choice([1, 2])) if ac == "future" else Decimal(rng.choice([10, 25, 50, 100]))
                side = rng.choice(["buy", "sell"])
                tick = Decimal("0.25") if ac == "future" else Decimal("0.01")
                entry = (px * Decimal(1 + rng.uniform(-0.05, 0.05)) / tick).quantize(Decimal(1)) * tick
                move = Decimal(str(round(rng.gauss(0.0012, 0.006), 5)))
                exit_ = (entry * (1 + move) / tick).quantize(Decimal(1)) * tick
                t_in = day + timedelta(minutes=rng.randint(0, 300))
                t_out = t_in + timedelta(minutes=rng.randint(3, 90))
                comm = Decimal("2.10") if ac == "future" else Decimal("1.00")
                for s, p, t in ((side, entry, t_in), ("sell" if side == "buy" else "buy", exit_, t_out)):
                    db.add(Execution(user_id=user.id, account_id=acct.id, instrument_id=inst.id, source="manual",
                                     fingerprint=manual_fingerprint(), side=s, quantity=qty, price=p, commission=comm,
                                     fees=Decimal(0), currency=inst.currency, executed_at=t,
                                     source_metadata={"synthetic": True}))  # fmt: skip
                stop_dist = entry * Decimal("0.004")
                meta.append(
                    (
                        t_in,
                        inst.id,
                        (entry - stop_dist if side == "buy" else entry + stop_dist).quantize(Decimal("0.01")),
                    )
                )
        db.flush()
        rebuild_account(db, acct)
        trades = {
            (t.opened_at, t.instrument_id): t for t in db.scalars(select(Trade).where(Trade.account_id == acct.id))
        }
        for t_in, iid, stop in meta:
            t = trades.get((t_in, iid))
            if not t:
                continue
            t.planned_stop_price = stop if rng.random() < 0.8 else None
            t.playbook_id = rng.choice(pbs).id if rng.random() < 0.85 else None
            t.followed_plan = rng.choice([True, True, True, False, None])
            if rng.random() < 0.25:
                db.add(TradeTag(trade_id=t.id, tag_id=rng.choice(tags).id, user_id=user.id))
        db.flush()
        rebuild_account(db, acct)  # recompute risk/R with the stops set above
        db.commit()
        print(f"Created demo user {EMAIL} (password demo-password-1) with {len(trades)} synthetic trades.")


if __name__ == "__main__":
    main()
