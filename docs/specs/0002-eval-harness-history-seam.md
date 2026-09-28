# 0002. A history seam for the evaluation harness

**Date**: 2026-09-27
**Status**: In Progress

## Summary

The evaluation harness (the tool that runs Critiq's review pipeline over a set of
labelled pull requests and scores the result) cannot see the history block that
the pipeline now injects into reviewer prompts. Spec 0001 added that history:
recent commits and earlier Critiq findings for each changed file. Nothing measures
whether it helps. This spec adds the seam, meaning the place where the harness
hands history to the pipeline and reads back what reached each prompt. A case
carries its history as plain data, a recording provider captures every prompt, and
one command scores the dataset twice, with and without history, and prints the
difference. The point is to turn the feature's central premise, that history makes
reviews better, into something you measure rather than assume.

## Context

Spec 0001 made reviewers history aware and is verified. Its premise, that grounding
a review in how the code evolved produces fewer and better findings, was accepted on
reasoning alone. The scope already defers the measurement, blocked on the harness:
the harness calls the pipeline with no history argument, so the pipeline renders an
empty block every time, and its mock provider accepts a system prompt, a user prompt,
and a schema, then discards all three and returns one canned response. The harness
can therefore neither inject a history block nor observe one. Until that changes, the
question of whether history earns its prompt tokens has no answer, and if the answer
is that it does not, the team keeps paying for it.

The forces shaping a fix are narrow. A scored run has to be repeatable offline, so it
cannot depend on GitHub credentials, a database, or the clock. The project rule is a
provider agnostic model layer, so nothing here may name a single vendor. The history
render and its budgets already exist in `src/critiq/ai/history.py` and were verified
against real code, so the harness must call them rather than reimplement them, or the
harness and the production budgets would drift. And the seam has to distinguish two
different claims, because they need different evidence: the plumbing claim that a
history block reaches a prompt at all, which is deterministic and provable with the
mock, and the quality claim that history changes the findings, which needs a real
model and is noisy.

> ⚠️ Premise note: this seam unblocks the measurement but does not perform it. The
> dataset today is one case with two expected findings, so any precision or recall
> delta computed from it is noise, not evidence. What this spec delivers is the ability
> to ask the question honestly. A quality claim needs a dataset with enough labelled
> cases to support it, which is separate work and is recorded under Follow-up. Building
> the seam first is still the right order, since it is the thing blocking that work.

## Requirements

**User stories**:
- As someone deciding whether Critiq's history feature earns its cost, I want a run scored with and without history in one command so that I can see its effect instead of assuming it.
- As someone debugging the seam, I want every prompt the harness sent captured with the file it judged so that I can tell a missing history block from a trimmed one.

**Acceptance criteria** (the contract, each criterion is IDed and independently checkable):
- **AC-1**: A dataset case can author a history block on each of its changed files, and the harness folds a case's files into exactly one `HistoryBlock` keyed by path, with one entry per changed file.
- **AC-2**: A changed file with no authored history block is treated as a confirmed empty record, so the reviewer prompt shows the clean file wording and never claims history was unchecked.
- **AC-3**: The per file status is derived from content, where any commit or finding line means `ok` and no lines means `empty`, and may be overridden only to `unavailable` or `not_explored`, the two failure wordings from spec 0001.
- **AC-4**: The harness can run one arm either with or without the case history, and passes the block to the pipeline, so reviewer prompts for a file carry that file's history rendered from the shared render function.
- **AC-5**: A recording provider wraps any provider, captures the system prompt, user prompt, and schema of every call, attributes a call to a file from the `Changed file:` marker in its user prompt, and leaves the file unset for the synthesis call, which has no such marker.
- **AC-6**: With the mock provider the two arms provably differ in what reached the prompt: in the with history arm a file's prompts carry that file's authored history lines and no other file's, a file with no authored block carries the clean file wording, and in the without history arm no prompt carries any history section at all.
- **AC-7**: Every recorded prompt carries both the history lines the case authored for that file and the lines the render actually emitted, so a block the synthesizer trimmed under its budget is visible and is distinguishable from a block that never arrived. A reviewer section renders in full and is never trimmed, so its authored and rendered counts are equal and the report must not claim otherwise.
- **AC-8**: The token estimate reported for a prompt comes from the same shared helper the history budgets use, so the report and the budgets it checks cannot drift apart.
- **AC-9**: A comparison entry point runs both arms and reports the difference in precision, recall, false positive rate, useful finding rate, and prompt tokens, each as the without value, the with value, and the change.
- **AC-10**: The report prints a delta table, a per case table, and a prompt observation section that states which provider mode produced the run and that a real provider run is not repeatable, so a small delta is not mistaken for a result.
- **AC-11**: The command line runs both arms by default, can be narrowed to a single arm for debugging, and a provider failure in either arm aborts the run with a message naming the arm and the case.
- **AC-12**: A real provider run reports the quality delta, while a mock run is labelled as proving plumbing only and never presents its delta as a quality claim.

- AC-9 is a comparison of two arms, so rounding matters more than usual: the existing
report formats every rate as a whole percent, which would turn a real sub one percent
change into a flat `0%` and hide it. The delta table must therefore show one decimal
place and a signed change, and must carry the underlying finding counts (true positives,
false positives, false negatives) beside every rate, so a reader can see whether a
change came from a different numerator or a different denominator.

## Options considered

### Option 1: Recorded history in the dataset, one command runs both arms (chosen)

A case carries its history as data under each of its changed files. The harness folds
a case into a `HistoryBlock`, runs the dataset once without history and once with it,
and prints a delta table alongside what each prompt actually received.

**Pros**:
- Deterministic and offline, so no credentials, no database, and no clock in the scored path.
- The comparison cannot be forgotten or run with mismatched settings, because one command does both arms.
- The recorded prompts make a broken seam distinguishable from a genuine no effect result.

**Cons**:
- History in the dataset is authored, so it can drift from what the real collector would return for that pull request.
- Still needs a real model run for any quality claim, which costs tokens and is noisy.

### Option 2: Observation only, no comparison

Add history injection and the recording provider, and stop there. The harness proves
the seam works and bounds the injected tokens, but reports no delta.

**Pros**:
- Smallest change that unblocks debugging, and fully deterministic.
- No model spend at all, so it can run on every code change.

**Cons**:
- Leaves the premise unmeasured, which is the entire reason the seam is on the list.
- Produces no number anyone can quote, so it will not change any decision.

### Option 3: Collect history live inside the harness

Run the real collector against GitHub and Postgres during an evaluation run, so the
history is genuine rather than authored.

**Pros**:
- History is exactly what production would collect, including real timeout and failure behaviour.

**Cons**:
- Every scored run needs GitHub credentials and a populated database, and becomes slow and nondeterministic.
- Couples the offline harness to two external systems, so a GitHub hiccup becomes an evaluation failure.

### Option 4: Teach the mock to vary by prompt so the comparison is deterministic

Make the mock return different findings depending on whether history was present, so
both arms run offline and produce a stable delta.

**Pros**:
- Fully deterministic and free, and the harness's own comparison logic gets exercised on every run.

**Cons**:
- Measures the harness, not the model. The resulting number could not be read as a quality claim, which is the only reason the seam exists.
- Encourages reading a fabricated delta as a result, which is the exact failure this feature is meant to prevent.

## Decision

**Chosen option**: Option 1: recorded history in the dataset, one command runs both arms.

A case authors its history inline under each changed file, the harness folds that into
a `HistoryBlock` and runs both arms in one command, and a recording provider captures
every prompt so the report shows what was injected as well as what was scored.

## Rationale

Option 1 is chosen because the two claims this feature must keep apart have different
evidence needs, and only this option serves both from one deterministic run. The
plumbing claim is provable offline with the mock, and AC-6 makes it a test rather than
an assertion. The quality claim needs a real model, so AC-12 forbids a mock delta from
being read as one. Recording prompts is what keeps those claims separable: without
AC-5 and AC-7 a zero delta is ambiguous between history doing nothing and history never
arriving, and that ambiguity is precisely what would let a broken seam survive.

History is authored rather than collected because the scored path must be repeatable
and credential free, and because the collector was already verified against real code
in spec 0001. Duplicating its render and budgets inside the harness was rejected
because the report would then be measuring a fork of the code under test, and AC-8
pins the one shared estimator so the two cannot drift.

Nesting history under each changed file, with the status derived from content, was
chosen over an authored status because it makes a whole class of dataset bug
impossible: a case cannot declare a file clean while listing lines for it, and cannot
name a file it does not change. The cost is that the two failure wordings need an
explicit override, which AC-3 permits and confines to those two values.

## Feature design

**Data model sketch** (no database and no migration; the harness opens no session):

| Type | Kind | Fields | Key |
| --- | --- | --- | --- |
| `EvalCase` | exists, unchanged | id, repo, number, title, files, expected | id |
| `EvalFile` | extends | path, patch, source, history | path within its case |
| `EvalHistory` | new | commits, findings, status override | owned by its file |
| `HistoryBlock` | exists, unchanged | entries keyed by path, changed_file_count | frozen |
| `PromptRecord` | new | system, user, schema, file, tokens, history lines authored, history lines rendered | none |
| `EvaluationReport` | exists, unchanged | cases, by category, aggregate data, `to_markdown` | none |
| `ArmResult` | new | label, report, prompts, prompt token total | label |
| `ComparisonReport` | new | without history arm, with history arm, deltas | none |

A case holds many files. A file holds zero or one history block, and zero means checked
and empty. A case folds into exactly one `HistoryBlock` with one entry per changed file.
An arm holds many prompt records, one per provider call. The comparison holds one of
each arm. An `ArmResult` wraps the existing `EvaluationReport` rather than redefining it,
so the per case and by category tables already written for a single arm keep working and
the comparison only has to add the delta view. Status is derived: any commit or finding
line means `ok`, no lines and no override means `empty`, and an override may only say
`unavailable` or `not_explored`.

**Interface surface** (a library and command line, not an HTTP service):

| Surface | Kind | Key inputs | Key outputs | Notes |
| --- | --- | --- | --- | --- |
| `run_evaluation` | function | cases, provider, policy, arm, run pipeline | `EvaluationReport` for one arm | gains `arm`; keeps the existing injectable `run_pipeline` |
| `compare_arms` | function | cases, provider, policy | `ComparisonReport` | runs `run_evaluation` twice |
| `history_for_case` | function | one `EvalCase` | `HistoryBlock` | folds files into one block |
| `RecordingProvider` | class | any provider | `.calls: list[PromptRecord]` | forwards every call untouched |
| `critiq-evaluate` | command | dataset, provider, arm, output | markdown report on stdout or a file | both arms by default |

The `arm` value is `none` or `case`. The command line takes `--provider`
(`mock` or `openrouter`, already present), a new arm flag accepting `none`, `case`, or
`both`, and the existing `--model` and `--output`.

Two existing signatures constrain this. `run_evaluation` already accepts an injectable
`run_pipeline` callable that defaults to `run_review`, and `run_review` already takes
`history` as a keyword argument, so no production signature changes. The harness must
pass `history` only in the case arm, so a caller that injects its own pipeline callable
that takes no `history` argument keeps working, and the existing single arm test keeps
passing without a rewrite.

**Value sourcing** (every value an acceptance criterion needs, and where it comes from):

| Action | Value produced or displayed | Source |
| --- | --- | --- |
| Fold a case | commit and finding lines per file | the case's authored `history` block in the dataset YAML |
| Fold a case | per file status | derived from line presence, per AC-3 |
| Fold a case | `changed_file_count` | the case's file list |
| Run one arm | which arm was run | the `arm` argument, from the command line or the function call |
| Run one arm | precision, recall, false positive rate, useful rate | the existing `measure` and `AggregateMetrics` in `src/critiq/ai/evaluation/metrics.py` |
| Record a prompt | system, user, schema | the arguments the wrapped provider received |
| Record a prompt | file judged | the `Changed file:` marker in the user prompt, absent for synthesis |
| Record a prompt | history lines authored | the case's history block for that file |
| Record a prompt | history lines rendered | lines beginning with `- ` after the history marker in that prompt, which is `Recorded history for the file you are reviewing:` for a reviewer and `Recorded history (how these files evolved before this PR):` for the synthesizer |
| Record a prompt | prompt tokens | the shared `estimate_tokens` helper, per AC-8 |
| Compare arms | each metric change | subtraction of the two arms' values, formatted to one decimal place with an explicit sign, per AC-9 |
| Compare arms | the counts behind each rate | true positives, false positives, false negatives, and predicted and expected totals, all already in `aggregate_dict` |
| Compare arms | an arm's total prompt tokens | the sum of the recorded `tokens` over every prompt in that arm, reported as a total and as a per case sum so a larger dataset does not read as a cost change |
| Report | per case row | the existing per case metrics for each arm on one row, so a change is read per case and not only in aggregate |
| Report | provider mode | the `--provider` argument, carried into the report |
| Report | non repeatability note | a fixed line, per AC-10 |

**Key invariants**:
- A `HistoryBlock` for a case has exactly one entry per changed file, so no entry can name a file the case does not change.
- A status override may only be `unavailable` or `not_explored`; any other authored value is rejected at load time.
- A mock arm's delta is never rendered as a quality claim.
- The with history arm for a file carries that file's history and no other file's, because the render is already scoped per file by spec 0001.
- A reviewer section is never trimmed, so authored and rendered counts are equal there and only the synthesis prompt can show fewer rendered than authored.
- The without history arm carries no history section at all, because the render returns an empty string for an absent block, so the two arms are never byte identical even when nothing is authored.
- A provider failure aborts the whole comparison rather than yielding a partial arm.

**Security model**: none to add. This is an offline command line tool with no authentication, no tenants, and no regulated data. One consequence is worth stating: a real provider run now also sends prior commit subjects and earlier finding titles, which is the same repository content the diff and file sources already send, so it needs no new gate.

**Configuration required**: no new environment variables or credentials. The new configuration is the arm flag on the command line.

**Critical test scenarios** (each maps to an acceptance criterion):
- Happy path: one case with history on two files, mock provider, both arms, verifies **AC-1**, **AC-4**, **AC-6**, **AC-9**
- Derived status: a file with no history block renders the clean file wording rather than an unchecked claim, verifies **AC-2**, **AC-3**
- Trimmed block: a synthesis prompt for a case authoring more history than the synthesis budget allows shows fewer rendered than authored, while a reviewer prompt for the same case shows them equal, verifies **AC-7**
- Nothing authored anywhere: the with history arm still differs from the without arm, because the with arm carries a per file header and the clean file wording while the without arm carries no history section, verifies **AC-2**, **AC-6**
- Synthesis attribution: the synthesis call has no `Changed file:` marker and its file is unset, verifies **AC-5**
- Failure: the provider raises on the third case of the with history arm and the message names the arm and the case, verifies **AC-11**
- Mock labelling: a mock run's report states it proves plumbing only, verifies **AC-12**
- Token agreement: the report's prompt token figure equals what the shared estimator returns for that prompt, verifies **AC-8**
- Rounding: a delta smaller than half a percent still renders as a visible signed change and the counts behind it are printed, verifies **AC-9**
- Backward compatibility: an existing dataset with no history blocks still loads, both arms run, and the existing single arm test still passes, verifies **AC-2**, **AC-11**

## Build plan

The project approach is Tracer bullet, so the first slice stands one case up end to
end through dataset, harness, provider, and report before anything is thickened. There
is no schema change and no migration in any slice.

1. Promote the private token estimator at `src/critiq/ai/history.py:340` into a shared `estimate_tokens` helper and have history call it, so one implementation serves the budgets and the report, satisfies **AC-8**
2. Add `EvalHistory` and the optional `history` block on `EvalFile`, with status derived from content and overrides confined to the two failure wordings, satisfies **AC-1**, **AC-2**, **AC-3**
3. Add `history_for_case` to fold a case's files into one `HistoryBlock` keyed by path, satisfies **AC-1**
4. Add `RecordingProvider` in the providers layer as a wrapper that captures every call and forwards it untouched, satisfies **AC-5**
5. Give `run_evaluation` an `arm` argument and pass the folded block to the pipeline, satisfies **AC-4**
6. Tracer thread: one case with one file's history, mock provider, assert the history reached that file's prompts and no other file's, satisfies **AC-6**
7. Record authored lines beside rendered lines on every prompt record, counting rendered lines beneath each prompt's own history marker, and cover the synthesis trim case alongside the untrimmed reviewer case, satisfies **AC-7**
8. Add `compare_arms` returning both arms and the metric deltas, formatting every rate to one decimal place with an explicit sign and carrying the finding counts beside each rate, satisfies **AC-9**
9. Render the delta table, the per case table, and the prompt observation section including the provider mode and the non repeatability note, reusing the existing single arm report rather than duplicating it, satisfies **AC-10**, **AC-12**
10. Wire the command line to run both arms by default with the arm flag to narrow, and name the arm and case in a provider failure, satisfies **AC-11**
11. Cover the failure, trimming, attribution, rounding, and backward compatibility scenarios, satisfies **AC-7**, **AC-9**, **AC-11**

## Consequences

**Positive**:
- Whether history helps becomes measurable, so the feature can be kept, tuned, or dropped on evidence.
- A broken seam is distinguishable from a genuine no effect, because the report shows what reached each prompt.
- The harness gains a general prompt recorder that any future eval or debug script can reuse.
- Existing datasets and existing callers keep working, since the history block is optional.

**Negative / tradeoffs**:
- Two arms means roughly double the pipeline calls and double the model spend on a real provider run.
- A real provider run is not repeatable, so a small delta is not a result, and the report can only warn about this rather than fix it.
- Authored history can drift from what the live collector would return for the same pull request, so the harness measures the render, not the collector.
- The `Changed file:` marker and the `- ` history line prefix become a mild coupling between the harness and how prompts are worded, so rewording a prompt could break attribution.

**Neutral**:
- No migration and no new environment variables.
- The recording provider holds every prompt in memory, which is bounded by dataset size and fine at this scale.
- Prompt token figures stay an estimate using the project's existing characters divided by four heuristic, not a real tokenizer.

## Migration plan

**Strategy**: no migration needed. The change is additive and the new key is optional.

**Phases**: none. The dataset format change ships with the code that reads it, and
because the `history` block on a file entry is optional, every existing dataset keeps
loading and its files resolve to `empty`.

**Rollback**: revert the commit. No data is transformed, so there is nothing to undo.

**Risks**: a case that names a history block for a file it does not change, or authors a
status other than the two permitted overrides, is rejected at load time rather than
silently ignored, which surfaces dataset mistakes early but means a malformed dataset
fails the whole run instead of one case.

## Follow-up

- [ ] Grow `datasets/` before making any quality claim. It holds one case with two expected findings, which cannot support a precision or recall delta. This is the first thing to do after the seam lands, and it blocks the deferred scope item that measures whether history changes finding quality.
- [ ] Run the measurement once the dataset is large enough, and if history does not help, reduce or drop the feature rather than tune it further.
- [ ] `docs/specs/0001-v3-auto-fix-history/index.md` still reads `In Progress` while the scope records that feature as verified, so the two disagree. Reconcile the status when convenient.
