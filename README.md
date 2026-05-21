# context-handoff

[中文](./README.zh-CN.md) | English

`context-handoff` is a lightweight workflow for reducing context rebuild cost across multi-worktree, multi-thread feature development with stable repo docs, a local sidecar state layer, and intake/handoff skills.

## What It Solves

- New threads repeatedly re-scan the same repository.
- Parallel worktrees and agent threads lose track of current task status.
- Feature or PR handoff is noisy, inconsistent, and expensive.

## Core Idea

Split project context into three layers:

- `docs/agent/`
  Stable repository facts that belong in version control.
- local sidecar
  Dynamic task state that should stay off feature PRs.
- `worktree-intake` / `worktree-handoff`
  Natural-language skill entry points for restoring and saving current task context.

## Repository Layout

```text
docs/
  agent/
    project-map.md
    conventions.md
    common-commands.md
skills/
  worktree-intake/
  worktree-handoff/
tools/
  worktree-context-reuse-v1/
    context_sidecar.py
    templates/
specs/
  multi-worktree-thread-handoff-v1.md
worktree-context-reuse-v1-usage.md
```

## Local Sidecar Layout

By default the tool writes local state to:

```text
%USERPROFILE%\.codex\projects\<project-id>\
  active-tasks.json
  handoffs\
  archive\
  events.jsonl
```

This state is local-only and should not be committed to feature PRs.

## Quick Start

1. Copy or adapt the stable repo docs in `docs/agent/`.
2. Install or copy the two skills into your local Codex skill directory.
3. From a real git worktree, run:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py init
python tools\worktree-context-reuse-v1\context_sidecar.py snapshot
python tools\worktree-context-reuse-v1\context_sidecar.py intake
```

4. Before ending a work session, write a handoff:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py handoff `
  --goal "current goal" `
  --status active `
  --next-step "next concrete step" `
  --thread-summary "2-4 sentence compressed summary"
```

5. When the task is done:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py archive
```

## Skill Prompts

Once installed locally, use prompts like:

- `Use $worktree-intake to recover the current worktree context and tell me the next step.`
- `Use $worktree-handoff to save the current worktree status and prepare the next agent handoff.`

## Validation Status

This repository includes a working v1 implementation that has been validated in:

- a non-git fallback workspace
- a temporary real git repo smoke test for:
  - `snapshot`
  - `handoff`
  - `intake`
  - `archive`

## Notes

- This project intentionally avoids custom MCP in v1.
- The current design prioritizes personal workflow first, then later sharing or evaluation.
- `events.jsonl` is a lightweight evaluation trace, not a full research benchmark.
