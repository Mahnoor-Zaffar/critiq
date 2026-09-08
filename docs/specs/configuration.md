# Critiq — Configuration

> Document type: configuration specification
> Related: `api.md`, `review-pipeline.md`, `llm-providers.md`

---

## 1. Overview

Critiq has two configuration layers:

1. **Environment** (runtime/global secrets & infra) — `.env`, see `.env.example`.
2. **Repository** (per-repo review behavior) — `.critiq.yml` checked into the repo.

---

## 2. Repository Config: `.critiq.yml`

Placed at the repo root. Optional; if absent, defaults are used.

```yaml
# .critiq.yml
review:
  mode: automatic            # automatic | approval | advisory

  severity_threshold: medium # lowest severity to consider (critical/high/medium)

  confidence_threshold: 0.85 # gate for posting to GitHub

  max_comments: 10           # cap on posted line comments (reduce noise)

  categories:
    correctness: true
    security: true
    architecture: true
    reliability: true
    performance: true
    testing: true

  style:
    naming: false            # excluded from V1
    formatting: false

  model_routing:
    cheap: openrouter/auto   # classification, context selection
    strong: openrouter/auto  # architecture/correctness, synthesis

  languages:
    - python                 # V1 supported languages
```

### Field descriptions

| Field | Default | Description |
| ----- | ------- | ----------- |
| `mode` | `automatic` | Human-in-the-loop mode |
| `severity_threshold` | `medium` | Drop findings below this severity |
| `confidence_threshold` | `0.85` | Drop findings below this confidence |
| `max_comments` | `10` | Upper bound on posted inline comments |
| `categories.*` | all `true` | Enable/disable review dimensions |
| `style.*` | `false` | Style/naming checks (kept off in V1) |
| `model_routing` | defaults | Cheap vs strong model mapping |
| `languages` | `[python]` | Supported languages to review |

---

## 3. Environment Config

Provided via environment variables (see `.env.example`). Used by `core/config.py`
(Pydantic settings). Includes GitHub App credentials, OpenRouter key, DB/Redis
URLs, and model pointers.

---

## 4. Precedence

1. `.critiq.yml` overrides defaults for review behavior.
2. Env vars supply secrets/infra and global defaults.
3. Explicit CLI flags (dev tooling) can override in the worker.

---

## 5. Policy Defaults

If `.critiq.yml` is absent, the system uses:

```yaml
mode: automatic
severity_threshold: medium
confidence_threshold: 0.85
categories: all true
max_comments: 10
```

---

## 6. Future

Behind this config, teams can later encode custom engineering standards
(e.g. `security: strict`), which the reviewers check PRs against.
