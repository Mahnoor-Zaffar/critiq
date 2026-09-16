# Rationale

**Date**: 2026-09-16

## Context

> Premise note: The system has no org or human auth model today. The requested
> org level admin role is approximated here as an operator token plus a small
> `OrgSetting` table, which is the honest minimum for a single operator setup.
> Shipping push mode also widens the GitHub App permission to write contents;
> a team that wants zero write risk can ship suggestions only and skip push
> mode entirely, and the spec still works.
>
> Premise note: The heaviest new cost is cloning and running tests inside the
> worker for every eligible finding. The design bounds it with one cap per
> file, one clone per review, a base clone cache under `CRITIQ_WORKSPACE_DIR`,
> and a 60 second per patch test cap. Bounded volume, not unbounded volume,
> is the assumption.

Critiq currently reads a diff, builds context, runs six reviewers plus custom
rules, validates evidence, gates by severity and confidence, and posts a
review. The loop is closed on feedback, confidence calibration, and the
dashboard. V3 turns the loop from advice into action: suggested fixes the
author can accept in place, and a review that knows the recent story of the
files it judges.

Three forces shaped the design. First, trust. A stranger creating commits on a
branch is a different act from leaving a comment, so the design separates the
two behind different gates: suggestions are the default, code writing needs
explicit org approval. Second, cost. Verifying a patch means cloning code and
running tests, which is expensive if done per finding across the whole suite,
so the design runs only the changed file's targeted tests with a hard cap.
Third, restraint. The existing data model already stores every finding with a
file path, so "what did Critiq flag on this file before" is one query, and
GitHub already keeps full commit history, so "what changed in this file
recently" is one API call. No new storage is worth building for either.

## Options considered

### Automated fixes: presentation and write model

**GitHub suggestion comments**: the default. Authors click accept; the diff
renders natively; no new surface. Cons: GitHub suggestions live inside one
diff hunk, so cross hunk and cross file fixes do not fit, which is why the spec
caps a patch to one contiguous hunk and one file.

**Commit to the PR branch ourselves**: true code writing. Power and risk need a
separate gate, which is why it exists as an add on behind `OrgSetting` and the
`fix.apply` config, defaulting to off, and bounded by compare and set plus
single verified file commits.

**Both (small suggestions plus large commits)**: the largest scope, deferred.
Suggestion first, push later, keeps the V3 thread thin.

### Verification depth

**Run the targeted tests for the changed file**: the chosen depth. Bounded,
repeatable, and meaningful for the line level fixes auto fix produces. Cons: a
file can have no dedicated tests, which forces the unverified fallback.

**Run the full test suite**: the strongest signal and the most expensive. Not
viable per finding on a worker; reserved as a possible later CI driven mode.

**No verification**: rejected. An unverified offer is still posted (degrade
path) but only as a labelled suggestion, never as a pushed commit.

### Patch generation contract

**Structured replacement**: the model returns `file`, `start_line`, `end_line`,
and `replacement_text`; we validate it, convert it to a diff and a suggestion
block. Deterministic when the finding is mechanical, model generated when it is
not. Chosen for the clean validation boundary.

**Raw unified diff text**: harder to validate and easier for a model to get
format wrong. Rejected.

**Template based**: fits custom pattern rules only, too narrow for the 
deterministic analyzer findings that ship first. Deferred.

### Applied and rejected state

**Diff recompute on the next event**: the chosen approach. We already receive
every `pull_request` event; comparing the stored replacement against the head
is unambiguous and needs no new webhook subscription.

**Review comment event only**: faster on some flows but misses pushes that came
in without a comment event. Rejected.

### History storage

**On demand, no table**: the chosen approach. History is perishable review
context, not a product. One API call per changed file plus one query against
existing rows covers it.

**Cached history table**: premature. No repeated query pattern exists yet; add
it only when a measured need appears.

## Rationale

The core decision is to keep the loop line level and human gated. A suggestion
the author accepts is a higher trust act than a pushed commit from an AI,
because the human still chose it. That is what the double gate protects:
anything posted must pass the quality gate, and anything written to a branch
must additionally pass a configured category, a passing targeted test, and an
explicit org approval. Separate gates keep the trust argument honest.

The targeted test bound is the decision that makes the feature affordable. A
single clone per review, one patch per file, and a 60 second test cap keep the
worker cost proportional to the few findings that qualify, which the
`max_patches` cap bounds even further. When the bound cannot be met (no tests,
non Python, timeout), the degrade path keeps the author experience intact by
still offering the fix labelled as unverified.

History is deliberately read only and volatile. The stored findings and the
GitHub commit API together answer the regression question with no new schema.
The 1200 token cap stops the history block from crowding out the diff, and the
best effort rule stops a context source from ever failing a review.

## References

None: the engineer chose to keep the spec clean of external links. The design
reads the existing specs `api.md`, `data-model.md`, `architecture.md`, and
`configuration.md`, plus the GitHub REST API paths named in `api.md`.