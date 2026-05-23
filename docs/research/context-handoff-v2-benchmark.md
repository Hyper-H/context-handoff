# Context Handoff V2 Benchmark Notes

This note sketches future evaluation without adding required steps to the normal workflow.

## Comparison Groups

- No shared context: each new agent thread starts from the repository and user prompt only.
- Stable repo docs only: agents can read `docs/agent/` but have no dynamic task sidecar.
- Sidecar plus handoff: agents use stable docs, `project-state.json`, active task records, and latest handoff Markdown.

## Objective Signals

- Time to first useful next step.
- Whether the latest handoff was available.
- Whether the sidecar had a matching task for the branch/worktree.
- Approximate scan scope, such as stable docs only, git status, or broader repository scan.
- Lifecycle event duration when practical.
- Whether the first proposed step was accepted or corrected.

## Event Source

`events.jsonl` records lightweight lifecycle traces for actions such as `start`, `resume`, `handoff`, `finish`, `project-status`, and `weekly-report`. These events are for coarse workflow analysis, not mandatory per-action scoring.

## Non-Goals

- Do not require manual subjective scoring after every action.
- Do not treat token measurement as mandatory when no token API is available.
- Do not write dynamic benchmark state into tracked repository docs.
