# AGENTS.md

## Project

**Critiq** — "The Staff Engineer in your GitHub PR." A GitHub App that reviews
pull requests with evidence-backed, Staff Engineer–level feedback.

## Docs

All product and architecture decisions live in `docs/specs/`. Read the relevant
spec before changing behavior. Do not duplicate decisions in comments.

- `docs/specs/PRD.md` — product requirements & scope
- `docs/specs/architecture.md` — system/components/module layout
- `docs/specs/review-pipeline.md` — pipeline, evidence, quality gate
- `docs/specs/data-model.md` — entities + DB
- `docs/specs/api.md` — endpoints, webhook & LLM contracts
- `docs/specs/github-app-setup.md` — App creation, permissions, tunnel
- `docs/specs/configuration.md` — `.critiq.yml` schema
- `docs/specs/llm-providers.md` — provider abstraction (OpenRouter)
- `docs/specs/evaluation.md` — eval dataset + metrics
- `docs/specs/roadmap.md` — V1/V2/V3

## Stack

- Python 3.12+ (uv), FastAPI, PostgreSQL, Redis + Arq
- GitHub App + webhooks + REST/GraphQL APIs
- LLM provider abstraction, default OpenRouter
- Tree-sitter; Semgrep optional/pluggable
- Docker Compose for local infra

## Conventions

- No code comments unless necessary; prefer readable names.
- Provider-agnostic LLM layer; never hardcode a single vendor.
- Findings must be evidence-backed; prioritize precision over volume.
- Config via env vars (`.env`, see `.env.example`) + repo `.critiq.yml`.
- Async-first (FastAPI async + Arq).

## Status

Phase 1: documentation/specs complete. Implementation (Phase 2) not started.
