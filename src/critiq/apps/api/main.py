from __future__ import annotations

from fastapi import FastAPI

from critiq.apps.api.routers import health, reviews, runs
from critiq.apps.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="Critiq", version="0.1.0")
    app.include_router(webhooks_router)
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(reviews.router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("critiq.apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
