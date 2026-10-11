from fastapi import APIRouter


def api_routers() -> list[APIRouter]:
    from app.modules.accounts.export import router as exports
    from app.modules.accounts.router import router as accounts
    from app.modules.analytics.router import router as analytics
    from app.modules.attachments.router import router as attachments
    from app.modules.auth.router import router as auth
    from app.modules.backtesting.router import router as backtests
    from app.modules.imports.router import router as imports
    from app.modules.journal.router import router as journal
    from app.modules.marketdata.router import router as marketdata
    from app.modules.marketdata.router import trade_router as trade_charts
    from app.modules.playbooks.router import router as playbooks
    from app.modules.replay.router import router as replay
    from app.modules.trades.review_router import router as trade_review
    from app.modules.trades.router import router as trades

    return [auth, accounts, imports, trades, trade_charts, journal, playbooks, attachments, analytics, exports,
            marketdata, replay, trade_review, backtests]  # fmt: skip
