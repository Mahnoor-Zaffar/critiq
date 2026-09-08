# Critiq — Review Pipeline

> Document type: pipeline specification
> Related: `PRD.md` (FR-2..FR-7), `architecture.md`

---

## 1. Overview

The review pipeline is the core of Critiq. It is designed to produce **fewer,
better, evidence-backed comments** rather than a high volume of generic feedback.

The pipeline runs as an Arq task in the worker:

```
1.  Parse PR
2.  Identify changed symbols
3.  Find relevant dependencies
4.  Retrieve relevant repository context
5.  Run deterministic analyzers
6.  Generate independent findings
7.  Remove duplicate findings
8.  Validate evidence
9.  Score severity
10. Score confidence
11. Reject weak findings
12. Staff Engineer synthesis
13. Generate GitHub comments
```

---

## 2. Pipeline Stages

### Stage 1 — Parse PR
Fetch PR metadata, changed files, and diff. Resolve added/removed lines and the
base/head refs.

### Stage 2 — Identify Changed Symbols
Use Tree-sitter AST to extract the functions, classes, imports, and module
symbols touched by the diff. This anchors downstream analysis.

### Stage 3 — Find Relevant Dependencies
Walk the repository graph to find callers/callees, imports, shared modules, and
related tests for each changed symbol.

### Stage 4 — Retrieve Relevant Repository Context
Only the relevant subgraph (not the whole repo) is passed to the LLM. Avoids
token explosion and focuses the model.

### Stage 5 — Run Deterministic Analyzers
Run static checks (Tree-sitter, optional Semgrep) that produce deterministic
findings (e.g. hardcoded secrets, dangerous subprocess, SQL injection patterns,
insecure deserialization).

### Stage 6 — Generate Independent Findings
Each of the six reviewers (Correctness, Security, Architecture, Reliability,
Performance, Testing) emits structured `Finding`s. Specialized passes rather
than six autonomous agents keep cost/complexity down initially.

### Stage 7 — Remove Duplicate Findings
Merge overlapping findings across reviewers, keeping the strongest evidence.

### Stage 8 — Validate Evidence
Confirm each finding cites real repository evidence (file + line exists,
referenced symbol is genuinely related). Unsupported findings are discarded.

### Stage 9 — Score Severity
Map finding to `CRITICAL` / `HIGH` / `MEDIUM` / `LOW`.

### Stage 10 — Score Confidence
Assign `HIGH` / `MEDIUM` / `LOW` (or a 0–1 score). Low-confidence findings are
dropped rather than posted.

### Stage 11 — Reject Weak Findings
A finding must clear both the **evidence gate** and the **confidence gate**
before reaching GitHub. See the Quality Gate below.

### Stage 12 — Staff Engineer Synthesis
The strong model produces the final narrative: overall decision, summary,
prioritized P0/P1/P2 issues with impact and effort, and what a Staff Engineer
would actually do first.

### Stage 13 — Generate GitHub Comments
Convert findings into GitHub review comments (file + line ranges) and the
summary body.

---

## 3. Review Dimensions

| Dimension | Focus |
| --------- | ----- |
| **Correctness** | Logic errors, incorrect assumptions, race conditions, edge cases, state inconsistencies |
| **Security** | Auth, authorization, injection, secrets, unsafe input, data exposure, dependency vulnerabilities |
| **Architecture** | Coupling, separation of concerns, abstraction violations, dependency direction, poor boundaries, regressions |
| **Reliability** | Missing retries/timeouts, failure handling, idempotency, transaction handling, resource exhaustion |
| **Performance** | N+1 queries, blocking operations, excessive API calls, memory problems, inefficient algorithms |
| **Testing** | Missing tests, weak assertions, missing edge cases, regression risk |

---

## 4. Evidence Validation

A finding must answer **"why do you think this is a problem?"** with concrete
context.

```
Finding
 ├── File
 ├── Line(s)
 ├── Evidence       # e.g. "line 87 performs a synchronous external API call"
 ├── Reasoning
 ├── Severity
 ├── Confidence
 └── Recommendation
```

**Failure mode to avoid** (hallucinated architecture):

> Bad: "This might cause scalability issues."

**Desired behavior**:

> `evaluation_service.py:87` performs a synchronous external API call. It is
> invoked directly by `POST /evaluation`, so the HTTP request remains open until
> the provider responds.

---

## 5. Severity Classification

| Level | Meaning |
| ----- | ------- |
| 🔴 **Critical** | Security vulnerability, data corruption, severe correctness problem |
| 🟠 **High** | Likely production issue or significant architectural/reliability problem |
| 🟡 **Medium** | Meaningful maintainability, performance, testing, or correctness concern |
| 🔵 **Low** | Non-blocking improvement |

V1 avoids `LOW` comments by default to maximize signal.

---

## 6. Confidence Classification

Confidence is `HIGH` / `MEDIUM` / `LOW`. The confidence gate is the primary
mechanism for reducing AI noise. Exact thresholds should come from evaluation
data (see `evaluation.md`) rather than intuition.

---

## 7. Quality Gate

Before a finding reaches GitHub:

```
                Finding
                   │
                   ▼
          Is there evidence?
             /          \
           NO            YES
           ↓              ↓
        DISCARD      Is impact meaningful?
                       /       \
                     NO         YES
                     ↓           ↓
                  DISCARD   Confidence ≥ threshold?
                               /    \
                             LOW     HIGH
                             ↓        ↓
                          DISCARD   POST
```

This gate is the most important component of the product.

---

## 8. Findings Model

A finding is the unit of review. Two-plus structural shapes:

- **Line-level:** specific lines in a changed file (e.g. `auth.py:42`).
- **File-level:** an entire changed file (e.g. "this file now owns provider
  communication, prompt construction, parsing, persistence, and retry handling").
- **PR-level:** overall summary (decision, risk, blocking issues).

---

## 9. Review Decision

`APPROVE` / `COMMENT` / `REQUEST CHANGES`. V1 defaults to `COMMENT` so the
system never blocks a PR prematurely.

---

## 10. Cost Controls

- Send the relevant **subgraph**, not the whole repository.
- Use a **cheap model** for classification/context selection/static findings.
- Use a **strong model** for architecture/correctness and final synthesis.
- Cache token-heavy context where possible.
- Run reviewer passes in parallel where independent.
- Use structured outputs (JSON schema) to avoid parsing cost/errors.

---

## 11. Example: Pipeline Output

**Input PR:** "Add asynchronous interview evaluation"
Changed: `evaluation_service.py`, `tasks.py`, `interview.py`, `models.py`,
`test_evaluation.py`.

**Change map:**
```
API → Interview Service → Evaluation Service → Background Worker → LLM Provider → DB
```

**Findings (after quality gate):**

- 🟠 HIGH · Reliability — `evaluation_service.py:87` synchronous LLM call with no
  timeout, invoked inside the request lifecycle.
- 🔴 CRITICAL · Security — missing authorization on `/api/interview` routes.
- 🟡 MEDIUM · Testing — no test for provider timeout path.

**Summary:**
```
Decision: REQUEST CHANGES
Risk: HIGH
2 high-confidence issues, 3 non-blocking recommendations
```
