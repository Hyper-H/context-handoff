# context-handoff

[中文](./README.zh-CN.md) | English

`context-handoff` is a lightweight project/task state layer for AI-assisted feature lifecycle work. V2 keeps the normal interface conversational through one primary skill, while a local sidecar stores compact dynamic state outside feature PRs.

## What It Solves

- New threads repeatedly re-scan the same repository.
- Parallel worktrees and agent threads lose track of current task status.
- Feature handoff, finish/archive, and weekly project reporting become inconsistent.
- Dynamic agent state accidentally leaks into repository docs or PRs.

## Core Model

- `docs/agent/`: stable repository facts that belong in version control.
- Local sidecar: dynamic project/task state under `%USERPROFILE%\.codex\projects\<project-id>\`.
- `skills/context-handoff`: the V2 conversation-first lifecycle skill.
- `worktree-intake` and `worktree-handoff`: V1-compatible skill entry points that remain usable.

The V2 workflow does not require MCP. The sidecar schema and CLI stay simple enough to wrap later, but the shareable MVP is a working skill + CLI + sidecar workflow.

## Sidecar Layout

```text
%USERPROFILE%\.codex\projects\<project-id>\
  active-tasks.json
  project-state.json
  handoffs\
  archive\
  reports\
  events.jsonl
```

`active-tasks.json` contains active-like tasks only. `project-state.json` is compact machine-readable status for agents. Long human-facing text belongs in Markdown handoffs and weekly reports, not in project-state JSON.

## Conversation-First Usage

Use the unified skill in normal work:

- `Use $context-handoff to start this feature: add V2 lifecycle state.`
- `Use $context-handoff to resume this worktree and tell me the next step.`
- `Use $context-handoff to save a handoff before I stop today.`
- `Use $context-handoff to finish this feature and generate PR text.`
- `Use $context-handoff to show project status from the project hub thread.`
- `Use $context-handoff to create this week's project report.`

The agent should run the sidecar CLI in the background, summarize the useful result, and avoid pasting long JSON unless you ask for it.

## Project Hub Thread

A project hub thread is a long-lived conversation for project status, planning, and short weekly report notifications. It is not the primary source of agent context. Agents should still use compact sidecar state plus the latest handoff when resuming work.

Weekly reports are human-facing Markdown files in the sidecar `reports/` directory. Manual `weekly-report` works without automation. If you add a recurring automation, bind it to the current project hub thread and have it post a short notification with the report path instead of pasting the full report by default.

## Low-Level CLI

The Python CLI is for skills, testing, debugging, and non-skill integrations:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py setup
python tools\worktree-context-reuse-v1\context_sidecar.py doctor
python tools\worktree-context-reuse-v1\context_sidecar.py start-feature --goal "Add lifecycle sidecar"
python tools\worktree-context-reuse-v1\context_sidecar.py resume-feature
python tools\worktree-context-reuse-v1\context_sidecar.py handoff --next-step "Run smoke tests"
python tools\worktree-context-reuse-v1\context_sidecar.py finish-feature
python tools\worktree-context-reuse-v1\context_sidecar.py project-status
python tools\worktree-context-reuse-v1\context_sidecar.py weekly-report
```

Compatibility commands remain available:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py init
python tools\worktree-context-reuse-v1\context_sidecar.py snapshot
python tools\worktree-context-reuse-v1\context_sidecar.py intake
python tools\worktree-context-reuse-v1\context_sidecar.py archive
```

## PR Finish Behavior

`finish-feature` archives the active task even when no PR URL exists. It generates PR title/body text by default. If you explicitly pass `--create-pr` and `gh` is installed and authenticated, it attempts to create the PR and records the resulting URL. If `gh` is missing or unauthenticated, it leaves `prUrl` empty, finishes the task, and reports setup guidance.

The tool never installs GitHub CLI, authenticates accounts, or changes global Codex settings silently.

## Setup And Doctor

Run `doctor` to check readiness without mutating global state. Run `setup` to create the local sidecar layout. Another developer cloning the repository only needs Python, Git, and the skill files; GitHub CLI is optional and only needed for automatic PR creation.

Dynamic sidecar state is local-only and should stay out of feature PRs.
