from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.schemas import decimal_safe_json
from app.modules.analytics import service
from app.modules.analytics.definitions import DEFINITIONS
from app.modules.auth.models import User
from app.modules.trades.filters import TradeFilters, trade_filters

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard", summary="Every KPI and chart series for the dashboard, under one set of filters")
def dashboard(
    f: TradeFilters = Depends(trade_filters),
    currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return decimal_safe_json(service.dashboard(db, user.id, f, currency))


@router.get("/calendar", summary="Daily net P&L for one month")
def calendar(
    month: date = Query(..., description="Any date inside the month, e.g. 2024-03-01"),
    f: TradeFilters = Depends(trade_filters),
    currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return decimal_safe_json(service.calendar(db, user.id, f, month, currency))


@router.get("/definitions", summary="Formulas behind every metric")
def definitions():
    return DEFINITIONS
