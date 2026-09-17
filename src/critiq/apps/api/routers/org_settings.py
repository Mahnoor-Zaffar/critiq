from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from critiq.core.config import settings
from critiq.infrastructure.postgres.models import OrgSetting, Repository
from critiq.infrastructure.postgres.session import async_session_factory

router = APIRouter(prefix="/api/org-settings")


class OrgSettingsPayload(BaseModel):
    auto_push_enabled: bool


def _require_admin_token(request: Request) -> None:
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {settings.admin_token}"
    if not settings.admin_token or auth != expected:
        raise HTTPException(status_code=401, detail="invalid or missing admin token")


@router.get("/{repository_id}")
async def get_org_settings(repository_id: int, request: Request) -> dict:
    _require_admin_token(request)
    async with async_session_factory() as session:
        repo = await session.get(Repository, repository_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Repository not found")
        setting = await session.scalar(
            select(OrgSetting).where(OrgSetting.repository_id == repository_id)
        )
        enabled = setting.auto_push_enabled if setting else False
    return {"auto_push_enabled": enabled}


@router.put("/{repository_id}")
async def put_org_settings(
    repository_id: int, payload: OrgSettingsPayload, request: Request
) -> dict:
    _require_admin_token(request)
    async with async_session_factory() as session:
        repo = await session.get(Repository, repository_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Repository not found")
        setting = await session.scalar(
            select(OrgSetting).where(OrgSetting.repository_id == repository_id)
        )
        if setting is None:
            setting = OrgSetting(
                repository_id=repository_id,
                auto_push_enabled=payload.auto_push_enabled,
            )
            session.add(setting)
        else:
            setting.auto_push_enabled = payload.auto_push_enabled
        await session.commit()
    return {"auto_push_enabled": payload.auto_push_enabled}
