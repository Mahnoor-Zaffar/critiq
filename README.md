# Critiq

**The Staff Engineer in your GitHub PR.**

Critiq is a GitHub App that reviews pull requests with evidence-backed,
Staff Engineer–level feedback — directly inside GitHub. It understands the
change, understands the surrounding system, finds what matters, and explains why.

## Status

Phase 1 (design/docs) is complete. See the specs below. Phase 2 (implementation)
is not started.

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

## Conventions

See [`AGENTS.md`](AGENTS.md).
