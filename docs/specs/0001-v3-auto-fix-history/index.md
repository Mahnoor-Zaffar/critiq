# 0001. V3: Auto Fix and Historical Awareness

**Date**: 2026-09-16
**Status**: Proposed

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
  findings per changed file and injects a bounded history block into the
  reviewer prompts.

## Cross child contract

- Auto fix hooks the pipeline after findings pass the evidence, severity,
  confidence and dedup gates, before the review is posted. History hooks the
  context builder before the reviewers run. Neither feature blocks the other.
- The review posting path gains the ability to carry a GitHub suggestion block
  on an inline comment. Only auto fix uses it.
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
- **AC-7**: For every changed file, the review context includes up to 3 recent
  commits that touched that file before the PR (queried against the base ref,
  so the PR's own commits are excluded) and up to 5 earlier Critiq findings on
  that file, aggregated across at most 10 explored files into a total of at
  most 1200 tokens of injected history.
- **AC-8**: History collection is best effort. A GitHub commits API failure or
  an empty prior record set produces no history block and never fails or
  degrades the review. Per file call and overall collection are bounded: 2
  seconds per call, 5 seconds in aggregate.

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
file from Postgres, and injects a block capped at 1200 tokens into the reviewer
prompts. No new table, no cache, no new endpoint. If GitHub is slow or errors,
history is skipped. Detailed design: `0001-history.md`.

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