from fastapi import APIRouter


def api_routers() -> list[APIRouter]:
    from app.modules.accounts.export import router as exports
    from app.modules.accounts.router import router as accounts
    from app.modules.attachments.router import router as attachments
    from app.modules.auth.router import router as auth
    from app.modules.imports.router import router as imports
    from app.modules.journal.router import router as journal
    from app.modules.playbooks.router import router as playbooks
    from app.modules.trades.router import router as trades

    return [auth, accounts, imports, trades, journal, playbooks, attachments, exports]
