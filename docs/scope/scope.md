# Scope

**Workflow**: Alpha
**Approach**: Tracer bullet (thin end to end thread first, then thicken)

## At a glance

| Feature | Status | Spec |
|---|---|---|
| V3 auto fix and history | in-progress | [0001](../specs/0001-v3-auto-fix-history/index.md) |

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
block. See the acceptance criteria AC-1 through AC-8 in the spec.

- [x] Design it (spec)
  - [0001](../../specs/0001-v3-auto-fix-history/index.md): V3 auto fix and history
- [ ] Build it: /develop v3 auto fix and history
  - [x] Data model and config: `AutoFixPatch` and `OrgSetting` migration, `fix` block parsing, profile merge (AC-1, AC-4, AC-5, AC-6)
  - [x] Patch eligibility + generation: eligibility filter, structured generation, tree-sitter validation, one retry then logged drop (AC-1)
  - [ ] Workspace clone, test runner, and suggestion posting: clone, targeted tests, suggestion as the finding's comment (AC-2, AC-3)
  - [ ] Lifecycle reconcile and push mode: applied, rejected, regenerate, and closed paths; org settings endpoints; Contents API push with a live ref guard and fork and protection fallbacks (AC-4, AC-5, AC-6)
  - [ ] History: base ref commits API and prior findings collector, total token budget, injection into reviewer and synthesizer prompts (AC-7, AC-8)
- [ ] Verify it: /check verify v3 auto fix and history
- [ ] Test it: /test v3 auto fix and history

## Deferred

None.