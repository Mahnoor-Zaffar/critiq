# 0001. V3: Auto Fix and Historical Awareness

**Date**: 2026-09-16
**Status**: In Progress

## Summary

V3 has two features: automated fixes and historical awareness. A finding now
appears with a tested code patch the author can accept in one click, pushed
straight to the PR as a GitHub suggestion. A second new capability gives the
reviewers recent commit history and past Critiq findings on the files being
changed, so the AI judges a change against how that code evolved, not in a
vacuum. Both work inside the pipeline that already exists; no new service, no
new database, no new queue.

## Structure

- `0001-auto-fix.md`: automated fixes. Converts eligible findings into a tested
  single file patch, posts it as a suggestion, reconciles applied or rejected
  state, and offers an org gated push mode.
- `0001-history.md`: historical awareness. Collects recent commits and prior
  findings per changed file, then injects a bounded history block rendered per
  file for each reviewer and in full for the synthesizer.

## Cross child contract

- Auto fix hooks the pipeline after findings pass the evidence, severity,
  confidence and dedup gates, before the review is posted. History hooks the
  context builder before the reviewers run. Neither feature blocks the other.
- The review posting path gains the ability to carry a GitHub suggestion block
  on an inline comment. Only auto fix uses it.
- History reaches a prompt only through its own two renders (per file for a
  reviewer, full block for the synthesizer). The shared context carries no
  history, so neither feature's context can leak into the other's prompts.
- Auto fix is configured by a new `fix` block in `.critiq.yml`. History is
  always on and best effort, with no config.
- Neither feature posts anything outside a normal review. A repo that never
  opts in sees its reviews exactly as today.

## Requirements

No repo or CI change is needed to receive suggestions; authors keep accepting
them on GitHub. Code writing (push mode) needs an explicit org approval and is
off by default.

**User stories**:
- As a PR author, I want a suggested fix I can accept in one click so I am not
  editing a fix by hand.
- As a PR author, I want a fix offered only after its targeted tests pass so
  the suggestion is trustworthy.
- As a repo admin, I want code writing gated behind an explicit org level
  approval so Critiq never writes to my branches without my consent.
- As a PR author, I want the reviewer to know when my change touches code that
  changed through earlier PRs or was flagged before, so the feedback carries
  that context.
- As a PR author, I want the reviewer to distinguish "nothing was ever flagged
  here" from "Critiq could not check", so silence reassures me for the right
  reason.

**Acceptance criteria** (the contract):

- **AC-1**: A finding is patch eligible only when all hold: its source is a
  deterministic analyzer (custom rule or static check), it carries a category
  from the closed policy enum, its category is in the configured fix categories
  (default security and correctness), its severity and confidence pass the
  review thresholds, its span is a subset of the PR's added lines inside a
  single contiguous hunk of a file the PR modifies, and the run has not reached
  `max_patches`. No other finding ever receives a patch.
- **AC-2**: A patch whose targeted tests pass is posted as an inline GitHub
  suggestion on the finding's lines, and that suggestion is the finding's
  review comment (no duplicate prose comment). A patch that cannot be tested
  (non Python repo, no matching test file, or a timeout) is posted as an
  unverified suggestion carrying a not test verified tag. Both post through the
  normal review path and count against `max_comments`. The suggestion carries
  minimal context lines, and if the hunk drifted so it can no longer apply, the
  offer degrades to a plain comment.
- **AC-3**: A patch whose targeted tests fail is never posted and never pushed.
- **AC-4**: Every eligible patch attempt persists as an `AutoFixPatch` row
  holding its review comment id. On the next `pull_request` event (actions
  `synchronize` and `reopened`), a row whose replacement now matches the head
  is marked applied; a row whose finding basis disappeared without an
  application is marked rejected; a row whose hunk moved is regenerated, re
  tested, re offered, and its prior comment body is edited to note the
  supersession. Closing or merging the PR marks all still offered rows as
  rejected.
- **AC-5**: Code writing requires both the repo config `fix.apply` equal to
  `push` and an `OrgSetting` with `auto_push_enabled` true, and applies only to
  same repo branches without branch protection (fork PRs always fall back to
  suggestions). A pushed commit changes exactly one file using the verified
  replacement, is authored as the app, and is guarded by compare and set: the
  live pull request head ref SHA fetched at push time must equal the head the
  patch was tested against. On a mismatch the patch falls back to a suggestion.
  A successful push posts no suggestion; the review summary notes the commits.
- **AC-6**: Auto fix is disabled by default. Adding the `fix` block or calling
  the org settings endpoints never alters reviews for a repo that has not opted
  in.
- **AC-7**: For every changed file, history collection reads up to 3 recent
  commits that touched that file before the PR (queried against the base SHA of
  the PR, so the PR's own commits are excluded) and up to 5 earlier Critiq
  findings on that file, across at most 10 explored files. The synthesizer
  prompt carries the collected history as one block capped at 1200 tokens. The
  shared review context carries no history, and per file reviewer history is
  governed by **AC-9**.
- **AC-8**: History collection is best effort. A GitHub commits API failure, a
  database failure, or an empty prior record set never fails or degrades the
  review; the affected file simply carries no history. Collection is bounded:
  the GitHub leg by a 5 second aggregate deadline across all files, with the 2
  second per call timeout acting only as a secondary guard, and the database leg
  by a 1 second timeout per query.
- **AC-9**: Each reviewer prompt carries history for the one file that reviewer
  is judging, rendered at the call site from the raw collected block and capped
  at 400 tokens, which sits above the arithmetic worst case for a single file so
  the reviewer render does not trim. A file with no record, a file whose lookup
  was unavailable, and a file beyond the exploration cap each render a distinct
  line, and only a confirmed empty record renders a "no recorded history"
  statement. The synthesizer prompt carries the full block, capped at 1200
  tokens. For every path, the lines the synthesizer block carries for that path
  are a superset of the lines the reviewer render carries for the same path.
- **AC-10**: A history line is never emitted without the file header it belongs
  to, and every explored file keeps at least one detail line. When the
  synthesizer block must be trimmed, commit lines are removed before prior
  finding lines, and whole files are dropped only once no file can lose a line
  without losing its floor. History collection runs its database leg with at
  most one task using the session at a time.

## Decision

Both features ship in V3 as enhancements to the existing pipeline.

**Automated fixes** default to offered suggestions, never code writing. Patch
generation uses the existing strong model and a validated structured
replacement; verification runs the changed file's targeted tests in the worker
with a 60 second cap. Push mode exists but is gated behind the repo config plus
an org level approval stored in a small `OrgSetting` table and managed by an
admin endpoint guarded by an operator token. Detailed design:
`0001-auto-fix.md`.

**Historical awareness** is on demand only. Each review asks GitHub for the last
3 commits touching each changed file, reads the last 5 Critiq findings on that
file from Postgres, bounds each item's length at collection, and renders the
result at the call site. Each reviewer receives only the file it is judging,
capped at 400 tokens; the synthesizer receives the whole block, capped at 1200.
A file with no record, a file Critiq could not check, and a file beyond the
exploration cap render distinct lines, so the model is never told a file is
clean when it was simply unchecked. No new table, no cache, no new endpoint. If
GitHub is slow or errors, history is skipped. Detailed design:
`0001-history.md`.

**Implementation skills**: `python-async-patterns` (`~/.config/opencode/skills/python-async-patterns/`) · `fastapi-async` (`~/.config/opencode/skills/fastapi-async/`)

## Build plan

Ordered as end to end slices: stand up the thinnest working thread first (one
tested suggestion through the real pipeline), then thicken it with lifecycle
and push mode, then land history, which is cheaper and independent.

1. Create the migration with `AutoFixPatch` (including its review comment id) and `OrgSetting`, satisfies **AC-4**, **AC-5**
2. Parse the `fix` block into the policy and profile merge, default disabled, satisfies **AC-1**, **AC-6**
3. Implement the patch generator (eligibility filter including the added lines span check, strong model replacement via a JSON schema, single hunk validation, tree-sitter parse check, one retry then logged drop), satisfies **AC-1**
4. Tracer thread end to end: workspace clone at the pull request head ref with a base cache keyed on the base SHA, replacement apply, targeted pytest in an isolated subprocess running `uv sync` first with a 60 s process group kill, suggestion posting with test verified or unverified tags as the finding's own comment, satisfies **AC-2**, **AC-3**
5. Lifecycle reconcile on `pull_request` events: applied, rejected, closed or merged, and regenerate with re test and comment supersession, satisfies **AC-4**
6. Push mode: `OrgSetting` endpoints with admin token auth, Contents API push to the head ref authored as the app with a live ref SHA guard, fork and branch protection fallback, satisfies **AC-5**, **AC-6**
7. Tests for the full auto fix path, the run ordering under `max_patches`, and the data model, satisfies **AC-1** through **AC-6**
8. History collector: base ref commits API with a 2 second per call timeout and prior findings query per changed file, up to 10 files, satisfies **AC-7**
9. History aggregator with a total 1200 token budget and injection into reviewer and synthesizer prompts, satisfies **AC-7**
10. History failure handling, aggregate deadline, and tests, satisfies **AC-8**
11. Collect history into a per path structure with a per path status, bound each
    item's length at collection, and scope each reviewer prompt to the file it
    judges, with the synthesizer keeping the full block, satisfies **AC-7**,
    **AC-9**
12. Attribution preserving budget trim with a per file floor, a serial database
    leg, prompt wording that admits the history, and tests for all of it,
    satisfies **AC-8**, **AC-10**

## Consequences

**Positive**:
- Authors apply one click fixes; tested offers build trust in suggestions.
- Push mode is double gated, so code writing is safe to offer later.
- Reviewers judge changes against repo history, catching regressions and
  previously flagged patterns.

**Negative / tradeoffs**:
- Running targeted tests adds worker time, disk space for clones, and CPU per
  eligible finding.
- The worker executes the target repo's tests, which are untrusted code. The
  test subprocess runs isolated with a stripped environment and a process group
  kill on timeout, and the admin token never lives in the worker environment.
  This is a documented risk, not a sandbox.
- Push mode widens the GitHub App permission to write contents and adds a new
  admin secret; a GitHub App re approval may be needed on install, and push
  mode cannot reach fork PRs or protected branches.
- Suggestions make reviews bigger, so `max_comments` matters more.
- Deterministic findings only; semantic (LLM) findings do not get patches yet.

**Neutral**:
- Two new tables and one Alembic migration.
- `configuration.md`, `api.md`, `data-model.md`, and `github-app-setup.md` need
  updates for the new surface.
- The review summary body and the dashboard are unchanged.

## Follow-up

- [ ] Update `github-app-setup.md` with the `Contents: write` permission request used only for push mode.
- [ ] Update `configuration.md` with the `fix` block schema.
- [ ] Update `data-model.md` and `api.md` with the new tables and endpoints.
- [ ] Add `CRITIQ_ADMIN_TOKEN`, `CRITIQ_TEST_TIMEOUT_SECONDS`, and `CRITIQ_WORKSPACE_DIR` to `.env.example`.
- [ ] A later slice can extend patches to LLM sourced findings (semantic fixes) and to a pure deterministic removal path once tested patches prove out.
- [ ] `python-async-patterns` and `fastapi-async` conventions are not yet referenced in `AGENTS.md`; they belong at root level before implementation begins.

## Rationale

Reasoning and options considered: see `rationale.md`.