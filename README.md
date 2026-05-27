# context-handoff

[中文](./README.zh-CN.md) | English

`context-handoff` is a self-contained Codex skill for AI-assisted feature lifecycle state. It helps agents resume work across branches, worktrees, and threads without repeatedly rebuilding the same project context.

The normal interface is conversation:

```text
Use $context-handoff to resume this worktree.
```

The skill bundles its own Python sidecar CLI under `skills/context-handoff/scripts/`, so users do not need to know where the CLI lives.

## What It Solves

- New agent threads repeatedly scan the same repository.
- Feature branches, worktrees, and threads lose task status.
- Handoff, finish/archive, and weekly reporting become inconsistent.
- Dynamic agent state leaks into repository docs or feature PRs.

## Install

Clone this repository, then run:

```powershell
python install.py
```

This copies the complete skill package to:

```text
%USERPROFILE%\.codex\skills\context-handoff\
```

Restart or refresh Codex if the skill list does not update immediately.

The installer only copies the skill package. It does not install GitHub CLI, authenticate accounts, or change global Codex configuration.

## Use

In any git project or worktree, ask Codex:

```text
Use $context-handoff to run doctor/setup for this project.
```

Then use natural prompts:

```text
Use $context-handoff to start this feature. Goal: improve the dashboard UI.
```

```text
Use $context-handoff to resume this worktree and tell me the immediate next step.
```

```text
Use $context-handoff to save a handoff before I stop today.
```

```text
Use $context-handoff to finish this feature and generate PR text.
```

```text
Use $context-handoff to generate last week's report.
```

## Sidecar State

Dynamic state is local-only and stays outside your repository:

```text
%USERPROFILE%\.codex\projects\<project-id>\
  active-tasks.json
  project-state.json
  handoffs\
  archive\
  reports\
  events.jsonl
```

`project-state.json` is compact machine-readable status for agents. Handoffs and weekly reports are Markdown for humans. Stable repository facts can still live in tracked `docs/agent/` files.

## Main Actions

- `doctor`: Check Python, Git, sidecar, and optional GitHub CLI readiness.
- `setup`: Create the local sidecar layout.
- `start-feature`: Track the current branch/worktree as an active task.
- `resume-feature`: Recover compact context for the current worktree.
- `handoff`: Save incomplete work and the next step.
- `finish-feature`: Archive the task and generate PR title/body; create a PR only when explicitly requested and GitHub CLI is ready.
- `project-status`: Summarize current project state for a project hub thread.
- `weekly-report`: Write a human-facing Markdown report under the sidecar `reports/` directory.

V1 `worktree-intake` and `worktree-handoff` have been merged into the unified `context-handoff` skill as `resume-feature` and `handoff`.

## Backfilling Existing Projects

Git history can recover objective facts such as branches, commits, and touched files. It cannot reliably recover intent, design decisions, blockers, validation status, or the correct next step.

For the first sidecar state in an existing project, combine:

- Git facts from the current worktree.
- Current thread or user-provided context.
- Existing PR, issue, or release notes when available.

After that first backfill, ongoing `start-feature`, `handoff`, and `finish-feature` actions keep future context cheaper to recover.

## GitHub PR Behavior

GitHub CLI is optional. `finish-feature` always works without a PR URL. If `gh` is installed and authenticated, the skill can create a PR when the user explicitly asks. Otherwise it generates PR title/body text and records local completion state.

## Research Notes

`events.jsonl` records lightweight lifecycle events for future evaluation. It is not a full benchmark by itself. See [docs/research/context-handoff-v2-benchmark.md](./docs/research/context-handoff-v2-benchmark.md) for the planned comparison between no shared context, stable repo docs only, and sidecar + handoff.
