# 0001. Historical Awareness

**Parent**: `0001-v3-auto-fix-history/index.md`
**Amended**: 2026-09-27

## Summary

Reviewers judge a change against the code as it looks today. Historical
awareness adds what came before: the last few commits that touched each changed
file, and the findings Critiq already raised on that file. Each reviewer now
sees only the history of the one file it is judging, and the synthesizer still
sees the whole picture. History is best effort, meaning it is a bonus and never
a requirement, so if GitHub is slow or unavailable the review runs with less
history and never fails.

## Context

Two forces shaped this decision.

The first is cost and attention. A review runs six reviewer categories
(Correctness, Security, Architecture, Reliability, Performance, Testing)
against every changed file, so a pull request touching ten files produces sixty
model calls. `docs/specs/review-pipeline.md` Stage 4 already sets the norm for
this project: pass only the relevant subgraph, because repeating everything
"spends tokens and focuses nothing". Under the original decision one 1200 token
history block was attached to the shared context, so all sixty calls carried it.
A per block cap that is sent sixty times is not a cap, and the effective ceiling
was about 72,000 duplicated tokens of history per review.

The second force is signal. A reviewer examining `app/a.py` cannot act on the
commit log of nine files it is not judging. Past a point more history in the
prompt does not mean more context; it means the diff, which is what the reviewer
is actually being asked to judge, competes with background prose for attention.

A third force is honesty about absence. A transport failure, an exploration cap,
a file trimmed away, and a file that genuinely never had history all look
identical to a renderer that only asks "is there a group for this path". If they
render the same line, the model is told a falsehood: a reviewer that would have
escalated a repeat offender instead reads reassurance. The shipped collector had
this problem in its sharpest form, running its database lookups from several
concurrent tasks against one `AsyncSession`, which wraps a single connection and
refuses concurrent use, so most per file lookups failed and were swallowed at
debug level, and prior findings attached to at most one file per review.

Leaving this undecided keeps paying for context that most calls cannot use, and
keeps a class of false statements in the prompt.

## Requirements

This child spec implements **AC-7** and **AC-8** from the umbrella index, and
adds **AC-9** and **AC-10** there for the prompt scoping decision, the honesty
rules about absence, and the collection invariants.

**User stories**:
- As a PR author, I want the reviewer to know when my change touches code that
  changed through earlier pull requests or was flagged before, so the feedback
  carries that context.
- As a repo admin, I want history to cost roughly what it is worth, so a ten
  file pull request does not pay for the same block sixty times.
- As a PR author, I want the reviewer to distinguish "nothing was ever flagged
  here" from "Critiq could not check", so silence reassures me for the right
  reason.

**Acceptance criteria** (the contract):
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

## Options considered

### Option 1: Bound values at collection, then scope the render

Keep what is collected, but bound each commit subject and prior finding title to
120 characters where the source is in hand, collect into a per path structure
that records a status per path, and render that structure twice: a slice for
each reviewer covering only the file it judges, and the whole block for the
synthesizer.

**Pros**:
- Bounds history length at the source, so the per file cost becomes arithmetic
  rather than something a trimmer has to defend against after the fact.
- Cuts injected history from about 72,000 tokens to about 9,000 on a ten file
  pull request with history on every file, and drops the worst case ceiling to
  about 24,000. No change to what is collected, only to how long each item may be.
- Gives each reviewer only the history of the file it is judging, which is the
  history it can act on, and keeps the cross file view in the one pass that reads
  all findings together.
- Distinguishes absent from unavailable, so the model is never handed a false
  reassurance.

**Cons**:
- A 120 character commit subject can lose the tail of a meaningful subject line.
  Accepted: the alternative is an unbounded value, and a truncated subject is
  still far more signal than no history.
- Two render paths from one structure, so a change to rendering can drift between
  them unless the parity property is tested.
- The truncation itself is a silent information loss, so a commit subject cut at
  120 characters looks like a complete subject to the reader.

### Option 2: Keep one shared block everywhere, lower the total cap

Leave the single shared block on the shared context and cut the 1200 token cap
so the multiplied cost becomes tolerable.

**Pros**:
- No change to the injection path at all.
- One place to reason about history rendering.

**Cons**:
- Every reviewer still reads nine files of history it cannot use, so the prompt
  stays diluted.
- Lowering the cap shrinks the synthesizer's cross file view too, which is the
  view the feature exists to provide.
- Does nothing about false absence statements, and actively makes them worse,
  since a smaller cap drops more groups and every dropped group then renders as
  "no recorded history".

### Option 3: Change nothing, measure first

Ship as is and use the harness in `docs/specs/evaluation.md` to measure whether
history improves finding quality before paying to reshape it.

**Pros**:
- Zero engineering effort, and the numbers would settle the question on
  evidence rather than argument.
- Avoids reshaping a feature whose value is unproven.

**Cons**:
- The harness cannot answer it today. It calls the pipeline with no history
  argument, holds no client or session, and its mock provider discards the user
  prompt, so it can neither inject nor observe a history block. Measuring first
  is not available without building the seam first.
- Leaves the multiplication and the false absence statements in place while
  measuring.

## Decision

**Chosen option**: Option 1: Bound values at collection, then scope the render.

History is collected once per review into a per path structure that records, for
each explored file, a status and its detail lines. Both prompts are rendered at
their call site from that one raw structure, through a single shared render
function, by passing different path sets. The shared context stops carrying
history, so the two renders are the only routes into a prompt, and neither can
read a pre-rendered view that the other cannot see.

**Implementation skills**: `python-async-patterns` (`~/.config/opencode/skills/python-async-patterns/`)

## Feature design

### Data model

No new tables. History is derived from:

- **Prior Critiq findings**: existing `Finding` rows joined through
  `ReviewRun` (with `completed_at`) and `PullRequest` to `Repository`, filtered
  to the same repository and `file_path`, ordered by `completed_at` descending,
  limited to 5. The `owner/repo` argument arrives as a task parameter
  (`review_service` already holds it), so the collector performs no repository
  read of its own.
- **Recent commits**: GitHub commits API `GET /repos/{repo}/commits` with
  `sha`, `path` and `per_page` parameters, where `sha` is the base **SHA** of
  the pull request, not a branch name, so the PR's own commits are excluded. The
  client already reduces a commit message to its first line.
- **Collected block**: an in memory per path structure, never persisted, holding
  for each explored file a status (`ok`, `empty`, `unavailable`, or
  `not_explored`) and its detail lines, plus the explored paths in a stable
  order sorted by path.

The GitHub leg runs with bounded concurrency (at most 4 in flight) under a 5
second aggregate deadline, with a 2 second per call timeout as a secondary
guard; at most 4 in flight over 10 files is three waves, so the aggregate
deadline is the bound that actually binds and the per call timeout rarely
fires. Cancelled tasks are awaited so no work outlives the call. The database leg
runs after it, serially, one indexed query per file with a 1 second timeout,
because an `AsyncSession` wraps a single connection and refuses concurrent use.
An empty base SHA is treated as `unavailable`, not as `empty`, since a missing
input is not evidence of an empty history.

The 10 explored files are chosen by descending added line count, ties broken by
path, so the files that cost the most prompt tokens are the files that get
history. The reviewer loop iterates every diff, so a file outside the explored
set must render `not_explored` rather than `empty`.

### Aggregation format

One render function, three sections. A file with history:

```
History Context for app/a.py
- Changed in abc1234: fix null check on user lookup
- Previously flagged in Run 42 (security): missing auth check on /users/{id}
```

A file confirmed to have no record, which is the only case allowed to say so:

```
History Context for app/new_file.py
- No recorded history for this file before this pull request.
```

A file Critiq could not check, covering both a failed or timed out lookup and a
file outside the exploration cap:

```
History Context for app/other.py
- History for this file is unavailable in this review.
```

The synthesizer render lists every explored file, sorted by path, in the first
shape, and its first line names how many of the pull request's changed files
were explored, so a partial block is visible rather than silent.

Token count is an approximate `len(rendered text) // 4`, measured on the final
rendered string. The cap covers the rendered history section only, including its
header and framing, and excludes the prompt's own instructions.

### Budgets

Worst case for one file, after truncation, with a 60 character path: header 80
characters, three commit lines at 22 plus 120 each, five finding lines at 42
plus 120 each, plus newlines, which is about 1,325 characters, or about 331
tokens. The reviewer cap is therefore set to 400, above that worst case, so the
reviewer render is a guarantee and never a silent trim.

The synthesizer's 1200 token cap is the only budget that binds, because ten
files at their worst case is about 3,300 tokens. Its trim rule, in order:
commit lines are removed before prior finding lines, because a prior finding
carries a 42 character fixed prefix against a commit line's 22 and is therefore
both longer and more valuable, so length alone would evict the signal first.
Within a class, the longest line goes first. Every explored file keeps a floor of
one detail line and its header, and only once no file can give up a line is a
whole group dropped, least valuable first.

### Value sourcing

| Value produced | Source |
|---|---|
| recent commits per changed file | GitHub commits API `sha` (the PR base SHA), `path`, `per_page=3` |
| commit subject text | the API commit message, already reduced to its first line by `GitHubClient` |
| prior findings per file | `Finding` joined via `ReviewRun`, `PullRequest`, and `Repository` |
| `owner/repo` for the API call | the task parameter `repo` (`owner/repo`) held by `review_service` |
| which 10 files are explored | descending `FileDiff` added line count, ties by path |
| the file a reviewer is judging | `FileDiff.path`, from the pipeline reviewer loop |
| which history group belongs to that reviewer | key of the collected per path block |
| per path status | derived: lookup succeeded with content (`ok`), succeeded empty (`empty`), failed, timed out, or base SHA missing (`unavailable`), beyond the exploration cap (`not_explored`) |
| the three section wordings | this spec, **AC-9** |
| commit subject and prior finding title truncation (120 chars) | this spec, **AC-9** |
| reviewer render budget (400 tokens) | this spec, **AC-9** |
| synthesizer render budget (1200 tokens) | this spec, **AC-7** |
| token count | approximate `len(rendered) // 4` on the final string |
| GitHub aggregate deadline (5 s) and per call timeout (2 s) | this spec, **AC-8** |
| database per query timeout (1 s) | this spec, **AC-8** |
| synthesizer sort order | sorted by path, stable, as the collector does today |

### Key invariants

- History is never a blocking condition. A failure, timeout, or empty result
  set never fails or degrades the review.
- History reaches a prompt only through the one shared render function, called
  with a path set. The shared context carries no history block, and no consumer
  reads a pre-rendered view.
- Both renders read the raw collected block at call time, never a fitted or
  pre-joined string, so one file's reviewer slice cannot depend on another
  file's history.
- The synthesizer's lines for a path are a superset of the reviewer's lines for
  that path.
- A history line is never emitted without the file header it belongs to, and
  every explored file keeps at least one detail line.
- Absence is never overstated: only a confirmed empty record says "no recorded
  history"; every other kind of absence says "unavailable".
- The database leg uses the session from at most one task at a time.
- A reviewer render never exceeds 400 tokens; the synthesizer render never
  exceeds 1200 tokens.
- Commits are always read against the base SHA, never the pull request head, so
  the block cannot be dominated by the PR's own churn.
- Collection stops at the 10 file exploration cap, the 5 second GitHub deadline,
  and the 1 second per query database bound.
- History is injected before the reviewers run and is never appended to the
  review body or the pull request summary.

### Telling the model the history exists

This is load bearing, and it was missing. As shipped, no prompt file in
`src/critiq/ai/prompts/` mentions history at all, and `synthesize.txt` rule 1
reads "Only reference the provided findings; do not invent new issues". A history
line is not a provided finding, so the synthesizer was explicitly forbidden from
using the block this feature exists to provide it.

So the build adds one line to each of the six reviewer prompts stating that a
recorded history section is present, that it is background rather than a
finding, and that a prior finding on the same file is a signal worth weighing
but not a finding to repeat. And it relaxes `synthesize.txt` rule 1 to "only
reference the provided findings and the recorded history; do not invent new
issues", so the synthesizer may cite a repeat offender. Without this the
per file scoping would be a cost saving with no behavioural payoff, and the
value claimed in Consequences would be fiction.

### Security model

- History queries use the same `GitHubClient` and database session the worker
  already has, so no new permissions and no new secrets.
- The commits API call reads only the file's commit log, so no new write access.
- History never leaves the LLM prompt. It is not posted to GitHub and not shown
  on the dashboard.
- Collection failures are logged at warning level with the file path. A
  repository path is not a secret and the worker log is not published, so paths
  at warning are in bounds. History content itself (commit subjects, finding
  titles) is never logged, at any level, because a commit subject from a private
  repo should not land in worker logs.

### Critical test scenarios

- Happy path: three changed files, two with three commits and prior findings and
  one confirmed empty. Verify the synthesizer block stays under 1200 tokens, each
  reviewer prompt carries only its own file, the empty file says "no recorded
  history", and the review completes, verifies **AC-7**, **AC-9**.
- Basis: a pull request whose head branch added many commits still produces
  history excluding those commits, because the query carries the base SHA,
  verifies **AC-7**.
- Failure case: the commits API returns a 500 for one file. Verify that file's
  reviewer says "unavailable" rather than "no recorded history", the other
  files still get their history, the review completes, and no error is posted,
  verifies **AC-8**, **AC-9**.
- Deadline: the commits API is slow and the 5 second aggregate deadline expires.
  Verify the review proceeds with whatever history arrived, and that files which
  never returned render "unavailable", verifies **AC-8**, **AC-9**.
- Empty state: a brand new file with no prior commits and no prior Critiq
  findings, confirmed empty. Verify the reviewer prompt says "no recorded
  history", verifies **AC-9**.
- Beyond the cap: a pull request with more changed files than the exploration
  cap. Verify the un explored files render "unavailable", that the explored set
  is the largest by added line count, and that the synthesizer block names how
  many files were explored, verifies **AC-9**.
- Concurrent collection: more changed files than the concurrency limit, each
  holding prior findings. Verify every explored file's findings appear and the
  session is never entered by two tasks at once, verifies **AC-10**.
- Budget trim keeps attribution and the floor: long paths and short commit
  subjects, enough to overflow the synthesizer budget, with groups carrying
  distinct headers. Verify every surviving detail sits under its own group's
  header, every explored file keeps at least one detail, and no prior finding
  line was removed while a commit line survived, verifies **AC-10**.
- Parity: for one review, verify the synthesizer block's lines for each path
  contain the reviewer render's lines for that same path, verifies **AC-9**.
- The model is told: verify each of the six reviewer prompts and
  `synthesize.txt` names history, and that the synthesizer rule no longer
  forbids citing it, verifies **AC-9**.

## Build plan

Ordered as thin slices through the real pipeline, per the project's Tracer
bullet approach: get one reviewer prompt carrying only its own file end to end,
then widen, then harden.

1. Collector truncates commit subjects and prior finding titles to 120
   characters, records a per path status, and returns a per path block instead
   of a joined string, keeping the 3 commits, 5 findings, and 10 file caps,
   satisfies **AC-7**, **AC-9**
2. Choose the explored set by descending added line count, ties by path, and
   record the rest as `not_explored`, satisfies **AC-7**, **AC-9**
3. Thread the raw block from `collect_history` through `review_service` and onto
   `RepoContext` as one field, and stop `RepoContext.render` from embedding
   history, satisfies **AC-7**, **AC-9**
4. One shared render function taking a path set, rendering the three status
   wordings and the synthesizer header count, satisfies **AC-9**
5. Thin thread end to end: `LlmReviewer` renders its own file's slice at the call
   site, verified through the real pipeline on a multi file pull request,
   satisfies **AC-9**
6. `Synthesizer` renders the full block from the same structure, sorted by path,
   satisfies **AC-7**, **AC-9**
7. Budgets: reviewer render ceiling 400 tokens with no trim, synthesizer fit at
   1200 by signal class with a one detail floor per explored file,
   satisfies **AC-7**, **AC-10**
8. Serial database leg with a 1 second per query timeout, and awaiting cancelled
   tasks after the aggregate deadline, satisfies **AC-8**, **AC-10**
9. Tell the model: one history line in each of the six reviewer prompts, and
   relax `synthesize.txt` rule 1 to admit the recorded history,
   satisfies **AC-9**
10. Update the four tests that encode the old shared context behaviour
    (`test_context.py` render and skip cases, `test_pipeline.py` inject and omit
    cases), and add tests for every scenario above, satisfies **AC-7**,
    **AC-8**, **AC-9**, **AC-10**

## Consequences

**Positive**:
- Injected history falls from about 72,000 tokens to about 9,000 on a ten file
  pull request with history on every file, and the worst case ceiling falls to
  about 24,000.
- Reviewers read only the history of the file they judge, so history stops
  competing with the diff.
- The synthesizer keeps the cross file view, so the value the feature exists for
  survives.
- The model is told history exists and is allowed to cite it, so the feature
  actually changes reviewer behaviour instead of only its cost.
- Absence is honest: a lookup failure no longer reads to the model as "nothing
  was ever wrong here".
- History length is bounded at the source, so the budget logic no longer has to
  defend against unbounded input.

**Negative / tradeoffs**:
- A 120 character commit subject can lose the meaningful tail of a subject line,
  and a truncated subject reads like a complete one.
- Six reviewers per file still receive a byte identical copy of that file's
  slice, so about 6 times the per file cost survives. This is accepted because
  each copy is small (a few hundred tokens) next to the diff and related source
  already in every prompt, and because collapsing six category passes into one
  history aware pass is a pipeline redesign, out of scope here.
- A reviewer can miss a cross file pattern. The synthesizer mitigates this, it
  does not remove it.
- Reviewer prompts are uneven in shape across files: some carry history, some
  carry "no recorded history", some carry "unavailable". That is the point, but
  it is a prompt shape variation to keep in mind when reading model output.
- Token counts are a character heuristic rather than a real tokenizer, so real
  spend can drift from a cap by roughly ten percent. Inherited from the original
  1200 cap.
- Nine prompt files and four existing tests change, so this is a wider diff than
  the original framing suggested.
- The 5 second GitHub deadline stays on the review critical path.

**Neutral**:
- No new table, no new endpoint, no configuration, no migration.
- The collector's return type changes from a string to a per path structure,
  which touches `review_service`, `RepoContext`, `LlmReviewer`, and
  `Synthesizer`.
- Two acceptance criteria were added to the umbrella index, **AC-9** and
  **AC-10**, and **AC-7** and **AC-8** were reworded so they survive the split.
- `python-async-patterns` conventions are load bearing here, since the single
  session rule is the whole reason the database leg is serial.

## Follow-up

- [ ] `RepoContext.render` duplicates far more than history: every one of the
  sixty reviewer calls also receives the full changed file list and up to eight
  related source files at 4000 characters each. That is a larger cost than the
  history block and a separate decision, worth its own spec.
  `docs/specs/review-pipeline.md` Stage 4 is the natural place to record it.
- [ ] Make the evaluation harness able to judge this feature before trusting it.
  Prerequisite work, currently missing: a `history` argument on the harness's
  `run_pipeline` call, and a recording provider, because today's mock provider
  discards the user prompt and can neither inject nor observe a history block.
  Until that seam exists, whether history improves finding quality is unmeasured.
- [ ] Once the harness can carry history, measure whether it changes finding
  quality at all. If it does not, the collection cost is not worth paying and the
  feature should be reduced or dropped rather than optimised further.
- [ ] Consider moving collection off the review critical path. A GitHub hiccup
  currently adds up to 5 seconds to every review.
- [ ] `get_recent_commits` builds a fresh `httpx.AsyncClient` per call, so
  collection adds up to 10 client constructions per review. Fine against
  installation token limits today, worth revisiting at higher volume.
- [ ] Revisit the 6x reviewer multiplier by collapsing the six category passes
  into one history aware pass, if prompt cost ever becomes the binding
  constraint.
- [ ] `python-async-patterns` conventions are not yet captured in `AGENTS.md`.
  This feature leans on them, so they belong at root level. `/sync` owns that
  file.
- [ ] The umbrella `index.md` was edited in the same pass to add **AC-9** and
  **AC-10**, reword **AC-7** and **AC-8**, and correct its historical awareness
  paragraph, so the two files agree.

## Rationale

Option 1 wins on all three forces in Context. The cost force says the shared
block was the wrong shape: a per block cap that is sent sixty times is not a cap,
and `docs/specs/review-pipeline.md` already told this project to narrow context
rather than repeat it. The signal force says the same block was diluted for a
second reason, because a reviewer cannot act on the commit log of a file it is
not judging. The honesty force says the cheapest possible fix, a line that says
"no recorded history", is actively dangerous unless absence is classified first,
so the collector now records a status and only a confirmed empty record is
allowed to make that claim.

Bounding values at collection rather than trimming after the fact is the load
bearing choice inside Option 1, and it is what makes the rest cheap. An
unbounded subject or title made every other number in the design unreliable: a
single file could reach roughly 464 tokens against a 200 cap, so the cap was
inert in the common case and violated more than twice over in the tail. Once the
source value is bounded, a file's cost is arithmetic, the reviewer cap becomes a
guarantee instead of a trim that quietly deletes the best line, and the
synthesizer's fit reduces to a stated eviction order with a floor.

The runner up, a lower shared cap, was rejected because it taxes the synthesizer
to fix a reviewer problem, and because a smaller cap makes the false absence
problem worse by dropping more groups that then render as "no recorded history".
Option 3, measuring first, was rejected because the harness cannot measure this
today; that seam is now a follow up rather than a reason to leave the
multiplication in place.

What is deliberately given up: a reviewer no longer sees a pattern that exists
only across files, and commit subjects are truncated. Both losses are accepted
because the synthesizer still sees the cross file view and a truncated subject is
still far more signal than none.
