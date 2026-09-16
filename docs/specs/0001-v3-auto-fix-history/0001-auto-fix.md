# 0001. Auto Fix

**Parent**: `0001-v3-auto-fix-history/index.md`

## Summary

Auto fix turns an eligible deterministic finding into a tested, single file
code change presented as a GitHub suggestion the author applies in one click.
A patch is only offered when its targeted tests pass under a hard time cap; a
patch that could not be tested is still offered, but clearly labelled
unverified. An optional push mode, gated by repo config and an org level
approval, lets the worker commit the verified change directly to the branch.
The feature is off by default and changes nothing for a repo that never opts
in.

## Requirements

This child spec implements **AC-1** through **AC-6** in the umbrella index:
patch eligibility rules, tested and unverified suggestion posting, never post
on failing tests, the persisted patch lifecycle, the double gated push mode,
and the disabled by default guarantee.

## Decision

Eligibility is deterministic only: custom rule and static analyzer findings
(source `static`) that carry a category from the closed policy enum, category
in the configured fix list, severity and confidence above threshold, a span
inside the PR's added lines within a single contiguous hunk, capped by
`max_patches` (ordered severity desc, then confidence desc, then creation
order; beyond cap findings are ineligible and persist no row). Generation
returns a structured replacement validated against the hunk and a tree-sitter
parse, with one retry then a logged drop. Verification runs the changed file's
targeted tests in the worker with a 60 second process group kill and degrades
to a labelled unverified suggestion when the bound cannot be met. Push mode
requires `fix.apply: push` in the repo config and an `OrgSetting` row with
`auto_push_enabled` true, pushes via the Contents API to the pull request head
ref authored as the app, guarded by a live ref SHA fetched at push time, and
applies only to same repo branches without branch protection.

**Implementation skills**: `python-async-patterns` (`~/.config/opencode/skills/python-async-patterns/`) · `fastapi-async` (`~/.config/opencode/skills/fastapi-async/`)

## Feature design

### Data model

`AutoFixPatch` records one patch attempt for a review run.

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `review_run_id` | FK to ReviewRun, required | |
| `finding_id` | FK to Finding, required | |
| `file_path` | str | absolute within repo |
| `line_start` | int | first line of the replacement in the head file |
| `line_end` | int | last line of the replacement in the head file |
| `replacement_text` | text | the new lines to put in place |
| `version` | int, default 1 | increments on regeneration |
| `status` | enum | `offered` / `applied` / `rejected` |
| `test_status` | enum, nullable | `passed` / `failed` / `unverified` |
| `review_comment_id` | int, nullable | GitHub id of the posted suggestion comment, used for supersession |
| `commit_sha` | str, nullable | set when a push mode commit lands |
| `created_at` | datetime | |
| `updated_at` | datetime | |

`OrgSetting` stores the org level approval for a repository.

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `repository_id` | FK to Repository, unique | |
| `auto_push_enabled` | bool, default false | |
| `updated_at` | datetime | |

### State transitions

```
offered ──┬── applied   (head diff now contains the replacement)
          └── rejected  (finding basis gone without application, or the PR closed or merged)
          └── regenerated: a new version row (offered) when the hunk moved,
              re tested and re offered, prior comment body edited to note supersession
```

`test_status` tracks `passed`, `failed`, or `unverified` independently of
`status`. One offered patch per file per run is an invariant enforced at
insert, so a regeneration supersedes the earlier row for the same file.

### API surface

| Endpoint | Method | Key inputs | Key outputs | Auth | Key errors |
|---|---|---|---|---|---|
| `/api/org-settings/{repository_id}` | PUT | `{auto_push_enabled: bool}` | stored row | bearer `CRITIQ_ADMIN_TOKEN` | 401, 404, 422 |
| `/api/org-settings/{repository_id}` | GET | none | `{auto_push_enabled: bool}` | bearer `CRITIQ_ADMIN_TOKEN` | 401, 404 |

No change to the public review endpoints. Suggestions post through the existing
review path; each eligible finding's inline comment body gains a GitHub
suggestion block plus a one line test tag.

### Value sourcing

| Action | Value produced | Source |
|---|---|---|
| Patch eligibility | fix categories, `max_patches` | `fix` block in `.critiq.yml` |
| Patch eligibility | severity, confidence, source, category, file and lines | the Finding row and its evidence |
| Patch eligibility | single contiguous hunk in a changed file | the parsed PR diff |
| Patch generation | `replacement_text`, `line_start`, `line_end` | strong model structured output via a JSON schema, one retry then logged drop |
| Patch validation | valid replacement | tree-sitter buffer parse (reuse `analysis/ast`) |
| Test verification | `passed` / `failed` / `unverified` | targeted pytest run, `CRITIQ_TEST_TIMEOUT_SECONDS` process group kill cap |
| Suggestion posting | suggestion is the review comment | synthesized comment body from the replacement and the finding |
| Suggestion posting | test tag | `test_status` |
| Push guard | live ref SHA fetched at push time | GitHub refs API |
| Push decision | `fix.apply == push` | repo config |
| Push decision | `auto_push_enabled` | `OrgSetting` row |
| Push commit | `commit_sha` | GitHub Contents API response |
| Push commit | author identity | app installation identity (commit authored as the app) |
| Applied | head file lines contain the replacement | recompute on next `pull_request` event |
| Review comment id | GitHub comment id for stale suggestion cleanup | posted review id |

### Key invariants

- A patch exists only for an eligible finding; eligibility is checked against
  the head diff, not the original review state.
- One offered patch per file per run; a regeneration supersedes the prior
  version and edits the prior comment body to note supersession.
- The suggestion is the finding's only review comment; no duplicate prose
  comment is posted for a covered finding.
- A patch with `test_status` equal to `failed` is never posted and never
  pushed.
- When eligible findings exceed `max_patches`, they are ordered severity
  descending then confidence descending then creation order, and only the top
  findings receive patches; over-cap findings are ineligible and persist no
  row.
- Category on deterministic findings comes from the originating rule or static
  analyzer definition, taken from the closed enum in `Finding.category`.
  Findings with no category are ineligible.
- A push happens only when `fix.apply` equals `push` and
  `OrgSetting.auto_push_enabled` is true, only when the branch is a same repo
  non protected branch, and only when the live pull request head ref SHA
  fetched at push time equals the head the patch was tested against.
- Fork PRs and protected branches always fall back to suggestions.
- `max_patches` and `max_comments` are never exceeded by posted suggestions.

### Patch anchoring

A suggestion is only valid when the replacement spans a subset of the PR's
added lines in a single hunk. The patch anchoring step maps the local
hunk coordinates to the GitHub review API format: the comment lands on a line
number within the added side (`side: RIGHT`) of the file's diff. New files are
treated separately (every line is added). The suggestion block carries minimal
context lines so the one click accept is reliable. If the surrounding context
has drifted between generation and posting, the offer degrades to a plain
review comment instead of a suggestion block.

### Test runner

Verification runs inside the worker using an isolated subprocess. The test
discovery heuristic is: if the changed file is itself a test, run that file;
otherwise look for `test_<stem>.py` by globbing next to the file and under
`tests/`; if no candidate is found, the result is `unverified`. The
subprocess runs under `uv sync` to provision dependencies, uses the workspace
clone as its working directory, and is killed on a process group level when
`CRITIQ_TEST_TIMEOUT_SECONDS` expires. Exit code semantics are: 0 is pass, a
non-zero exit after pytest reports "no tests collected" is `unverified`, and
any other non-zero exit is `failed`.

### Generation and validation contract

Patch generation uses the existing strong model and a structured JSON schema
through the provider contract. The parse check runs the replacement through
the existing tree-sitter buffer parser (`analysis/ast`). On generation or
validation failure the worker retries once; if the second attempt fails it
logs a warning and drops the candidate with no row (AC-4's "attempt" applies to
a valid replacement, not a failed generation). Regeneration re-invokes the
model and must re-test before re-offering.

### Push mechanics

Push mode uses the GitHub Contents API to write the single changed file to the
pull request's head ref. The commit is authored as the app installation
identity (name and email from the installation token profile). The atomic
guard is a live ref SHA fetched from the pull request's head ref at push time;
if that SHA does not equal the head SHA the patch was tested against, the push
is aborted and a suggestion is posted instead. On a successful push the
suggestion is not posted; the review summary notes the committed file and
commit sha. Push mode works only on same repo branches without branch
protection. Fork PRs always receive suggestions.

### Workspace checkout

The workspace checkout fetches the pull request ref via `refs/pull/N/head`
into the base repo so fork PRs resolve correctly. A shallow clone cached per
base SHA avoids a fresh checkout on every event; the cache is invalidated when
the base advances. The replacement is applied by editing the file in place in
the clone, then running targeted tests in the same directory tree so imports
resolve against the full repo.

### Reconcile decision tree

Reconcile runs on `synchronize` and `reopened` events only. For each offered
`AutoFixPatch` row the worker fetches the head file, then runs three checks in
order: (1) if the replacement text appears in the head file at the expected
line range, mark `applied`; (2) else if the added line basis that anchored the
finding is no longer in the diff, mark `rejected`; (3) else (basis present but
position moved) trigger regeneration: re-invoke the model, re-test, re-offer,
and edit the prior comment body to note the supersession. When the PR is
closed or merged, all still offered rows are marked `rejected`.

### Security model

- Reading and posting suggestions use the existing installation token and
  review access; no new permission.
- Push mode widens the GitHub App to request `Contents: write` on opted in
  repositories only. The worker pushes a single file commit built from a
  verified replacement via the Contents API guarded by a live ref SHA.
- Fork PRs and protected branches always fall back to suggestions.
- The org settings endpoints are guarded by the `CRITIQ_ADMIN_TOKEN` bearer
  secret, since the system has no human accounts. `auto_push_enabled` defaults
  to false.
- The target repo's tests are untrusted code executed as a subprocess. The
  subprocess runs isolated with a stripped environment and its own working
  directory, `CRITIQ_ADMIN_TOKEN` is never present in the worker environment,
  and a process group kill enforces the timeout. This is a documented risk,
  not a full sandbox.
- A patch with a failing test or a mismatched ref never reaches a branch.

### Configuration required

- `fix` block in `.critiq.yml`:
  `enabled` (bool, default false), `categories` (list, default
  `[security, correctness]`), `max_patches` (int, default 10),
  `apply` (`suggest` or `push`, default `suggest`).
- `CRITIQ_ADMIN_TOKEN`: bearer secret for org settings endpoints.
- `CRITIQ_TEST_TIMEOUT_SECONDS`: per patch test cap, default 60.
- `CRITIQ_WORKSPACE_DIR`: directory for the review workspace clones and the
  base clone cache, defaults to a temp directory.

### Critical test scenarios

- Happy path: a custom rule finding on a Python PR generates a patch, the
  changed file's targeted pytest passes, and the suggestion posts as the
  finding's review comment with a test verified tag, verifies **AC-2**.
- Failure case: pytest fails for the patch, nothing posts and nothing pushes,
  the row records `failed`, verifies **AC-3**.
- Degrade: a non Python repo, no matching test file, or a timeout produces an
  unverified suggestion with the label, verifies **AC-2**.
- Drift: the hunk context moved between generation and posting, so the offer
  degrades to a plain comment, verifies **AC-2**.
- Cap: twelve eligible findings with `max_patches` 10 produce exactly ten
  patches, ordered by severity, and the remaining findings persist no row,
  verifies **AC-1**.
- Lifecycle: a sync moves the hunk, the recompute regenerates version 2, re
  tests it, re offers it, and edits the version 1 comment; a close event marks
  outstanding rows rejected, verifies **AC-4**.
- Race: the branch head changed before the push, the live ref SHA signal
  fails compare and set, and a suggestion is posted instead, verifies **AC-5**.
- Forks: a fork PR with push mode configured receives a suggestion, never a
  push, verifies **AC-5**.
- Gate: org settings mutate without the token, or a repo sets `fix.apply:
  push` with no approval; no push occurs and existing reviews are untouched,
  verifies **AC-5**, **AC-6**.

## Rationale

The deterministic first rule is a trust on ramp. Custom rule and static
findings anchor cleanly to added lines and a contiguous hunk, which makes the
generated replacement validate against a parse and a test run. Semantic LLM
findings often span reasoning, not lines, so patching them early would flood
reviews with low quality suggestions; the follow up in the umbrella index
opens that path once tested patches prove out.

The degrade path exists because an offer is better than no offer. The targeted
test cap bounds worker cost, and the unverified label keeps the trust
difference explicit: a suggestion is human gated either way, only the
confidence note changes.

Inline rationale (short form): the option comparison for suggestion versus
push, verification depth, generation contract, and applied state tracking is
recorded in the umbrella `rationale.md`, since the reasoning is shared with the
V3 decision.