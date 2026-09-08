# Critiq — Product Requirements Document (PRD)

> Status: MVP Specification
> Version: 1.0
> Working name: **Critiq**
> Positioning: **"The Staff Engineer in your GitHub PR."**
> Primary interface: **GitHub App**
> LLM provider: **OpenRouter** (provider-agnostic behind an abstraction)

---

## 1. Product Summary

Critiq is a GitHub App that automatically reviews pull requests and provides
**Staff Engineer–level feedback** directly inside GitHub.

It analyzes the PR diff in the context of the surrounding codebase, identifies
meaningful engineering risks, assigns severity and confidence, and posts review
comments against the specific files and lines where issues occur.

The goal is **not** maximum comment volume. The goal is:

> Fewer, higher-quality comments that a strong human engineer would actually make.

The core quality loop:

```
Understand → Analyze → Find → Prove → Prioritize → Comment
```

If **Prove** is weak, Critiq becomes a noisy AI reviewer. If **Prove + Prioritize**
are excellent, Critiq becomes something far more valuable.

---

## 2. Problem

Existing automated code review falls into three categories:

| Approach            | Strength                                        | Weakness                                           |
| ------------------- | ----------------------------------------------- | -------------------------------------------------- |
| Static analysis     | Excellent at deterministic issues               | Poor at architectural reasoning                    |
| AI code review      | Can identify issues                             | Generic/low-value comments, often without context  |
| Human review        | High quality                                    | Expensive and slow                                 |

Developers need something **between** automated linting and a senior engineer.

A PR reviewer should understand:

1. **What changed?**
2. **Why was it changed?**
3. **How does it interact with the existing system?**
4. **Could it break something?**
5. **Will it scale?**
6. **Is it maintainable?**
7. **What actually deserves a comment?**

---

## 3. Product Goal

Automatically produce a PR review that approximates the quality and reasoning
style of an experienced Staff Engineer.

### Success criteria

A successful review should:

- Identify meaningful correctness problems
- Identify security vulnerabilities
- Identify architectural problems
- Identify reliability risks
- Understand repository context
- Reference concrete evidence
- Comment on exact lines/files
- Avoid trivial stylistic feedback
- Prioritize findings
- Explain **why** something matters
- Provide actionable recommendations
- Know when **not** to comment

---

## 4. Non-Goals

The MVP will **not** attempt to:

- Replace human code review completely
- Automatically modify code
- Automatically merge PRs
- Act as a generic coding assistant
- Replace linters
- Review every line of every PR
- Comment on formatting/style
- Make subjective comments without evidence
- Guarantee that every finding is correct

Critiq is a **reviewer**, not an autonomous developer.

---

## 5. Target User

**Primary:** Backend/full-stack software engineers working with GitHub.

**Secondary:**

- Engineering teams
- Startup engineering teams
- Open-source maintainers
- Engineering managers
- Tech leads

---

## 6. Core User Journey

```
Developer
   │  Opens PR
   ▼
GitHub
   │  Webhook
   ▼
Critiq
   ├── Fetch PR
   ├── Fetch diff
   ├── Inspect repository
   ├── Analyze dependencies
   ├── Run static analysis
   └── Build context
           │
           ▼
      AI Review Engine
           │
      ┌────┼─────┐
      ▼    ▼     ▼
 Correctness Security Architecture
 Performance Reliability  Testing
      │
      ▼
   Evidence Validator
      │
      ▼
   Severity + Confidence
      │
      ▼
   Review Synthesizer
      │
      ▼
   GitHub PR Review
```

---

## 7. Functional Requirements

### FR-1: GitHub Integration

Users install the GitHub App on personal repositories, selected repositories,
or organizations. The application receives `pull_request` events:
`opened`, `synchronize`, `reopened`.

### FR-2: PR Ingestion

For each PR, collect:

- **PR metadata:** repository, number, author, title, description, base/head branch
- **Code:** changed files, diff, added/removed lines, relevant surrounding code
- **Repository context:** directory structure, related modules, imports, callers,
  tests, configuration, dependency files, README, architecture docs where available

Critiq should **not** ingest the entire repository blindly. Context is selected
based on relevance.

### FR-3: Diff Analysis

Determine what the PR is actually changing. Build a **change map** (e.g.
`API → Service → Worker → Provider → DB`) as context for later reviewers.

### FR-4: Multi-Dimensional Review

Six dimensions in V1:

1. **Correctness** — logic errors, incorrect assumptions, race conditions, edge cases, state inconsistencies
2. **Architecture** — coupling, separation of concerns, abstraction violations, dependency direction, poor boundaries, regressions
3. **Security** — authentication, authorization, injection, secrets, unsafe input, data exposure, dependency vulnerabilities
4. **Reliability** — missing retries/timeouts, failure handling, idempotency, transaction handling, resource exhaustion
5. **Performance** — N+1 queries, blocking operations, excessive API calls, memory problems, inefficient algorithms
6. **Testing** — missing tests, weak assertions, missing edge cases, regression risk

Deliberately **excluded** from V1 categories: naming, formatting, style.

### FR-5: File-Level Reviews

Critiq can review an entire changed file, e.g. flagging that a single module now
owns prompt construction, LLM communication, retry handling, parsing, and
persistence (high coupling between domain and infrastructure).

### FR-6: Line-Level Reviews

Comments attach to the relevant GitHub diff line. Each comment includes:

- Severity
- Finding
- Evidence
- Impact
- Recommendation
- Confidence

### FR-7: Evidence-Based Findings

Every meaningful finding must cite repository evidence.

> Bad: "This might cause scalability issues."
>
> Good: `evaluation_service.py:87` performs a synchronous external API call. The
> endpoint is invoked directly by `POST /evaluation`, meaning the HTTP request
> remains open until the provider responds.

Internal finding model:

```
Finding
 ├── File
 ├── Line(s)
 ├── Evidence
 ├── Reasoning
 ├── Severity
 └── Confidence
```

### FR-8: Severity Classification

| Level | Meaning |
| ----- | ------- |
| 🔴 **Critical** | Security vulnerability, data corruption, severe correctness problem |
| 🟠 **High** | Likely production issue or significant architectural/reliability problem |
| 🟡 **Medium** | Meaningful maintainability, performance, testing, or correctness concern |
| 🔵 **Low** | Non-blocking improvement |

V1 avoids low-severity comments by default.

### FR-9: Confidence Classification

Every finding receives `HIGH` / `MEDIUM` / `LOW`. Low-confidence findings are
generally discarded rather than posted (a key mechanism for reducing AI noise).

### FR-10: Review Policy

Configurable via `.critiq.yml` (see `configuration.md`).

### FR-11: Final PR Summary

After inline comments, Critiq posts a summary with a **Decision**
(APPROVE / COMMENT / REQUEST CHANGES), summary of findings, blocking issues,
architecture notes, testing coverage, and overall risk.

### FR-12: Review Decision

Supports `APPROVE`, `COMMENT`, `REQUEST CHANGES`. V1 defaults to `COMMENT` to
avoid blocking early PRs.

### FR-13: Human-in-the-Loop

Three modes: **Automatic** (AI → GitHub), **Approval** (AI → Human → GitHub),
**Advisory** (AI → report only). V1 default: Automatic.

---

## 8. Suggested Stack

- **Backend:** Python 3.12+, FastAPI, PostgreSQL, Redis, Arq
- **Code analysis:** Tree-sitter, Semgrep (optional/pluggable)
- **LLM:** Provider abstraction (`LLMProvider`) with an **OpenRouter** implementation; strong model for synthesis, cheap model for classification
- **Frontend:** None in V1 (GitHub is the UI)
- **GitHub:** GitHub App + Webhooks + REST/GraphQL APIs
- **Infra:** Docker, uv

---

## 9. Cost Model

- Target: **~$0.05–$0.30 per review** depending on context size and model choice.
- Infrastructure for early MVP: **~$20–$50/month** before significant usage.

Cost controls: context filtering, caching, parallel analysis, model routing,
structured outputs, small models for deterministic tasks.

---

## 10. MVP Scope

### V1 must have

- GitHub App
- PR webhooks (`opened`/`synchronize`/`reopened`)
- Diff extraction
- Repository context retrieval
- Python/backend support
- Static analysis (Tree-sitter, optional Semgrep)
- AI review pipeline
- File-level analysis
- Line-level comments
- Severity + confidence
- Evidence
- PR summary
- `.critiq.yml` configuration
- Automatic GitHub posting

### V1 does NOT need

- Dashboard
- Billing
- Teams
- Multi-provider UI
- Mobile app
- Automatic code fixes
- Complex RAG infrastructure
- 20 programming languages

---

## 11. Success Metrics

Do **not** measure success by number of comments.

| Metric | Target |
| ------ | ------ |
| **Precision** (valid findings / total) | >85% |
| **Useful finding rate** (comments devs would keep) | >70% |
| **False-positive rate** | <15% |
| **Coverage** (meaningful PR risks detected) | >60% initially |
| **Human intervention** | <5 min / 100 PRs in automatic mode |

The product optimizes primarily for **precision**.

---

## 12. Evaluation Dataset

Collect real PRs and manually label findings (`valid`/`invalid`, severity,
category, human action). Benchmark Critiq against experienced engineers; see
`evaluation.md`.

---

## 13. Biggest Technical Risks

1. **AI review spam** — mitigate with evidence requirement, confidence/severity
   thresholds, dedup, explicit "don't comment" policy.
2. **Insufficient repository context** — build a lightweight dependency graph.
3. **Hallucinated architecture** — require findings to cite real repo evidence.
4. **Token explosion** — send the relevant subgraph, not the whole repository.
5. **GitHub API complexity** — abstract line-level comment positioning early
   (`ReviewComment(file, start_line, end_line, body)`).

---

## 14. Product Thesis

Critiq is not trying to review more code than humans. It is trying to make
**fewer, better engineering comments.**

The core quality loop is:

```
Understand → Analyze → Find → Prove → Prioritize → Comment
```

If **Prove** is weak, Critiq becomes another noisy AI reviewer.
If **Prove + Prioritize** are excellent, you have something much more compelling.
