# Critiq — LLM Providers

> Document type: model/provider specification
> Related: `api.md` (LLM contract), `configuration.md` (model routing)

---

## 1. Overview

Critiq is **provider-agnostic**. All model access flows through an
`LLMProvider` interface. The V1 implementation targets **OpenRouter**, which
gives access to many models through a single OpenAI-compatible endpoint, but the
abstraction means the product is never hardcoded to one vendor.

---

## 2. Provider Interface

```
class LLMProvider(Protocol):
    async def generate(
        self,
        *,
        system: str,
        user: str,
        schema: dict | None = None,
    ) -> dict: ...
```

- `system`: system prompt.
- `user`: the user message (context + task).
- `schema`: optional JSON schema for **structured output**.

Returns structured `dict` (parsed from the model response).

---

## 3. OpenRouterProvider

- **Endpoint:** `POST https://openrouter.ai/api/v1/chat/completions`
- **Auth:** `Authorization: Bearer <CRITIQ_OPENROUTER_API_KEY>`
- **Compatibility:** OpenAI chat-completions request/response format.
- **Structured output:** uses `response_format: { type: "json_schema", json_schema: {...} }`
  where the provider supports it; falls back to JSON mode/prompt-guidance.

### Model selection

OpenRouter accepts model identifiers (e.g. `openrouter/auto`, or a specific
model like `anthropic/claude-sonnet`). Critiq routes:

- **Cheap model** → classification, context selection, deterministic-ish tasks.
- **Strong model** → architecture/correctness reasoning and final synthesis.

Routing is configurable via `.critiq.yml` `model_routing`.

---

## 4. Structured Output Schema

Reviewers emit findings conforming to a shared JSON schema:

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
      "explanation": "This external call executes inside the request lifecycle.",
      "evidence": "Invoked directly by POST /evaluation.",
      "recommendation": "Add a provider-level timeout."
    }
  ]
}
```

Using structured output avoids brittleness in parsing free-form text.

---

## 5. Model Strategy (Cost & Quality)

Do **not** use the strongest/most expensive model for everything.

| Task | Model tier |
| ---- | ---------- |
| Classification / context selection | cheap |
| Static finding categorization | cheap |
| Architecture / correctness | strong |
| Final synthesis (Staff narrative) | strong |

This controls cost toward the **~$0.05–$0.30 per PR** target.

---

## 6. Plugging In Other Providers

A new provider implements `LLMProvider` and is registered in the provider
factory. No change to reviewers or the synthesizer is needed.

```
LLMProvider
├── OpenRouterProvider   # V1 default
├── (Future) AnthropicProvider
└── (Future) LocalProvider
```

For offline/testing, a `LocalProvider` (or a deterministic mock) can accept a
recorded response so the pipeline runs without network/API cost.

---

## 7. Reliability & Fallbacks

- Retry transient provider errors with backoff.
- Timeout provider calls to avoid hanging the review job.
- On provider failure, fall back to static-only findings (no LLM) where safe.
- Log model + token usage for cost tracking.
