# Routing And Handoffs

Load this reference for detailed task resolution, route confirmation, aliases, handoff loading, or thread registration. The default decisions remain in `SKILL.md`.

## Natural-Language Resolution

- Prefer `resume-query --query "<whole user phrase>"` when the user wants to continue named work from any known project, repo, container, or worktree path.
- Use `resume-feature` only when the user explicitly means the already-selected worktree.
- Use `resolve-task` to inspect or route without resuming.
- Match against user aliases, task id, branch, worktree basename, goal, `continuePhrase`, handoff summary, and touched areas. The local resolver uses normalized strings, token overlap, and `difflib`; it does not use LLMs, embeddings, MCP, UI, or thread APIs.
- Treat `continuePhrase` below exact user aliases and above generated aliases. Treat touched areas/files as locator evidence, not a required first scan path.
- If resolved, follow the returned `cd`/`worktreePath` and summarize compact fields. If unresolved, ask the returned `disambiguationQuestion` once.

## Route Guard

- Respect branch, task id, worktree path, and continue-phrase hints in user instructions or handoffs. Never write a handoff to the current worktree when those hints identify another task.
- Surface `routingStatus: mismatch` or `ambiguous`; do not guess.
- Surface `routingStatus: inferred` and `routingNeedsReview: true`; do not describe inferred relationships as user-confirmed.
- If the user identifies this Task as execution, validation, review, dogfood, discussion, research, hub, or explainer work, orient first. Resume a named task before attaching durable role metadata.
- Attach only after a safe, confirmed route or explicit confirmation. Do not use `--confirm-route` to force an ambiguous candidate into a confirmed task binding.
- For project-level research/discussion/hub topics, use `--scope project-level`. A canonical repo path can be a storage anchor without making the thread feature-scoped.

## Aliases And Containers

- Persist only user-confirmed aliases with `start-feature --alias`, `handoff --alias`, or `alias-task`. Generated aliases remain transient.
- A known non-Git project container can route to the project's latest known worktree/canonical root. If multiple projects match, ask once.
- Use one stable `projectId` across worktrees. Correct inference only when objective Git/config evidence shows it is wrong.

## Loading Saved State

For same-role continuation in a new Task:

```powershell
python scripts\context_sidecar.py resume-query --worktree <known-path> --query "<continue phrase>"
python scripts\context_sidecar.py load-handoff --worktree <resolved-path> --query "<same phrase>" --mode compact
```

- Compact mode is the default: receipt, next step, risks/blockers, and continue phrase.
- Use `--mode section --section validation --reason validation-needed` for validation work.
- Other targeted sections include `risks`, `thread-summary`, `facts`, and `next-step`.
- Use `--mode full` only on explicit request or when compact/section output cannot answer a concrete continuation question.
- If ambiguous, ask once. If no Markdown handoff exists, report that precisely, then use `resume-feature`, `audit-context`, or targeted repo investigation.
- `--thread-id` and `--thread-role` refine metadata selection; the Markdown handoff remains task-level.
- Loading telemetry may record mode, section, reason, role, and content size, never handoff contents, diffs, logs, or reasoning.

## Saving Durable State

Save a handoff when findings must survive the chat, when work passes to another role/agent, when stopping after meaningful work, or when the user asks. Do not save at every startup or turn.

Include concise facts, inferences, unknowns, safety rules, validation commands/results/timestamps, decisions, touched areas, blocker/risks, next step, thread summary, and a natural `continuePhrase`. Keep facts observable or user-provided, inferences labeled, and unknowns unguessed.

Lead the response with `compactReceipt` and `continuePhrase`; task id and handoff path are secondary debugging details.

## Thread Registration

- `scan-codex-threads` reads minimal local metadata and reports mismatches without writing sidecar state. Titles are opt-in; previews and chat content are excluded.
- `reconcile-threads` compares metadata with `threads[].codexThreadId`, caches only mismatch audit state, and returns short `refreshRequests`.
- When Codex thread messaging is available, send each returned refresh prompt to its target. Otherwise return the prompts as manual actions.
- `refresh-thread-registration` runs inside the target Task to update its Codex thread id, role, label, purpose, scope, and last-seen metadata.
- Never read full JSONL transcripts for routine reconciliation.
