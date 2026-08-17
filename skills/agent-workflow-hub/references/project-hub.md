# Project Hub Protocol

Load this reference for whole-project inventory, multi-worktree routing, Project Hub output, cleanup/backfill prompts, or visualization.

## Topology And Ownership

Use `Project context -> Task -> Thread -> Environment(optional)`.

- A Project Hub Task owns the project map, real worktree inventory, routing, prioritization, rebaseline, and reports. It does not own feature implementation detail.
- A task may have several durable discussion, research, review, validation, dogfood, explainer, and primary-execution threads.
- A Primary Execution Task owns implementation, local planning, validation, handoff, finish/archive, and PR text for one task/worktree.
- Project-level threads may have no environment. Absence of a worktree is not an error for those threads.
- Use `parentTaskId` only for real ownership, such as follow-up or validation child tasks. Put merely related relationships in facts/inferences/next step.

Keep normal small work in the current Codex Task. Recommend a new Task/worktree only for independent, parallel, long-lived, separately based, or explicitly requested work. Reuse the same Task/worktree for same-task continuation and tiny non-durable work.

## Whole-Project Audit

`project-status` contains only sidecar-known active tasks and is never the complete worktree inventory. For hub, all-worktree, branch coverage, or backfill requests:

1. Run `audit-project` from the canonical repo/worktree with the expected project id and base branch.
2. If unavailable, combine `project-status`, `git worktree list --porcelain`, and per-worktree `audit-context`.
3. Report branch, worktree path, head SHA, dirty state, `sidecarHit`, task status, handoff/validation/safety availability, stale state, blocker, and next step.
4. Report totals for Git worktrees, sidecar active tasks, tracked/untracked, dirty/stale, missing validation/safety/handoff, and tasks whose worktree no longer exists.
5. Group `threadPromptsByBranch`, backfill prompts, recommended actions, and cleanup prompts by branch/worktree.

Rows with `sidecarHit: false` have no real sidecar task. Report `taskStatus: missing`; never promote provisional audit context into sidecar truth. If project-id input is canonicalized, state it once.

Recommended actions for gaps should contain both `oldThreadBackfillPrompt` and `newExecutionThreadPrompt`; the CLI cannot know whether an older execution Task still has semantic context. Ask a human to confirm merged/abandoned/moved state before cleanup. Never auto-delete worktrees.

## Routing From The Hub

- Whole-project status, prioritization, or routing stays in the hub and starts with `audit-project`.
- One branch/task build, fix, refactor, validate, or finish goes to Primary Execution.
- Repo-bound but fuzzy implementation can start in Primary Execution and plan there.
- Product direction, user value, priority, or whether a task should exist stays in hub/discussion.
- External evidence, prior art, market/ecosystem comparison, novelty, baselines, experiments, or publication readiness belongs in research.
- Short throwaway questions can stay in the current Task; copy only durable decisions back to sidecar or the owning thread.
- Deep onboarding can use explainer; real workflow feedback can use dogfood; narrow independent checks can use review/validation.

## Hub Output

Do not return only the current task. Include compact inventory counts, the worktree table, grouped prompts, recommended actions, execution prompts, and cleanup prompts. Avoid full sidecar JSON and full handoffs.

Execution receipts returned to the hub should lead with `compactReceipt` and `continuePhrase`, then optional task id, handoff path, branch/worktree, validation, risks, PR status, and archive path.

## Visualization

For `visualize project`, `show project graph`, `可视化项目`, `显示项目图`, `项目关系图`, or `看一下项目全局`, run `visualize-project --open-dashboard` in interactive Codex. Return a clickable `dashboardUrl` first, otherwise `dashboardPath`/HTML report path, then Markdown if useful.

Do not paste full JSON, HTML, or Markdown by default. The generated graph uses Project as page context and shows `Task -> Thread -> Environment(optional)`; health belongs in badges/classes and the details table. Latest report files overwrite previous dashboard snapshots.
