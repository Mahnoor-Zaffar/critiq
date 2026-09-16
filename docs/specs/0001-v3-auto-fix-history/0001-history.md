# 0001. Historical Awareness

**Parent**: `0001-v3-auto-fix-history/index.md`

## Summary

Historical awareness asks the question: what happened in the code before this
PR? For each changed file, the worker pulls the last three commits that
touched that file before the PR from GitHub and the last five earlier Critiq
findings on that file from Postgres, aggregates them into one bounded block of
at most 1200 tokens total, and injects the block into the reviewer prompts. No
new table, no cache, no new endpoint; a failure at any step produces an empty
history and a review that still runs. The feature is on by default, best
effort, and invisible in the final review body.

## Requirements

This child spec implements **AC-7** and **AC-8** in the umbrella index: the
bounded commit and prior finding collection, the token capped injection, and
the never fail guarantee.

## Decision

History is on demand and never persisted. Each review calls the GitHub commits
API for the changed files and reads prior Critiq findings from the existing
`Finding` table joined through `ReviewRun` and `PullRequest` to the repository.
Commits are queried against the base ref (`merge-base`), so the PR's own
commits are excluded and the block reflects how the code evolved before the
PR. The collector caps at 3 commits per file, 5 prior findings per file, and
10 explored files. A total budget of 1200 tokens is enforced across all files
using an approximate character heuristic (4 chars per token for English text).
Injection appends a `History Context` block to the shared context fed to every
reviewer prompt and the synthesizer. Each commits API call has a 2 second
timeout and the whole collection a 5 second aggregate deadline; a
`GitHubClient` error, a database error, or an empty record set produces no
history block and no retry.

**Implementation skills**: `python-async-patterns` (`~/.config/opencode/skills/python-async-patterns/`)

## Feature design

### Data model

No new tables. History is derived from:

- **Prior Critiq findings**: existing `Finding` rows joined through
  `ReviewRun` (with `completed_at`) and `PullRequest` to `Repository`, filtered
  to the same `repository_id` and `file_path`, ordered by `completed_at`
  descending, limited to 5.
- **Recent commits**: GitHub commits API
  `GET /repos/{owner}/{repo}/commits?path={file}&per_page=3` queried against
  the base ref (`merge-base`), extracting the commit message and short SHA.
  Pull request references inside the message (e.g. `#182`) are preserved as
  is. `owner` and `repo` come from the `PullRequest` row via the repository's
  `full_name`. Calls run with bounded concurrency (at most 4 in flight), a 2
  second per call timeout, and a 5 second aggregate deadline across all files.

### Aggregation format

History is assembled as a simple markdown block:

```
History Context

path/to/file.py
- Changed in abc1234: fix null check on user lookup
- Changed in def5678: add retry logic around DB call
- Previously flagged in Run 42 (security): missing auth check on /users/{id}
```

Token budget uses an approximate count of `len(text) / 4`. The total budget is
1200 tokens across all files, split so the file group is trimmed as one unit
(longest entries cut first) when it overflows. The collector explores at most
10 changed files. History groups are not posted to GitHub; they exist only in
the LLM context.

### Value sourcing

| Value produced | Source |
|---|---|
| recent commits per changed file | GitHub commits API against the base ref |
| prior findings per file | `Finding` joined via `ReviewRun`, `PullRequest`, and `Repository` |
| `owner` and `repo` for the API call | `PullRequest` via repository `full_name` |
| token cap | approximate `len / 4` heuristic, total across files |
| per call deadline | 2 second timeout on each commits call |
| aggregate deadline | 5 second bound across the whole collection |
| injection target | reviewer shared context block and synthesizer |

### Key invariants

- History is never a blocking condition. A failure, timeout, or empty result
  set produces no history block; the review proceeds with zero history.
- History is injected before the reviewers run, not appended to the review
  body or the PR summary.
- The total history budget (1200 tokens) is never exceeded across all files.
- Commits are always read against the base ref, never the PR head, so the
  block cannot be dominated by the PR's own churn.
- Collection stops at the 10 file cap and the 5 second aggregate deadline,
  whichever comes first.

### Security model

- History queries use the same `GitHubClient` and database session the worker
  already has; no new permissions, no new secrets.
- The commits API call reads only the file's commit log; no new write access.

### Critical test scenarios

- Happy path: three changed files, two with three commits and prior findings
  and one with none, verify the total history block stays under the 1200 token
  budget across files and the review completes, verifies **AC-7**.
- Basis: a PR whose head branch added many commits still produces history that
  excludes those commits, because the query runs against the base ref,
  verifies **AC-7**.
- Failure case: the commits API returns a 500; verify no history block is
  injected, the review completes, and no error is posted, verifies **AC-8**.
- Deadline: the commits API is slow, the 5 second aggregate deadline expires,
  and the review proceeds with whatever history arrived plus no error,
  verifies **AC-8**.
- Empty state: a brand new file with no prior commits and no prior Critiq
  findings, verify the collector produces an empty history group for that file
  and the review completes normally, verifies **AC-7**, **AC-8**.

## Rationale

The main reason to persist history would be repeated queries across reviews of
the same repository, but that pattern does not exist yet; a single review
per pull request event is the current volume. Storing the data before a
measured repeated use pattern appears would add schema and maintenance cost
with no return. GitHub keeps the authoritative commit log, and the stored
findings table already answers "what did Critiq flag here before."

The token cap exists because the history is context, not the main act. Too
much history drowns the diff, which is what the reviewers actually judge. A
total budget of 1200 tokens at most 3 short commit messages plus 5 short
finding titles per file, enough to surface a prior pattern without dominating
the prompt, and the base ref query keeps the block about the past, not the
PR's own churn.

Inline rationale (short form): the option comparison for on demand versus
cached storage, and injection versus visible summary, is recorded in the
umbrella `rationale.md`, since the reasoning is shared with the V3 decision.