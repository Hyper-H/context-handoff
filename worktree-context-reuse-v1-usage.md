# Worktree Context Reuse v1 Usage

## Installed Paths

- Shared tool:
  `tools/worktree-context-reuse-v1/context_sidecar.py`
- Skill:
  `skills/worktree-intake`
- Skill:
  `skills/worktree-handoff`

## Stable Repo Docs

This repository includes starter templates:

- `docs/agent/project-map.md`
- `docs/agent/conventions.md`
- `docs/agent/common-commands.md`

Fill these with stable, low-frequency repo facts. Do not put task progress or handoff state here.

## Basic Commands

Run from the target worktree directory:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py init
python tools\worktree-context-reuse-v1\context_sidecar.py snapshot
python tools\worktree-context-reuse-v1\context_sidecar.py intake
```

Write a handoff:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py handoff `
  --goal "current goal" `
  --status active `
  --next-step "next concrete step" `
  --thread-summary "2-4 sentence compressed summary"
```

Archive the current task after it is done:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py archive
```

## Sidecar Location

By default the project sidecar is created at:

```text
%USERPROFILE%\.codex\projects\<project-id>\
```

## Validation Notes

- The shared tool works for `init`, `snapshot`, `intake`, `handoff`, and `archive`.
- The skill directories are structured for local Codex installation or reuse.
- A real temporary git repo smoke test passed for `snapshot -> handoff -> intake -> archive`.
- If git is installed but not discoverable, set `CODEX_GIT_EXE` to the absolute `git.exe` path.

## Known Working Git Path On The Author Machine

```text
D:\install\Git\cmd\git.exe
```
