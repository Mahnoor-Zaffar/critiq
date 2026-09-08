from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from critiq.infrastructure.postgres.models import Finding as DbFinding
from critiq.infrastructure.postgres.models import ReviewRun
from critiq.infrastructure.postgres.session import async_session_factory

router = APIRouter()


@router.get("/reviews/{run_id}")
async def get_review(run_id: int) -> dict:
    async with async_session_factory() as session:
        run = await session.get(ReviewRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="ReviewRun not found")
        rows = (
            await session.scalars(
                select(DbFinding).where(DbFinding.review_run_id == run_id)
            )
        ).all()

    return {
        "decision": run.decision,
        "summary": run.summary,
        "findings": [
            {
                "category": f.category,
                "file_path": f.file_path,
                "line_start": f.line_start,
                "line_end": f.line_end,
                "severity": f.severity,
                "confidence": f.confidence,
                "title": f.title,
                "explanation": f.explanation,
                "evidence": f.evidence,
                "recommendation": f.recommendation,
            }
            for f in rows
        ],
    }
