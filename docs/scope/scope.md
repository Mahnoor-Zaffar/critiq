# Scope

**Workflow**: Alpha
**Approach**: Tracer bullet (thin end to end thread first, then thicken)

## At a glance

| Feature | Status | Spec |
|---|---|---|
| V3 auto fix and history | verified | [0001](../specs/0001-v3-auto-fix-history/index.md) |
| Prompt context scoping (from spec 0001) | planned | — |
| Evaluation harness history seam (from spec 0001) | in-progress | [0002](../specs/0002-eval-harness-history-seam.md) |

## Current cycle

### V3 auto fix and history

Turn advice into action: eligible deterministic findings become tested,
single file patches offered as one click GitHub suggestions, with an optional
org gated push mode that commits verified fixes directly to the branch.
Reviewers gain recent history of the changed files (commits before the PR and
earlier Critiq findings) so reviews are grounded in how the code evolved.

Done when: a tested custom rule finding posts as a suggestion the author can
accept in one click; unverified offers are labelled, failing tests never post,
offered patches reconcile to applied or rejected across events, push mode is
double gated and compare and set, and reviewer prompts carry a bounded history
block that distinguishes a clean file from an unchecked one. See the acceptance
criteria AC-1 through AC-10 in the spec.

- [x] Design it (spec)
  - [0001](../specs/0001-v3-auto-fix-history/index.md): V3 auto fix and history
- [x] Build it: /develop v3 auto fix and history
  - [x] Data model and config: `AutoFixPatch` and `OrgSetting` migration, `fix` block parsing, profile merge (AC-1, AC-4, AC-5, AC-6)
  - [x] Patch eligibility + generation: eligibility filter, structured generation, tree-sitter validation, one retry then logged drop (AC-1)
  - [x] Workspace clone, test runner, and suggestion posting: clone, targeted tests, suggestion as the finding's comment (AC-2, AC-3)
  - [x] Lifecycle reconcile and push mode: applied, rejected, regenerate, and closed paths; org settings endpoints; Contents API push with a live ref guard and fork and protection fallbacks (AC-4, AC-5, AC-6)
  - [x] History: base ref commits API and prior findings collector, bounded 1200 token injection into reviewer and synthesizer prompts, failure handling and aggregate deadline (AC-7, AC-8)
  - [x] History collection rework: bound commit subjects and prior finding titles at collection, record a per path status, select the explored set by added line count, return a per path block (AC-7, AC-9)
  - [x] History prompt scoping: thread the raw block, stop the shared context carrying history, one render function at the call site, each reviewer scoped to its own file at 400 tokens, synthesizer full at 1200 (AC-7, AC-9)
  - [x] History budgets and bounds: reviewer ceiling that never trims, synthesizer fit by signal class with a one detail floor per file, serial database leg with a 1 second per query timeout (AC-7, AC-8, AC-10)
  - [x] History tells the model and covers itself: a history line in each of the six reviewer prompts, `synthesize.txt` rule 1 relaxed to admit recorded history, the four tests that encode the old shared context updated, scenario tests added (AC-8, AC-9, AC-10)
- [x] Verify it: /check verify v3 auto fix and history
  - Ten of ten acceptance criteria driven against the running app with a real HTTP fake, a real git clone, a real pytest subprocess and real Postgres
  - Two defects found and fixed: `AutoFixRunner._suggestion` stored untested patches as `passed`, and `_apply_push_mode` compared the live ref against itself instead of the tested head
  - Fixes: store the real verifier verdict, carry the head under test on `ReviewResult`, and refuse to push when it is unknown or has moved
- [x] Test it: /test v3 auto fix and history
  - Full suite 215 passed; the two defects are locked in by regression tests that fail without their fix
- code in `src/critiq/ai/history.py`, `src/critiq/analysis/context.py`,
  `src/critiq/pipeline.py`, `src/critiq/ai/synthesizer.py`,
  `src/critiq/apps/worker/review_service.py`, `src/critiq/ai/prompts/`,
  `src/critiq/integrations/github/client.py`

### Evaluation harness history seam (from spec 0001) · in-progress

The evaluation harness calls the pipeline with no history argument and its mock
provider discards the user prompt, so it can neither inject nor observe a
history block. Without this seam, whether history improves finding quality at
all stays unmeasured, and the feature's central premise stays untested.

Done when: one command scores a run with and without history, the report shows
the difference alongside what each prompt actually received, a trimmed block is
distinguishable from one that never arrived, and a mock run is labelled as
plumbing proof rather than a quality result. See the acceptance criteria AC-1
through AC-12 in the spec.

- [x] Design it (spec)
  - [0002](../specs/0002-eval-harness-history-seam.md): A history seam for the evaluation harness
- [ ] Build it: /develop evaluation harness history seam
  - [ ] Shared history surface: promote the token estimator, add `EvalHistory` to each changed file in the dataset with status derived from content, and fold a case into one `HistoryBlock` (AC-1, AC-2, AC-3, AC-8)
  - [ ] Injection and observation: give `run_evaluation` an arm argument, pass the block to the pipeline, and add a recording provider that attributes every prompt to a file and records authored beside rendered history lines (AC-4, AC-5, AC-6, AC-7)
  - [ ] Comparison and report: add `compare_arms` and the metric deltas, then render the delta table, the per case table, and the prompt observation section with the provider mode and non repeatability note (AC-9, AC-10, AC-12)
  - [ ] Command line: run both arms by default with an arm flag to narrow, name the arm and case in a provider failure, and cover failure, trimming, attribution, and old datasets (AC-11)
- [ ] Verify it: /check verify evaluation harness history seam

## Next up

### Prompt context scoping (from spec 0001)

`RepoContext.render` sends every one of the sixty reviewer calls the full changed
file list plus up to eight related source files at 4000 characters each, which
costs more than the history block ever did. Render the shared context per file
the same way history now is.

Done when: each reviewer prompt receives only the changed file list and related
source relevant to the file it is judging, the synthesizer keeps the full
context, and injected context tokens fall by a measured amount on a ten file pull
request. Needs its own spec before it is built.

### Grow the evaluation dataset (from spec 0002)

`datasets/` holds one case with two expected findings, so any precision or recall
delta computed from it is noise rather than evidence. Labelled cases are the input
the quality measurement needs, and they are the thing standing between the history
feature and an evidence based keep or drop decision.

Done when: the dataset holds enough labelled cases that a precision or recall
delta between two runs means something, and the harness can score it end to end.
Needs its own spec before it is built.

## Deferred

- [ ] Measure whether history changes finding quality, once the harness seam
  above exists and the dataset is large enough. If it does not, reduce or drop
  the feature rather than optimise it further.
- [ ] Consider moving history collection off the review critical path, since a
  GitHub hiccup currently adds up to 5 seconds to every review.
- [ ] `get_recent_commits` builds a fresh `httpx.AsyncClient` per call, so
  collection adds up to 10 client constructions per review.
- [ ] Revisit the 6x reviewer multiplier by collapsing the six category passes
  into one history aware pass, if prompt cost ever becomes the binding
  constraint.
- [ ] Reconcile the status of `docs/specs/0001-v3-auto-fix-history/index.md`,
  which still reads `In Progress` while this scope records that feature as
  verified.
