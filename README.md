# Critiq

**The Staff Engineer in your GitHub PR.**

Critiq is a GitHub App that reviews pull requests with evidence-backed,
Staff Engineer–level feedback — directly inside GitHub. It understands the
change, understands the surrounding system, finds what matters, and explains why.

## Status

Phase 1 (docs), Phase 2 (full GitHub App pipeline), and Phase 3 (repository
intelligence + evaluation harness) are complete.

The full architecture is implemented: GitHub App auth + webhooks, diff parsing,
repo context graph + persistent index, static + LLM review pipeline, quality
gate, GitHub review posting, and an evaluation harness that measures
precision/recall/false-positive rate against labeled data.

## Docs

All product and architecture decisions live in [`docs/specs/`](docs/specs/):

- [PRD](docs/specs/PRD.md) — product requirements & scope
- [Architecture](docs/specs/architecture.md) — system & module layout
- [Review pipeline](docs/specs/review-pipeline.md) — pipeline, evidence, quality gate
- [Data model](docs/specs/data-model.md) — entities & DB
- [API](docs/specs/api.md) — endpoints & contracts
- [GitHub App setup](docs/specs/github-app-setup.md) — App creation & webhook
- [Configuration](docs/specs/configuration.md) — `.critiq.yml` schema
- [LLM providers](docs/specs/llm-providers.md) — provider abstraction (OpenRouter)
- [Evaluation](docs/specs/evaluation.md) — eval dataset & metrics
- [Roadmap](docs/specs/roadmap.md) — V1/V2/V3

## Stack

Python 3.12+ · FastAPI · PostgreSQL · Redis + Arq · GitHub App · Tree-sitter ·
OpenRouter (provider-agnostic).

## Getting started

### Setup

1. Create a GitHub App and add credentials + OpenRouter key to `.env`
   (see `.env.example` and [`docs/specs/github-app-setup.md`](docs/specs/github-app-setup.md)).
2. Copy `.critiq.yml.sample` to `.critiq.yml` (in a target repo) to configure
   review behavior.

### Run locally

```bash
# Install deps (uv)
uv sync

# Start Postgres + Redis
docker compose up -d postgres redis

# Create schema (dev bootstrap; use Alembic migrations for prod)
uv run critiq-init-db

# Run the API
uv run critiq-api

# Run the Arq worker (in another terminal)
uv run arq src.critiq.apps.worker.worker.WorkerSettings
```

Expose the API with a tunnel (e.g. `ngrok http 8000`) and point the GitHub App
webhook URL at `https://<tunnel>/webhooks/github`.

### Evaluation & repo indexing

```bash
# Run the evaluation harness over a labeled dataset (mock provider, no API key)
uv run critiq-evaluate datasets/sample.yml

# Build and cache a repository index (speeds context retrieval)
uv run critiq-index /path/to/repo --cache-dir .critiq-cache --key owner/repo@headsha
```

### Tests

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```

## Conventions

See [`AGENTS.md`](AGENTS.md).
