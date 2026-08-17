---
name: context-handoff
description: Legacy-compatible Agent Workflow Hub entrypoint for Codex project routing, worktrees, handoffs, audits, validation, and safety state through the local context sidecar CLI.
---

# Context Handoff

Use this legacy compatibility entrypoint when `$agent-workflow-hub` is unavailable or an existing workflow invokes `$context-handoff`. Prefer `$agent-workflow-hub` in new prompts. Both packages use the same local sidecar data, schema, CLI actions, and behavioral contract.

## Core Model

- Keep normal small tasks in one Codex Task by default. Recommend a new Task or Git worktree only for independent, parallel, long-lived, separately based, or explicitly requested work.
- Do not load a reference or create durable sidecar state for a routine small task unless routing, continuity, audit, or handoff needs it.
- Use `Project context -> Task -> Thread -> Environment(optional)`. Multiple threads may share a task or environment; project-level threads may have no worktree.
- Treat sidecar state as auditable routing and continuity evidence, not proof of correctness or a memory replacement. Re-check current Git state, files, and validation when needed.
- Keep dynamic workflow state under `%USERPROFILE%\.codex\projects\<project-id>\`, never in tracked repo docs. Store concise facts and receipts, not transcripts, long logs, or model reasoning.
- Use `threadLabel` in conversation; `threadId` is an internal machine key. Sidecar `threads[]` is workflow truth. Codex thread discovery supplies only best-effort metadata evidence.

## CLI Entry

Run the bundled compatibility CLI, resolving the script relative to this `SKILL.md`:

```powershell
python scripts\context_sidecar.py <action> --worktree <current-worktree>
```

Pass the user's current repository/worktree through `--worktree`; do not ask the user for the script path. Do not require MCP.

For multi-worktree projects, keep one stable project identity. Resolution order is `--project-id`, `CONTEXT_HANDOFF_PROJECT_ID`, local sidecar config, Git remote/common-dir, then repo-root fallback. Use `--project-id` only to correct inference and `--base-branch` only when the feature base differs.

Before the first action, use `doctor` when readiness is uncertain; use `setup` only when the sidecar layout is missing.

## Default Routing

- Informal continuation such as `continue <task>`, `resume <task>`, `接手`, `继续`, or `恢复`: run `resume-query --query "<whole user phrase>"` first.
- Explicit current-worktree continuation: run `resume-feature`.
- Route/inspect without continuing: run `resolve-task`.
- New role-specific thread: run `orient-thread --role <role> --query "<topic>"` first. Read `references/thread-role-charters.md` before role decisions or role-aware prompts.
- New repo-bound feature: run `start-feature` with its goal and next step. Planning may remain inside the current execution Task.
- Saved continuation in a new thread: run `resume-query`, then `load-handoff` in compact mode.
- Passing or pausing meaningful work: run `handoff` with concrete facts, inferences, unknowns, safety rules, validation, next step, and a useful continue phrase.
- Completed feature: run `finish-feature`; create a PR only when explicitly requested.
- Whole-project/worktree inventory: run `audit-project`, not `project-status`.
- Stale sidecar/thread registration: run `reconcile-threads`; do not inspect full transcripts by default.
- Dogfood feedback: prefer `draft-issue`; create an issue only with explicit permission or enabled dogfood issue mode.
- Project graph request: run `visualize-project --open-dashboard` in an interactive Codex session and return the dashboard link.

If routing is ambiguous, mismatch, or needs review, surface that state and ask the returned short disambiguation question. Do not guess or convert inferred routing into user-confirmed routing. Respect branch, task-id, and worktree hints from the user or handoff.

## Compact Context Defaults

- Summarize action results conversationally; do not paste full sidecar JSON.
- `load-handoff` defaults to compact receipt, next step, risks/blockers, and continue phrase.
- Load one named section with a concrete reason when compact state is insufficient.
- Load a full handoff only when the user explicitly requests it or targeted loading cannot answer a continuation question.
- Keep handoffs structured, concise, and directly pasteable. Log only loading metadata, never handoff content.
- Hub threads should prefer audits, compact receipts, project status, and recommended actions over full task handoffs.

## Safety And Output

- Never delete worktrees or rewrite historical sidecar records automatically. Require explicit confirmation for archive/cleanup actions that expose confirmation flags.
- Create GitHub PRs or issues only when explicitly authorized and the CLI is authenticated; preserve draft-only dogfood behavior otherwise.
- Keep Facts, Inferences, Unknowns, validation evidence, and safety rules distinct. Treat stale handoffs as warnings to re-check current state.
- Lead single-task responses with `compactReceipt`, `continuePhrase`, status, next step, risks/blockers, and links when useful.
- Keep machine keys, actions, enums, branches, paths, and Git output in English/original form. Use `--language zh-CN` for Chinese human-facing output and `--language en` for English; persist a stated preference with `set-language`.

## Compatibility And Installation

- Keep `$context-handoff` supported, but prefer `$agent-workflow-hub` in new prompts.
- Keep both installed packages compatible in scripts, references, schema, sidecar paths, and behavior.
- Use source `install.py` to deploy both packages without migrating or rewriting existing sidecar state.

## Load References Only When Needed

- Read [routing-handoffs.md](references/routing-handoffs.md) for detailed natural-language resolution, aliases, route confirmation, handoff loading, or thread registration.
- Read [thread-role-charters.md](references/thread-role-charters.md) when starting or explaining a role, deciding role boundaries, or generating a role-aware handoff.
- Read [project-hub.md](references/project-hub.md) for whole-project audit tables, worktree coverage, visualization, cleanup prompts, or Project Hub reporting.
- Read [action-catalog.md](references/action-catalog.md) when choosing among less-common CLI actions or needing exact action intent.
- Read [prompt-templates.md](references/prompt-templates.md) only when the user asks for a new Task/thread, hub, research, execution, review, or dogfood prompt.
- Read [advanced-workflows.md](references/advanced-workflows.md) for rebaseline, dogfood hygiene/issues, backfill, evaluation, reports, or advanced archive behavior.
- Read [maintenance.md](references/maintenance.md) before updating, repairing, reinstalling, inspecting, or debugging this skill. Installed skill directories are deployment copies, not canonical source.
