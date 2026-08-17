# Advanced Workflows

Load this reference for backfill, rebaseline, dogfood hygiene/issues, evaluation, reports, or advanced archive behavior. Read `maintenance.md` instead for source-package repair or installation.

## Existing-Project Backfill

Git can prove branches, commits, touched files, and changed areas. It cannot reliably recover intent, design decisions, validation status, blockers, or next step.

Build initial state from:

- Git facts from `snapshot`, `start-feature`, and recent commits.
- Current user/Task context for goal, status, blocker, validation, safety, and next step.
- Existing PR, issue, or release text when available.

When semantics are missing, create provisional state and label unknowns instead of guessing. `touchedFiles` describes current dirty/touched files and is only a locator signal; choose the investigation path that fits the task.

Prefer an old execution Task for backfill when it exists because it may retain semantic context Git cannot recover. Otherwise use the audit's `newExecutionThreadPrompt` to recover or initialize state, distinguish facts/inferences/unknowns, add validation/safety/next step, save a handoff, and return a compact receipt.

## Project Rebaseline

Use `rebaseline-project` when merged PRs or stale historical tasks make the hub/dashboard misrepresent the current repository.

- Distinguish Git facts, inferred baseline, user-confirmed changes, and stale sidecar records.
- Default to recommendations only.
- Use `--update-current-hub-task` only when the user wants a fresh hub task/handoff written.
- Use `--confirm-archive-stale` only after explicit confirmation.
- Recommend `visualize-project` after a written rebaseline.

Never auto-archive or rewrite historical tasks merely because they appear stale.

## Dogfood Hygiene And Issues

Use `hygiene-dogfood` only for stale dogfood/smoke records superseded by later pass evidence. It is report-only by default and excludes ordinary execution tasks. Archive exactly one eligible record only with explicit confirmation and `--confirm-archive --task-id <id>`.

Dogfood issue reporting is draft-only by default. Keep Facts, Inferences, Unknowns, Reproduction, Suggested Fix, and Priority separate. Before issue creation, the CLI must verify GitHub authentication, search likely duplicates, and reject secrets, private paths, long logs, or sensitive content. Created issues receive `agent-reported` and `needs-triage`. On any safety/auth/duplicate failure, return the draft.

## Reports And Evaluation

- Use `weekly-report` for a human project-progress update. Return a short notification and report path, not the full report.
- Use `eval-report` when asked whether AWH is helping or for workflow/dogfood metrics. Its measurements are proxies, not exact token counts or proof of correctness.
- Use `audit-context` before a sensitive handoff/resume when current state trust is uncertain.
- Use `audit-project` rather than `project-status` for real worktree inventory.

## Advanced Archive Safety

Prefer `finish-feature` for completed work. Use manual `archive`, stale-task archival, and dogfood-record archival only for the narrow documented case and only after explicit confirmation. Never delete Git worktrees as a side effect of sidecar cleanup.
