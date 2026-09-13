from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from critiq.core.feedback import FeedbackSignal
from critiq.infrastructure.postgres.models import FindingFeedback
from critiq.infrastructure.postgres.session import async_session_factory

router = APIRouter(prefix="/api/feedback", include_in_schema=False)


class FeedbackCreate(BaseModel):
    signal: FeedbackSignal
    note: str = ""


@router.post("/findings/{finding_id}", status_code=201)
async def record_feedback(finding_id: int, body: FeedbackCreate) -> dict:
    """Record developer feedback on a finding."""
    async with async_session_factory() as session:
        fb = FindingFeedback(
            finding_id=finding_id,
            signal=body.signal.value,
            payload={"note": body.note} if body.note else {},
        )
        session.add(fb)
        await session.commit()
        return {
            "id": fb.id,
            "finding_id": fb.finding_id,
            "signal": fb.signal,
            "created_at": fb.created_at,
        }


@router.get("/findings/{finding_id}")
async def get_feedback(finding_id: int) -> list[dict]:
    """List all feedback entries for a finding."""
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(FindingFeedback)
                .where(FindingFeedback.finding_id == finding_id)
                .order_by(FindingFeedback.id.desc())
            )
        ).scalars().all()

    return [
        {
            "id": fb.id,
            "signal": fb.signal,
            "note": fb.payload.get("note", ""),
            "created_at": fb.created_at,
        }
        for fb in rows
    ]


@router.get("/stats")
async def feedback_stats() -> dict:
    """Aggregate feedback statistics across all findings."""
    async with async_session_factory() as session:
        total = await session.scalar(
            select(func.count()).select_from(FindingFeedback)
        ) or 0
        rows = (
            await session.execute(
                select(FindingFeedback.signal, func.count())
                .group_by(FindingFeedback.signal)
            )
        ).all()
        by_signal = {signal: count for signal, count in rows}

    accepted = by_signal.get("accepted", 0)
    rejected = by_signal.get("rejected", 0)
    resolved = by_signal.get("resolved", 0)
    actionable = accepted + rejected + resolved
    acceptance_rate = (accepted / actionable * 100) if actionable else 0.0

    return {
        "total": total,
        "by_signal": by_signal,
        "accepted": accepted,
        "rejected": rejected,
        "resolved": resolved,
        "acceptance_rate": round(acceptance_rate, 1),
    }
