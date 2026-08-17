# CLI Action Catalog

Load this catalog only when the default routing in `SKILL.md` does not identify the action or exact intent is needed.

## Task And Thread Lifecycle

- `start-feature`: create/update the active task for the current branch/worktree with goal and next step.
- `alias-task`: add/remove a user-confirmed alias.
- `attach-thread`: attach durable role, label, purpose, parent task, phase, scope, and route-review metadata.
- `orient-thread`: report role/project/task orientation and suggested next actions; write only with `--attach` on a safe or confirmed route.
- `resolve-task`: resolve a natural-language query without continuing work.
- `resume-feature`: recover compact current-worktree task, Git, handoff availability, stable docs, and next-step state.
- `resume-query`: resolve a natural-language task and resume the matched worktree at sufficient confidence.
- `handoff`: save concise durable state, validation, risks, safety, next step, continue phrase, and compact receipt.
- `load-handoff`: load compact, section, or full saved handoff context; compact is the default.
- `finish-feature`: finish/archive the active task; create a PR only when explicitly authorized.
- `project-status`: compact sidecar-known project tasks for planning, not a complete Git worktree inventory.
- `snapshot`: current-worktree Git facts for lightweight backfill.

## Trust And Project Audit

- `audit-context`: check handoff presence, stale HEAD/dirty files, validation, safety, blocker, and backfill needs for one task.
- `audit-project`: compare real Git worktrees with sidecar tasks and return inventory, gaps, prompts, and recommended actions.
- `rebaseline-project`: inspect Git, sidecar history, and recent merged PRs; recommend baseline changes by default.
- `hygiene-dogfood`: report stale dogfood/smoke records superseded by later pass evidence; archive only one explicitly confirmed eligible record.
- `weekly-report`: write a human Markdown progress report under sidecar `reports/` and return only a short notification by default.
- `eval-report`: write proxy workflow evaluation Markdown/JSON; it is not exact token accounting or correctness proof.
- `visualize-project`: write latest-only Markdown, JSON, and HTML Project Hub views; use `--open-dashboard` for interactive visualization requests.

## Thread Metadata Audit

- `scan-codex-threads`: read minimal local Codex metadata and report registration mismatches without sidecar writes.
- `reconcile-threads`: compare Codex metadata with sidecar thread registrations and return short refresh prompts.
- `refresh-thread-registration`: update the current Task's Codex thread id and durable role/label/purpose/scope metadata.

## Dogfood And Configuration

- `draft-issue`: create a structured local dogfood/debug issue draft; never requires GitHub CLI.
- `create-issue`: create a GitHub issue only when authorized, authenticated, safe, and not a likely duplicate.
- `enable-dogfood-issue-mode` / `disable-dogfood-issue-mode`: persist local permission for dogfood issue creation.
- `set-language`: persist `zh-CN` or `en` for human-facing sidecar output.
- `setup`: create the local project sidecar layout.
- `doctor`: report Python, Git, repository, sidecar, and optional GitHub CLI readiness without installing or changing global configuration.

## Advanced And Legacy

- `init`: legacy alias for `setup`.
- `intake`: legacy low-level resume JSON; prefer `resume-feature`.
- `archive`: advanced manual archive; prefer `finish-feature` for completed feature work.
