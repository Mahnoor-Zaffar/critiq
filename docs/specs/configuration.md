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

  profile: team-security     # optional — named team profile to overlay (CRITIQ_PROFILES_DIR)

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

  rules:                     # custom engineering rules (V2)
    - id: no-todo-in-prs
      name: No TODO comments in PRs
      description: >
        TODO/FIXME comments must be filed as issues, not left in code.
      severity: low
      categories: [correctness]
      path: "**/*.py"
      patterns:
        - "TODO"
        - "FIXME"

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
| `profile` | — | Named team profile to overlay (see §2a) |
| `severity_threshold` | `medium` | Drop findings below this severity |
| `confidence_threshold` | `0.85` | Drop findings below this confidence |
| `max_comments` | `10` | Upper bound on posted inline comments |
| `categories.*` | all `true` | Enable/disable review dimensions |
| `rules` | `[]` | Custom engineering rules (see §2b) |
| `style.*` | `false` | Style/naming checks (kept off in V1) |
| `model_routing` | defaults | Cheap vs strong model mapping |
| `languages` | `[python]` | Supported languages to review |

### 2a. Team Profiles (`CRITIQ_PROFILES_DIR`)

A directory of YAML profile files applied across repos. Profiles supply
defaults that repos can override.

- Set `CRITIQ_PROFILES_DIR` to a directory of `*.yml` files (e.g. `profiles/team-security.yml`).
- A repo references a profile by name: `review.profile: team-security`.
- Merge precedence: **defaults ← profile ← `.critiq.yml`** (repo wins at every level).
- Unknown profile names fall back to the repo config alone (review never blocks on a missing profile).

### 2b. Custom Rules (`review.rules`)

Each rule has:

| Field | Required | Description |
| ----- | -------- | ----------- |
| `id` | yes | Unique identifier |
| `name` | no | Readable name (defaults to `id`) |
| `description` | yes | Natural language description; injected into LLM reviewer prompts |
| `severity` | no | `critical` / `high` / `medium` / `low` (default `medium`) |
| `categories` | no | Which reviewers enforce this (default: all) |
| `path` | no | Glob for affected files (default `**/*`) |
| `patterns` | no | Regex patterns matched against added lines (deterministic) |

Rules are enforced two ways:
1. **Deterministic** — patterns are matched against added lines; violations become findings.
2. **LLM-injected** — descriptions are appended to the relevant reviewer prompts so the LLM can catch semantic violations.

Invalid rules (bad regex, missing fields) are skipped with a logged warning.

---

## 3. Environment Config

Provided via environment variables (see `.env.example`). Used by `core/config.py`
(Pydantic settings). Includes GitHub App credentials, OpenRouter key, DB/Redis
URLs, and model pointers.

---

## 4. Precedence

1. `.critiq.yml` overrides defaults for review behavior.
2. If `.critiq.yml` declares `review.profile`, the named profile's values are
   loaded first; repo values win at every level.
3. Env vars supply secrets/infra and global defaults.
4. Explicit CLI flags (dev tooling) can override in the worker.

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

Team-standard severity presets (e.g. `security: strict`) that tighten
per-category thresholds, layered on top of custom rules and profiles.
