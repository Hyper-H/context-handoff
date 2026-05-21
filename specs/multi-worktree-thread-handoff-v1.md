# 多 Worktree / 多 Thread 上下文复用与交接方案 v1

本文件收录当前 v1 的最小实施规范，包含：

- 仓库内稳定事实层
- 本机 sidecar 动态状态层
- `worktree-intake` / `worktree-handoff` skill 入口
- 轻量实验留痕思路

实现版本请结合仓库中的：

- `tools/worktree-context-reuse-v1/context_sidecar.py`
- `skills/worktree-intake/`
- `skills/worktree-handoff/`
- `docs/agent/`

补充说明见：

- `worktree-context-reuse-v1-usage.md`

原始设计过程和更完整的讨论版曾在本地工作区中整理过；本仓库保留的是更适合共享和实现的版本。
