---
name: worktree-handoff
description: Save the latest feature status for multi-worktree, multi-thread development by updating the local sidecar task record, writing the latest handoff markdown, and preserving a short next-agent summary. Use when Codex needs to end a worktree session, prepare another agent to continue a branch, or reduce repeated explanation during feature or PR handoff.
---

# Worktree Handoff

## Overview

Use this skill to compress the current task state into the local sidecar and a latest handoff file before the thread ends. Prefer this skill whenever the user asks to hand off a worktree, wrap a feature round, or preserve current branch state for the next agent.

## Workflow

1. Gather the high-value semantics from the current conversation or workspace state:
- current goal
- status
- blocker
- next step
- 2-4 sentence thread summary
- done / not done items
- risks
- validation status

2. Run the shared sidecar tool with explicit fields:

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py handoff --goal "..." --status active --next-step "..." --thread-summary "..."
```

Add repeated flags as needed:
- `--done`
- `--not-done`
- `--risk`
- `--key-file`
- `--touched-area`
- `--validation-tests`
- `--validation-manual`
- `--validation-notes`

3. Read the JSON result to confirm:
- which task was updated
- where the handoff file was written
- which active task file was updated

4. Report the result using the fixed format in [references/output-template.md](references/output-template.md).

## Writing Rules

- Keep `goal`, `nextStep`, and `lastThreadSummary` short.
- Prefer facts and executable next actions over narrative process retelling.
- If validation did not happen, write `not run` instead of guessing.
- If PR URL is unknown, leave it empty rather than blocking the handoff.
- If the task should leave the active set, run the shared tool with `archive` after the handoff is written.

## Fallback Rules

- If there is no sidecar yet, let the tool initialize it.
- If there is no matching task, let the tool create one from the current branch.
- If information is incomplete, still write the handoff with the minimum viable fields:
  - `goal`
  - `next step`
  - `risks`
  - `thread summary`
