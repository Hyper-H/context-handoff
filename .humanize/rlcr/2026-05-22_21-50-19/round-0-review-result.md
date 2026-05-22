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
