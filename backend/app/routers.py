from fastapi import APIRouter


def api_routers() -> list[APIRouter]:
    from app.modules.auth.router import router as auth

    return [auth]
