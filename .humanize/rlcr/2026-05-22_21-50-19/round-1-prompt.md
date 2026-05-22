Your work is not finished. Read and execute the below with ultrathink.

## Original Implementation Plan

**IMPORTANT**: Before proceeding, review the original plan you are implementing:
@specs/context-handoff-v2-humanize-plan.md

This plan contains the full scope of work and requirements. Ensure your work aligns with this plan.

---

For all tasks that need to be completed, please use the Task system (TaskCreate, TaskUpdate, TaskList) to track each item in order of importance.
You are strictly prohibited from only addressing the most important issues - you MUST create Tasks for ALL discovered issues and attempt to resolve each one.

Before executing each task in this round:
1. Read @/c/Users/Administrator/Documents/context-handoff/.humanize/bitlesson.md
2. Run `bitlesson-selector` for each task/sub-task
3. Follow selected lesson IDs (or `NONE`) during implementation

---
Below is Codex's review result:
<!-- CODEX's REVIEW RESULT START -->
# Round 0 Review Result

## Findings

### [P1] Do not record guessed PR search URLs as known `prUrl`

`tools/worktree-context-reuse-v1/context_sidecar.py:187-210` derives `GitContext.pr_url` from any GitHub remote and current branch by returning a `/pulls?q=is%3Apr+head%3A...` search URL. That guessed search URL is then copied into new tasks via `default_task`/`upsert_task` and returned by `finish-feature` even when PR creation was not requested and no actual PR URL is known.

This violates AC-4: "`prUrl` is recorded when known and left empty when unavailable." I reproduced it in a temporary repository with `origin=https://github.com/example/repo.git`, branch `feature/no-pr`, no PR creation, and no `--pr-url`. `start-feature` stored:

```json
"prUrl": "https://github.com/example/repo/pulls?q=is%3Apr+head%3Afeature/no-pr"
```

Then `finish-feature` returned the same value under `pr.prUrl` even though `requested` and `created` were both false. This is not a PR URL; it is a search page, and it makes downstream agents and project status believe a PR is known.

Required implementation plan:

1. Remove the `_guess_pr_url` behavior from current task state. `GitContext.pr_url` must default to `""` unless the implementation can resolve an actual PR URL.
2. Keep explicit user-supplied PR URLs working: `finish-feature --pr-url <url>` and task updates with `--pr-url` should still persist that exact URL.
3. Keep successful `gh pr create` working: when `gh pr create` succeeds, record the returned PR URL in the archived task payload and finish output.
4. Do not replace the actual `prUrl` field with a search URL. If a search helper is useful, expose it under a different advisory field such as `prSearchUrl` or only in guidance text, not in task `prUrl`.
5. Add or rerun a smoke test with a GitHub remote and no actual PR:
   - `start-feature` output task has `prUrl: ""`.
   - `finish-feature` without `--create-pr` returns `pr.prUrl: ""`.
   - `finish-feature --create-pr` with missing or unauthenticated `gh` still archives the task and returns `pr.prUrl: ""`.
6. Verify the previous lifecycle smoke test still passes: setup, start, resume, handoff, project-status, weekly-report, finish fallback, no repo-local `.codex` leak, and `project-state.json` contains no weekly report narrative.

## Goal Alignment Summary

ACs: 6/7 addressed | Forgotten items: 0 | Unjustified deferrals: 0

AC-1, AC-2, AC-3, AC-5, AC-6, and AC-7 are materially addressed by the committed files and smoke tests. AC-4 is not fully satisfied because unavailable PR URLs are not consistently left empty. The Goal Tracker had no explicit deferrals and no missing task categories, but I added the PR URL issue to Open Issues because it blocks AC-4.

## Verification Performed

- Read `specs/context-handoff-v2-humanize-plan.md`, the Round 0 prompt, and `goal-tracker.md`.
- Inspected the V2 sidecar CLI, unified skill, English/Chinese READMEs, and benchmark note.
- Ran `python -m py_compile tools\worktree-context-reuse-v1\context_sidecar.py`.
- Ran CLI help and `doctor`; `doctor` reported `mutatedSystemState: false`.
- Ran an isolated temporary repo smoke test covering `setup`, `start-feature`, `resume-feature`, `handoff`, `project-status`, `weekly-report`, and `finish-feature --create-pr` with missing `gh`; the general lifecycle passed.
- Ran a focused temporary repo repro showing the false `prUrl` behavior with a GitHub remote and no actual PR.
<!-- CODEX's REVIEW RESULT  END  -->
---

## Goal Tracker Reference (READ-ONLY after Round 0)

Before starting work, **read** @/c/Users/Administrator/Documents/context-handoff/.humanize/rlcr/2026-05-22_21-50-19/goal-tracker.md to understand:
- The Ultimate Goal and Acceptance Criteria you're working toward
- Which tasks are Active, Completed, or Deferred
- Any Plan Evolution that has occurred
- Open Issues that need attention

**IMPORTANT**: You CANNOT directly modify goal-tracker.md after Round 0.
If you need to update the Goal Tracker, include a "Goal Tracker Update Request" section in your summary (see below).

---

Note: You MUST NOT try to exit by lying, editing loop state files, or executing `cancel-rlcr-loop`.

After completing the work, please:
0. If the `code-simplifier` plugin is installed, use it to review and optimize your code. Invoke via: `/code-simplifier`, `@agent-code-simplifier`, or `@code-simplifier:code-simplifier (agent)`
1. Commit your changes with a descriptive commit message
2. Write your work summary into @/c/Users/Administrator/Documents/context-handoff/.humanize/rlcr/2026-05-22_21-50-19/round-1-summary.md

## Task Tag Routing Reminder

Follow the plan's per-task routing tags strictly:
- `coding` task -> Claude executes directly
- `analyze` task -> execute via `/humanize:ask-codex`, then integrate the result
- Keep Goal Tracker Active Tasks columns `Tag` and `Owner` aligned with execution

**If Goal Tracker needs updates**, include this section in your summary:
```markdown
## Goal Tracker Update Request

### Requested Changes:
- [E.g., "Mark Task X as completed with evidence: tests pass"]
- [E.g., "Add to Open Issues: discovered Y needs addressing"]
- [E.g., "Plan Evolution: changed approach from A to B because..."]
- [E.g., "Defer Task Z because... (impact on AC: none/minimal)"]

### Justification:
[Explain why these changes are needed and how they serve the Ultimate Goal]
```

Codex will review your request and update the Goal Tracker if justified.
