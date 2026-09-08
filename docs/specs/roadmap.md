# Critiq — Roadmap

> Document type: roadmap / scope
> Related: `PRD.md` (MVP scope), `review-pipeline.md`

---

## 1. V1 — Full Pipeline, PRs Only

The primary interface is the GitHub PR itself. No dashboard.

**Must have**
- GitHub App + PR webhooks (`opened` / `synchronize` / `reopened`)
- Diff extraction + repository context retrieval
- Python/backend support
- Static analysis (Tree-sitter, optional Semgrep)
- AI review pipeline (6 dimensions)
- File-level + line-level comments
- Severity + confidence + evidence
- PR summary
- `.critiq.yml` configuration
- Automatic posting to GitHub

**Explicitly excluded in V1**
- Dashboard, billing, team management
- Automatic fixes, auto-merge
- IDE extensions, Slack integration
- 20+ languages
- Embedding/vector DB, fine-tuned model
- Autonomous code changes

---

## 2. V2 — Repository Intelligence & Policies

Once review quality is proven:

- Custom engineering policies (`.critiq.yml` extension)
- Team review profiles
- Review history
- Developer feedback loops
- **Learning from accepted/rejected comments** (when a dev accepts, rejects,
  resolves, or edits a suggestion, use it as feedback)
- Dashboard

---

## 3. V3 — Toward a Staff Engineer Platform

- **Automated fixes**: `Finding → generate patch → run tests → show change`
- **Historical awareness**: "This code used to work differently before PR #182"
- **Production awareness**: PR → code → architecture → observability →
  production risk

That moves Critiq toward an actual AI Staff Engineer platform.

---

## 4. Feature Ladder (by priority)

| Feature | V1 | V2 | V3 |
| ------- | --- | --- | --- |
| GitHub App / PR review | ✅ | — | — |
| 6 review dimensions | ✅ | — | — |
| Evidence + confidence gates | ✅ | — | — |
| `.critiq.yml` | ✅ | — | — |
| Custom policies | — | ✅ | — |
| Learning from feedback | — | ✅ | — |
| Dashboard | — | ✅ | — |
| Automated fixes | — | — | ✅ |
| Historical awareness | — | — | ✅ |
| Production awareness | — | — | ✅ |

---

## 5. Positioning

- **Not** "AI Code Reviewer" (crowded, generic).
- Positioned as **"The Staff Engineer in your GitHub PR"** / "Get a Staff
  Engineer review on every PR."

**Fundamental promise:** Understand the change. Understand the system. Find what
matters. Explain why.
