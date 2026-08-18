---
name: context-handoff
description: Conversation-first local project context layer for Codex worktrees using the context sidecar CLI.
---

# Context Handoff

> Legacy compatibility entrypoint: `$context-handoff` remains supported, but new projects and docs should prefer `$agent-workflow-hub` from V2.7 onward. This package uses the same local sidecar data and compatible CLI.

Use this skill when the user wants to start, resume, hand off, finish, inspect, audit project hub state, or report on feature work for the current repository. Keep normal interaction conversational. The Python sidecar CLI is the implementation layer, not the primary user experience.

## Implementation Layer

Use the bundled sidecar CLI in this skill package. Do not ask the user to paste a CLI path during normal use.

Run actions through:

```powershell
python scripts\context_sidecar.py <action> --worktree <current-worktree>
```

If the current working directory is the installed skill directory, use the relative script path above. If running from another directory, resolve `scripts\context_sidecar.py` relative to this `SKILL.md` file and pass the user's current repository or worktree through `--worktree`.

The user can still say `Use $context-handoff ...` for compatibility, but prefer `Use $agent-workflow-hub ...` for new work. CLI path resolution is the agent's responsibility.

If the user asks to update, repair, reinstall, inspect, or debug this skill, first read `references/maintenance.md`. The installed skill directory is not the canonical source repo.

The sidecar stays local at:

```text
%USERPROFILE%\.codex\projects\<project-id>\
```

Do not write dynamic task state into tracked repo docs. Do not require MCP for this workflow.

Use the sidecar as workflow state, not as a memory replacement. It records auditable task/worktree/handoff/validation/safety state, not chat transcripts, long logs, or model reasoning.

For multi-worktree projects, keep one stable project identity. The CLI resolves projectId in this order: `--project-id`, `CONTEXT_HANDOFF_PROJECT_ID`, existing local sidecar `config.json`, Git remote/common-dir, then repo root name fallback. Use `--project-id` only when the inferred identity would be wrong. Use `--base-branch dev` when the feature base branch is not the inferred default; it persists in sidecar config.

## Language Behavior

Human-facing output can be generated in English or Simplified Chinese. Machine JSON keys, CLI action names, status enums, event names, branch names, paths, and Git output stay in English/original form.

- In Chinese conversations, pass `--language zh-CN` to human-facing actions such as `handoff`, `resume-feature`, `audit-context`, `audit-project`, `weekly-report`, `draft-issue`, and `create-issue`.
- In English conversations, pass `--language en` or omit the flag.
- If the user asks to keep using Chinese or English for future Agent Workflow Hub output, run `set-language --language zh-CN` or `set-language --language en`. This writes only to local sidecar config as `preferredLanguage`.
- Markdown handoffs, reports, issue bodies, start summaries, warnings, findings messages, and backfill prompts follow the resolved language.

Examples:

```text
Use $agent-workflow-hub to set human-facing output language to zh-CN.
Use $agent-workflow-hub to generate this week's report in Chinese.
Use $agent-workflow-hub to save a handoff in Chinese.
```

## Natural-Language Task Routing

This compatibility entrypoint supports the same V2.8 routing actions as `$agent-workflow-hub`, but new prompts should prefer `$agent-workflow-hub`.

- Use `resume-query --query "<user phrase>"` when the user says "continue <nickname>" and you have any known project/worktree path.
- Chinese/natural-language takeover phrases such as `接手 <task>`, `继续 <task>`, `恢复 <task>`, `你是 <task> 的执行进程`, and `作为 <task> execution thread` must route to `resume-query --query "<task>"` first.
- If a prior handoff gave a phrase like `继续图像质量 research` or `continue image quality research`, use that whole phrase with `resume-query`; users should not need to remember `taskId` or `handoffPath`.
- Use `resume-feature` only when the user explicitly says `当前 worktree`, `this worktree`, or otherwise clearly means the already-selected Git worktree.
- Use `resolve-task --query "<user phrase>"` when routing without resuming.
- If `resolved: false`, ask the returned `disambiguationQuestion` once instead of guessing.
- If the user says this thread is an execution, validation, review, dogfood, discussion, or explainer process for a named task, use `resume-query` first and then `attach-thread` when the sidecar needs a durable `threadRole`, `threadLabel`, `threadPurpose`, `parentTaskId`, or `phase`.
- If handoff text or user instructions mention a branch, task id, or worktree path that differs from the current cwd, respect those hints. Do not write a handoff to the cwd task unless the route is explicitly confirmed. When the CLI returns `routingStatus: mismatch` or `ambiguous`, explain the route conflict and ask or rerun with the correct worktree/task.
- Treat `routingStatus: inferred` and `routingNeedsReview: true` as visible audit state: mention it briefly and do not describe the relationship as user-confirmed.
- `resume-feature` and `resume-query` restore recorded workflow state; they do not prove correctness or replace validation, PR review, or targeted investigation.
- Persist only user-confirmed aliases with `start-feature --alias`, `handoff --alias`, or `alias-task --alias`. `continuePhrase` also participates in matching below exact aliases and above generated aliases. Generated aliases participate in matching but are not written to task `aliases`.
- The resolver is local and deterministic: normalized strings, token overlap, and `difflib`; no LLMs, embeddings, vectors, UI, MCP, or thread API.

## Handoff Loading

Use `load-handoff` when a new thread needs saved sidecar/handoff context from an older thread. Prefer `$agent-workflow-hub` wording in new prompts, but this compatibility entrypoint supports the same behavior.

- For same-role continuation in a new thread, first run `resume-query --query "<continue phrase or task>"`, then run `load-handoff --query "<same phrase>" --mode compact`.
- Compact mode is the default and should return a short receipt, next step, risks/blockers, and continue phrase without pasting full Markdown.
- Use `--mode section --section validation --reason validation-needed` for validation threads.
- Use section mode for review/discussion follow-up when only facts, risks, next step, validation, or thread summary are needed.
- Use `--mode full` only when the user explicitly asks for the complete handoff, or when compact/section output is insufficient for a concrete continuation question.
- If ambiguous, ask the returned disambiguation question once. If the handoff is missing, report the missing Markdown and use `resume-feature`, `audit-context`, or targeted investigation.
- Hub threads should prefer `audit-project`, `project-status`, compact receipts, and recommended actions over full handoff loading.
- `load-handoff` logs telemetry about mode, section, reason, role, and content size, not handoff content or chat transcripts.

When a discussion, research, or hub thread outputs an implementation plan, add one short recommendation:

```text
Execution target recommendation: open a new Primary Execution Thread.
```

or:

```text
Execution target recommendation: continue the existing execution thread.
```

or:

```text
Execution target recommendation: ask before choosing.
```

## New Thread Self-Orientation

When the user says this is a new research, discussion, execution, hub, review, validation, dogfood, or explainer thread, run `orient-thread` first with `--role <role>` and `--query "<topic or task phrase>"`.

- Role startup is orientation, not execution. Opening a role-specific thread should run `orient-thread`, summarize scope, boundary, and possible next investigation or execution paths, then wait for user direction.
- When the user starts a role-specific thread, asks about role behavior, or requests a role-aware handoff or prompt, read `references/thread-role-charters.md` before deciding routing or handoff expectations. The charter defines Agent Workflow Hub coordination behavior, not agent capability; do not treat it as a rigid output template.
- `orient-thread` is report-only by default. It should identify the likely project, canonical thread role, role boundary, task route, first recommended action, handoff expectations, and optional companion skills without writing sidecar state.
- Use `--scope project-level` when a research/discussion/hub topic is about the whole project, global direction, project roadmap, research route, or phrases such as `整个`, `全局`, `项目`, `研究路线`, `roadmap`, `overall`, or `project direction`.
- For project-level research/discussion, do not bind the thread to a feature worktree just because a related execution task matched. Treat execution matches as `relatedCandidates`; use the canonical repo/project `storageAnchor` only as storage context, not task scope.
- During startup, do not invoke external helper skills, run `eval-report` or `audit-project`, search the web, or write a heavy handoff unless the user explicitly asks to begin that work.
- If it recommends `resume-query`, run that before creating new sidecar state.
- If it recommends `attach-thread` or `orient-thread --attach`, attach only when the route is confirmed or the user explicitly confirms. Inferred, ambiguous, mismatch, or non-Git-derived routes require `--confirm-route`.
- Do not turn an ambiguous task route into a confirmed feature binding with `--attach --confirm-route`. Ask once, or attach a project-level/provisional thread task with `--scope project-level`.
- If external helper skills are suggested but unavailable, do not block. Continue with built-in tools and record the missing support as an unknown or risk.
- Do not treat suggested external skills as required dependencies; do not install skills automatically. Suggested external skills are advisory until the user asks to begin the research, investigation, comparison, validation, or implementation.

## Multi-Thread Workflow Playbook

Use this playbook when the user asks whether to open a new thread, worktree, subagent, side chat, or project hub. The goal is stable routing, not new infrastructure. Do not add CLI actions, change sidecar schema, or require UI/MCP support for these workflows.

Default mental model: `Hub -> Discussion/Research -> Execution`.

Core roles users should remember:

- `hub`: global status, task map, routing, prioritization, summaries, rebaseline, reports, and project-wide prompts.
- `discussion`: engineering route, product direction, architecture tradeoffs, task shaping, and implementation readiness.
- `research`: evidence-seeking thread for external knowledge, academic/product/ecosystem research, related work, market comparison, prior art, novelty, baselines, experiments, and evidence-backed direction finding.
- `primary-execution`: implementation, bug fixing, local validation, task handoff, finish/archive, and PR text.

Support roles remain available for structured sidecar state but are optional in the default workflow: `review`, `validation`, `dogfood`, and `explainer`.

Default topology:

- One project has one Project Hub Thread. It owns the project map, whole-project status, worktree inventory, routing decisions, and periodic `audit-project` / `weekly-report` summaries.
- One active worktree/task has one Primary Execution Thread. It owns implementation, local planning, validation, handoff, finish/archive, and PR text for that task.
- Create a new worktree when the task needs an isolated branch, parallel implementation, or a different base. Reuse the existing worktree when continuing the same task or doing tiny scratch work that will not become durable.
- A repo-bound but still fuzzy task can start directly in a Primary Execution Thread. Plan inside that thread first, then implement once the task is shaped.
- A fuzzy product-direction task stays in the Project Hub Thread or a short-lived Discussion Thread until it becomes repo-bound and actionable.
- A research-shaped question belongs in a Research Thread when the durable output is external evidence, prior art, market/ecosystem comparison, paper story, novelty, related work direction, baselines, experiment design, or feasibility rather than immediate implementation.
- Side chats are for short questions, scratch wording, or throwaway drafts. They should not become the canonical project memory.
- Subagents are temporary helpers for review, investigation, comparison, or validation. They should report findings back to the primary or hub thread and should not become long-term task owners.
- Explainer Threads are for deep project explanation or onboarding. Use them to avoid turning the hub into a long tutorial.
- Dogfood/QA Threads are for real-project testing feedback, reproduction notes, and issue drafts.
- `sidecar`, `handoff`, and `audit-project` are the shared state layer between these threads. Thread conversation is useful, but sidecar state is the durable coordination point.

Routing rules:

- If the user asks "where are we across the project?", stay in or create the Project Hub Thread and run `audit-project`.
- If the user asks to build, fix, refactor, validate, or finish one branch/worktree task, use a Primary Execution Thread and run `resume-feature` or `start-feature`.
- If the user asks whether to open a worktree, recommend one only when isolation, parallel work, or a separate branch/base is useful; otherwise continue in the current worktree.
- If the user has a task but the exact implementation path is fuzzy and it clearly belongs to one repo/worktree, create the execution thread anyway and start with planning in that thread.
- If the user is still deciding product direction, user value, priority, or whether the task should exist, keep it in the hub or create a Discussion Thread.
- If the user is asking about external evidence, academic/product/ecosystem research, market comparison, prior art, paper potential, novelty, related work, baselines, experiments, ablations, reviewer expectations, feasibility, or publication readiness, use a Research Thread with `threadRole: research`.
- If the question is small and does not need durable project memory, use a side chat and copy only final decisions back to the hub or execution thread when needed.
- If independent review, targeted research, or validation would help, launch a subagent with a narrow question and an explicit "return findings only" instruction.
- If the user wants a deep explanation of architecture, history, or onboarding, create an Explainer Thread and point it at stable docs plus the current repo.
- If feedback comes from dogfooding or QA, use a Dogfood/QA Thread and prefer `draft-issue` unless the user explicitly asks to create an issue or dogfood issue mode is enabled.

State handoff rules:

- The Project Hub Thread should not own every implementation detail. It should keep the map, inventory, routing decisions, and links or summaries from execution threads.
- The Primary Execution Thread must update sidecar state with `start-feature`, `resume-feature`, `handoff`, `audit-context`, and `finish-feature` as appropriate.
- Completion summaries from execution threads should lead with the handoff `compactReceipt` and `continuePhrase`, then include machine/debug details such as taskId, handoffPath, validation, unresolved risks, PR status, and archive path when useful.
- Discussion, side chat, explainer, dogfood, and subagent results become durable only after their useful decisions or facts are copied into the hub, the relevant execution thread, or sidecar handoff/audit output.
- Handoff is event-driven, not startup-driven or turn-driven. Save a handoff when durable findings/state should survive the chat, when passing work to another role/agent, when stopping after meaningful work, or when the user asks.
- Never treat `project-status` as the whole-project inventory; use `audit-project` for hub-level status.

Recommended prompt templates:

When the user asks for a thread handoff, discussion handoff, execution thread handoff, project hub prompt, backfill prompt, or new thread prompt, output a workflow-aware thread-start prompt rather than a plain summary. Every generated thread handoff prompt must start with this exact first line:

```text
Use $agent-workflow-hub first. If only $context-handoff is available, use it as the compatible entrypoint.
```

Discussion Thread Handoff:

```text
Use $agent-workflow-hub first. If only $context-handoff is available, use it as the compatible entrypoint.
You are a Discussion Thread for <project>. threadRole: discussion. Topic: <topic>. Repo/worktree if known: <path>. Do not create a worktree or modify code unless implementation begins. Use resume-query first if this topic may already exist. If no matching sidecar task exists, start or attach a provisional discussion task with the topic, current facts, and open questions. Keep dynamic state in sidecar/handoffs, not tracked repo docs. If you only opened/oriented the thread, stop after scope, boundary, and possible next paths. Save a sidecar handoff only when durable facts, inferences, unknowns, decisions, or nextStep should survive this chat, when passing work to another role/agent, or before stopping after meaningful work. Report only durable takeaways and requested follow-up back to the Project Hub.
```

Research Thread Handoff:

```text
Use $agent-workflow-hub first. If only $context-handoff is available, use it as the compatible entrypoint.
You are a Research Thread for <project>. threadRole: research. Research topic or paper question: <topic>. Repo/worktree if known: <path>. Do not create a worktree or modify code unless implementation begins. Use resume-query first if this research topic, feature, or paper-planning task may already exist. If no matching sidecar task exists, start or attach a provisional research task. If the user is only opening/orienting the research thread, run orientation, state scope/boundary and possible next paths, then wait for direction. External academic, literature, reviewer, or paper-planning skills are advisory; use them only when the user asks to begin research, investigate, compare, survey, or plan evidence. Use the agent's own investigation strategy; avoid full scans unless necessary. Possible research directions include engineering facts, paper story, research questions, related work directions/search keywords, novelty hypotheses, baselines, experiments/ablations, publication readiness, engineering tasks serving the paper, unknowns/risks, and next step. Choose only the structure that fits the user's request and available evidence. Save durable research findings to a sidecar handoff only when they should survive this chat, when passing work to another role/agent, or before stopping after meaningful work. Report the relevant takeaways, risks, and proposed next step back to the Project Hub when useful.
```

Primary Execution Thread Handoff:

```text
Use $agent-workflow-hub first. If only $context-handoff is available, use it as the compatible entrypoint.
You are the Primary Execution Thread for <project>/<task>. threadRole: primary-execution. Repo/worktree: <path>. Use resume-query first if the task may already exist; otherwise run resume-feature for this worktree if a task exists, or start-feature with this goal: <goal>. Plan briefly inside this thread, then implement when the user has asked for execution. Keep dynamic state in sidecar/handoffs, not tracked repo docs. Before stopping after meaningful work, run relevant validation, audit-context if useful, and save a handoff with facts, inferences, unknowns, safety rules, validation, blockers, risks, decisions, nextStep, and a useful --continue-phrase when the user gave one. Report back to the Project Hub with a compact receipt first: concise result, nextStep, risks/blockers, and "Next time say: ..."; then include optional machine details such as taskId, handoffPath, branch, worktree, validation, and PR/issue links.
```

Project Hub Thread Handoff:

```text
Use $agent-workflow-hub first. If only $context-handoff is available, use it as the compatible entrypoint.
You are the Project Hub Thread for <project>. threadRole: hub. Canonical repo/worktree: <path>. Run audit-project with the expected project id/base branch, and use visualize-project or weekly-report only when useful for human-facing output. Build the hub view from real git worktrees plus sidecar active tasks. Summarize active execution threads, discussion/research threads, missing sidecar coverage, stale handoffs, validation/safety gaps, recommended actions, concrete backfill prompts, and cleanup prompts. Do not treat project-status as the full inventory. Do not implement feature code in the hub thread. Route work to the appropriate execution, discussion, research, dogfood, or review thread and request a durable receipt back to the hub.
```

Dogfood/QA Thread Handoff:

```text
Use $agent-workflow-hub first. If only $context-handoff is available, use it as the compatible entrypoint.
You are a Dogfood/QA Thread for <project>. threadRole: dogfood. Feedback: <observed behavior>. Expected: <expected behavior>. Repo/worktree if known: <path>. Use resume-query first if this feedback may belong to an existing task or issue. Otherwise start or attach a provisional dogfood/QA task. Keep Facts, Inferences, Unknowns, Reproduction, Suggested Fix, Priority, safety concerns, and nextStep separate. Prefer draft-issue by default. Do not create a GitHub issue unless I explicitly ask or dogfood issue mode is enabled. Save durable QA findings to a sidecar handoff when they should survive this chat, when passing work to another role/agent, or before stopping after meaningful work; report the issue draft/path, priority, and next recommended action back to the Project Hub when useful.
```

## Actions

- `start-feature`: Create or update the active task for the current branch/worktree. Use when the user starts a new feature or says what this branch is for.
- `alias-task`: Add or remove user-confirmed task aliases. Use when a user names a durable nickname for a task.
- `attach-thread`: Attach a thread role, label, purpose, parent task, phase, and routing review metadata to a sidecar task without requiring a code change.
- `orient-thread`: Orient a new thread from a role and short query. It is report-only by default, summarizes project/task routing, role boundaries, startup protocol, optional next CLI commands, event-driven handoff expectations, and advisory companion skills. Use `--attach` only when the route is safe or explicitly confirmed.
- `resolve-task`: Resolve a natural-language query to a sidecar task. Use when routing without resuming.
- `resume-feature`: Recover compact task state, latest handoff availability, stable docs, git status, and next-step hints. Use when taking over or continuing a branch.
- `resume-query`: Resolve a natural-language query and resume the matched worktree when confidence is high. Use when the user says "continue <nickname>".
- `handoff`: Save incomplete work, next step, blockers, touched areas, facts, inferences, unknowns, validation commands/results/time, safety rules, concise thread summary, `continuePhrase`, and compact human-facing receipt.
- `load-handoff`: Load saved sidecar/handoff context by task id, natural-language query, or current worktree. Defaults to compact receipt; section/full loading requires explicit mode and is logged for audit.
- `audit-context`: Check whether the current context is trustworthy before handoff/resume. It reports missing handoff, stale HEAD/dirty files, missing validation, missing safety rules, dirty worktree, and backfill prompts.
- `audit-project`: Project hub inventory for all Git worktrees. It compares real `git worktree list` output with sidecar active tasks, audits every worktree, and reports untracked worktrees, stale tasks, missing validation/safety/handoff, recommended actions, execution-thread prompts, and cleanup prompts.
- `rebaseline-project`: Safely refresh the current project hub/task baseline after many PRs or versions have merged. It inspects Git, active/archived sidecar tasks, recent merged PRs when `gh` is available, and audit-project-style findings. By default it only recommends changes; use `--update-current-hub-task` to write a fresh hub task/handoff and `--confirm-archive-stale` only after human confirmation to archive stale historical active tasks.
- `hygiene-dogfood`: Inspect stale dogfood/smoke sidecar records that have later pass evidence. It is report-only by default; archive exactly one eligible record only with `--confirm-archive --task-id <id>` after human confirmation.
- `finish-feature`: Finish and archive the active task. Create a PR only if the user explicitly asks and GitHub CLI is already installed and authenticated.
- `project-status`: Return compact sidecar project state for planning. This is not the full Git worktree inventory.
- `weekly-report`: Generate a human-facing Markdown report under the sidecar `reports/` directory and reply with a short notification, not the full report by default.
- `eval-report`: Generate lightweight workflow evaluation Markdown and JSON reports under the sidecar `reports/` directory. It reports proxy workflow metrics, not exact token usage or proof of correctness.
- `visualize-project`: Generate Markdown + Mermaid, companion JSON, and a static HTML Project Hub dashboard under the sidecar `reports/` directory. Use for human-facing project map requests; do not paste the full JSON by default and do not auto-open the HTML. The HTML dashboard keeps Project as page context, shows Task -> Worktree -> Thread, supports route spotlight, uses text health badges, hides archive by default, keeps dependencies plus `th-project-hub` outside the ownership graph, and displays canonical `threadRole` separately from `threadLabel`.
- The optional `awh-project-hub` MCP App provides an inline launcher and read-only fullscreen view in compatible Codex hosts. It reads authoritative state through `project-hub-payload`; it is not required for AWH state or routing. Keep `visualize-project` available as the static dashboard fallback.
- `snapshot`: Print current worktree Git facts for lightweight backfill.
- `draft-issue`: Generate a dogfood/debug issue draft with Facts, Inferences, Unknowns, Reproduction, Suggested Fix, and Priority. This never requires GitHub CLI.
- `create-issue`: Create a dogfood/debug GitHub issue only when the user explicitly asks or dogfood issue mode is enabled, GitHub CLI is authenticated, content is safe, and no likely duplicate is found.
- `enable-dogfood-issue-mode` / `disable-dogfood-issue-mode`: Persist local sidecar permission for dogfood issue creation. This writes only to sidecar config.
- `set-language`: Persist local sidecar language preference for human-facing output. This writes only to sidecar config.
- `setup`: Safely create the local sidecar layout for this project.
- `doctor`: Report readiness without installing tools or changing global Codex/GitHub configuration.

## Routing Guide

- Before the first action in a project, run the bundled CLI with the current worktree path. Prefer `doctor` before `setup` when the project has not used the sidecar before.
- If the user says "start this feature", "track this branch", or gives a feature goal, run `start-feature` with `--goal` and optional `--next-step`.
- If the user says "continue <task nickname>" from a hub or container context, run `resume-query --query "<task nickname>"` and follow its confidence/disambiguation output.
- If this is a new thread continuing previous saved work, run `resume-query` first and then `load-handoff --mode compact`. Escalate to `--mode section` or `--mode full` only when needed.
- If the user says "you are a <role> thread", "as a <role> execution/research/discussion thread", or opens a new role-specific thread with a topic, run `orient-thread --role <role> --query "<topic>"` first.
- If the user says "take over", "resume", "where are we", or "continue this worktree", run `resume-feature`, then summarize only the useful context and next step.
- If the user asks to audit trustworthiness, run `audit-context` and summarize findings plus backfill prompts.
- If the user is ending a session or passing work to another agent, run `handoff` with concrete done/not-done fields and explicit `--fact`, `--inference`, `--unknown`, `--safety-rule`, `--validation-command`, `--validation-result`, `--validation-at`, and `--continue-phrase` values where known. Reply with the compact receipt first; taskId and handoffPath are secondary details.
- If the user says the task is done, run `finish-feature`. Add `--create-pr` only when the user explicitly requests PR creation.
- If the user reports dogfood/debug feedback, prefer `draft-issue` by default and return the copyable title/body.
- If the user explicitly says "create issue", "提 issue", or asks to enable dogfood issue mode, use `enable-dogfood-issue-mode` or `create-issue` as appropriate. Never create an issue from inferred intent alone.
- If the user asks from a project hub thread, asks for all worktrees, asks what is active across the project, or mentions a canonical repo with many worktrees, use `audit-project` first. Use `project-status` only for compact sidecar state and `weekly-report` for a human update.
- If the user says the project map is stale, the current project appears as an old version, many PRs were merged, or the sidecar baseline needs refresh, run `rebaseline-project` first. Do not archive stale tasks unless the user explicitly confirms; then use `--confirm-archive-stale`. Use `--update-current-hub-task` when the user wants the current hub baseline written.
- If old dogfood/smoke blocker records, pre-reinstall failures, stale environment smoke tasks, or superseded dogfood findings pollute `audit-project` or `visualize-project`, run `hygiene-dogfood`. Treat it as a narrow dogfood smoke hygiene report; archive only one eligible stale record after explicit human confirmation with `--confirm-archive --task-id <id>`.
- If the user asks whether Agent Workflow Hub is helping, asks for dogfood/evaluation metrics, or asks for a tool-effectiveness report, run `eval-report`. Keep it distinct from `weekly-report`, which is project progress reporting.
- If the user says `visualize project`, `show project graph`, `可视化项目`, `显示项目图`, `项目关系图`, or `看一下项目全局`, run `visualize-project`. Reply with the Mermaid graph, Legend, details table, and needs-attention summary from the generated Markdown; avoid pasting the full JSON unless asked.
- If setup is uncertain, run `doctor` first. Explain any missing optional tools without installing them.

## Project Hub / Multi-Worktree Protocol

`project-status` only reports sidecar-known active tasks. It must not be treated as the complete project or worktree inventory.

When the user asks for project hub status, whole-project status, all worktrees, branch/task coverage, or asks which feature threads need backfill:

1. Run `audit-project` for the canonical repo/worktree with the same `--project-id` and `--base-branch` the user expects.
2. If `audit-project` is unavailable, fall back to `project-status`, `git -C <canonical-repo> worktree list --porcelain`, and per-worktree `audit-context`.
3. Report a table with branch, worktree path, headSha, dirty/clean, sidecarHit, task status, handoffAvailable, validationPresent, safetyRulesPresent, stale, blocker, and nextStep.
4. Explicitly report total Git worktrees, total sidecar active tasks, tracked versus untracked worktrees, dirty worktrees, stale worktrees, missing validation/safety/handoff, and active sidecar tasks whose worktree no longer exists.
5. Group concrete backfill prompts and `threadPromptsByBranch` by branch/worktree.
6. Include `recommendedActions` for untracked worktrees, stale tasks, missing validation/safety/handoff, and dirty worktrees. Each action should include both `oldThreadBackfillPrompt` and `newExecutionThreadPrompt` because the CLI cannot know whether an old execution thread exists.
7. Include `cleanupPrompts` for active sidecar tasks whose recorded worktree no longer exists. Ask the human to confirm merged/abandoned/moved state; never auto-delete worktrees.
8. If a requested project id is canonicalized, say so once, for example `paus_robot_lab_host` -> `paus-robot-lab-host`.

Rows with `sidecarHit: false` mean no real sidecar task exists. In `audit-project`, report these rows as `taskStatus: missing`; any `provisionalTaskStatus` is audit-only fallback context and must not be described as sidecar state.

Never infer that sidecar active tasks are the full worktree inventory.

Prefer old execution threads for backfill when they exist, because they may still have semantic context that Git cannot recover. If no old execution thread exists, use `newExecutionThreadPrompt` to open a new Primary Execution Thread. The new thread must recover or initialize sidecar state, distinguish facts/inferences/unknowns, add validation/safety/nextStep, save a handoff, and report back to the Project Hub. The prompt should not micromanage the agent's investigation path: the agent may use code reading, commits, PRs, issues, tests, or targeted search as needed.

For project visualization requests, run `visualize-project` instead of asking the user to name Mermaid or workflow graph internals. The graph should show the main chain `Project -> Task -> Worktree -> Thread Role`; state and health belong in badges/classes and the details table, not as default graph nodes.

Task hierarchy is intentionally lightweight. Use `parentTaskId` for ownership when a feature has follow-up, validation, or bugfix child tasks. Do not invent dependencies or multiple parents; if a relationship is merely related but not owned, describe it in facts/inferences or next steps instead.

Use `rebaseline-project` when stale historical sidecar tasks make the Project Hub or visualization misrepresent the current repo baseline. It must distinguish Git facts, inferred project baseline, user-confirmed changes, and stale historical sidecar records. It may recommend archiving stale active tasks, but destructive cleanup requires explicit human confirmation. It should refresh or create a current hub task such as `agent-workflow-hub-main` only when `--update-current-hub-task` is used, write a fresh handoff, and recommend `visualize-project` afterward.

Use `hygiene-dogfood` when dogfood/smoke records are stale because a later run already proved the environment or install was fixed. It detects only narrow dogfood/smoke evidence, reports candidates in `dogfoodHygiene`, adds `archive-stale-dogfood-record` recommendations to hub outputs, and never bulk archives or deletes worktrees. Non-dogfood execution tasks are out of scope.

## Backfill Guidance

When initializing an existing project, git history can provide objective facts such as branches, commits, touched files, and changed areas. Git history alone cannot reliably recover intent, design decisions, validation status, blockers, or what should happen next.

For a useful first sidecar state, combine:

- Git facts from `snapshot`, `start-feature`, and recent commits.
- Current thread or user-provided context for goal, current status, next step, blocker, and validation.
- Existing PR descriptions, issue text, or release notes when available.

If semantic context is missing, write a provisional task state and say what is missing rather than pretending the git history is enough.

`touchedFiles` means current Git dirty/touched files. It is a locator signal when context is thin, not an instruction to inspect those files first. Agents should choose their own investigation strategy and avoid full scans unless necessary.

Handoffs must distinguish:

- Facts: observed git state, user-provided statements, exact validation results.
- Inferences: agent conclusions drawn from facts.
- Unknowns: missing context that should not be guessed.
- Safety rules: constraints for future agents, such as not deleting worktrees and not writing dynamic state into the target repo.

The sidecar records `headSha`, `upstream`, `dirtyFiles`, and `dirtyFingerprint`. Treat `resume-feature` stale output as a warning to re-check current files before trusting an older handoff.

## Dogfood Issue Guidance

Dogfood issue reporting is draft-only by default. Issue drafts and created issues must keep Facts, Inferences, Unknowns, Reproduction, Suggested Fix, and Priority separate.

Before creating a GitHub issue, the CLI checks GitHub CLI authentication, searches for similar open issues, and blocks creation when content appears to include secrets, private paths, long logs, or other sensitive material. Created issues always receive `agent-reported` and `needs-triage` labels. If GitHub CLI is unavailable, unauthenticated, unsafe, or likely duplicate, return the generated draft instead.

## Output Style

For single feature actions, return a short conversational summary:

- Lead with `compactReceipt` and the natural-language `continuePhrase` when a handoff was saved.
- Current task and status.
- Latest useful next step.
- Handoff or report path when useful for debugging or automation.
- PR URL when known, or generated PR title/body guidance when GitHub CLI is unavailable.

For project hub actions, do not only return a short current-task summary. Always include compact inventory counts, a table of worktrees, grouped backfill prompts, recommended actions, execution-thread prompts, and cleanup prompts. Avoid pasting long sidecar JSON or full weekly reports unless the user asks for detail.

## Advanced / Legacy Actions

- `init`: Legacy alias for sidecar setup. Prefer `setup`.
- `intake`: Legacy low-level resume JSON. Prefer `resume-feature`.
- `archive`: Advanced manual archive. Prefer `finish-feature` when a feature is complete.
