from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from critiq.core.config import settings
from critiq.infrastructure.postgres import models as db
from critiq.infrastructure.postgres.session import async_session_factory
from critiq.repository.store import IndexCache, cache_key

router = APIRouter(prefix="/dashboard", include_in_schema=False)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M UTC")


@router.get("", response_class=HTMLResponse)
async def overview(request: Request) -> HTMLResponse:
    async with async_session_factory() as session:
        data = await _overview_query(session)
    context = {"active": "overview", **data}
    return templates.TemplateResponse(request, "overview.html", context)


@router.get("/repos", response_class=HTMLResponse)
async def repos_page(request: Request) -> HTMLResponse:
    async with async_session_factory() as session:
        data = await _repos_query(session)
    context = {"active": "repos", "repos": data, "index_totals": _index_snapshot()[0]}
    return templates.TemplateResponse(request, "repos.html", context)


@router.get("/repos/{repo_id}", response_class=HTMLResponse)
async def repo_detail(request: Request, repo_id: int) -> HTMLResponse:
    async with async_session_factory() as session:
        data = await _repo_detail_query(session, repo_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    context = {"active": "repos", **data}
    return templates.TemplateResponse(request, "repo_detail.html", context)


@router.get("/runs", response_class=HTMLResponse)
async def runs_page(request: Request) -> HTMLResponse:
    repo = request.query_params.get("repo") or None
    async with async_session_factory() as session:
        data = await _runs_history_query(session, repo=repo)
    context = {
        "active": "runs",
        "runs": data["runs"],
        "repo_filter": repo,
        "repos": data["repos"],
        "counts": data["counts"],
    }
    return templates.TemplateResponse(request, "runs.html", context)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: int) -> HTMLResponse:
    async with async_session_factory() as session:
        data = await _run_detail_query(session, run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="ReviewRun not found")
    context = {"active": "runs", **data}
    return templates.TemplateResponse(request, "run_detail.html", context)


async def _overview_query(session) -> dict:
    counts = {
        "repositories": await _count_rows(session, db.Repository),
        "pull_requests": await _count_rows(session, db.PullRequest),
        "review_runs": await _count_rows(session, db.ReviewRun),
        "findings": await _count_rows(session, db.Finding),
    }
    severity = await _grouped_counts(session, db.Finding.severity)
    category = await _grouped_counts(session, db.Finding.category)
    recent = await _runs_history_query(session, repo=None, limit=8)
    totals, _ = _index_snapshot()
    return {
        "counts": counts,
        "severity": severity,
        "category": category,
        "recent_runs": recent["runs"],
        "index_totals": totals,
    }


async def _count_rows(session, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar() or 0


async def _grouped_counts(session, column) -> dict[str, int]:
    stmt = select(column, func.count()).group_by(column)
    rows = (await session.execute(stmt)).all()
    return {label: count for label, count in rows}


def _runs_stmt(limit: int, repo: str | None = None):
    finding_count = (
        select(func.count())
        .select_from(db.Finding)
        .where(db.Finding.review_run_id == db.ReviewRun.id)
        .scalar_subquery()
    )
    stmt = (
        select(db.ReviewRun, db.PullRequest, db.Repository, finding_count)
        .join(db.PullRequest, db.ReviewRun.pull_request_id == db.PullRequest.id)
        .join(db.Repository, db.PullRequest.repository_id == db.Repository.id)
        .order_by(db.ReviewRun.id.desc())
        .limit(limit)
    )
    if repo:
        stmt = stmt.where(db.Repository.full_name == repo)
    return stmt


def _run_display(run, pr, repo, finding_count: int) -> dict:
    return {
        "run_id": run.id,
        "repo_id": repo.id,
        "repo": repo.full_name,
        "pr": pr.github_pr_number,
        "pr_title": pr.title or "",
        "status": run.status,
        "decision": run.decision,
        "finding_count": finding_count,
        "completed_at": _fmt_dt(run.completed_at),
        "error": run.error,
        "summary": (run.summary or "")[:200],
    }


async def _runs_history_query(session, repo: str | None = None, limit: int = 100) -> dict:
    stmt = _runs_stmt(limit=limit, repo=repo)
    rows = (await session.execute(stmt)).all()
    runs = [_run_display(run, pr, r, n) for run, pr, r, n in rows]

    repos_stmt = select(db.Repository.full_name).order_by(db.Repository.full_name)
    repos = list((await session.execute(repos_stmt)).scalars().all())
    counts = {"total": len(runs)}
    for status in ("success", "running", "failed"):
        counts[status] = sum(1 for r in runs if r["status"] == status)
    return {"runs": runs, "repos": repos, "counts": counts}


async def _repos_query(session) -> list[dict]:
    rows = (
        await session.execute(select(db.Repository).order_by(db.Repository.full_name))
    ).scalars()

    pr_stmt = (
        select(db.PullRequest.repository_id, func.count())
        .group_by(db.PullRequest.repository_id)
    )
    pr_counts = dict((await session.execute(pr_stmt)).all())

    run_stmt = (
        select(db.PullRequest.repository_id, func.count())
        .join(db.ReviewRun, db.ReviewRun.pull_request_id == db.PullRequest.id)
        .group_by(db.PullRequest.repository_id)
    )
    run_counts = dict((await session.execute(run_stmt)).all())

    _, index_by_key = _index_snapshot()
    repos = []
    for repo in rows:
        info = index_by_key.get(cache_key(repo.full_name))
        repos.append(
            {
                "id": repo.id,
                "full_name": repo.full_name,
                "default_branch": repo.default_branch or "HEAD",
                "pr_count": pr_counts.get(repo.id, 0),
                "run_count": run_counts.get(repo.id, 0),
                "indexed": info is not None,
                "index_files": info["files"] if info else 0,
                "index_lines": info["lines"] if info else 0,
            }
        )
    return repos


async def _repo_detail_query(session, repo_id: int) -> dict | None:
    result = await session.execute(select(db.Repository).where(db.Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if repo is None:
        return None

    pr_stmt = (
        select(db.PullRequest)
        .where(db.PullRequest.repository_id == repo_id)
        .order_by(db.PullRequest.id.desc())
        .limit(25)
    )
    prs = list((await session.execute(pr_stmt)).scalars().all())

    runs = await _runs_history_query(session, repo=repo.full_name, limit=25)

    per_pr_runs = Counter(r["pr"] for r in runs["runs"])
    cache = IndexCache(settings.repo_index_dir)
    index = cache.load(repo.full_name)
    modules = []
    if index is not None:
        modules = [
            {
                "path": path,
                "symbols": len(info.symbols),
                "lines": info.source.count("\n"),
                "related": index.related_for_change(path)[:6],
            }
            for path, info in sorted(
                index.modules.items(), key=lambda it: it[1].source.count("\n"), reverse=True
            )[:40]
        ]

    return {
        "repo": {
            "id": repo.id,
            "full_name": repo.full_name,
            "default_branch": repo.default_branch or "HEAD",
            "last_analyzed_at": _fmt_dt(repo.last_analyzed_at),
        },
        "index": (
            {
                "file_count": index.file_count,
                "total_lines": index.total_lines,
            }
            if index
            else None
        ),
        "modules": modules,
        "pull_requests": [
            {
                "number": pr.github_pr_number,
                "title": pr.title or "",
                "state": pr.state or "open",
                "head_branch": pr.head_branch or "",
                "runs": per_pr_runs.get(pr.github_pr_number, 0),
            }
            for pr in prs
        ],
        "runs": runs["runs"],
    }


async def _run_detail_query(session, run_id: int) -> dict | None:
    stmt = (
        select(db.ReviewRun, db.PullRequest, db.Repository)
        .join(db.PullRequest, db.ReviewRun.pull_request_id == db.PullRequest.id)
        .join(db.Repository, db.PullRequest.repository_id == db.Repository.id)
        .where(db.ReviewRun.id == run_id)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    run, pr, repo = row

    f_stmt = (
        select(db.Finding)
        .where(db.Finding.review_run_id == run_id)
        .order_by(db.Finding.severity)
    )
    findings = (await session.execute(f_stmt)).scalars().all()

    return {
        "run": {
            "id": run.id,
            "status": run.status,
            "mode": run.mode,
            "decision": run.decision,
            "summary": run.summary,
            "started_at": _fmt_dt(run.started_at),
            "completed_at": _fmt_dt(run.completed_at),
            "error": run.error,
        },
        "pr": {
            "number": pr.github_pr_number,
            "title": pr.title or "",
            "head_branch": pr.head_branch or "",
            "head_sha": pr.head_sha or "",
        },
        "repo": repo.full_name,
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
            for f in findings
        ],
    }


def _index_snapshot() -> tuple[dict, dict[str, dict]]:
    """Aggregate the on-disk repo index cache (count/file/line totals + per-key)."""
    totals = {"count": 0, "files": 0, "lines": 0, "disk_bytes": 0}
    by_key: dict[str, dict] = {}
    cache_dir = Path(settings.repo_index_dir)
    if not cache_dir.exists():
        return totals, by_key
    for path in sorted(cache_dir.glob("*.index.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        key = path.stem.removesuffix(".index")
        files = len(payload.get("modules", {}))
        lines = sum(
            m.get("source", "").count("\n") for m in payload.get("modules", {}).values()
        )
        totals["count"] += 1
        totals["files"] += files
        totals["lines"] += lines
        totals["disk_bytes"] += path.stat().st_size
        by_key[key] = {"files": files, "lines": lines}
    return totals, by_key
