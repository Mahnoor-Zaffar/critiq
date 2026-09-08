# Critiq — Data Model

> Document type: database / entity specification
> Storage: PostgreSQL (SQLAlchemy async ORM + Alembic migrations)
> Related: `architecture.md`, `api.md`

---

## 1. Overview

Critiq persists installation state, repositories, pull requests, review runs,
findings, and review policies. Entities are scoped so that one GitHub App
installation can manage many repositories and PRs.

---

## 2. Entities

### Installation

Represents a GitHub App installation on an account (user or org).

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | PK | |
| `github_installation_id` | bigint, unique | GitHub's installation id |
| `account_login` | str | Owner account login |
| `account_type` | enum | `User` / `Organization` |
| `access_token` | str | Last cached installation token |
| `token_expires_at` | datetime | |
| `created_at` | datetime | |

### Repository

A repository where Critiq is installed.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | PK | |
| `installation_id` | FK → Installation | |
| `github_repo_id` | bigint, unique | |
| `full_name` | str | `owner/repo` |
| `default_branch` | str | |
| `last_analyzed_at` | datetime, nullable | |
| `created_at` | datetime | |

### PullRequest

Represents a single pull request.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | PK | |
| `repository_id` | FK → Repository | |
| `github_pr_number` | int | |
| `title` | str | |
| `author_login` | str | |
| `base_branch` | str | |
| `head_branch` | str | |
| `head_sha` | str | |
| `state` | enum | `open` / `closed` / `merged` |
| `created_at` | datetime | |
| `updated_at` | datetime | |

Unique: `(repository_id, github_pr_number)`.

### ReviewRun

One execution of the pipeline for a PR.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | PK | |
| `pull_request_id` | FK → PullRequest | |
| `status` | enum | `pending` / `running` / `success` / `failed` / `approved` |
| `mode` | enum | `automatic` / `approval` / `advisory` |
| `overall_score` | numeric, nullable | 0–10 |
| `decision` | enum, nullable | `approve` / `comment` / `request_changes` |
| `summary` | text, nullable | Markdown summary posted to GitHub |
| `started_at` | datetime, nullable | |
| `completed_at` | datetime, nullable | |
| `error` | text, nullable | |

### Finding

A single finding emitted by a reviewer and (optionally) posted.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | PK | |
| `review_run_id` | FK → ReviewRun | |
| `category` | enum | `correctness` / `security` / `architecture` / `reliability` / `performance` / `testing` |
| `file_path` | str | |
| `line_start` | int, nullable | |
| `line_end` | int, nullable | |
| `severity` | enum | `critical` / `high` / `medium` / `low` |
| `confidence` | numeric | 0–1 |
| `title` | str | |
| `explanation` | text | |
| `evidence` | text | |
| `recommendation` | text | |
| `source` | enum | `static` / `llm` |
| `posted` | bool | Whether it was posted to GitHub |
| `created_at` | datetime | |

### ReviewPolicy

Repo-specific `.critiq.yml` settings, parsed and cached.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | PK | |
| `repository_id` | FK → Repository, unique | |
| `severity_threshold` | enum | lowest severity to consider |
| `confidence_threshold` | numeric | 0–1 |
| `categories_enabled` | jsonb | per-category booleans |
| `mode` | enum | `automatic` / `approval` / `advisory` |
| `model_routing` | jsonb | cheap vs strong model mapping |
| `updated_at` | datetime | |

---

## 3. Relationships

```
Installation 1 ── * Repository 1 ── * PullRequest 1 ── * ReviewRun 1 ── * Finding
                      │                                    │
                      └── * ReviewPolicy                   └── mode/decision
```

---

## 4. Mappings

- `ReviewRun.mode`, `Finding.category`, `Finding.severity` are Python `Enum`s.
- `ReviewPolicy.categories_enabled` and `model_routing` are JSONB.
- All timestamps use UTC.

---

## 5. Migration Strategy

- Alembic manages schema changes.
- Initial migration creates all tables above.
- Indexes: `ReviewRun(pull_request_id)`, `Finding(review_run_id)`,
  `PullRequest(repository_id, github_pr_number)` (unique),
  `Repository(installation_id)`.

---

## 6. Result Types (runtime, not persisted separately)

`ReviewComment` is the portable structure used to render GitHub line comments,
decoupled from GitHub's API shape:

```
ReviewComment(file, start_line, end_line, body)
```

`ReviewResult` carries the overall decision, summary, and the assembled
`ReviewComment`s.
