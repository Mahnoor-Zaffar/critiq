from __future__ import annotations

from fastapi import APIRouter, HTTPException

from critiq.infrastructure.postgres.models import ReviewRun
from critiq.infrastructure.postgres.session import async_session_factory

router = APIRouter()


@router.get("/runs/{run_id}")
async def get_run(run_id: int) -> dict:
    async with async_session_factory() as session:
        run = await session.get(ReviewRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="ReviewRun not found")
    return {
        "id": run.id,
        "status": run.status,
        "mode": run.mode,
        "decision": run.decision,
        "overall_score": run.overall_score,
        "summary": run.summary,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "error": run.error,
    }
