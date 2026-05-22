- [P2] Remove checked-in Humanize session state — C:\Users\Administrator\Documents\context-handoff\.humanize\.pending-session-id:1-1
  This file records a local pending Humanize session with machine-specific absolute paths under `C:/Users/Administrator`. When another developer clones the repo, these paths are invalid and can confuse any tooling that treats `.humanize` as active workflow state; these generated session artifacts should stay local/ignored rather than versioned.

- [P2] Validate Git and V2 layout in doctor — C:\Users\Administrator\Documents\context-handoff\tools\worktree-context-reuse-v1\context_sidecar.py:944-945
  When `doctor` is run outside a Git repository, `_detect_git_context` falls back to the worktree path, so `manager.git.repo_root.exists()` is true even though Git detection failed; similarly, an existing V1 sidecar root passes `sidecar-layout` while missing V2 files such as `project-state.json` and `reports/`. This makes `doctor` report readiness instead of the setup guidance users need.

- [P2] Sanitize report period before building the path — C:\Users\Administrator\Documents\context-handoff\tools\worktree-context-reuse-v1\context_sidecar.py:910-912
  If a caller passes a period containing path separators, such as `--period ../archive/foo` or `..\archive\foo`, this filename composition writes the weekly report outside the `reports/` directory. That violates the documented sidecar layout guarantee that weekly reports live under `reports/`; normalize the label or verify the resolved path stays inside `manager.reports_dir`.
2026-05-22T14:26:41.780113Z  WARN codex_state::runtime: failed to remove legacy logs db file C:\Users\Administrator\.codex\logs_2.sqlite: 另一个程序正在使用此文件，进程无法访问。 (os error 32)
2026-05-22T14:26:41.780204Z  WARN codex_state::runtime: failed to remove legacy logs db file C:\Users\Administrator\.codex\logs_2.sqlite-shm: 另一个程序正在使用此文件，进程无法访问。 (os error 32)
2026-05-22T14:26:41.780271Z  WARN codex_state::runtime: failed to remove legacy logs db file C:\Users\Administrator\.codex\logs_2.sqlite-wal: 另一个程序正在使用此文件，进程无法访问。 (os error 32)
2026-05-22T14:26:41.781373Z  WARN codex_state::runtime: failed to open state db at C:\Users\Administrator\.codex\state_5.sqlite: migration 23 was previously applied but is missing in the resolved migrations
2026-05-22T14:26:41.781835Z  WARN codex_state::runtime: failed to remove legacy logs db file C:\Users\Administrator\.codex\logs_2.sqlite: 另一个程序正在使用此文件，进程无法访问。 (os error 32)
2026-05-22T14:26:41.781937Z  WARN codex_state::runtime: failed to remove legacy logs db file C:\Users\Administrator\.codex\logs_2.sqlite-shm: 另一个程序正在使用此文件，进程无法访问。 (os error 32)
2026-05-22T14:26:41.781964Z  WARN codex_state::runtime: failed to remove legacy logs db file C:\Users\Administrator\.codex\logs_2.sqlite-wal: 另一个程序正在使用此文件，进程无法访问。 (os error 32)
2026-05-22T14:26:41.782756Z  WARN codex_state::runtime: failed to open state db at C:\Users\Administrator\.codex\state_5.sqlite: migration 23 was previously applied but is missing in the resolved migrations
2026-05-22T14:26:41.815873Z  WARN codex_rollout::list: state db discrepancy during find_thread_path_by_id_str_in_subdir: falling_back
The patch adds useful V2 lifecycle functionality, but it also commits local generated workflow state and has concrete correctness issues in the new doctor and weekly-report commands. These should be fixed before considering the change correct.

Full review comments:

- [P2] Remove checked-in Humanize session state — C:\Users\Administrator\Documents\context-handoff\.humanize\.pending-session-id:1-1
  This file records a local pending Humanize session with machine-specific absolute paths under `C:/Users/Administrator`. When another developer clones the repo, these paths are invalid and can confuse any tooling that treats `.humanize` as active workflow state; these generated session artifacts should stay local/ignored rather than versioned.

- [P2] Validate Git and V2 layout in doctor — C:\Users\Administrator\Documents\context-handoff\tools\worktree-context-reuse-v1\context_sidecar.py:944-945
  When `doctor` is run outside a Git repository, `_detect_git_context` falls back to the worktree path, so `manager.git.repo_root.exists()` is true even though Git detection failed; similarly, an existing V1 sidecar root passes `sidecar-layout` while missing V2 files such as `project-state.json` and `reports/`. This makes `doctor` report readiness instead of the setup guidance users need.

- [P2] Sanitize report period before building the path — C:\Users\Administrator\Documents\context-handoff\tools\worktree-context-reuse-v1\context_sidecar.py:910-912
  If a caller passes a period containing path separators, such as `--period ../archive/foo` or `..\archive\foo`, this filename composition writes the weekly report outside the `reports/` directory. That violates the documented sidecar layout guarantee that weekly reports live under `reports/`; normalize the label or verify the resolved path stays inside `manager.reports_dir`.
