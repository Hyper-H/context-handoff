# context-handoff

中文 | [English](./README.md)

`context-handoff` 是一个自包含的 Codex skill，用来为 AI 辅助 feature 开发维护轻量项目/任务状态。它帮助 agent 在不同 branch、worktree、thread 之间恢复上下文，减少重复扫项目和重复解释。

日常入口是对话：

```text
Use $context-handoff to resume this worktree.
```

skill 自带 Python sidecar CLI，位置在 `skills/context-handoff/scripts/`。用户安装 skill 后，不需要知道 CLI 在哪里。

## 解决什么问题

- 新 agent thread 反复扫描同一个仓库。
- feature branch、worktree、thread 之间丢失任务状态。
- handoff、完成归档、周报输出不稳定。
- 动态 agent 状态误写进仓库文档或 feature PR。

## 安装

clone 本仓库后运行：

```powershell
python install.py
```

它会把完整 skill 包复制到：

```text
%USERPROFILE%\.codex\skills\context-handoff\
```

如果 Codex 没有立刻刷新 skill 列表，请重启或刷新 Codex。

安装器只复制 skill 包，不会安装 GitHub CLI，不会登录账号，也不会修改全局 Codex 配置。

## 使用

在任意 git 项目或 worktree 中，对 Codex 说：

```text
Use $context-handoff to run doctor/setup for this project.
```

然后就可以自然对话：

```text
Use $context-handoff to start this feature. Goal: improve the dashboard UI.
```

```text
Use $context-handoff to resume this worktree and tell me the immediate next step.
```

```text
Use $context-handoff to save a handoff before I stop today.
```

```text
Use $context-handoff to finish this feature and generate PR text.
```

```text
Use $context-handoff to generate last week's report.
```

## Sidecar 状态

动态状态只保存在本机，不进入目标仓库：

```text
%USERPROFILE%\.codex\projects\<project-id>\
  active-tasks.json
  project-state.json
  handoffs\
  archive\
  reports\
  events.jsonl
```

`project-state.json` 是给 agent 读的紧凑机器状态。handoff 和 weekly report 是给人读的 Markdown。稳定仓库事实仍然可以放在受版本控制的 `docs/agent/` 中。

## 主要动作

- `doctor`：检查 Python、Git、sidecar、可选 GitHub CLI 是否就绪。
- `setup`：创建本机 sidecar 结构。
- `start-feature`：把当前 branch/worktree 记录为 active task。
- `resume-feature`：恢复当前 worktree 的紧凑上下文。
- `handoff`：保存未完成工作、下一步和阻塞点。
- `finish-feature`：归档任务并生成 PR 标题/正文；只有在用户明确要求且 GitHub CLI 可用时才创建 PR。
- `project-status`：为 project hub thread 汇总当前项目状态。
- `weekly-report`：在 sidecar 的 `reports/` 目录生成给人看的 Markdown 周报。

V1 的 `worktree-intake` 和 `worktree-handoff` 已合并进统一的 `context-handoff` skill，分别对应 `resume-feature` 和 `handoff`。

## 给旧项目补状态

Git 历史可以恢复客观事实，例如 branch、commit、改动文件和触达目录。它不能可靠恢复目标、设计决策、阻塞点、验证状态或正确下一步。

第一次给旧项目补 sidecar 状态时，建议组合：

- 当前 worktree 的 Git 事实。
- 当前 thread 或用户补充的语义上下文。
- 已有 PR、issue 或 release notes。

第一次补录可能多花一点 token。之后持续使用 `start-feature`、`handoff`、`finish-feature`，后续恢复和周报就会更便宜。

## GitHub PR 行为

GitHub CLI 是可选能力。没有 PR URL 时，`finish-feature` 也能正常完成和归档。如果本机已安装并登录 `gh`，且用户明确要求创建 PR，skill 才会尝试创建 PR。否则它只生成 PR 标题/正文，并记录本地完成状态。

## 研究说明

`events.jsonl` 会记录轻量生命周期事件，方便以后评估效果。它本身不是完整 benchmark。后续对照实验设计见 [docs/research/context-handoff-v2-benchmark.md](./docs/research/context-handoff-v2-benchmark.md)。
