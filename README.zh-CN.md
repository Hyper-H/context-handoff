# context-handoff

中文 | [English](./README.md)

`context-handoff` 是一套轻量的上下文复用与交接工作流，用来降低多 worktree、多 thread 的 feature/PR 开发中的上下文重建成本。它由仓库内稳定事实、本机 sidecar 状态层，以及 intake/handoff skills 组成。

## 它解决什么问题

- 新 thread 反复重扫同一个仓库
- 多个 worktree 和 agent thread 之间容易丢失任务状态
- feature 或 PR 的交接噪声大、不稳定、成本高

## 核心思路

把项目上下文拆成三层：

- `docs/agent/`
  放入版本控制的稳定仓库事实
- local sidecar
  不进入 feature PR 的动态任务状态
- `worktree-intake` / `worktree-handoff`
  用自然语言触发的 skill 入口，用来恢复和保存当前任务上下文

## 仓库结构

```text
docs/
  agent/
    project-map.md
    conventions.md
    common-commands.md
skills/
  worktree-intake/
  worktree-handoff/
tools/
  worktree-context-reuse-v1/
    context_sidecar.py
    templates/
specs/
  multi-worktree-thread-handoff-v1.md
worktree-context-reuse-v1-usage.md
```

## 本机 Sidecar 结构

工具默认把本机状态写到：

```text
%USERPROFILE%\.codex\projects\<project-id>\
  active-tasks.json
  handoffs\
  archive\
  events.jsonl
```

这些状态是本机私有的，不应该进 feature PR。

## 快速开始

1. 先补齐 `docs/agent/` 下的稳定事实文档
2. 把两个 skill 安装或复制到本机 Codex skill 目录
3. 在真实 git worktree 里运行：

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py init
python tools\worktree-context-reuse-v1\context_sidecar.py snapshot
python tools\worktree-context-reuse-v1\context_sidecar.py intake
```

4. 每轮工作结束前写一次 handoff：

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py handoff `
  --goal "current goal" `
  --status active `
  --next-step "next concrete step" `
  --thread-summary "2-4 sentence compressed summary"
```

5. 任务彻底完成后归档：

```powershell
python tools\worktree-context-reuse-v1\context_sidecar.py archive
```

## Skill 用法

本地安装后，可以直接这样对 Codex 说：

- `Use $worktree-intake to recover the current worktree context and tell me the next step.`
- `Use $worktree-handoff to save the current worktree status and prepare the next agent handoff.`

## 当前验证状态

这个仓库里的 v1 实现目前已经验证过：

- 非 git 回退场景
- 一个临时真实 git 仓库中的 smoke test：
  - `snapshot`
  - `handoff`
  - `intake`
  - `archive`

## 说明

- 这个项目在 v1 明确不优先做自定义 MCP
- 当前设计优先服务个人工作流，之后再考虑共享或实验评估
- `events.jsonl` 只是轻量实验留痕，不是正式 benchmark
