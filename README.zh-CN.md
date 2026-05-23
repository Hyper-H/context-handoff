# context-handoff

中文 | [English](./README.md)

`context-handoff` 是一个面向 AI 辅助 feature 生命周期的轻量项目/任务状态层。V2 的日常入口是一个统一的对话式 skill，本机 sidecar 负责保存紧凑的动态状态，并且这些状态不进入 feature PR。

## 它解决什么问题

- 新 thread 反复重扫同一个仓库。
- 多 worktree、多 agent thread 之间容易丢任务状态。
- feature 交接、完成归档、周报输出不稳定。
- 动态 agent 状态容易误写进仓库文档或 PR。

## 核心模型

- `docs/agent/`：应该进入版本控制的稳定仓库事实。
- 本机 sidecar：位于 `%USERPROFILE%\.codex\projects\<project-id>\` 的动态项目/任务状态。
- `skills/context-handoff`：V2 的统一对话式生命周期 skill。
- `worktree-intake` 和 `worktree-handoff`：继续可用的 V1 兼容入口。

V2 不需要 MCP。sidecar schema 和 CLI 会保持简单，方便以后再包 MCP，但这个 MVP 的成功标准是 skill + CLI + sidecar 能跑通。

## Sidecar 结构

```text
%USERPROFILE%\.codex\projects\<project-id>\
  active-tasks.json
  project-state.json
  handoffs\
  archive\
  reports\
  events.jsonl
```

`active-tasks.json` 只保存 active-like 任务。`project-state.json` 保存给 agent 使用的紧凑机器可读状态。较长的人类叙事应该放在 Markdown handoff 和 weekly report 里，不混进 project-state JSON。

## 对话优先用法

日常使用优先通过统一 skill：

- `Use $context-handoff to start this feature: add V2 lifecycle state.`
- `Use $context-handoff to resume this worktree and tell me the next step.`
- `Use $context-handoff to save a handoff before I stop today.`
- `Use $context-handoff to finish this feature and generate PR text.`
- `Use $context-handoff to show project status from the project hub thread.`
- `Use $context-handoff to create this week's project report.`

agent 应该在后台调用 sidecar CLI，然后用自然语言总结关键结果。除非用户明确要求，不要直接粘贴很长的 JSON。

## Project Hub Thread

project hub thread 是一个长期线程，用于项目状态、规划和短周报通知。它不是 agent 的主要上下文输入。agent 恢复工作时仍应优先使用紧凑 sidecar 状态和最新 handoff。

weekly report 是写入 sidecar `reports/` 目录的人类可读 Markdown。手动运行 `weekly-report` 不依赖 automation。如果要配置周期 automation，请把通知绑定到当前 project hub thread，并默认只发简短通知和报告路径，不粘贴完整报告。

## 底层 CLI

Python CLI 是 skill 的实现层，也可用于测试、调试和非 skill 集成：

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py setup
python tools\worktree-context-reuse-v1\context_sidecar.py doctor
python tools\worktree-context-reuse-v1\context_sidecar.py start-feature --goal "Add lifecycle sidecar"
python tools\worktree-context-reuse-v1\context_sidecar.py resume-feature
python tools\worktree-context-reuse-v1\context_sidecar.py handoff --next-step "Run smoke tests"
python tools\worktree-context-reuse-v1\context_sidecar.py finish-feature
python tools\worktree-context-reuse-v1\context_sidecar.py project-status
python tools\worktree-context-reuse-v1\context_sidecar.py weekly-report
```

兼容命令仍然保留：

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py init
python tools\worktree-context-reuse-v1\context_sidecar.py snapshot
python tools\worktree-context-reuse-v1\context_sidecar.py intake
python tools\worktree-context-reuse-v1\context_sidecar.py archive
```

## PR 完成策略

`finish-feature` 即使没有 PR URL 也会归档当前任务。默认行为是生成 PR title/body 文案。如果你显式传入 `--create-pr`，并且本机已经安装且登录了 `gh`，它会尝试创建 PR 并记录 URL。如果 `gh` 缺失或未登录，它会保留空的 `prUrl`、继续完成归档，并输出设置指导。

工具不会静默安装 GitHub CLI、不会替你登录账号，也不会偷偷修改全局 Codex 设置。

## Setup 和 Doctor

`doctor` 只检查环境准备情况，不修改全局状态。`setup` 用来创建本机 sidecar 结构。其他开发者 clone 仓库后只需要 Python、Git 和 skill 文件即可开始使用；GitHub CLI 是可选项，只用于自动创建 PR。

动态 sidecar 状态是本机私有状态，不应该进入 feature PR。
