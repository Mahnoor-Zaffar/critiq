# Critiq — API Specification

> Document type: API / contract specification
> Related: `architecture.md`, `github-app-setup.md`, `llm-providers.md`

---

## 1. Overview

Critiq exposes a small FastAPI surface. The primary interface is GitHub; the
API exists to accept webhooks, enqueue jobs, expose read/status endpoints, and
(V2) serve a read-only dashboard at `/dashboard` (see `dashboard.md`).

---

## 2. FastAPI Endpoints

### POST `/webhooks/github`

Receives GitHub webhook deliveries (primarily `pull_request` events).

- **Headers:** `X-GitHub-Event`, `X-GitHub-Delivery`, `X-Hub-Signature-256`
- **Body:** raw JSON delivery payload
- **Verification:** HMAC SHA-256 signature using the webhook secret
- **Behavior:**
  - For `pull_request` events with action `opened` / `synchronize` /
    `reopened`, enqueue a `review_pull_request` job.
  - Respond `200` (GitHub) even if we queue asynchronously.
- **Responses:**
  - `200` — accepted
  - `401` — invalid signature

### GET `/health`

Liveness probe. Returns service status + DB/Redis connectivity.

### GET `/runs/{run_id}`

Returns the status and metadata of a review run (dashboard-lite).

```
{
  "id": "...",
  "status": "running",
  "decision": null,
  "overall_score": null,
  "summary": null,
  "findings": [...]
}
```

### GET `/reviews/{review_id}`

Returns a generated review report.

---

## 3. GitHub Webhook Contract

### Event: `pull_request`

Actions handled: `opened`, `synchronize`, `reopened`.

```json
{
  "action": "opened",
  "number": 142,
  "pull_request": {
    "id": 987654321,
    "title": "Add async interview evaluation",
    "body": "...",
    "state": "open",
    "head": { "sha": "abc123", "ref": "feature/eval" },
    "base": { "sha": "def456", "ref": "main" },
    "user": { "login": "john-doe" },
    "changed_files": 5,
    "additions": 632,
    "deletions": 91
  },
  "repository": {
    "id": 123456789,
    "full_name": "john-doe/fastapi-chatbot",
    "default_branch": "main"
  },
  "installation": { "id": 555 }
}
```

**Signature verification:** HMAC-SHA256 of the raw body using the GitHub App's
webhook secret, hex-encoded, compared against `X-Hub-Signature-256`.

---

## 4. LLM Contract (OpenRouter)

OpenRouter exposes an OpenAI-compatible
`POST https://openrouter.ai/api/v1/chat/completions`.

### Request

```json
{
  "model": "openrouter/auto",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." }
  ],
  "response_format": { "type": "json_schema", "json_schema": { ... } }
}
```

Critiq's `LLMProvider` abstracts this so the product is not hardcoded to one
provider.

### Structured Output

Findings are emitted as JSON matching the internal schema:

```json
{
  "findings": [
    {
      "category": "reliability",
      "file_path": "services/evaluation.py",
      "line_start": 87,
      "line_end": 87,
      "severity": "high",
      "confidence": 0.94,
      "title": "Synchronous LLM call without timeout",
      "explanation": "...",
      "evidence": "...",
      "recommendation": "..."
    }
  ]
}
```

### Provider Interface (conceptual)

```
class LLMProvider(Protocol):
    async def generate(
        self, *, system: str, user: str, schema: dict | None
    ) -> dict: ...
```

Implementations: `OpenRouterProvider` (default), plus a pluggable `LocalProvider`
for offline/testing.

---

## 5. GitHub API Calls Used

- `POST /repos/{owner}/{repo}/pulls/{n}/reviews` — create a review (body + comments)
- `GET /repos/{owner}/{repo}/pulls/{n}` — PR metadata
- `GET /repos/{owner}/{repo}/pulls/{n}/files` — changed files + patch
- `GET /repos/{owner}/{repo}/contents/{path}` — file contents
- `GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1` — repo tree
- `POST /app/installations/{id}/access_tokens` — installation access token

---

## 6. Auth Scope

- **GitHub App authentication:** App JWT (RS256) → installation access token.
- **LLM:** OpenRouter API key via `Authorization: Bearer`.
