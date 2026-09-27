# Scope

**Workflow**: Alpha
**Approach**: Tracer bullet (thin end to end thread first, then thicken)

## At a glance

| Feature | Status | Spec |
|---|---|---|
| V3 auto fix and history | in-progress | [0001](../specs/0001-v3-auto-fix-history/index.md) |
| Prompt context scoping (from spec 0001) | planned | — |
| Evaluation harness history seam (from spec 0001) | planned | — |

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
- [ ] Verify it: /check verify v3 auto fix and history
- [ ] Test it: /test v3 auto fix and history
- code in `src/critiq/ai/history.py`, `src/critiq/analysis/context.py`,
  `src/critiq/pipeline.py`, `src/critiq/ai/synthesizer.py`,
  `src/critiq/apps/worker/review_service.py`, `src/critiq/ai/prompts/`,
  `src/critiq/integrations/github/client.py`

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

### Evaluation harness history seam (from spec 0001)

The evaluation harness calls the pipeline with no history argument and its mock
provider discards the user prompt, so it can neither inject nor observe a
history block. Without this seam, whether history improves finding quality at
all stays unmeasured, and the feature's central premise stays untested.

Done when: the harness accepts a history block and a recording provider captures
the rendered prompts, so a run can be scored with and without history. Needs its
own spec before it is built.

## Deferred

- [ ] Measure whether history changes finding quality, once the harness seam
  above exists. If it does not, reduce or drop the feature rather than optimise
  it further.
- [ ] Consider moving history collection off the review critical path, since a
  GitHub hiccup currently adds up to 5 seconds to every review.
- [ ] `get_recent_commits` builds a fresh `httpx.AsyncClient` per call, so
  collection adds up to 10 client constructions per review.
- [ ] Revisit the 6x reviewer multiplier by collapsing the six category passes
  into one history aware pass, if prompt cost ever becomes the binding
  constraint.