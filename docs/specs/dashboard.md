# Critiq — Dashboard Specification

> Document type: product / UI specification
> Related: `architecture.md`, `data-model.md`, `api.md`, `roadmap.md` (V2)

---

## 1. Purpose

The dashboard is the V2 read + feedback side of Critiq. GitHub PRs remain the
primary interface, but the dashboard surfaces what Critiq knows and has done:

- **Repository intelligence** — the cached `RepoIndex` (modules, symbols, line
  counts, related-file graph) that powers review context retrieval.
- **Review history** — every `ReviewRun` with its `PullRequest`, `Repository`,
  decision, and per-finding detail (severity, confidence, evidence).
- **Feedback loop** — developers accept/reject/resolve findings from the run
  detail page. Those signals (plus optional notes) are stored per finding and
  become future calibration data for confidence scoring.

---

## 2. Pages

Routes are served by the FastAPI app (`apps/api/dashboard.py`) as Jinja2
templates under `/dashboard`, excluded from the OpenAPI schema.

| Route | Page | Data |
| ----- | ---- | ---- |
| `GET /dashboard` | Overview | Counts (repos/PRs/runs/findings), findings by severity + category, index-cache totals, 8 most recent runs |
| `GET /dashboard/repos` | Repositories | All repositories with PR/run counts and per-repo index status |
| `GET /dashboard/repos/{id}` | Repository detail | Repo metadata, index modules (symbols, lines, related files), PRs, recent runs |
| `GET /dashboard/runs` | Review history | Runs (filterable by `?repo=`), status counts |
| `GET /dashboard/runs/{id}` | Run detail | Run metadata, summary, error, all findings with per-finding feedback |
| `POST /dashboard/findings/{id}/feedback` | Run detail (htmx) | Record `signal` + optional note on a finding; returns the re-rendered finding card |
| `GET /dashboard/feedback` | Feedback | Aggregate counts/acceptance rate, per-category breakdown, recent signals |

`GET /static/dashboard.css` serves the theme. `base.html` provides the shared
top nav and layout.

---

## 3. Data Sources

- **Postgres** — `Repository`, `PullRequest`, `ReviewRun`, `Finding`
  (see `data-model.md`). Queries are read-only and use the async session
  factory from `infrastructure/postgres/session.py`.
- **Index cache on disk** — `settings.repo_index_dir` (`.critiq-index/`),
  JSON files written by `critiq-index` (see `repository/store.py`). The
  dashboard aggregates these for repository intelligence. A repo is linked to
  its cache via `repository.store.cache_key(full_name)` — the same key the
  worker uses when loading an index for a review.

Empty states are handled per page (e.g. "No reviews yet", "not indexed").

---

## 4. Frontend approach

- Server-rendered Jinja2 + a single CSS theme (dark, "dev-tool" aesthetic).
- [htmx](https://htmx.org) (CDN) used only for progressive enhancement — the
  Overview "Refresh" button swaps the stat cards in place; every element flows
  back to a plain GET/link when JS is unavailable.
- No framework build step; the dashboard runs from `uv run critiq-api`.

---

## 5. Non-goals (for now)

- Auth/teams/billing around the dashboard
- Pagination beyond current limits (runs capped at 100, modules at 40)
- Write/configuration UI (editing `.critiq.yml`, approving reviews)
- Real-time updates (no websockets/SSE)

---

## 6. Future (V3)

- Index health: staleness vs. HEAD, reindex trigger
- Charts for finding density over time