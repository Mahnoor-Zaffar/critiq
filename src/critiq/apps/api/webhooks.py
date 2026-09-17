from __future__ import annotations

import logging

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Request, Response

from critiq.core.config import settings
from critiq.integrations.github.webhook import verify_signature

logger = logging.getLogger("critiq.webhooks")
router = APIRouter()

HANDLED_ACTIONS = {"opened", "synchronize", "reopened", "closed"}


@router.post("/webhooks/github")
async def github_webhook(request: Request) -> Response:
    event = request.headers.get("X-GitHub-Event", "")
    signature = request.headers.get("X-Hub-Signature-256", "")
    payload = await request.body()

    if not verify_signature(payload, signature, settings.github_webhook_secret):
        return Response(status_code=401)

    if event != "pull_request":
        return Response(status_code=200)

    data = await request.json()
    action = data.get("action", "")
    if action not in HANDLED_ACTIONS:
        return Response(status_code=200)

    installation_id = (data.get("installation") or {}).get("id")
    repo = (data.get("repository") or {}).get("full_name")
    number = (data.get("pull_request") or {}).get("number")
    if not installation_id or not repo or not number:
        return Response(status_code=200)

    await _enqueue(installation_id, repo, number, action)
    return Response(status_code=200)


async def _enqueue(installation_id: int, repo: str, number: int, action: str) -> None:
    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            await pool.enqueue_job(
                "review_pull_request",
                installation_id=installation_id,
                repo=repo,
                number=number,
                action=action,
            )
        finally:
            await pool.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue failed for %s#%s: %s", repo, number, exc)
