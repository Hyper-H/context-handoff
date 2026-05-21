---
name: worktree-intake
description: Recover the current feature or branch context for multi-worktree, multi-thread development by reading the local sidecar state, the latest handoff, and stable repo docs before scanning code. Use when Codex needs to take over a worktree, resume a feature, continue a branch, or reduce repeated project re-scanning during feature or PR work.
---

# Worktree Intake

## Overview

Use this skill to recover the current worktree context from the local sidecar before doing a broad project scan. Prefer this skill when the user asks to continue a branch, take over a worktree, or resume a feature with minimal repeated context building.

## Workflow

1. Run the shared sidecar tool:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py intake
```

2. Read the JSON result and determine:
- matched `taskId`
- whether the task is provisional
- whether a latest handoff exists
- which stable docs are missing
- which conflicts or blockers need to be called out

3. If `handoffAvailable` is true, read the handoff file before scanning code.

4. If stable docs exist, read them in this order:
- `docs/agent/project-map.md`
- `docs/agent/conventions.md`
- `docs/agent/common-commands.md`

5. Only if the above is still insufficient, do a minimal code scan limited to:
- `touchedAreas`
- `touchedFiles`
- files implied by `nextStep`

## Output Contract

Use the fixed output shape in [references/output-template.md](references/output-template.md).

Rules:
- Keep the response short and operational.
- Prefer concrete next actions over long summaries.
- If the task is provisional, say so explicitly.
- If stable docs or handoff files are missing, list them under `Missing Context`.
- If branch/worktree conflicts are reported, mention them before suggesting any next step.

## Fallback Rules

- If there is no sidecar task, continue with a provisional intake based on the current branch.
- If there is no handoff, derive the minimal summary from `lastThreadSummary`, `touchedAreas`, and `nextStep`.
- If there are no stable docs, continue working but say that the stable fact layer is missing.
- Do not expand into a full-project overview unless the user explicitly asks for one.
