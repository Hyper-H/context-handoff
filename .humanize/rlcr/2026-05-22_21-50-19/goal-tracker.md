# Goal Tracker

<!--
This file tracks the ultimate goal, acceptance criteria, and plan evolution.
It prevents goal drift by maintaining a persistent anchor across all rounds.

RULES:
- IMMUTABLE SECTION: Do not modify after initialization
- MUTABLE SECTION: Update each round, but document all changes
- Every task must be in one of: Active, Completed, or Deferred
- Deferred items require explicit justification
-->

## IMMUTABLE SECTION
<!-- Do not modify after initialization -->

### Ultimate Goal

Upgrade `context-handoff` from a v1 worktree handoff prototype into a shareable MVP for AI-assisted feature lifecycle state management.

The V2 product should let a user interact conversationally through one primary skill while the implementation persists compact project/task state in a local sidecar. The user should be able to start a feature, resume a feature, write an incomplete-work handoff, finish/archive a feature, inspect project status from a project hub thread, and generate weekly human-facing reports without committing dynamic state into the repository.

The implementation must keep MCP out of scope for V2. The sidecar schema and CLI should remain simple enough to be wrapped by MCP later, but V2 success is measured by a working skill + CLI + sidecar workflow.

## Acceptance Criteria

### Acceptance Criteria
<!-- Each criterion must be independently verifiable -->
<!-- Claude must extract or define these in Round 0 -->


- AC-1: Unified conversation-first skill exists.
  - Positive Tests (expected to PASS):
    - A `skills/context-handoff/SKILL.md` file exists and documents the actions `start-feature`, `resume-feature`, `handoff`, `finish-feature`, `project-status`, `weekly-report`, `setup`, and `doctor`.
    - The skill tells the agent to use the sidecar CLI as the implementation layer and to keep normal usage conversational.
    - The existing `worktree-intake` and `worktree-handoff` skills remain usable for compatibility.
  - Negative Tests (expected to FAIL):
    - The V2 README tells users to primarily run raw Python commands during normal usage.
    - The new skill requires MCP to work.

- AC-2: Sidecar supports V2 project lifecycle state.
  - Positive Tests (expected to PASS):
    - The sidecar layout includes `active-tasks.json`, `project-state.json`, `handoffs/`, `archive/`, `reports/`, and `events.jsonl`.
    - `active-tasks.json` still tracks only active-like tasks.
    - `project-state.json` stores compact machine-readable project status for agents.
    - Weekly reports are Markdown files under the sidecar `reports/` directory and are not written into the repository.
  - Negative Tests (expected to FAIL):
    - Dynamic task state is written under repo-tracked docs.
    - Weekly report text is mixed into `project-state.json` as long narrative history.

- AC-3: CLI supports lifecycle actions.
  - Positive Tests (expected to PASS):
    - `context_sidecar.py start-feature` creates or updates a task record for the current branch/worktree.
    - `context_sidecar.py resume-feature` resolves the current task and returns compact JSON suitable for skill output.
    - `context_sidecar.py handoff` still updates the latest incomplete-work handoff.
    - `context_sidecar.py finish-feature` archives the task, removes it from active tasks, updates project state, and returns PR-related output.
    - `context_sidecar.py project-status` returns compact project status.
    - `context_sidecar.py weekly-report` writes a Markdown report into sidecar reports.
    - `context_sidecar.py doctor` reports environment readiness without mutating global system state.
  - Negative Tests (expected to FAIL):
    - `finish-feature` fails only because GitHub CLI is absent.
    - `doctor` silently installs GitHub CLI or modifies Codex configuration without explicit user consent.

- AC-4: PR creation follows the hybrid strategy.
  - Positive Tests (expected to PASS):
    - If `gh` is installed and authenticated, `finish-feature` can create a PR when explicitly requested.
    - If `gh` is absent or unauthenticated, `finish-feature` generates PR title/body text, updates sidecar state, and reports setup guidance instead of failing.
    - `prUrl` is recorded when known and left empty when unavailable.
  - Negative Tests (expected to FAIL):
    - The default finish flow silently installs `gh`.
    - The task cannot be finished or archived when no PR URL exists.

- AC-5: Project hub and weekly report behavior is documented and usable.
  - Positive Tests (expected to PASS):
    - README describes the `project hub thread` as a long-lived thread for project status, planning, and short weekly report notifications.
    - Weekly report output is human-facing Markdown in sidecar.
    - Automation setup instructions bind weekly report notifications to the current project hub thread.
    - The thread notification is short and does not paste the full report by default.
  - Negative Tests (expected to FAIL):
    - Weekly reports are positioned as the primary context input for agents.
    - Automation is required for manual `weekly-report` to work.

- AC-6: Telemetry and research scaffold exist without making the workflow heavy.
  - Positive Tests (expected to PASS):
    - `events.jsonl` records lifecycle events such as `start`, `resume`, `handoff`, `finish`, `project-status`, and `weekly-report`.
    - Events include objective fields such as timestamp, projectId, taskId when available, sidecar hit, handoff availability, scan scope, and duration where practical.
    - A research or benchmark note describes future comparisons among no shared context, stable repo docs only, and sidecar + handoff.
  - Negative Tests (expected to FAIL):
    - The normal workflow requires manual subjective scoring after every action.
    - Token measurement is treated as mandatory when no token API is available.

- AC-7: Documentation supports a shareable MVP.
  - Positive Tests (expected to PASS):
    - README and Chinese README explain the V2 positioning as a lightweight project/task state layer.
    - Documentation includes conversation-first examples for start, resume, finish, project status, and weekly report.
    - Documentation clearly says dynamic sidecar state stays local and out of feature PRs.
    - Setup/doctor guidance is understandable for another developer cloning the repo.
  - Negative Tests (expected to FAIL):
    - The docs present V2 as only a handoff template.
    - The docs imply users must use MCP in V2.

---

## MUTABLE SECTION
<!-- Update each round with justification for changes -->

### Plan Version: 2 (Updated: Round 1)

#### Plan Evolution Log
<!-- Document any changes to the plan with justification -->
| Round | Change | Reason | Impact on AC |
|-------|--------|--------|--------------|
| 0 | Initial plan | - | - |
| 1 | Resolved guessed PR URL review finding. | Codex verified `GitContext.pr_url` no longer derives GitHub PR search URLs, and smoke tests showed unknown PRs remain empty while finish/archive still succeeds. | Completes AC-4 hybrid PR behavior without changing scope. |

#### Active Tasks
<!-- Map each task to its target Acceptance Criterion and routing tag -->
| Task | Target AC | Status | Tag | Owner | Notes |
|------|-----------|--------|-----|-------|-------|

### Completed and Verified
<!-- Only move tasks here after Codex verification -->
| AC | Task | Completed Round | Verified Round | Evidence |
|----|------|-----------------|----------------|----------|
| AC-1..AC-7 | Initialize Goal Tracker from the V2 plan | 0 | 1 | Populated full immutable acceptance criteria and active task map from `specs/context-handoff-v2-humanize-plan.md`; Codex re-read tracker and original plan in Round 1. |
| AC-2, AC-3, AC-6 | Expand sidecar layout and lifecycle CLI commands | 0 | 1 | Added V2 sidecar paths, project-state refresh, lifecycle events, and start/resume/finish/project-status commands in `context_sidecar.py`; Round 1 smoke exercised setup/start/resume/handoff/project-status/finish. |
| AC-2, AC-3, AC-5, AC-6 | Add weekly report and project status outputs | 0 | 1 | Added compact `project-status` output and sidecar Markdown `weekly-report` generation; Round 1 smoke verified report under sidecar `reports/` and no weekly narrative in `project-state.json`. |
| AC-3, AC-4 | Add hybrid PR fallback and non-mutating doctor/setup behavior | 0 | 1 | Round 1 verified read-only `doctor`, empty unknown `prUrl`, normal finish without PR URL, and `finish-feature --create-pr` fallback with missing `gh` still archives the task. |
| AC-1, AC-5, AC-7 | Add unified conversation-first skill and compatibility docs | 0 | 1 | `skills/context-handoff/SKILL.md`, README, and Chinese README document conversation-first usage, project hub behavior, weekly reports, setup/doctor, and V1 compatibility. |
| AC-5, AC-6, AC-7 | Add research scaffold and README updates | 0 | 1 | `docs/research/context-handoff-v2-benchmark.md` documents future comparisons and lightweight objective signals without mandatory scoring or token measurement. |
| AC-1..AC-7 | Run smoke validation and fix review findings | 0 | 1 | Round 1 passed `py_compile`, `doctor`, and isolated temp repo smoke covering GitHub remote with no PR: start/resume/finish/fallback kept `prUrl` empty, active task count reached 0, report stayed in sidecar, and no repo-local `.codex` leaked. |

### Explicitly Deferred
<!-- Items here require strong justification -->
| Task | Original AC | Deferred Since | Justification | When to Reconsider |
|------|-------------|----------------|---------------|-------------------|

### Open Issues
<!-- Issues discovered during implementation -->
| Issue | Discovered Round | Blocking AC | Resolution Path |
|-------|-----------------|-------------|-----------------|
