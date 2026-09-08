# Critiq — Technical Architecture

> Document type: architecture specification
> Related: `PRD.md`, `review-pipeline.md`, `api.md`, `data-model.md`

---

## 1. High-Level System

Critiq is an event-driven GitHub App. A **GitHub webhook** triggers a review
job that runs asynchronously in a worker. The worker parses the PR diff, builds
a relevant repository subgraph, runs a set of specialized reviewers, validates
evidence, scores severity/confidence, and posts a review back to GitHub.

```
                    GitHub
                       │
                   Webhooks (pull_request)
                       │
                       ▼
                FastAPI (apps/api)
                    │  verify signature
                    │  enqueue job
                    ▼
                Redis + Arq (apps/worker)
                    │
        ┌───────────┼──────────────┐
        ▼           ▼              ▼
  Diff Parser   Repo/Code Graph   Static checks
        │           │              │
        └───────────┼──────────────┘
                    ▼
             Context Builder (relevant subgraph only)
                    │
                    ▼
            6 Reviewers (specialized passes)
                    ▼
        Evidence Validator → Severity → Confidence → Dedup
                    ▼
            Staff Synthesizer (OpenRouter — strong model)
                    ▼
                GitHub API
                    │
                    ▼
                PR Review (inline comments + summary)
```

---

## 2. Components

| Component | Location | Responsibility |
| --------- | -------- | -------------- |
| **API** | `apps/api/` | FastAPI app: receives GitHub webhooks, verifies signatures, enqueues review jobs, exposes read/status endpoints |
| **Worker** | `apps/worker/` | Arq worker: consumes review jobs and runs the full pipeline |
| **Analysis** | `analysis/` | Diff parsing, AST parsing, dependency/context graph, static checks |
| **AI** | `ai/` | LLM providers, per-category reviewers, prompts, synthesizer |
| **GitHub integration** | `integrations/github/` | REST client, App auth (JWT + installation token), webhook verification |
| **Postgres** | `infrastructure/postgres/` | SQLAlchemy async models, Alembic migrations |
| **Config** | `core/` | Settings, `.critiq.yml` loading, review policy model |

---

## 3. Module Layout

```
critiq/
│
├── apps/
│   ├── api/                      # FastAPI application
│   │   ├── main.py               # app factory, routers, middleware
│   │   ├── webhooks.py           # /webhooks/github handler + signature verify
│   │   ├── routers/
│   │   │   ├── health.py         # GET /health
│   │   │   ├── runs.py           # GET /runs/{id}
│   │   │   └── reviews.py        # GET /reviews/{id}
│   │   └── deps.py               # DB/session/queue dependencies
│   │
│   └── worker/
│       ├── worker.py             # Arq worker entrypoint
│       └── tasks.py              # review_pull_request task + pipeline driver
│
├── core/
│   ├── config.py                 # Pydantic settings from env
│   ├── findings.py               # Finding dataclass/model
│   ├── scoring.py                # severity + confidence scoring logic
│   ├── policy.py                 # ReviewPolicy (parsed .critiq.yml)
│   └── result.py                 # ReviewRun result types (decision, summary)
│
├── analysis/
│   ├── diff.py                   # unified diff parser → changed files/lines
│   ├── ast.py                    # tree-sitter wrapper (Python)
│   ├── graph.py                  # lightweight dependency/call graph
│   ├── context.py                # relevance-based context builder
│   ├── static.py                 # deterministic analyzers
│   └── semgrep.py                # optional Semgrep integration (pluggable)
│
├── ai/
│   ├── providers/
│   │   ├── base.py               # LLMProvider protocol
│   │   └── openrouter.py         # OpenRouterProvider (OpenAI-compatible)
│   ├── reviewers/
│   │   ├── base.py               # Reviewer protocol (analyze → findings[])
│   │   ├── correctness.py
│   │   ├── security.py
│   │   ├── architecture.py
│   │   ├── reliability.py
│   │   ├── performance.py
│   │   └── testing.py
│   ├── prompts/
│   │   ├── correctness.txt
│   │   ├── security.txt
│   │   ├── ...
│   │   └── synthesize.txt
│   ├── context_builder.py        # assemble LLM context (subgraph)
│   ├── synthesizer.py            # merge/dedup/evidence → narrative
│   └── schemas.py                # structured output JSON schemas
│
├── integrations/
│   └── github/
│       ├── client.py             # REST/GraphQL client (fetch PR, diff, files, review)
│       ├── auth.py               # App JWT + installation access token
│       ├── webhook.py            # payload + signature verification
│       └── mapping.py            # ReviewComment → GitHub API review payload
│
├── infrastructure/
│   └── postgres/
│       ├── models.py             # SQLAlchemy async ORM entities
│       ├── session.py            # async engine/session factory
│       └── migrations/           # Alembic
│
├── tests/
│   ├── unit/                     # diff, scoring, providers, policy
│   ├── integration/              # pipeline against fixture repos
│   └── evaluation/               # accuracy dataset + metrics
│
├── .critiq.yml.sample
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## 4. End-to-End Data Flow

1. GitHub sends a `pull_request` webhook to `POST /webhooks/github`.
2. API verifies `X-Hub-Signature-256` using the webhook secret.
3. API enqueues a `review_pull_request` Arq job (async).
4. Worker fetches installation access token, PR metadata, diff, and files
   from the GitHub API.
5. `analysis/diff` parses the diff into changed files + line ranges.
6. `analysis/graph` + `analysis/context` build the relevant repository subgraph
   (imports, callers/callees, related tests, config).
7. The **six reviewers** run specialized analysis passes and emit structured
   `Finding`s.
8. `Evidence Validator` confirms each finding's cited file/lines exist and are
   relevant; weak findings are discarded.
9. `scoring` assigns severity + confidence; dedup removes overlaps.
10. The **Staff Synthesizer** (strong model) produces the final narrative, sets
    the review decision, and formats per-line comments.
11. Worker posts the review via the GitHub API (inline comments + summary body).
12. `ReviewRun`, `Finding`, and `Review` records are persisted to Postgres.

---

## 5. Async Model

- **Queue:** Redis + **Arq** (chosen over Celery for simplicity and Python-native
  typing).
- Jobs are idempotent and keyed by `(installation_id, repository_id, pr_number)`.
- Large/review-heavy PRs can be handled by a single worker initially; horizontal
  scaling is supported by adding more worker processes.

---

## 6. Configuration

All runtime config comes from environment variables (see `.env.example`),
with repository-specific overrides in `.critiq.yml` (see `configuration.md`).

---

## 7. Runtime Modes

Three human-in-the-loop modes (configurable per-repo via `.critiq.yml`):

| Mode | Flow | Notes |
| ---- | ---- | ----- |
| `automatic` | AI → GitHub | Default; posts high-confidence findings |
| `approval` | AI → Human → GitHub | Human reviews drafts before posting |
| `advisory` | AI → Report | Nothing posted automatically |

---

## 8. Deployment

- **Local dev:** `docker-compose.yml` runs Postgres, Redis, API, and worker.
  Expose the API publicly via `ngrok` or `cloudflared` so GitHub can reach the
  webhook.
- **Prod (later):** containerized services, managed Postgres/Redis, App hosting.
