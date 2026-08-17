#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = {"active", "paused", "blocked", "review", "validation"}
VALID_PHASES = {"implementation", "validation", "post-merge-validation", "follow-up", "bugfix"}
VALID_THREAD_ROLES = {"hub", "primary-execution", "discussion", "research", "review", "validation", "dogfood", "explainer"}
VALID_ROUTING_STATUSES = {"confirmed", "inferred", "ambiguous", "mismatch", "provisional"}
LOAD_HANDOFF_MODES = {"compact", "section", "full"}
LOAD_HANDOFF_SECTIONS = {
    "meta",
    "receipt",
    "objective",
    "facts",
    "inferences",
    "unknowns",
    "safety",
    "done",
    "not-done",
    "blocker",
    "touched-areas",
    "key-files",
    "next-step",
    "validation",
    "risks",
    "thread-summary",
}
LOAD_HANDOFF_REASONS = {
    "resume",
    "validation-needed",
    "decision-trace",
    "route-mismatch",
    "stale-head",
    "compact-insufficient",
    "debug",
    "user-asked",
    "other",
}
SIDECAR_VERSION = 2
GH_AUTH_STATUS_TIMEOUT_SECONDS = 15
DOGFOOD_ISSUE_LABELS = ["agent-reported", "needs-triage"]
DOGFOOD_HYGIENE_SCOPE_TERMS = [
    "dogfood",
    "smoke",
    "pre-reinstall",
    "pre reinstall",
    "stale environment",
    "role model consistency",
    "old checksum",
    "installed skill stale",
]
DOGFOOD_HYGIENE_FAILURE_TERMS = [
    "fail",
    "failed",
    "failure",
    "blocked",
    "stale",
    "version mismatch",
    "source stale",
    "old checksum",
    "not installed",
    "not running the target patch",
]
DOGFOOD_HYGIENE_PASS_TERMS = [
    "pass",
    "passed",
    "resolved",
    "install passed",
    "checksum match",
    "checksums now match",
    "source updated",
    "stale environment issue",
    "not a patch failure",
    "not a real",
    "smoke passed",
]
DOGFOOD_HYGIENE_ARCHIVE_REASON = "stale dogfood/smoke record superseded by later passing validation"
ORIENT_HUB_RECEIPT_FIELDS = ["taskId", "threadRole", "routingStatus", "scope", "boundary", "possible next paths", "risks/unknowns"]
ORIENT_HANDOFF_REQUIREMENTS = ["event-driven only", "durable facts/findings", "inferences", "unknowns", "decisions", "risks", "nextStep"]
ORIENT_STARTUP_PROTOCOL = [
    "run orient-thread",
    "summarize scope, boundary, and possible next paths",
    "wait for user direction before research, execution, audit, validation, web search, or heavy handoff",
    "save handoff only when durable state should survive, when passing work to another role/agent, before stopping after meaningful work, or when the user asks",
]
ROLE_BOUNDARIES = {
    "hub": "Hub threads maintain the global project map, routing, prioritization, project inventory, summaries, and follow-up prompts. They do not own feature implementation details.",
    "discussion": "Discussion threads shape internal project, product, and engineering tradeoffs. They do not create worktrees or modify code unless implementation begins.",
    "research": "Research threads seek external evidence, prior art, related work, academic/product/ecosystem context, market comparison, novelty, baselines, experiments, and feasibility. They do not modify code unless explicitly redirected.",
    "primary-execution": "Primary execution threads implement code changes, run validation, prepare PR/handoff state, and report durable status back to the Project Hub.",
    "review": "Review threads inspect code, design, rigor, or PR readiness and return findings. They do not become long-running task owners.",
    "validation": "Validation threads run focused checks, benchmarks, browser/UI/a11y validation, or regression tests and report exact commands/results.",
    "dogfood": "Dogfood threads reproduce real workflow feedback, keep facts/inferences/unknowns separate, prefer draft issues, and report durable findings back to the Project Hub.",
    "explainer": "Explainer threads produce onboarding, architecture, or history explanations and save durable facts or docs pointers back to sidecar when useful.",
}
ROLE_EXTERNAL_SKILLS = {
    "research": [
        {
            "skill": "academic-research-suite",
            "roles": ["research", "review", "validation"],
            "reason": "Useful for literature review, paper planning, reviewer perspective, and experiment design.",
            "fallback": "Continue with built-in Codex reasoning/tools and record missing specialist support as an unknown or risk.",
        },
        {
            "skill": "pdf / literature / citation / plotting skills",
            "roles": ["research"],
            "reason": "Useful when evidence comes from PDFs, papers, citation trails, charts, or experimental plots.",
            "fallback": "Use available local/web tools and record any unavailable specialist workflow as a limitation.",
        },
    ],
    "review": [
        {
            "skill": "code review / paper reviewer / rigor-review skills",
            "roles": ["review"],
            "reason": "Useful for independent critique, correctness checks, reviewer perspective, and rigor gaps.",
            "fallback": "Perform a focused built-in review and record any missing specialist perspective as a risk.",
        }
    ],
    "validation": [
        {
            "skill": "browser / UI / accessibility / eval / benchmark skills",
            "roles": ["validation"],
            "reason": "Useful for targeted runtime, interface, accessibility, evaluation, or benchmark checks.",
            "fallback": "Run the strongest available local validation and record missing tooling as an unknown.",
        }
    ],
    "explainer": [
        {
            "skill": "documents / PDF / presentation / context explanation skills",
            "roles": ["explainer"],
            "reason": "Useful for durable onboarding, architecture explanation, and human-facing project summaries.",
            "fallback": "Produce a concise explanation with available repo and sidecar context.",
        }
    ],
    "dogfood": [
        {
            "skill": "browser/control, accessibility, baseline UI, and native draft-issue",
            "roles": ["dogfood"],
            "reason": "Useful for real workflow reproduction, UI checks, accessibility feedback, and issue drafting.",
            "fallback": "Use built-in reproduction steps and `draft-issue`; do not create issues unless explicitly allowed.",
        }
    ],
}
SENSITIVE_ISSUE_PATTERNS = [
    r"gho_[A-Za-z0-9_]+",
    r"ghp_[A-Za-z0-9_]+",
    r"ghs_[A-Za-z0-9_]+",
    r"ghu_[A-Za-z0-9_]+",
    r"ghr_[A-Za-z0-9_]+",
    r"github_pat_[A-Za-z0-9_]+",
    r"sk-[A-Za-z0-9_-]{16,}",
    r"AKIA[0-9A-Z]{16}",
    r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}",
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    r"npm_[A-Za-z0-9]{16,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*\S+",
    r"(?i)\b(users\\[^\\\s]+\\|/users/[^/\s]+/|/home/[^/\s]+/)",
]
JSON_READ_RETRIES = 5
JSON_READ_RETRY_SECONDS = 0.05
FILE_LOCK_TIMEOUT_SECONDS = 10
FILE_LOCK_POLL_SECONDS = 0.05
SUPPORTED_LANGUAGES = {"en", "zh-CN"}


TEXT = {
    "en": {
        "none": "None",
        "none_recorded": "None recorded",
        "not_recorded": "not recorded",
        "not_run": "not run",
        "handoff": "Handoff",
        "meta": "Meta",
        "goal": "Goal",
        "goal_not_recorded": "Goal not recorded.",
        "status": "Status",
        "branch": "Branch",
        "base_branch": "Base Branch",
        "worktree": "Worktree",
        "head_sha": "Head SHA",
        "upstream": "Upstream",
        "dirty_fingerprint": "Dirty Fingerprint",
        "updated_at": "Updated At",
        "current_objective": "Current Objective",
        "current_objective_missing": "Current objective not recorded.",
        "facts": "Facts",
        "inferences": "Inferences",
        "unknowns": "Unknowns",
        "safety_rules": "Safety Rules",
        "done": "Done",
        "not_done": "Not Done",
        "blocker": "Blocker",
        "touched_areas": "Touched Areas",
        "key_files": "Key Files",
        "suggested_next_step": "Suggested Next Step",
        "next_step_missing": "Next step not recorded.",
        "validation_status": "Validation Status",
        "validated_at": "Validated At",
        "commands": "Commands",
        "results": "Results",
        "notes": "Notes",
        "risks": "Risks",
        "thread_summary": "Thread Summary",
        "thread_summary_missing": "Thread summary not recorded.",
        "summary_title": "Agent Workflow Hub Start Summary",
        "handoff_available": "Handoff",
        "stale": "Stale",
        "stale_warning": "Stale Warning",
        "stale_warning_text": "verify before trusting this handoff.",
        "stale_warning_none": "none",
        "stale_reasons": "Stale Reasons",
        "validation": "Validation",
        "last_validation_at": "Last validation at",
        "command": "Command",
        "result": "Result",
        "immediate_next_step": "Immediate Next Step",
        "risks_blockers": "Risks / Blockers",
        "sidecar": "Sidecar",
        "handoff_path": "Handoff path",
        "weekly_report": "Weekly Report",
        "period": "Period",
        "sidecar_path": "Sidecar",
        "snapshot": "Snapshot",
        "active_tasks": "Active tasks",
        "current_branch": "Current branch",
        "active_work": "Active Work",
        "no_active_tasks": "No active tasks recorded.",
        "human_note": "Human Note",
        "weekly_human_note": "Use this report as a short project update. Agents should prefer `project-state.json` plus latest handoff for compact context.",
        "reproduction": "Reproduction",
        "suggested_fix": "Suggested Fix",
        "priority": "Priority",
        "context": "Context",
        "project": "Project",
        "task": "Task",
        "worktree_name": "Worktree Name",
        "generated_at": "Generated At",
        "finding_missing_handoff": "No latest handoff Markdown exists for the resolved task.",
        "finding_stale": "Recorded task snapshot differs from current git state.",
        "finding_missing_validation": "No validation time, command, result, or notes are recorded.",
        "finding_missing_safety_rules": "No first-class safetyRules are recorded.",
        "finding_dirty_worktree": "Current worktree has uncommitted changes.",
        "finding_missing_task": "No sidecar task matched the current branch/worktree.",
        "prompt_handoff": "Write a handoff with concrete done/not-done, next step, facts, inferences, unknowns, validation, and safety rules.",
        "prompt_validation": "Record validation command(s), result(s), and validation time after running checks.",
        "prompt_safety": "Record safetyRules that constrain the next agent's edits and repo hygiene.",
        "prompt_stale": "Review current HEAD and dirty files before trusting the previous handoff.",
        "prompt_facts": "Backfill objective facts from git status, recent commits, PR/issue text, or the current thread.",
        "prompt_unknowns": "Name unknowns explicitly instead of filling missing context with guesses.",
        "warning_worktree_count": "Git worktree count differs from sidecar active task count; project-status is not a full worktree inventory.",
        "warning_project_id_canonicalized": "Project id was canonicalized from {requested} to {canonical}.",
        "available": "available",
        "missing": "missing",
        "yes": "yes",
        "no": "no",
        "weekly_ready": "Weekly context report is ready: {path}",
        "issue_draft_guidance": "Draft only by default. Ask to create issue or enable dogfood issue mode to allow creation.",
        "resolver_no_match": "No task matched \"{query}\". Please give a branch, task id, or alias.",
        "resolver_disambiguation": "I found multiple possible tasks for \"{query}\": {candidates}. Which one do you want to continue?",
        "resolver_project_multiple": "Multiple projects matched this container path. Which project should Agent Workflow Hub use?",
        "resolver_project_missing": "This path is not a Git worktree and no known Agent Workflow Hub project matched it. Please provide --worktree or --project-id.",
        "action_reason_missing_task": "sidecar task missing",
        "action_reason_stale": "task snapshot is stale",
        "action_reason_missing_handoff": "handoff missing",
        "action_reason_missing_validation": "validation missing",
        "action_reason_missing_safety": "safety rules missing",
        "action_reason_dirty_worktree": "worktree has uncommitted changes",
        "cleanup_reason_missing_worktree": "active sidecar task points to a missing worktree",
        "hub_receipt_expected": "Report back to the Project Hub with: taskId, status, handoffPath, nextStep, blocker, validation, risks.",
        "old_thread_backfill_prompt": (
            "You are the existing Primary Execution Thread for project {project_id}, branch {branch}. "
            "Repo/worktree: {worktree_path}. Use $agent-workflow-hub first: run resume-feature and audit-context for this worktree. "
            "If no sidecar task exists, create a provisional task with start-feature. "
            "Backfill or refresh sidecar state and handoff because audit-project reported: {reasons}. "
            "Use your own investigation strategy; do not full-scan unless necessary. "
            "Use sidecar/handoff/git facts/touchedFiles/recent commits/PR/issue/targeted search as evidence as needed; touchedFiles means current Git dirty/touched files and is only one locator signal. "
            "Before stopping, update facts, inferences, unknowns, safety rules, validation, nextStep, blockers/risks, save a handoff, and report back to the hub."
        ),
        "new_thread_execution_prompt": (
            "You are a new Primary Execution Thread for project {project_id}, branch {branch}. "
            "Repo/worktree: {worktree_path}. Use $agent-workflow-hub first: run resume-feature if a task already exists, otherwise start-feature with a provisional goal from the branch/worktree. "
            "Then run audit-context and do the minimum useful intake needed to make the context trustworthy because audit-project reported: {reasons}. "
            "Use your own investigation strategy; do not full-scan unless necessary. "
            "Use sidecar/handoff/git facts/touchedFiles/recent commits/PR/issue/targeted search as evidence as needed; touchedFiles means current Git dirty/touched files and is only one locator signal. "
            "Before stopping, distinguish facts/inferences/unknowns, add validation and safety rules, set nextStep and blocker/risks, save a handoff, and report back to the hub."
        ),
        "stale_refresh_prompt": (
            "This task appears stale. In the execution thread for project {project_id}, branch {branch}, worktree {worktree_path}, use $agent-workflow-hub to run resume-feature and audit-context. "
            "Verify current HEAD, dirty state, validation, and nextStep before trusting older handoff content. "
            "Refresh facts, inferences, unknowns, safety rules, validation, and handoff, then report back to the hub."
        ),
        "cleanup_prompt": (
            "Project Hub cleanup request for project {project_id}: sidecar task {task_id} on branch {branch} points to a missing worktree: {worktree_path}. "
            "Ask the human to confirm whether this task was merged, abandoned, moved, or still needs recovery. "
            "If complete, use $agent-workflow-hub finish-feature or archive as appropriate; if abandoned, archive with a clear reason. "
            "Do not automatically delete any worktree or repo files. Report the archived/finished state back to the hub."
        ),
    },
    "zh-CN": {
        "none": "无",
        "none_recorded": "未记录",
        "not_recorded": "未记录",
        "not_run": "未运行",
        "handoff": "交接",
        "meta": "元信息",
        "goal": "目标",
        "goal_not_recorded": "未记录目标。",
        "status": "状态",
        "branch": "分支",
        "base_branch": "基准分支",
        "worktree": "工作树",
        "head_sha": "HEAD SHA",
        "upstream": "上游",
        "dirty_fingerprint": "未提交变更指纹",
        "updated_at": "更新时间",
        "current_objective": "当前目标",
        "current_objective_missing": "未记录当前目标。",
        "facts": "事实",
        "inferences": "推断",
        "unknowns": "未知",
        "safety_rules": "安全规则",
        "done": "已完成",
        "not_done": "未完成",
        "blocker": "阻塞",
        "touched_areas": "触达区域",
        "key_files": "关键文件",
        "suggested_next_step": "建议下一步",
        "next_step_missing": "未记录下一步。",
        "validation_status": "验证状态",
        "validated_at": "验证时间",
        "commands": "命令",
        "results": "结果",
        "notes": "备注",
        "risks": "风险",
        "thread_summary": "线程摘要",
        "thread_summary_missing": "未记录线程摘要。",
        "summary_title": "Agent Workflow Hub 接手摘要",
        "handoff_available": "交接",
        "stale": "过期",
        "stale_warning": "过期警告",
        "stale_warning_text": "信任此交接前请先核验当前状态。",
        "stale_warning_none": "无",
        "stale_reasons": "过期原因",
        "validation": "验证",
        "last_validation_at": "最近验证时间",
        "command": "命令",
        "result": "结果",
        "immediate_next_step": "立即下一步",
        "risks_blockers": "风险 / 阻塞",
        "sidecar": "Sidecar",
        "handoff_path": "交接文件",
        "weekly_report": "周报",
        "period": "周期",
        "sidecar_path": "Sidecar 路径",
        "snapshot": "快照",
        "active_tasks": "活跃任务",
        "current_branch": "当前分支",
        "active_work": "活跃工作",
        "no_active_tasks": "没有记录活跃任务。",
        "human_note": "人工备注",
        "weekly_human_note": "将此报告作为简短项目更新。Agent 应优先使用 `project-state.json` 和最新 handoff 来恢复紧凑上下文。",
        "reproduction": "复现步骤",
        "suggested_fix": "建议修复",
        "priority": "优先级",
        "context": "上下文",
        "project": "项目",
        "task": "任务",
        "worktree_name": "工作树名称",
        "generated_at": "生成时间",
        "finding_missing_handoff": "未找到该任务的最新 handoff Markdown。",
        "finding_stale": "记录的任务快照与当前 Git 状态不一致。",
        "finding_missing_validation": "未记录验证时间、命令、结果或备注。",
        "finding_missing_safety_rules": "未记录一等字段 safetyRules。",
        "finding_dirty_worktree": "当前 worktree 存在未提交变更。",
        "finding_missing_task": "当前分支/worktree 没有匹配的 sidecar task。",
        "prompt_handoff": "补写 handoff，包含具体 done/not-done、下一步、事实、推断、未知、验证和安全规则。",
        "prompt_validation": "运行检查后记录验证命令、结果和验证时间。",
        "prompt_safety": "记录约束下一位 agent 修改和仓库卫生的 safetyRules。",
        "prompt_stale": "信任旧 handoff 前，先核对当前 HEAD 和 dirty files。",
        "prompt_facts": "从 git status、近期 commits、PR/issue 文本或当前 thread 补录客观事实。",
        "prompt_unknowns": "明确写出未知项，不要用猜测填补缺失上下文。",
        "warning_worktree_count": "Git worktree 数量与 sidecar active task 数量不一致；project-status 不是完整 worktree 清单。",
        "warning_project_id_canonicalized": "Project id 已从 {requested} 规范化为 {canonical}。",
        "available": "可用",
        "missing": "缺失",
        "yes": "是",
        "no": "否",
        "weekly_ready": "周报已生成：{path}",
        "issue_draft_guidance": "默认只生成 draft。用户要求创建 issue 或启用 dogfood issue mode 后才允许创建。",
    },
}


TEXT["zh-CN"].update(
    {
        "action_reason_missing_task": "sidecar task 缺失",
        "action_reason_stale": "task 快照已过期",
        "action_reason_missing_handoff": "handoff 缺失",
        "action_reason_missing_validation": "validation 缺失",
        "action_reason_missing_safety": "safety rules 缺失",
        "action_reason_dirty_worktree": "worktree 存在未提交变更",
        "cleanup_reason_missing_worktree": "active sidecar task 指向不存在的 worktree",
        "hub_receipt_expected": "回执 Project Hub：taskId、status、handoffPath、nextStep、blocker、validation、risks。",
        "old_thread_backfill_prompt": (
            "你是项目 {project_id}、分支 {branch} 的旧 Primary Execution Thread。"
            "Repo/worktree: {worktree_path}。先使用 $agent-workflow-hub：在这个 worktree 运行 resume-feature 和 audit-context。"
            "如果没有 sidecar task，就用 start-feature 创建 provisional task。"
            "audit-project 报告了这些问题，请补录或刷新 sidecar 状态和 handoff：{reasons}。"
            "使用你自己的调查策略；除非必要，不要做全量扫描。"
            "按需使用 sidecar/handoff/git facts/touchedFiles/recent commits/PR/issue/targeted search 作为证据；touchedFiles 表示当前 Git dirty/touched files，只是定位线索之一。"
            "停止前更新 facts、inferences、unknowns、safety rules、validation、nextStep、blockers/risks，保存 handoff，并回执 hub。"
        ),
        "new_thread_execution_prompt": (
            "你是项目 {project_id}、分支 {branch} 的新 Primary Execution Thread。"
            "Repo/worktree: {worktree_path}。先使用 $agent-workflow-hub：如果已有 task 就运行 resume-feature，否则基于 branch/worktree 的 provisional goal 运行 start-feature。"
            "然后运行 audit-context，并做最小必要 intake，让上下文变得可信；audit-project 报告了这些问题：{reasons}。"
            "使用你自己的调查策略；除非必要，不要做全量扫描。"
            "按需使用 sidecar/handoff/git facts/touchedFiles/recent commits/PR/issue/targeted search 作为证据；touchedFiles 表示当前 Git dirty/touched files，只是定位线索之一。"
            "停止前区分 facts/inferences/unknowns，补 validation 和 safety rules，设置 nextStep 与 blocker/risks，保存 handoff，并回执 hub。"
        ),
        "stale_refresh_prompt": (
            "这个 task 看起来已过期。请在项目 {project_id}、分支 {branch}、worktree {worktree_path} 的 execution thread 中使用 $agent-workflow-hub 运行 resume-feature 和 audit-context。"
            "信任旧 handoff 前，核对当前 HEAD、dirty state、validation 和 nextStep。"
            "刷新 facts、inferences、unknowns、safety rules、validation 和 handoff，然后回执 hub。"
        ),
        "cleanup_prompt": (
            "Project Hub cleanup 请求：项目 {project_id} 的 sidecar task {task_id}（分支 {branch}）指向不存在的 worktree：{worktree_path}。"
            "请让人类确认该任务是否已 merge、废弃、移动，或仍需恢复。"
            "如果已完成，使用 $agent-workflow-hub finish-feature 或 archive；如果废弃，用清晰原因 archive。"
            "不要自动删除任何 worktree 或 repo 文件。完成后把归档/完成状态回执 hub。"
        ),
    }
)


TEXT["zh-CN"].update(
    {
        "resolver_no_match": "没有任务匹配“{query}”。请提供分支、task id 或 alias。",
        "resolver_disambiguation": "我找到了多个可能的“{query}”任务：{candidates}。你要继续哪个？",
        "resolver_project_multiple": "这个容器路径匹配到多个项目。Agent Workflow Hub 应该使用哪个项目？",
        "resolver_project_missing": "这个路径不是 Git worktree，也没有匹配到已知 Agent Workflow Hub 项目。请提供 --worktree 或 --project-id。",
    }
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_language(value: str) -> str:
    value = (value or "").strip()
    if value.lower() in {"zh", "zh-cn", "zh_cn", "cn", "chinese"}:
        return "zh-CN"
    if value.lower() in {"en", "en-us", "en_us", "english"}:
        return "en"
    return value if value in SUPPORTED_LANGUAGES else "en"


def tr(language: str, key: str, **fields: Any) -> str:
    language = normalize_language(language)
    template = TEXT.get(language, TEXT["en"]).get(key, TEXT["en"].get(key, key))
    return template.format(**fields) if fields else template


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-") or "unknown"


def short_text(value: str, max_len: int = 240) -> str:
    value = " ".join(value.split())
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def subprocess_timeout_output(exc: subprocess.TimeoutExpired) -> str:
    parts = []
    for part in [exc.stdout, exc.stderr]:
        if not part:
            continue
        if isinstance(part, bytes):
            part = part.decode("utf-8", errors="replace")
        parts.append(str(part).strip())
    return "\n".join(part for part in parts if part)


def default_weekly_period() -> str:
    iso_year, iso_week, _ = datetime.now().isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def parse_datetime_filter(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    candidate = value
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        candidate = f"{candidate}T00:00:00"
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise SystemExit(f"invalid datetime filter: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def datetime_in_range(value: str, since: datetime | None, until: datetime | None) -> bool:
    timestamp = parse_datetime_filter(value)
    if timestamp is None:
        return False
    if since and timestamp < since:
        return False
    if until and timestamp > until:
        return False
    return True


def is_pr_search_url(value: str) -> bool:
    return bool(re.search(r"/pulls(?:[/?#]|$)", value.strip(), flags=re.IGNORECASE))


def normalized_pr_fields(pr_url: Any, pr_search_url: Any = "", fallback_search_url: str = "") -> tuple[str, str]:
    pr_url_text = str(pr_url or "").strip()
    pr_search_url_text = str(pr_search_url or "").strip()
    fallback_search_url = fallback_search_url.strip()
    if is_pr_search_url(pr_url_text):
        pr_search_url_text = pr_search_url_text or pr_url_text
        pr_url_text = ""
    if not pr_search_url_text and fallback_search_url:
        pr_search_url_text = fallback_search_url
    return pr_url_text, pr_search_url_text


def normalize_task_pr_fields(task: dict[str, Any], fallback_search_url: str = "") -> None:
    pr_url, pr_search_url = normalized_pr_fields(
        task.get("prUrl", ""),
        task.get("prSearchUrl", ""),
        fallback_search_url,
    )
    task["prUrl"] = pr_url
    task["prSearchUrl"] = pr_search_url


def compact_task(task: dict[str, Any]) -> dict[str, Any]:
    pr_url, pr_search_url = normalized_pr_fields(task.get("prUrl", ""), task.get("prSearchUrl", ""))
    return {
        "taskId": task.get("taskId", ""),
        "status": task.get("status", "active"),
        "parentTaskId": task.get("parentTaskId", ""),
        "phase": task.get("phase", ""),
        "threadRole": task.get("threadRole", ""),
        "threadLabel": task.get("threadLabel", ""),
        "threadPurpose": task.get("threadPurpose", ""),
        "threads": compact_thread_entries(ensure_task_threads(task, mutate=False)),
        "routingStatus": task.get("routingStatus", ""),
        "routingConfidence": task.get("routingConfidence", None),
        "routingNeedsReview": bool(task.get("routingNeedsReview", False)),
        "routingEvidence": task.get("routingEvidence", []),
        "routingCandidates": task.get("routingCandidates", []),
        "continuePhrase": task.get("continuePhrase", ""),
        "compactReceipt": task.get("compactReceipt", ""),
        "receiptUpdatedAt": task.get("receiptUpdatedAt", ""),
        "goal": task.get("goal", ""),
        "branch": task.get("branch", ""),
        "baseBranch": task.get("baseBranch", ""),
        "worktreePath": task.get("worktreePath", ""),
        "aliases": task.get("aliases", []),
        "prUrl": pr_url,
        "prSearchUrl": pr_search_url,
        "touchedAreas": task.get("touchedAreas", []),
        "nextStep": task.get("nextStep", ""),
        "blocker": task.get("blocker", ""),
        "headSha": task.get("headSha", ""),
        "upstream": task.get("upstream", ""),
        "dirtyFiles": task.get("dirtyFiles", []),
        "dirtyFingerprint": task.get("dirtyFingerprint", ""),
        "validation": task.get("validation", {}),
        "safetyRules": task.get("safetyRules", []),
        "updatedAt": task.get("updatedAt", ""),
    }


def unique_nonempty(values: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if limit is not None and len(result) >= limit:
            break
    return result


def make_thread_id() -> str:
    return f"thr_{secrets.token_hex(5)}"


def legacy_thread_id_for_task(task: dict[str, Any]) -> str:
    seed = "|".join(
        [
            str(task.get("taskId") or ""),
            str(task.get("threadRole") or ""),
            str(task.get("threadLabel") or ""),
            str(task.get("worktreePath") or ""),
        ]
    )
    return "thr_" + hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:10]


def thread_display_label(thread: dict[str, Any]) -> str:
    return str(
        thread.get("threadDisplayLabel")
        or thread.get("threadLabel")
        or thread.get("threadRole")
        or "primary-execution"
    )


def normalize_thread_entry(
    thread: dict[str, Any],
    task: dict[str, Any],
    *,
    handoff_available: bool | None = None,
    handoff_path: str = "",
) -> dict[str, Any]:
    role = normalize_thread_role(str(thread.get("threadRole") or "")) or str(thread.get("threadRole") or "") or "primary-execution"
    worktree_path = str(thread.get("worktreePath") or "")
    return {
        "threadId": str(thread.get("threadId") or make_thread_id()),
        "codexThreadId": str(thread.get("codexThreadId") or ""),
        "threadRole": role,
        "threadLabel": short_text(str(thread.get("threadLabel") or ""), max_len=120),
        "threadDisplayLabel": short_text(
            str(thread.get("threadDisplayLabel") or thread.get("threadLabel") or role),
            max_len=120,
        ),
        "threadPurpose": short_text(str(thread.get("threadPurpose") or ""), max_len=320),
        "worktreePath": worktree_path,
        "environmentType": str(thread.get("environmentType") or ("worktree" if worktree_path else "project-level")),
        "nextStep": short_text(str(thread.get("nextStep") or task.get("nextStep") or ""), max_len=240),
        "lastSummary": short_text(str(thread.get("lastSummary") or thread.get("threadSummary") or task.get("lastThreadSummary") or ""), max_len=320),
        "continuePhrase": short_text(str(thread.get("continuePhrase") or task.get("continuePhrase") or ""), max_len=96),
        "handoffAvailable": bool(task.get("_handoffAvailable", False) if handoff_available is None else handoff_available),
        "handoffPath": handoff_path or str(thread.get("handoffPath") or task.get("_handoffPath") or ""),
        "compactReceipt": short_text(str(thread.get("compactReceipt") or task.get("compactReceipt") or ""), max_len=500),
        "updatedAt": str(thread.get("updatedAt") or task.get("updatedAt") or now_iso()),
    }


def legacy_thread_from_task(
    task: dict[str, Any],
    *,
    handoff_available: bool | None = None,
    handoff_path: str = "",
) -> dict[str, Any]:
    role = normalize_thread_role(str(task.get("threadRole") or "")) or str(task.get("threadRole") or "") or "primary-execution"
    worktree_path = str(task.get("worktreePath") or "")
    return normalize_thread_entry(
        {
            "threadId": str(task.get("threadId") or legacy_thread_id_for_task(task)),
            "threadRole": role,
            "threadLabel": task.get("threadLabel", ""),
            "threadDisplayLabel": task.get("threadDisplayLabel", "") or task.get("threadLabel", "") or role,
            "threadPurpose": task.get("threadPurpose", ""),
            "worktreePath": worktree_path,
            "environmentType": "worktree" if worktree_path else "project-level",
            "nextStep": task.get("nextStep", ""),
            "lastSummary": task.get("lastThreadSummary", ""),
            "continuePhrase": task.get("continuePhrase", ""),
            "compactReceipt": task.get("compactReceipt", ""),
            "updatedAt": task.get("updatedAt", ""),
        },
        task,
        handoff_available=handoff_available,
        handoff_path=handoff_path,
    )


def ensure_task_threads(
    task: dict[str, Any],
    *,
    mutate: bool = False,
    handoff_available: bool | None = None,
    handoff_path: str = "",
) -> list[dict[str, Any]]:
    raw_threads = task.get("threads")
    threads: list[dict[str, Any]] = []
    if isinstance(raw_threads, list):
        for item in raw_threads:
            if isinstance(item, dict):
                threads.append(normalize_thread_entry(item, task, handoff_available=handoff_available, handoff_path=handoff_path))
    if not threads:
        threads = [legacy_thread_from_task(task, handoff_available=handoff_available, handoff_path=handoff_path)]
    if mutate:
        task["threads"] = threads
    return threads


def compact_thread_entries(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for thread in threads:
        compact.append(
            {
                "threadId": thread.get("threadId", ""),
                "threadRole": thread.get("threadRole", ""),
                "threadLabel": thread.get("threadLabel", ""),
                "threadDisplayLabel": thread_display_label(thread),
                "threadPurpose": thread.get("threadPurpose", ""),
                "worktreePath": thread.get("worktreePath", ""),
                "environmentType": thread.get("environmentType", ""),
                "nextStep": thread.get("nextStep", ""),
                "lastSummary": thread.get("lastSummary", ""),
                "handoffAvailable": bool(thread.get("handoffAvailable", False)),
                "updatedAt": thread.get("updatedAt", ""),
            }
        )
    return compact


def upsert_current_thread(
    task: dict[str, Any],
    args: argparse.Namespace,
    *,
    handoff_available: bool | None = None,
    handoff_path: str = "",
    compact_receipt: str = "",
    continue_phrase: str = "",
) -> dict[str, Any]:
    threads = ensure_task_threads(task, mutate=True, handoff_available=handoff_available, handoff_path=handoff_path)
    requested_id = str(getattr(args, "thread_id", "") or "").strip()
    role = normalize_thread_role(getattr(args, "thread_role", None)) or str(task.get("threadRole") or "primary-execution")
    label_value = getattr(args, "thread_label", None) if getattr(args, "thread_label", None) is not None else task.get("threadLabel", "")
    purpose_value = getattr(args, "thread_purpose", None) if getattr(args, "thread_purpose", None) is not None else task.get("threadPurpose", "")
    label = short_text(str(label_value or ""), max_len=120)
    purpose = short_text(str(purpose_value or ""), max_len=320)
    worktree_path = "" if getattr(args, "project_level_orientation", False) else str(task.get("worktreePath") or "")

    selected: dict[str, Any] | None = None
    if requested_id:
        selected = next((thread for thread in threads if str(thread.get("threadId") or "") == requested_id), None)
    if selected is None:
        matches = [
            thread
            for thread in threads
            if str(thread.get("threadRole") or "") == role
            and str(thread.get("threadLabel") or "") == label
            and str(thread.get("worktreePath") or "") == worktree_path
        ]
        if len(matches) == 1:
            selected = matches[0]
    if selected is None:
        selected = {"threadId": requested_id or make_thread_id()}
        threads.append(selected)

    selected.update(
        {
            "threadRole": role,
            "threadLabel": label,
            "threadDisplayLabel": label or role,
            "threadPurpose": purpose,
            "worktreePath": worktree_path,
            "environmentType": "worktree" if worktree_path else "project-level",
            "nextStep": short_text(str(task.get("nextStep") or ""), max_len=240),
            "lastSummary": short_text(str(getattr(args, "thread_summary", None) or task.get("lastThreadSummary") or ""), max_len=320),
            "continuePhrase": short_text(continue_phrase or str(task.get("continuePhrase") or ""), max_len=96),
            "handoffAvailable": bool(task.get("_handoffAvailable", False) if handoff_available is None else handoff_available),
            "handoffPath": handoff_path or str(task.get("_handoffPath") or selected.get("handoffPath") or ""),
            "compactReceipt": short_text(compact_receipt or str(task.get("compactReceipt") or ""), max_len=500),
            "updatedAt": now_iso(),
        }
    )
    task["threads"] = [
        normalize_thread_entry(thread, task, handoff_available=thread.get("handoffAvailable", False), handoff_path=str(thread.get("handoffPath") or ""))
        for thread in threads
    ]
    return normalize_thread_entry(selected, task, handoff_available=selected.get("handoffAvailable", False), handoff_path=str(selected.get("handoffPath") or ""))


def bool_label(value: bool) -> str:
    return "yes" if value else "no"


def normalized_dedupe_key(value: str) -> str:
    return " ".join(value.casefold().split())


def humanize_identifier(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return re.sub(r"[-_]+", " ", value).strip()


def continue_prefix(language: str) -> str:
    return "继续" if normalize_language(language) == "zh-CN" else "continue"


def strip_continue_prefix(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    lowered = value.casefold()
    for prefix in ["继续", "continue", "resume"]:
        prefix_lower = prefix.casefold()
        if lowered == prefix_lower:
            return ""
        if lowered.startswith(prefix_lower + " "):
            return value[len(prefix):].strip()
    return value


def is_suitable_continue_phrase(value: str) -> bool:
    value = " ".join((value or "").split())
    return bool(3 <= len(value) <= 96)


def generate_continue_phrase(task: dict[str, Any], language: str, explicit: str = "") -> str:
    explicit = " ".join((explicit or "").split())
    if explicit:
        return short_text(explicit, max_len=96)
    existing = " ".join(str(task.get("continuePhrase") or "").split())
    if is_suitable_continue_phrase(existing):
        return short_text(existing, max_len=96)
    name = ""
    for alias in task.get("aliases") or []:
        alias_text = str(alias).strip()
        if 2 <= len(alias_text) <= 72:
            name = alias_text
            break
    if not name:
        name = str(task.get("threadLabel") or "").strip()
    if not name:
        name = humanize_identifier(str(task.get("taskId") or ""))
    name = strip_continue_prefix(name)
    if not name:
        name = str(task.get("taskId") or "this task")
    return short_text(f"{continue_prefix(language)} {name}".strip(), max_len=96)


def compact_receipt_lines(task: dict[str, Any], args: argparse.Namespace, continue_phrase: str, handoff_path: Path, language: str) -> list[str]:
    name = task.get("threadLabel") or task.get("goal") or humanize_identifier(task.get("taskId", "")) or task.get("taskId", "")
    summary = (
        getattr(args, "thread_summary", None)
        or next((item for item in (getattr(args, "done", None) or []) if item and item.strip()), "")
        or task.get("lastThreadSummary")
        or task.get("goal")
        or ""
    )
    if not summary:
        summary = "工作流状态已保存。" if normalize_language(language) == "zh-CN" else "Workflow state saved."
    risks = [item.strip() for item in (getattr(args, "risks", None) or []) if item and item.strip()]
    blocker = str(task.get("blocker") or "").strip()
    lines = [f"{'已保存' if normalize_language(language) == 'zh-CN' else 'Saved'}: {short_text(str(name), max_len=120)}"]
    if summary:
        lines.append(short_text(str(summary), max_len=160))
    if task.get("nextStep"):
        label = "下一步" if normalize_language(language) == "zh-CN" else "Next"
        lines.append(f"{label}: {short_text(str(task.get('nextStep')), max_len=160)}")
    if blocker or risks:
        label = "风险/阻塞" if normalize_language(language) == "zh-CN" else "Risks/blockers"
        risk_text = blocker or risks[0]
        lines.append(f"{label}: {short_text(risk_text, max_len=160)}")
    next_label = "下次可以直接说" if normalize_language(language) == "zh-CN" else "Next time say"
    lines.append(f"{next_label}: {continue_phrase}")
    return lines[:5]


def build_compact_receipt(task: dict[str, Any], args: argparse.Namespace, continue_phrase: str, handoff_path: Path, language: str) -> str:
    return "\n".join(compact_receipt_lines(task, args, continue_phrase, handoff_path, language))


def build_user_facing_receipt(task: dict[str, Any], args: argparse.Namespace, continue_phrase: str, compact_receipt: str) -> dict[str, Any]:
    risks = [item.strip() for item in (getattr(args, "risks", None) or []) if item and item.strip()]
    return {
        "title": task.get("threadLabel") or task.get("goal") or humanize_identifier(task.get("taskId", "")) or task.get("taskId", ""),
        "summary": getattr(args, "thread_summary", None) or task.get("lastThreadSummary") or task.get("goal", ""),
        "nextStep": task.get("nextStep", ""),
        "risks": risks,
        "blocker": task.get("blocker", ""),
        "continuePhrase": continue_phrase,
        "compactReceipt": compact_receipt,
    }


def unique_normalized_nonempty(values: list[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        original = value.strip()
        key = normalized_dedupe_key(original)
        if not original or not key or key in seen:
            continue
        seen.add(key)
        result.append(original)
        if limit is not None and len(result) >= limit:
            break
    return result


def add_unique_path(values: list[Any], path: Path | str | None, *, limit: int | None = None) -> list[str]:
    result = [str(item).strip() for item in values if str(item).strip()]
    if path:
        with contextlib.suppress(OSError):
            candidate = str(Path(path).resolve())
            result.append(candidate)
    return unique_normalized_nonempty(result, limit=limit)


def normalized_note_list(values: list[str] | None, limit: int | None = None, max_len: int = 240) -> list[str]:
    return unique_normalized_nonempty([short_text(item, max_len=max_len) for item in (values or [])], limit=limit)


def normalize_optional_slug(value: str | None) -> str:
    return slugify(value) if value and value.strip() else ""


def normalize_phase(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    normalized = slugify(value)
    return normalized if normalized in VALID_PHASES else normalized


def normalize_thread_role(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    normalized = slugify(value)
    aliases = {
        "project-hub": "hub",
        "projecthub": "hub",
        "hub-thread": "hub",
        "primary": "primary-execution",
        "execution": "primary-execution",
        "primary-execution-thread": "primary-execution",
        "research-planning": "research",
        "research-strategy": "research",
        "paper-strategy": "research",
        "paper-planning": "research",
        "academic-research": "research",
        "research-discussion": "research",
        "dogfood-qa": "dogfood",
        "qa-thread": "dogfood",
        "dogfood-thread": "dogfood",
        "validator": "validation",
        "validation-thread": "validation",
        "review-thread": "review",
        "explainer-thread": "explainer",
        "qa": "validation",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in VALID_THREAD_ROLES else normalized


def normalize_routing_status(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    normalized = slugify(value)
    return normalized if normalized in VALID_ROUTING_STATUSES else normalized


def task_update_text_for_route_hints(args: argparse.Namespace) -> str:
    parts: list[str] = []
    scalar_names = [
        "task_id",
        "goal",
        "next_step",
        "blocker",
        "thread_summary",
        "current_objective",
        "notes",
        "thread_label",
        "thread_purpose",
        "parent_task_id",
    ]
    list_names = [
        "aliases",
        "touched_areas",
        "facts",
        "inferences",
        "unknowns",
        "safety_rules",
        "validation_commands",
        "validation_results",
        "done",
        "not_done",
        "risks",
        "key_files",
        "routing_evidence",
    ]
    for name in scalar_names:
        value = getattr(args, name, None)
        if value:
            parts.append(str(value))
    for name in list_names:
        for value in getattr(args, name, None) or []:
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def extract_branch_hints(text: str) -> list[str]:
    hints = re.findall(r"\bcodex/[A-Za-z0-9._/-]+", text or "")
    hints.extend(re.findall(r"\b(?:branch|Branch)\s*:\s*([A-Za-z0-9._/-]+)", text or ""))
    return unique_normalized_nonempty([item.strip(".,);]\"'") for item in hints], limit=12)


def extract_abs_path_hints(text: str) -> list[str]:
    pattern = r"(?:(?:/[A-Za-z0-9._@%+=:,~-]+)+|[A-Za-z]:\\[^\s,;)\]]+)"
    return unique_normalized_nonempty([item.strip(".,);]\"'") for item in re.findall(pattern, text or "")], limit=20)


def resolved_path_text(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve())
    except (OSError, RuntimeError):
        return value


def task_route_candidate(task: dict[str, Any], reason: str) -> dict[str, str]:
    return {
        "taskId": str(task.get("taskId") or ""),
        "branch": str(task.get("branch") or ""),
        "worktreePath": str(task.get("worktreePath") or ""),
        "reason": reason,
    }


def route_result(status: str, **fields: Any) -> dict[str, Any]:
    return {"routeStatus": status, "routingStatus": status, **fields}


def route_guard_for_write(manager: "SidecarManager", payload: dict[str, Any], args: argparse.Namespace, action: str) -> dict[str, Any]:
    if getattr(args, "confirm_route", False):
        return route_result("confirmed", routingNeedsReview=False, routingEvidence=["route explicitly confirmed by --confirm-route"])

    text = task_update_text_for_route_hints(args)
    if not text.strip():
        return route_result("confirmed", routingNeedsReview=False, routingEvidence=["no explicit route hints provided"])

    tasks = payload.get("tasks", [])
    branch_hints = extract_branch_hints(text)
    raw_path_hints = extract_abs_path_hints(text)
    task_id_hint = normalize_optional_slug(getattr(args, "task_id", None))
    current_branch = manager.git.branch
    current_worktree = str(manager.git.worktree_path)
    current_worktree_resolved = resolved_path_text(current_worktree)

    candidates: list[dict[str, str]] = []
    evidence: list[str] = []
    for branch in branch_hints:
        evidence.append(f"text mentions branch {branch}")
        candidates.extend(
            task_route_candidate(task, f"branch hint {branch}")
            for task in tasks
            if str(task.get("branch") or "") == branch
        )
    route_path_hints: list[str] = []
    for hinted_path in raw_path_hints:
        hinted_resolved = resolved_path_text(hinted_path)
        matches_known_task = False
        for task in tasks:
            task_path = str(task.get("worktreePath") or "")
            if task_path and resolved_path_text(task_path) == hinted_resolved:
                candidates.append(task_route_candidate(task, f"worktree path hint {hinted_path}"))
                matches_known_task = True
        likely_route_path = matches_known_task or "worktree" in hinted_path.casefold() or "projects" in hinted_path.casefold()
        if likely_route_path:
            route_path_hints.append(hinted_path)
            evidence.append(f"text mentions worktree path {hinted_path}")
    if task_id_hint:
        for task in tasks:
            if str(task.get("taskId") or "") == task_id_hint:
                candidates.append(task_route_candidate(task, f"task id hint {task_id_hint}"))
                evidence.append(f"argument task id matches {task_id_hint}")

    candidates = list({json.dumps(candidate, sort_keys=True): candidate for candidate in candidates}.values())
    hinted_branches = {item for item in branch_hints if item}
    hinted_paths = {resolved_path_text(item) for item in route_path_hints if item}
    branch_conflict = bool(hinted_branches and current_branch not in hinted_branches)
    path_conflict = bool(
        hinted_paths
        and not any(
            current_worktree_resolved == hinted_path
            or hinted_path.startswith(f"{current_worktree_resolved}{os.sep}")
            or current_worktree_resolved.startswith(f"{hinted_path}{os.sep}")
            for hinted_path in hinted_paths
        )
    )
    if not candidates and not branch_conflict and not path_conflict:
        return route_result("confirmed", routingNeedsReview=False, routingEvidence=evidence or ["route hints match current context"])

    current = {"branch": current_branch, "worktreePath": current_worktree}
    hinted = {"branches": sorted(hinted_branches), "worktreePaths": sorted(hinted_paths)}
    explicit_task_match = bool(task_id_hint and candidates)
    if (branch_conflict or path_conflict) and explicit_task_match:
        return route_result("inferred", **{
            "routeMismatch": True,
            "routingNeedsReview": True,
            "routingConfidence": 0.82,
            "current": current,
            "hinted": hinted,
            "routingEvidence": unique_normalized_nonempty(
                [
                    f"current branch is {current_branch}",
                    f"current worktree is {current_worktree}",
                    "explicit --task-id matched an existing sidecar task",
                    *evidence,
                ],
                limit=20,
            ),
            "routingCandidates": candidates[:5],
        })

    if branch_conflict or path_conflict:
        return route_result("mismatch", **{
            "routeMismatch": True,
            "routingNeedsReview": True,
            "routingConfidence": 0.45,
            "current": current,
            "hinted": hinted,
            "routingEvidence": unique_normalized_nonempty(
                [
                    f"current branch is {current_branch}",
                    f"current worktree is {current_worktree}",
                    *evidence,
                ],
                limit=20,
            ),
            "routingCandidates": candidates[:5],
            "recommendation": f"Use the hinted worktree/task or rerun {action} with --confirm-route if the current route is intentional.",
            "repoMutated": False,
        })

    if len(candidates) > 1:
        return route_result("ambiguous", **{
            "routeMismatch": False,
            "routingNeedsReview": True,
            "routingConfidence": 0.55,
            "current": current,
            "hinted": hinted,
            "routingEvidence": evidence,
            "routingCandidates": candidates[:5],
            "recommendation": f"Multiple route candidates matched; rerun {action} with a specific --task-id/--worktree or --confirm-route.",
            "repoMutated": False,
        })

    return route_result("inferred", **{
        "routingNeedsReview": True,
        "routingConfidence": 0.78,
        "routingEvidence": evidence,
        "routingCandidates": candidates[:1],
    })


def task_id_exists(payload: dict[str, Any], task_id: str) -> bool:
    return any(str(task.get("taskId") or "") == task_id for task in payload.get("tasks", []))


def parent_would_cycle(payload: dict[str, Any], task_id: str, parent_task_id: str) -> bool:
    if not task_id or not parent_task_id:
        return False
    if task_id == parent_task_id:
        return True
    by_id = {str(task.get("taskId") or ""): task for task in payload.get("tasks", [])}
    seen: set[str] = set()
    current = parent_task_id
    while current:
        if current == task_id:
            return True
        if current in seen:
            return True
        seen.add(current)
        current = str((by_id.get(current) or {}).get("parentTaskId") or "")
    return False


def apply_route_metadata(task: dict[str, Any], route: dict[str, Any]) -> None:
    if not route:
        return
    status = normalize_routing_status(str(route.get("routeStatus") or route.get("routingStatus") or ""))
    if status:
        task["routingStatus"] = status
    if route.get("routingConfidence") is not None:
        with contextlib.suppress(TypeError, ValueError):
            task["routingConfidence"] = round(float(route.get("routingConfidence")), 3)
    if route.get("routingNeedsReview") is not None:
        task["routingNeedsReview"] = bool(route.get("routingNeedsReview"))
    evidence = normalized_note_list(route.get("routingEvidence") or [], limit=20, max_len=240)
    if evidence:
        task["routingEvidence"] = unique_normalized_nonempty([*task.get("routingEvidence", []), *evidence], limit=30)
    candidates = route.get("routingCandidates")
    if candidates:
        task["routingCandidates"] = candidates[:5]


def route_allows_git_snapshot_refresh(manager: "SidecarManager", task: dict[str, Any], args: argparse.Namespace, route: dict[str, Any] | None) -> bool:
    if getattr(args, "project_level_orientation", False):
        return False
    if task.get("_isNewTask"):
        return True
    current_path = resolved_path_text(str(manager.git.worktree_path))
    task_path = str(task.get("worktreePath") or "")
    if task_path and resolved_path_text(task_path) != current_path:
        return False
    current_branch = str(manager.git.branch or "")
    task_branch = str(task.get("branch") or "")
    if task_branch and current_branch and task_branch != current_branch:
        return False
    if route and route.get("routeStatus") in {"inferred", "mismatch", "ambiguous"} and getattr(args, "task_id", None):
        return False
    return True


def build_validation_record(args: argparse.Namespace, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    validation = dict(existing or {})
    commands = list(validation.get("commands") or [])
    results = list(validation.get("results") or [])
    for command in getattr(args, "validation_commands", None) or []:
        command = command.strip()
        if command:
            commands.append({"command": short_text(command, max_len=320), "recordedAt": now_iso()})
    for result in getattr(args, "validation_results", None) or []:
        result = result.strip()
        if result:
            results.append({"result": short_text(result, max_len=320), "recordedAt": now_iso()})
    if getattr(args, "validation_tests", None):
        commands.append({"command": short_text(args.validation_tests, max_len=320), "kind": "tests", "recordedAt": now_iso()})
    if getattr(args, "validation_manual", None):
        results.append({"result": short_text(args.validation_manual, max_len=320), "kind": "manual", "recordedAt": now_iso()})
    if getattr(args, "validation_notes", None):
        validation["notes"] = short_text(args.validation_notes, max_len=500)
    if commands:
        validation["commands"] = commands
    if results:
        validation["results"] = results
    if getattr(args, "validation_at", None):
        validation["validatedAt"] = args.validation_at
    elif commands or results or validation.get("notes"):
        validation.setdefault("validatedAt", now_iso())
    validation.setdefault("commands", [])
    validation.setdefault("results", [])
    validation.setdefault("notes", "")
    validation.setdefault("validatedAt", "")
    return validation


def stale_detection(task: dict[str, Any], git: GitContext) -> dict[str, Any]:
    reasons: list[str] = []
    saved_head = task.get("headSha") or ""
    saved_dirty = task.get("dirtyFingerprint") or ""
    if saved_head and git.head_sha and saved_head != git.head_sha:
        reasons.append("HEAD changed since last recorded handoff/task snapshot")
    if saved_dirty != git.dirty_fingerprint:
        reasons.append("dirty files changed since last recorded handoff/task snapshot")
    return {
        "isStale": bool(reasons),
        "reasons": reasons,
        "recordedHeadSha": saved_head,
        "currentHeadSha": git.head_sha,
        "recordedDirtyFingerprint": saved_dirty,
        "currentDirtyFingerprint": git.dirty_fingerprint,
    }


def safe_filename_label(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip(".-_")
    return value or fallback


def suspicious_cli_output(value: str) -> bool:
    return bool(re.search(r"(Traceback|TypeError|Exception|stack trace)", value or "", flags=re.IGNORECASE))


def find_git_executable() -> str | None:
    env_override = os.environ.get("CODEX_GIT_EXE")
    if env_override and Path(env_override).exists():
        return env_override

    detected = shutil.which("git")
    if detected:
        return detected

    candidates = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        r"C:\Users\Administrator\AppData\Local\Programs\Git\cmd\git.exe",
        r"C:\Users\Administrator\AppData\Local\Programs\Git\bin\git.exe",
        r"D:\install\Git\cmd\git.exe",
        r"D:\install\Git\bin\git.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    git_executable = find_git_executable()
    if not git_executable:
        return 127, "", "git executable not found"
    try:
        proc = subprocess.run(
            [git_executable, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return 127, "", "git executable not found"
    except OSError as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def run_git_bytes(args: list[str], cwd: Path) -> tuple[int, bytes, bytes]:
    git_executable = find_git_executable()
    if not git_executable:
        return 127, b"", b"git executable not found"
    try:
        proc = subprocess.run(
            [git_executable, *args],
            cwd=str(cwd),
            capture_output=True,
        )
    except FileNotFoundError:
        return 127, b"", b"git executable not found"
    except OSError as exc:
        return 1, b"", str(exc).encode("utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


def detect_git_repo(worktree: Path) -> tuple[bool, str]:
    rc, repo_root, _ = run_git(["rev-parse", "--show-toplevel"], worktree)
    if rc != 0 or not repo_root:
        return False, ""
    return True, str(Path(repo_root).resolve())


def parse_git_status_porcelain_z(repo_root: Path) -> tuple[list[str], list[str]]:
    rc, stdout, _ = run_git_bytes(["status", "--porcelain=v1", "-z"], repo_root)
    if rc != 0 or not stdout:
        return [], []

    records = [item.decode("utf-8", errors="replace") for item in stdout.split(b"\0") if item]
    summary: list[str] = []
    touched: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        status = record[:2] if len(record) >= 2 else record
        prefix = f"{status} "
        path = record.removeprefix(prefix).lstrip()
        if status.startswith(("R", "C")) and index + 1 < len(records):
            old_path = records[index + 1]
            summary.append(f"{status} {old_path} -> {path}")
            touched.extend([old_path, path])
            index += 2
            continue
        summary.append(f"{status} {path}".rstrip())
        if path:
            touched.append(path)
        index += 1

    return summary, unique_nonempty(touched)


def parse_git_worktree_list(repo_root: Path) -> tuple[list[dict[str, str]], str]:
    rc, stdout, stderr = run_git(["worktree", "list", "--porcelain"], repo_root)
    if rc != 0:
        return [], stderr or stdout or "git worktree list failed"

    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.removeprefix("worktree ").strip()}
        elif line.startswith("HEAD "):
            current["headSha"] = line.removeprefix("HEAD ").strip()
        elif line.startswith("branch "):
            ref = line.removeprefix("branch ").strip()
            current["branch"] = ref.removeprefix("refs/heads/")
        elif line == "bare":
            current["bare"] = "true"
        elif line == "detached":
            current["detached"] = "true"
        elif line == "prunable":
            current["prunable"] = "true"
    if current:
        worktrees.append(current)
    return worktrees, ""


def fingerprint_dirty_files(status_lines: list[str]) -> str:
    if not status_lines:
        return ""
    payload = "\0".join(sorted(status_lines)).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def lock_path_for(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


@contextlib.contextmanager
def file_lock(path: Path):
    lock_path = lock_path_for(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + FILE_LOCK_TIMEOUT_SECONDS
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out acquiring sidecar lock: {lock_path}")
            time.sleep(FILE_LOCK_POLL_SECONDS)
    try:
        os.write(fd, f"{os.getpid()} {now_iso()}\n".encode("utf-8"))
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temp_path, path)


def read_json(path: Path, default: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(JSON_READ_RETRIES):
        if not path.exists():
            return default
        try:
            raw = path.read_text(encoding="utf-8-sig")
            if not raw.strip():
                raise json.JSONDecodeError("empty JSON file", raw, 0)
            return json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < JSON_READ_RETRIES - 1:
                time.sleep(JSON_READ_RETRY_SECONDS * (attempt + 1))
                continue
            return default
    return default


def write_json(path: Path, payload: Any) -> None:
    with file_lock(path):
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


@dataclass
class GitContext:
    repo_root: Path
    is_git_worktree: bool
    branch: str
    base_branch: str
    worktree_path: Path
    common_dir: Path | None
    remote_url: str
    head_sha: str
    upstream: str
    recent_commits: list[str]
    touched_files: list[str]
    git_status_summary: list[str]
    dirty_files: list[str]
    dirty_fingerprint: str
    pr_url: str
    pr_search_url: str


class SidecarManager:
    def __init__(self, worktree: Path, project_id_override: str = "", base_branch_override: str = ""):
        self.worktree = worktree.resolve()
        self.git = self._detect_git_context()
        self.project_id_source = ""
        self.base_branch_override = (base_branch_override or "").strip()
        self.project_id = self._resolve_project_id(project_id_override)
        if self.base_branch_override:
            self.git.base_branch = self.base_branch_override
        self.sidecar_root = Path.home() / ".codex" / "projects" / self.project_id
        self.active_tasks_path = self.sidecar_root / "active-tasks.json"
        self.project_state_path = self.sidecar_root / "project-state.json"
        self.config_path = self.sidecar_root / "config.json"
        self.handoffs_dir = self.sidecar_root / "handoffs"
        self.archive_dir = self.sidecar_root / "archive"
        self.reports_dir = self.sidecar_root / "reports"
        self.events_path = self.sidecar_root / "events.jsonl"

    def _resolve_project_id(self, project_id_override: str = "") -> str:
        explicit = (project_id_override or "").strip()
        if explicit:
            self.project_id_source = "cli"
            return slugify(explicit)

        env_project_id = os.environ.get("CONTEXT_HANDOFF_PROJECT_ID", "").strip()
        if env_project_id:
            self.project_id_source = "env"
            return slugify(env_project_id)

        sidecar_config_project_id = self._sidecar_config_project_id()
        if sidecar_config_project_id:
            self.project_id_source = "sidecar-config"
            return slugify(sidecar_config_project_id)

        remote_or_common = self._project_id_from_remote_or_common_dir()
        if remote_or_common:
            self.project_id_source = "git-remote-common-dir"
            return remote_or_common

        self.project_id_source = "repo-root"
        return slugify(self.git.repo_root.name)

    def _sidecar_config_project_id(self) -> str:
        projects_root = Path.home() / ".codex" / "projects"
        if not projects_root.exists():
            return ""
        current_common_dir = str(self.git.common_dir or "")
        current_repo_root = str(self.git.repo_root)
        current_remote = self.git.remote_url.strip()
        for path in projects_root.glob("*/config.json"):
            if not path.exists():
                continue
            try:
                payload = read_json(path, {})
            except (OSError, json.JSONDecodeError):
                continue
            project_id = str(payload.get("projectId") or path.parent.name).strip()
            if not project_id:
                continue
            if current_remote and payload.get("remoteUrl") == current_remote:
                return project_id
            if current_common_dir and payload.get("gitCommonDir") == current_common_dir:
                return project_id
            if payload.get("canonicalRepoRoot") == current_repo_root:
                return project_id
            if payload.get("repoRoot") == current_repo_root:
                return project_id
        return ""

    def _project_id_from_remote_or_common_dir(self) -> str:
        remote_url = self.git.remote_url.strip()
        if remote_url:
            normalized = remote_url
            if normalized.startswith("git@github.com:"):
                normalized = normalized.replace("git@github.com:", "https://github.com/")
            if normalized.endswith(".git"):
                normalized = normalized[:-4]
            match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/#?]+)", normalized)
            if match:
                return slugify(f"{match.group('owner')}-{match.group('repo')}")
            return slugify(normalized)

        if self.git.common_dir:
            common_dir = self.git.common_dir
            name = common_dir.parent.name if common_dir.name == ".git" else common_dir.name
            return slugify(name)
        return ""

    def _detect_git_context(self) -> GitContext:
        rc, repo_root, _ = run_git(["rev-parse", "--show-toplevel"], self.worktree)
        is_git_worktree = bool(rc == 0 and repo_root)
        if rc != 0 or not repo_root:
            repo_root = str(self.worktree)
        repo_root_path = Path(repo_root).resolve()

        common_dir_path: Path | None = None
        rc, common_dir, _ = run_git(["rev-parse", "--git-common-dir"], repo_root_path)
        if rc == 0 and common_dir:
            common_dir_path = (repo_root_path / common_dir).resolve() if not Path(common_dir).is_absolute() else Path(common_dir).resolve()

        rc, branch, _ = run_git(["branch", "--show-current"], repo_root_path)
        if rc != 0 or not branch:
            branch = "unknown"

        base_branch = self._remote_default_branch(repo_root_path, "origin")
        if not base_branch:
            base_branch = self._current_upstream_branch(repo_root_path)
        if not base_branch:
            rc, upstream_remote, _ = run_git(["config", f"branch.{branch}.remote"], repo_root_path)
            if rc == 0 and upstream_remote and upstream_remote != "origin":
                base_branch = self._remote_default_branch(repo_root_path, upstream_remote)
        base_branch = base_branch or "main"

        rc, head_sha, _ = run_git(["rev-parse", "HEAD"], repo_root_path)
        if rc != 0:
            head_sha = ""

        upstream = self._current_upstream_full(repo_root_path)

        rc, recent_commits_raw, _ = run_git(
            ["log", "--oneline", "-5"],
            repo_root_path,
        )
        recent_commits = [line for line in recent_commits_raw.splitlines() if line] if rc == 0 else []

        status_lines, touched_files = parse_git_status_porcelain_z(repo_root_path)
        dirty_files = touched_files
        dirty_fingerprint = fingerprint_dirty_files(status_lines)
        pr_search_url = ""
        rc, remote_url, _ = run_git(["remote", "get-url", "origin"], repo_root_path)
        if rc != 0:
            remote_url = ""
        if rc == 0 and remote_url:
            pr_search_url = self._guess_pr_search_url(remote_url, branch)

        return GitContext(
            repo_root=repo_root_path,
            is_git_worktree=is_git_worktree,
            branch=branch,
            base_branch=base_branch,
            worktree_path=self.worktree,
            common_dir=common_dir_path,
            remote_url=remote_url,
            head_sha=head_sha,
            upstream=upstream,
            recent_commits=recent_commits,
            touched_files=touched_files,
            git_status_summary=status_lines,
            dirty_files=dirty_files,
            dirty_fingerprint=dirty_fingerprint,
            pr_url="",
            pr_search_url=pr_search_url,
        )

    def _remote_default_branch(self, repo_root_path: Path, remote: str) -> str:
        rc, remote_head, _ = run_git(["symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD"], repo_root_path)
        if rc != 0 or not remote_head:
            return ""
        prefix = f"{remote}/"
        return remote_head[len(prefix) :] if remote_head.startswith(prefix) else remote_head

    def _current_upstream_branch(self, repo_root_path: Path) -> str:
        rc, upstream, _ = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], repo_root_path)
        if rc != 0 or not upstream:
            return ""
        return upstream.split("/", 1)[1] if "/" in upstream else upstream

    def _current_upstream_full(self, repo_root_path: Path) -> str:
        rc, upstream, _ = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], repo_root_path)
        return upstream if rc == 0 else ""

    def _guess_pr_search_url(self, remote_url: str, branch: str) -> str:
        normalized = remote_url.strip()
        if normalized.startswith("git@github.com:"):
            normalized = normalized.replace("git@github.com:", "https://github.com/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        if normalized.startswith("https://github.com/") and branch and branch != "unknown":
            return f"{normalized}/pulls?q=is%3Apr+head%3A{branch}"
        return ""

    def ensure_layout(self) -> None:
        self.sidecar_root.mkdir(parents=True, exist_ok=True)
        self.handoffs_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            write_json(
                self.config_path,
                {
                    "version": SIDECAR_VERSION,
                    "projectId": self.project_id,
                    "projectIdSource": self.project_id_source,
                    "baseBranch": self.base_branch_override or self.git.base_branch,
                    "canonicalRepoRoot": str(self.git.repo_root),
                    "repoRoot": str(self.git.repo_root),
                    "gitCommonDir": str(self.git.common_dir) if self.git.common_dir else "",
                    "remoteUrl": self.git.remote_url,
                    "lastWorktreePath": str(self.git.worktree_path),
                    "currentWorktreePath": str(self.git.worktree_path),
                    "knownWorktreeRoots": [str(self.git.worktree_path)],
                    "projectContainerRoots": [str(self.git.repo_root.parent)],
                    "updatedAt": now_iso(),
                },
            )
        if not self.active_tasks_path.exists():
            write_json(
                self.active_tasks_path,
                {"version": SIDECAR_VERSION, "projectId": self.project_id, "tasks": []},
            )

    def sidecar_config(self) -> dict[str, Any]:
        self.ensure_layout()
        config = read_json(self.config_path, {})
        before = json.dumps(config, ensure_ascii=False, sort_keys=True)
        config.setdefault("version", SIDECAR_VERSION)
        config.setdefault("projectId", self.project_id)
        config.setdefault("canonicalRepoRoot", config.get("repoRoot") or str(self.git.repo_root))
        config.setdefault("repoRoot", config["canonicalRepoRoot"])
        config["preferredLanguage"] = normalize_language(config.get("preferredLanguage") or "en")
        config["knownWorktreeRoots"] = add_unique_path(config.get("knownWorktreeRoots") or [], self.git.worktree_path)
        config["projectContainerRoots"] = add_unique_path(config.get("projectContainerRoots") or [], self.git.repo_root.parent)
        config["lastWorktreePath"] = str(self.git.worktree_path)
        config["currentWorktreePath"] = str(self.git.worktree_path)
        if self.base_branch_override:
            config["baseBranch"] = self.base_branch_override
            self.git.base_branch = self.base_branch_override
        elif config.get("baseBranch"):
            self.git.base_branch = config["baseBranch"]
        after = json.dumps(config, ensure_ascii=False, sort_keys=True)
        if after != before:
            write_json(self.config_path, {**config, "updatedAt": now_iso()})
        return config

    def save_sidecar_config(self, **updates: Any) -> None:
        config = self.sidecar_config()
        config.update({key: value for key, value in updates.items() if value is not None})
        config["version"] = SIDECAR_VERSION
        config["projectId"] = self.project_id
        config.setdefault("canonicalRepoRoot", config.get("repoRoot") or str(self.git.repo_root))
        config.setdefault("repoRoot", config["canonicalRepoRoot"])
        if "preferredLanguage" in config:
            config["preferredLanguage"] = normalize_language(config.get("preferredLanguage") or "en")
        config["knownWorktreeRoots"] = add_unique_path(config.get("knownWorktreeRoots") or [], self.git.worktree_path)
        config["projectContainerRoots"] = add_unique_path(config.get("projectContainerRoots") or [], self.git.repo_root.parent)
        config["gitCommonDir"] = str(self.git.common_dir) if self.git.common_dir else ""
        config["remoteUrl"] = self.git.remote_url
        config["lastWorktreePath"] = str(self.git.worktree_path)
        config["currentWorktreePath"] = str(self.git.worktree_path)
        config["updatedAt"] = now_iso()
        write_json(self.config_path, config)

    def load_active_tasks(self) -> dict[str, Any]:
        self.ensure_layout()
        payload = read_json(
            self.active_tasks_path,
            {"version": SIDECAR_VERSION, "projectId": self.project_id, "tasks": []},
        )
        payload.setdefault("version", SIDECAR_VERSION)
        payload.setdefault("projectId", self.project_id)
        payload.setdefault("tasks", [])
        config = self.sidecar_config()
        if self.base_branch_override:
            self.save_sidecar_config(baseBranch=self.base_branch_override)
            self.git.base_branch = self.base_branch_override
        elif config.get("baseBranch"):
            self.git.base_branch = str(config["baseBranch"])
        for task in payload.get("tasks", []):
            normalize_task_pr_fields(task)
            task.setdefault("baseBranch", self.git.base_branch)
            task.setdefault("headSha", "")
            task.setdefault("upstream", "")
            task.setdefault("dirtyFiles", [])
            task.setdefault("dirtyFingerprint", "")
            task.setdefault("validation", {})
            task.setdefault("continuePhrase", "")
            task.setdefault("compactReceipt", "")
            task.setdefault("receiptUpdatedAt", "")
            task.setdefault("facts", [])
            task.setdefault("inferences", [])
            task.setdefault("unknowns", [])
            task.setdefault("safetyRules", [])
            task["aliases"] = unique_normalized_nonempty(
                [short_text(str(item), max_len=80) for item in task.get("aliases", [])],
                limit=20,
            )
            for field in ["facts", "inferences", "unknowns", "safetyRules"]:
                task[field] = unique_normalized_nonempty([str(item) for item in task.get(field, [])], limit=30)
        if not self.project_state_path.exists():
            self.write_project_state(payload.get("tasks", []))
        return payload

    def save_active_tasks(self, payload: dict[str, Any]) -> None:
        payload["version"] = SIDECAR_VERSION
        payload["projectId"] = self.project_id
        write_json(self.active_tasks_path, payload)
        self.write_project_state(payload.get("tasks", []))

    def write_project_state(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        active_like_tasks = [
            compact_task(task)
            for task in tasks
            if task.get("status", "active") in VALID_STATUSES
        ]
        state = {
            "version": SIDECAR_VERSION,
            "projectId": self.project_id,
            "projectIdSource": self.project_id_source,
            "repoRoot": str(self.git.repo_root),
            "sidecarRoot": str(self.sidecar_root),
            "updatedAt": now_iso(),
            "activeTaskCount": len(active_like_tasks),
            "activeTasks": active_like_tasks,
            "currentBranch": self.git.branch,
            "baseBranch": self.git.base_branch,
            "currentWorktree": str(self.git.worktree_path),
            "isGitWorktree": self.git.is_git_worktree,
            "headSha": self.git.head_sha,
            "upstream": self.git.upstream,
            "dirtyFiles": self.git.dirty_files,
            "dirtyFingerprint": self.git.dirty_fingerprint,
            "lastKnownPrUrl": self.git.pr_url,
            "prSearchUrl": self.git.pr_search_url,
            "stableDocs": stable_doc_status(self.git.repo_root),
        }
        write_json(self.project_state_path, state)
        return state

    def log_event(
        self,
        event: str,
        task_id: str = "",
        started_at: float | None = None,
        **fields: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": now_iso(),
            "projectId": self.project_id,
            "taskId": task_id,
            "event": event,
            "sidecarHit": fields.pop("sidecar_hit", None),
            "handoffAvailable": fields.pop("handoff_available", None),
            "scanScope": fields.pop("scan_scope", "git-status"),
            "durationMs": elapsed_ms(started_at) if started_at is not None else None,
        }
        payload.update(fields)
        append_jsonl(self.events_path, payload)

    def find_task(self, payload: dict[str, Any], branch_first: bool = True) -> tuple[dict[str, Any] | None, list[str]]:
        tasks = payload.get("tasks", [])
        branch = self.git.branch
        worktree = str(self.git.worktree_path)
        conflicts: list[str] = []

        branch_matches = [task for task in tasks if task.get("branch") == branch]
        worktree_matches = [task for task in tasks if task.get("worktreePath") == worktree]

        candidates = branch_matches if branch_first and branch_matches else worktree_matches
        if not candidates:
            candidates = worktree_matches if branch_first else branch_matches
        if not candidates:
            return None, conflicts
        if len(candidates) > 1:
            candidates = sorted(candidates, key=lambda task: task.get("updatedAt", ""), reverse=True)
            conflicts = [task.get("taskId", "<unknown>") for task in candidates[1:]]
        selected = candidates[0]
        if branch_matches and worktree_matches and branch_matches[0] != worktree_matches[0]:
            conflicts.append("branch/worktree mismatch detected")
        return selected, conflicts

    def task_id_for_branch(self) -> str:
        branch = self.git.branch if self.git.branch and self.git.branch != "unknown" else self.git.repo_root.name
        return slugify(branch)

    def default_touched_areas(self) -> list[str]:
        areas: list[str] = []
        for relpath in self.git.touched_files:
            parts = Path(relpath).parts
            if not parts:
                continue
            area = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
            if area not in areas:
                areas.append(area)
        return areas[:8]

    def default_task(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id_for_branch(),
            "status": "active",
            "parentTaskId": "",
            "phase": "",
            "threadRole": "",
            "threadLabel": "",
            "threadPurpose": "",
            "threads": [],
            "routingStatus": "confirmed" if self.git.is_git_worktree else "provisional",
            "routingConfidence": 1.0 if self.git.is_git_worktree else 0.3,
            "routingEvidence": ["created from current Git worktree"] if self.git.is_git_worktree else ["created from non-Git path"],
            "routingNeedsReview": not self.git.is_git_worktree,
            "routingCandidates": [],
            "continuePhrase": "",
            "compactReceipt": "",
            "receiptUpdatedAt": "",
            "goal": "",
            "branch": self.git.branch,
            "baseBranch": self.git.base_branch,
            "worktreePath": str(self.git.worktree_path),
            "aliases": [],
            "repoRoot": str(self.git.repo_root),
            "headSha": self.git.head_sha,
            "upstream": self.git.upstream,
            "dirtyFiles": self.git.dirty_files,
            "dirtyFingerprint": self.git.dirty_fingerprint,
            "prUrl": self.git.pr_url,
            "prSearchUrl": self.git.pr_search_url,
            "touchedAreas": self.default_touched_areas(),
            "nextStep": "",
            "blocker": "",
            "lastThreadSummary": "",
            "facts": [],
            "inferences": [],
            "unknowns": [],
            "safetyRules": [],
            "validation": {"commands": [], "results": [], "notes": "", "validatedAt": ""},
            "updatedAt": now_iso(),
        }

    def upsert_task(
        self,
        payload: dict[str, Any],
        task: dict[str, Any] | None,
        args: argparse.Namespace,
        *,
        default_status: str = "active",
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tasks = payload.setdefault("tasks", [])
        is_new_task = task is None
        if task is None:
            task = self.default_task()
            task["_isNewTask"] = True
            tasks.append(task)

        if getattr(args, "task_id", None):
            task["taskId"] = slugify(args.task_id)
        elif task.get("branch") and task.get("branch") != self.git.branch:
            task["taskId"] = self.task_id_for_branch()
        if getattr(args, "status", None):
            task["status"] = args.status
        elif not task.get("status"):
            task["status"] = default_status
        parent_task_id = normalize_optional_slug(getattr(args, "parent_task_id", None))
        if parent_task_id:
            if parent_would_cycle(payload, task.get("taskId", ""), parent_task_id):
                raise SystemExit(f"invalid parentTaskId would create a cycle: {parent_task_id}")
            task["parentTaskId"] = parent_task_id
            if not task_id_exists(payload, parent_task_id):
                task["parentTaskMissing"] = True
        elif "parentTaskId" not in task:
            task["parentTaskId"] = ""
        phase = normalize_phase(getattr(args, "phase", None))
        if phase:
            task["phase"] = phase
        else:
            task.setdefault("phase", "")
        thread_role = normalize_thread_role(getattr(args, "thread_role", None))
        if thread_role:
            task["threadRole"] = thread_role
        else:
            task.setdefault("threadRole", "")
        if getattr(args, "thread_label", None) is not None:
            task["threadLabel"] = short_text(args.thread_label, max_len=120)
        else:
            task.setdefault("threadLabel", "")
        if getattr(args, "thread_purpose", None) is not None:
            task["threadPurpose"] = short_text(args.thread_purpose, max_len=320)
        else:
            task.setdefault("threadPurpose", "")
        if getattr(args, "continue_phrase", None) is not None:
            task["continuePhrase"] = short_text(args.continue_phrase, max_len=96)
        else:
            task.setdefault("continuePhrase", "")
        task.setdefault("compactReceipt", "")
        task.setdefault("receiptUpdatedAt", "")
        if route:
            apply_route_metadata(task, route)
        else:
            task.setdefault("routingStatus", "confirmed")
            task.setdefault("routingConfidence", 1.0)
            task.setdefault("routingEvidence", [])
            task.setdefault("routingNeedsReview", False)
            task.setdefault("routingCandidates", [])
        if getattr(args, "goal", None) is not None:
            task["goal"] = short_text(args.goal)
        if getattr(args, "next_step", None) is not None:
            task["nextStep"] = short_text(args.next_step)
        if getattr(args, "blocker", None) is not None:
            task["blocker"] = short_text(args.blocker)
        if getattr(args, "thread_summary", None) is not None:
            task["lastThreadSummary"] = short_text(args.thread_summary, max_len=320)
        if getattr(args, "pr_url", None) is not None:
            task["prUrl"] = args.pr_url
        elif not task.get("prUrl"):
            task["prUrl"] = self.git.pr_url
        normalize_task_pr_fields(task, self.git.pr_search_url)

        touched_areas = getattr(args, "touched_areas", None)
        if touched_areas:
            task["touchedAreas"] = unique_nonempty(
                [short_text(area, max_len=80) for area in touched_areas],
                limit=8,
            )
        elif not task.get("touchedAreas"):
            task["touchedAreas"] = self.default_touched_areas()

        aliases = normalized_note_list(getattr(args, "aliases", None), limit=20, max_len=80)
        if aliases:
            task["aliases"] = unique_normalized_nonempty([*task.get("aliases", []), *aliases], limit=20)
        else:
            task.setdefault("aliases", [])

        for field, arg_name in [
            ("facts", "facts"),
            ("inferences", "inferences"),
            ("unknowns", "unknowns"),
            ("safetyRules", "safety_rules"),
        ]:
            values = normalized_note_list(getattr(args, arg_name, None), limit=20, max_len=320)
            if values:
                task[field] = unique_normalized_nonempty([*task.get(field, []), *values], limit=30)
            else:
                task.setdefault(field, [])

        if any(
            getattr(args, name, None)
            for name in ["validation_commands", "validation_results", "validation_tests", "validation_manual", "validation_notes", "validation_at"]
        ):
            task["validation"] = build_validation_record(args, task.get("validation") or {})
        else:
            task.setdefault("validation", {"commands": [], "results": [], "notes": "", "validatedAt": ""})

        if route_allows_git_snapshot_refresh(self, task, args, route):
            task["branch"] = self.git.branch
            task["baseBranch"] = self.git.base_branch
            task["worktreePath"] = str(self.git.worktree_path)
            task["repoRoot"] = str(self.git.repo_root)
            task["headSha"] = self.git.head_sha
            task["upstream"] = self.git.upstream
            task["dirtyFiles"] = self.git.dirty_files
            task["dirtyFingerprint"] = self.git.dirty_fingerprint
        else:
            task.setdefault("branch", self.git.branch)
            task.setdefault("baseBranch", self.git.base_branch)
            task.setdefault("worktreePath", str(self.git.worktree_path))
            task.setdefault("repoRoot", str(self.git.repo_root))
            task.setdefault("headSha", "")
            task.setdefault("upstream", "")
            task.setdefault("dirtyFiles", [])
            task.setdefault("dirtyFingerprint", "")
        upsert_current_thread(task, args)
        task["updatedAt"] = now_iso()
        task.pop("_isNewTask", None)
        return task

    def handoff_path_for(self, task: dict[str, Any]) -> Path:
        return self.handoffs_dir / f"{task['taskId']}.md"

    def task_snapshot(self, task: dict[str, Any], conflicts: list[str] | None = None) -> dict[str, Any]:
        handoff_path = self.handoff_path_for(task)
        handoff_available = handoff_path.exists()
        task_output = compact_task(task)
        if not task_output.get("prSearchUrl"):
            task_output["prSearchUrl"] = self.git.pr_search_url
        return {
            "projectId": self.project_id,
            "sidecarRoot": str(self.sidecar_root),
            "task": task_output,
            "handoffPath": str(handoff_path),
            "handoffAvailable": handoff_available,
            "projectStatePath": str(self.project_state_path),
            "conflicts": conflicts or [],
        }


def stable_doc_status(repo_root: Path) -> list[dict[str, str]]:
    docs = [
        ("project-map", repo_root / "docs" / "agent" / "project-map.md"),
        ("conventions", repo_root / "docs" / "agent" / "conventions.md"),
        ("common-commands", repo_root / "docs" / "agent" / "common-commands.md"),
    ]
    return [
        {"name": name, "path": str(path), "exists": "true" if path.exists() else "false"}
        for name, path in docs
    ]


def build_handoff_markdown(task: dict[str, Any], args: argparse.Namespace, manager: SidecarManager, language: str = "en") -> str:
    done_items = [item.strip() for item in (args.done or []) if item.strip()][:5]
    not_done_items = [item.strip() for item in (args.not_done or []) if item.strip()][:5]
    risk_items = [item.strip() for item in (args.risks or []) if item.strip()]
    key_files = [item.strip() for item in (args.key_files or manager.git.touched_files[:8]) if item.strip()]
    touched_areas = task.get("touchedAreas") or manager.default_touched_areas()
    pr_url, pr_search_url = normalized_pr_fields(
        task.get("prUrl") or manager.git.pr_url,
        task.get("prSearchUrl"),
        manager.git.pr_search_url,
    )
    validation = task.get("validation") or build_validation_record(args, {})
    validation_commands = validation.get("commands") or []
    validation_results = validation.get("results") or []
    validation_notes = validation.get("notes") or ""
    validation_at = validation.get("validatedAt") or ""
    current_objective = args.current_objective or task.get("goal") or tr(language, "current_objective_missing")
    facts = task.get("facts") or []
    inferences = task.get("inferences") or []
    unknowns = task.get("unknowns") or []
    safety_rules = task.get("safetyRules") or []

    lines = [
        f"# {tr(language, 'handoff')}: {task['taskId']}",
        "",
        f"## {tr(language, 'meta')}",
        f"- {tr(language, 'goal')}: {task.get('goal') or tr(language, 'goal_not_recorded')}",
        f"- {tr(language, 'status')}: {task.get('status') or 'active'}",
        f"- Parent Task: {task.get('parentTaskId') or tr(language, 'none')}",
        f"- Phase: {task.get('phase') or tr(language, 'none')}",
        f"- Thread Role: {task.get('threadRole') or tr(language, 'none')}",
        f"- Thread Label: {task.get('threadLabel') or tr(language, 'none')}",
        f"- Thread Purpose: {task.get('threadPurpose') or tr(language, 'none')}",
        f"- Continue Phrase: {task.get('continuePhrase') or tr(language, 'none')}",
        f"- Routing: {task.get('routingStatus') or tr(language, 'none')} (needsReview={bool_label(bool(task.get('routingNeedsReview')))}, confidence={task.get('routingConfidence', tr(language, 'none'))})",
        f"- {tr(language, 'branch')}: {task.get('branch') or manager.git.branch}",
        f"- {tr(language, 'base_branch')}: {task.get('baseBranch') or manager.git.base_branch}",
        f"- {tr(language, 'worktree')}: {task.get('worktreePath') or str(manager.git.worktree_path)}",
        f"- {tr(language, 'head_sha')}: {task.get('headSha') or manager.git.head_sha or 'unknown'}",
        f"- {tr(language, 'upstream')}: {task.get('upstream') or manager.git.upstream or tr(language, 'none')}",
        f"- {tr(language, 'dirty_fingerprint')}: {task.get('dirtyFingerprint') or 'clean'}",
        f"- PR: {pr_url or 'None'}",
        f"- PR Search: {pr_search_url or 'None'}",
        f"- {tr(language, 'updated_at')}: {task.get('updatedAt') or now_iso()}",
        "",
        "## Compact Receipt",
        task.get("compactReceipt") or tr(language, "none_recorded"),
        "",
        f"## {tr(language, 'current_objective')}",
        current_objective,
        "",
        f"## {tr(language, 'facts')}",
    ]
    lines.extend([f"- {item}" for item in facts] or [f"- {tr(language, 'none_recorded')}"])
    lines.extend(["", f"## {tr(language, 'inferences')}"])
    lines.extend([f"- {item}" for item in inferences] or [f"- {tr(language, 'none_recorded')}"])
    lines.extend(["", f"## {tr(language, 'unknowns')}"])
    lines.extend([f"- {item}" for item in unknowns] or [f"- {tr(language, 'none_recorded')}"])
    lines.extend(["", f"## {tr(language, 'safety_rules')}"])
    lines.extend([f"- {item}" for item in safety_rules] or [f"- {tr(language, 'none_recorded')}"])
    lines.extend([
        "",
        f"## {tr(language, 'done')}",
    ])
    lines.extend([f"- {item}" for item in done_items] or [f"- {tr(language, 'none')}"])
    lines.extend(["", f"## {tr(language, 'not_done')}"])
    lines.extend([f"- {item}" for item in not_done_items] or [f"- {tr(language, 'none')}"])
    lines.extend(["", f"## {tr(language, 'blocker')}", f"- {task.get('blocker') or tr(language, 'none')}", "", f"## {tr(language, 'touched_areas')}"])
    lines.extend([f"- {item}" for item in touched_areas] or [f"- {tr(language, 'none')}"])
    lines.extend(["", f"## {tr(language, 'key_files')}"])
    lines.extend([f"- {item}" for item in key_files] or [f"- {tr(language, 'none')}"])
    lines.extend(["", f"## {tr(language, 'suggested_next_step')}", f"- {task.get('nextStep') or tr(language, 'next_step_missing')}"])
    lines.extend(
        [
            "",
            f"## {tr(language, 'validation_status')}",
            f"- {tr(language, 'validated_at')}: {validation_at or tr(language, 'not_recorded')}",
            f"- {tr(language, 'commands')}:",
        ]
    )
    lines.extend([f"  - {item.get('command')}: {item.get('recordedAt', tr(language, 'not_recorded'))}" for item in validation_commands] or [f"  - {tr(language, 'none')}"])
    lines.extend([f"- {tr(language, 'results')}:"])
    lines.extend([f"  - {item.get('result')}: {item.get('recordedAt', tr(language, 'not_recorded'))}" for item in validation_results] or [f"  - {tr(language, 'none')}"])
    lines.extend(
        [
            f"- {tr(language, 'notes')}: {validation_notes or tr(language, 'none')}",
            "",
            f"## {tr(language, 'risks')}",
        ]
    )
    lines.extend([f"- {item}" for item in risk_items] or [f"- {tr(language, 'none')}"])
    lines.extend(["", f"## {tr(language, 'thread_summary')}", task.get("lastThreadSummary") or tr(language, 'thread_summary_missing'), ""])
    return "\n".join(lines)


SECTION_ALIASES = {
    "meta": ["meta"],
    "receipt": ["compact receipt"],
    "objective": ["current objective"],
    "facts": ["facts"],
    "inferences": ["inferences"],
    "unknowns": ["unknowns"],
    "safety": ["safety rules"],
    "done": ["done"],
    "not-done": ["not done"],
    "blocker": ["blocker"],
    "touched-areas": ["touched areas"],
    "key-files": ["key files"],
    "next-step": ["suggested next step"],
    "validation": ["validation status", "validation"],
    "risks": ["risks"],
    "thread-summary": ["thread summary"],
}


def normalize_heading(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def parse_handoff_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = normalize_heading(match.group(1))
            sections[current] = [line]
            continue
        if current:
            sections[current].append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def handoff_section(markdown: str, section: str) -> tuple[str, str]:
    sections = parse_handoff_sections(markdown)
    wanted = SECTION_ALIASES.get(section, [section])
    for alias in wanted:
        normalized = normalize_heading(alias)
        if normalized in sections:
            return normalized, sections[normalized]
    return "", ""


def select_handoff_thread(task: dict[str, Any] | None, args: argparse.Namespace) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    if not task:
        return None, [], ""
    threads = ensure_task_threads(task, mutate=False)
    requested_id = str(getattr(args, "thread_id", "") or "").strip()
    requested_role = normalize_thread_role(getattr(args, "thread_role", None)) if getattr(args, "thread_role", None) else ""
    if requested_id:
        matches = [thread for thread in threads if str(thread.get("threadId") or "") == requested_id]
        return (matches[0] if len(matches) == 1 else None), matches, "thread-id"
    if requested_role:
        matches = [thread for thread in threads if str(thread.get("threadRole") or "") == requested_role]
        return (matches[0] if len(matches) == 1 else None), matches, "thread-role"
    return (threads[0] if len(threads) == 1 else None), threads, "none"


def task_for_load_handoff(manager: SidecarManager, payload: dict[str, Any], args: argparse.Namespace, language: str) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    if getattr(args, "task_id", None):
        task = task_by_id(manager, payload, slugify(args.task_id))
        return task, "task-id", {"resolved": bool(task), "taskId": slugify(args.task_id)}
    if getattr(args, "query", None):
        resolution = resolve_task_from_payload(manager, payload, args.query, language)
        if resolution.get("resolved"):
            return task_by_id(manager, payload, resolution.get("taskId", "")), "query", resolution
        return None, "query", resolution
    task, conflicts = manager.find_task(payload)
    return task, "current-worktree", {"resolved": bool(task), "conflicts": conflicts}


def build_load_handoff_output(
    manager: SidecarManager,
    task: dict[str, Any] | None,
    *,
    mode: str,
    section: str,
    reason: str,
    reason_note: str,
    resolved_by: str,
    resolution: dict[str, Any],
    language: str,
    selected_thread: dict[str, Any] | None = None,
    thread_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    task_id = str((task or {}).get("taskId") or resolution.get("taskId") or "")
    handoff_path = manager.handoff_path_for(task) if task else manager.handoffs_dir / f"{task_id}.md"
    handoff_available = bool(task and handoff_path.exists())
    if handoff_available:
        with handoff_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            markdown = handle.read()
    else:
        markdown = ""
    content = ""
    content_returned = False
    selected_section = ""
    if handoff_available:
        if mode == "full":
            content = markdown
            content_returned = True
        elif mode == "section":
            selected_section, content = handoff_section(markdown, section)
            content_returned = bool(content)
        else:
            receipt = str((task or {}).get("compactReceipt") or "").strip()
            lines = [
                f"{'任务' if normalize_language(language) == 'zh-CN' else 'Task'}: {task_id}",
                f"{'状态' if normalize_language(language) == 'zh-CN' else 'Status'}: {(task or {}).get('status') or 'active'}",
            ]
            if receipt:
                lines.extend(receipt.splitlines()[:5])
            else:
                if (task or {}).get("goal"):
                    lines.append(f"{tr(language, 'goal')}: {task.get('goal')}")
                if (task or {}).get("nextStep"):
                    lines.append(f"{tr(language, 'suggested_next_step')}: {task.get('nextStep')}")
                if (task or {}).get("blocker"):
                    lines.append(f"{tr(language, 'blocker')}: {task.get('blocker')}")
            if (task or {}).get("continuePhrase"):
                lines.append(f"Continue: {task.get('continuePhrase')}")
            content = "\n".join(unique_nonempty([short_text(line, max_len=220) for line in lines], limit=8))
            content_returned = bool(content)
    return {
        "projectId": manager.project_id,
        "taskId": task_id,
        "threadId": (selected_thread or {}).get("threadId", ""),
        "threadRole": (selected_thread or {}).get("threadRole", (task or {}).get("threadRole", "")),
        "threadLabel": (selected_thread or {}).get("threadLabel", (task or {}).get("threadLabel", "")),
        "selectedThread": selected_thread or {},
        "threadCandidates": compact_thread_entries(thread_candidates or ensure_task_threads(task, mutate=False) if task else []),
        "continuePhrase": (task or {}).get("continuePhrase", ""),
        "mode": mode,
        "section": section if mode == "section" else "",
        "selectedSection": selected_section,
        "reasonCode": reason,
        "reasonNotePresent": bool(reason_note.strip()),
        "resolvedBy": resolved_by,
        "resolution": resolution,
        "handoffPath": str(handoff_path),
        "handoffAvailable": handoff_available,
        "contentReturned": content_returned,
        "contentChars": len(content),
        "content": content,
        "fullMarkdownReturned": mode == "full" and content_returned,
        "repoMutated": False,
        "sidecarMutated": False,
    }


def build_pr_text(task: dict[str, Any], manager: SidecarManager, args: argparse.Namespace) -> tuple[str, str]:
    title = args.pr_title or f"{task.get('branch') or manager.git.branch}: {task.get('goal') or 'complete feature'}"
    body_lines = [
        "## Summary",
        task.get("goal") or "Complete the current feature work.",
        "",
        "## Current State",
        f"- Task: {task.get('taskId')}",
        f"- Branch: {task.get('branch') or manager.git.branch}",
        f"- Status: {task.get('status') or 'review'}",
        f"- Next step: {task.get('nextStep') or 'None'}",
        f"- Blocker: {task.get('blocker') or 'None'}",
        "",
        "## Validation",
        args.validation or "Not provided.",
    ]
    body = args.pr_body or "\n".join(body_lines)
    return title, body


def issue_list(values: list[str] | None, language: str = "en") -> list[str]:
    items = [short_text(item, max_len=500) for item in (values or []) if item and item.strip()]
    return [f"- {item}" for item in items] or [f"- {tr(language, 'not_recorded')}"]


def build_issue_text(manager: SidecarManager, args: argparse.Namespace, language: str = "en") -> tuple[str, str]:
    title = short_text(args.issue_title or "Dogfood feedback from Agent Workflow Hub", max_len=120)
    priority = short_text(args.priority or "triage-needed", max_len=80)
    lines = [
        f"## {tr(language, 'facts')}",
        *issue_list(args.facts, language),
        "",
        f"## {tr(language, 'inferences')}",
        *issue_list(args.inferences, language),
        "",
        f"## {tr(language, 'unknowns')}",
        *issue_list(args.unknowns, language),
        "",
        f"## {tr(language, 'reproduction')}",
        *issue_list(args.reproduction, language),
        "",
        f"## {tr(language, 'suggested_fix')}",
        *issue_list(args.suggested_fix, language),
        "",
        f"## {tr(language, 'priority')}",
        f"- {priority}",
        "",
        f"## {tr(language, 'context')}",
        f"- {tr(language, 'project')}: {manager.project_id}",
        f"- {tr(language, 'branch')}: {manager.git.branch}",
        f"- {tr(language, 'worktree_name')}: {manager.git.worktree_path.name}",
        f"- {tr(language, 'generated_at')}: {now_iso()}",
    ]
    return title, "\n".join(lines) + "\n"


def sensitive_issue_findings(title: str, body: str) -> list[str]:
    haystack = f"{title}\n{body}"
    findings: list[str] = []
    for pattern in SENSITIVE_ISSUE_PATTERNS:
        if re.search(pattern, haystack):
            findings.append(pattern)
    if len(body.splitlines()) > 160 or len(body) > 12000:
        findings.append("long-log-or-large-body")
    return findings


def issue_search_query(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9_-]{4,}", title)
    return " ".join(words[:8]) or title


def find_similar_open_issues(manager: SidecarManager, title: str, gh_path: str) -> dict[str, Any]:
    query = issue_search_query(title)
    result: dict[str, Any] = {"ok": False, "query": query, "issues": [], "message": ""}
    command = [
        gh_path,
        "issue",
        "list",
        "--state",
        "open",
        "--search",
        query,
        "--json",
        "number,title,url",
        "--limit",
        "5",
    ]
    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        proc = subprocess.run(
            command,
            cwd=str(manager.git.repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        result["message"] = "similar issue search timed out"
        return result
    if proc.returncode != 0 or not proc.stdout.strip():
        result["message"] = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part) or "similar issue search failed"
        return result
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        result["message"] = f"similar issue search returned invalid JSON: {exc}"
        return result
    if not isinstance(data, list):
        result["message"] = "similar issue search returned unexpected JSON"
        return result
    result["ok"] = True
    result["issues"] = data
    result["message"] = "similar issue search completed"
    return result


def try_create_issue(manager: SidecarManager, title: str, body: str, args: argparse.Namespace) -> dict[str, Any]:
    sensitive_findings = sensitive_issue_findings(title, body)
    status = gh_status()
    result: dict[str, Any] = {
        "requested": True,
        "created": False,
        "title": title,
        "body": body,
        "labels": DOGFOOD_ISSUE_LABELS,
        "gh": status,
        "sensitiveFindings": sensitive_findings,
        "similarOpenIssues": [],
        "similarIssueSearch": {"ok": None, "query": "", "message": "not checked"},
        "guidance": "",
    }
    if sensitive_findings:
        result["guidance"] = "Sensitive or oversized content was detected; issue creation was blocked and a draft was returned."
        return result
    if not status["available"] or not status["authenticated"]:
        result["guidance"] = "GitHub CLI is unavailable or unauthenticated; use the returned title/body as a draft."
        return result

    gh_path = status["path"]
    search_result = find_similar_open_issues(manager, title, gh_path)
    result["similarIssueSearch"] = {
        "ok": search_result.get("ok", False),
        "query": search_result.get("query", ""),
        "message": search_result.get("message", ""),
    }
    if not search_result.get("ok", False):
        result["guidance"] = "Similar issue search failed; creation was blocked and a draft was returned."
        return result
    similar_issues = search_result.get("issues", [])
    result["similarOpenIssues"] = similar_issues
    if similar_issues and not args.allow_duplicate:
        result["guidance"] = "Similar open issues were found; creation was blocked to avoid duplicates."
        return result

    command = [gh_path, "issue", "create", "--title", title, "--body", body]
    for label in DOGFOOD_ISSUE_LABELS:
        command.extend(["--label", label])
    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        proc = subprocess.run(
            command,
            cwd=str(manager.git.repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        result["guidance"] = "GitHub CLI timed out while creating the issue; use the returned title/body as a draft."
        result["ghError"] = subprocess_timeout_output(exc)
        return result
    if proc.returncode == 0:
        result["created"] = True
        result["issueUrl"] = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        result["guidance"] = "Issue created with GitHub CLI."
        return result
    result["guidance"] = "GitHub CLI failed while creating the issue; use the returned title/body as a draft."
    result["ghError"] = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
    return result


def build_start_thread_summary(
    manager: SidecarManager,
    task: dict[str, Any],
    handoff_available: bool,
    stale: dict[str, Any],
    language: str = "en",
) -> str:
    def add_limited_items(lines: list[str], title: str, items: list[Any], *, limit: int, empty: str | None = None) -> None:
        values = [str(item).strip() for item in items if str(item).strip()]
        lines.append(f"{title}:")
        lines.extend([f"- {short_text(item, max_len=140)}" for item in values[:limit]] or [f"- {empty or tr(language, 'not_recorded')}"])

    validation = task.get("validation") or {}
    validation_commands = validation.get("commands") or []
    validation_results = validation.get("results") or []
    last_command = validation_commands[-1] if validation_commands else {}
    last_result = validation_results[-1] if validation_results else {}
    stale_reasons = stale.get("reasons") or []
    risks = task.get("risks") or []
    blocker = task.get("blocker") or ""
    if blocker:
        risks = [blocker, *risks]

    lines = [
        tr(language, "summary_title"),
        f"{tr(language, 'project')}: {manager.project_id}",
        f"{tr(language, 'task')}: {task.get('taskId') or tr(language, 'not_recorded')}",
        f"{tr(language, 'branch')}: {task.get('branch') or manager.git.branch}",
        f"{tr(language, 'worktree')}: {task.get('worktreePath') or str(manager.git.worktree_path)}",
        f"{tr(language, 'status')}: {task.get('status') or 'active'}",
        f"Continue: {task.get('continuePhrase') or tr(language, 'not_recorded')}",
        f"{tr(language, 'handoff_available')}: {tr(language, 'available') if handoff_available else tr(language, 'missing')}",
        f"{tr(language, 'stale')}: {tr(language, 'yes') if stale.get('isStale') else tr(language, 'no')}",
    ]
    if stale.get("isStale"):
        lines.append(f"{tr(language, 'stale_warning')}: {tr(language, 'stale_warning_text')}")
    else:
        lines.append(f"{tr(language, 'stale_warning')}: {tr(language, 'stale_warning_none')}")
    add_limited_items(lines, tr(language, "stale_reasons"), stale_reasons, limit=2, empty=tr(language, "none"))
    add_limited_items(lines, tr(language, "safety_rules"), task.get("safetyRules") or [], limit=3)
    add_limited_items(lines, tr(language, "current_objective"), [task.get("goal") or ""], limit=1)
    add_limited_items(lines, tr(language, "facts"), task.get("facts") or [], limit=3)
    add_limited_items(lines, tr(language, "inferences"), task.get("inferences") or [], limit=2)
    add_limited_items(lines, tr(language, "unknowns"), task.get("unknowns") or [], limit=2)
    lines.append(f"{tr(language, 'validation')}:")
    if validation.get("validatedAt") or last_command or last_result or validation.get("notes"):
        lines.extend(
            [
                f"- {tr(language, 'last_validation_at')}: {validation.get('validatedAt') or tr(language, 'not_recorded')}",
                f"- {tr(language, 'command')}: {last_command.get('command') or tr(language, 'not_recorded')}",
                f"- {tr(language, 'result')}: {last_result.get('result') or tr(language, 'not_recorded')}",
            ]
        )
    else:
        lines.append(f"- {tr(language, 'not_recorded')}")
    add_limited_items(lines, tr(language, "immediate_next_step"), [task.get("nextStep") or ""], limit=1)
    add_limited_items(lines, tr(language, "risks_blockers"), risks, limit=2, empty=tr(language, "none"))
    add_limited_items(lines, tr(language, "touched_areas"), task.get("touchedAreas") or manager.default_touched_areas(), limit=3, empty=tr(language, "none"))
    lines.extend(
        [
            f"{tr(language, 'sidecar')}:",
            f"- {tr(language, 'handoff_path')}: {manager.handoff_path_for(task)}",
        ]
    )
    return "\n".join(lines[:40])


def pr_base_for_create(task: dict[str, Any], manager: SidecarManager, explicit_base: str | None) -> str:
    base = explicit_base or task.get("baseBranch") or manager.git.base_branch
    base = (base or "").strip()
    current_branch = (task.get("branch") or manager.git.branch or "").strip()
    if not base or base == "unknown" or base == current_branch:
        return ""
    return base


def gh_status() -> dict[str, Any]:
    gh_path = shutil.which("gh")
    if not gh_path:
        return {
            "available": False,
            "authenticated": False,
            "path": "",
            "message": "GitHub CLI is not installed or not on PATH.",
        }

    gh_env = os.environ.copy()
    gh_env["GH_PROMPT_DISABLED"] = "1"
    try:
        proc = subprocess.run(
            [gh_path, "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=gh_env,
            stdin=subprocess.DEVNULL,
            timeout=GH_AUTH_STATUS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output = subprocess_timeout_output(exc)
        return {
            "available": True,
            "authenticated": False,
            "path": gh_path,
            "timedOut": True,
            "message": output or "GitHub CLI auth status timed out.",
        }
    output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
    authenticated = proc.returncode == 0 and not suspicious_cli_output(output)
    return {
        "available": True,
        "authenticated": authenticated,
        "path": gh_path,
        "message": output or ("authenticated" if authenticated else "not authenticated"),
        "exitCode": proc.returncode,
    }


def try_create_pr(
    task: dict[str, Any],
    manager: SidecarManager,
    args: argparse.Namespace,
) -> dict[str, Any]:
    normalize_task_pr_fields(task, manager.git.pr_search_url)
    title, body = build_pr_text(task, manager, args)
    guidance = (
        "Install and authenticate GitHub CLI, then create the PR with the generated title/body "
        "or the archived task JSON returned by finish-feature."
    )
    result: dict[str, Any] = {
        "requested": bool(args.create_pr),
        "created": False,
        "prUrl": task.get("prUrl", ""),
        "prSearchUrl": task.get("prSearchUrl", ""),
        "title": title,
        "body": body,
        "gh": {
            "checked": False,
            "available": None,
            "authenticated": None,
            "path": "",
            "message": "GitHub CLI was not checked because PR creation was not requested.",
        },
        "guidance": "",
    }

    if not args.create_pr:
        result["guidance"] = "PR creation was not requested; use the generated title/body manually after finish archives the task."
        return result
    status = gh_status()
    result["gh"] = status
    if not status["available"] or not status["authenticated"]:
        result["guidance"] = guidance
        return result

    gh_path = status["path"]
    command = [
        gh_path,
        "pr",
        "create",
        "--title",
        title,
        "--body",
        body,
    ]
    pr_base = pr_base_for_create(task, manager, args.base)
    if pr_base:
        command.extend(["--base", pr_base])
    if args.draft:
        command.append("--draft")

    gh_env = os.environ.copy()
    gh_env["GH_PROMPT_DISABLED"] = "1"
    try:
        proc = subprocess.run(
            command,
            cwd=str(manager.git.repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=gh_env,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        result["guidance"] = (
            "GitHub CLI timed out while creating the PR. The feature was still finished locally; "
            "use the generated title/body or archived task JSON after checking gh setup."
        )
        result["ghError"] = subprocess_timeout_output(exc)
        return result
    if proc.returncode == 0:
        pr_url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        result["created"] = True
        result["prUrl"] = pr_url
        result["guidance"] = "PR created with GitHub CLI."
        return result

    result["guidance"] = (
        "GitHub CLI was available, but PR creation failed. The feature was still finished locally; "
        "use the generated title/body or inspect gh output."
    )
    result["ghError"] = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
    return result


def archive_task(
    manager: SidecarManager,
    payload: dict[str, Any],
    task: dict[str, Any],
    *,
    event: str,
    started_at: float | None = None,
    pr_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_base = f"{task['taskId']}-{timestamp}"
    archive_json_path = manager.archive_dir / f"{archive_base}.json"
    archive_md_path = manager.archive_dir / f"{archive_base}.md"
    handoff_path = manager.handoff_path_for(task)
    normalize_task_pr_fields(task, manager.git.pr_search_url)

    archive_payload = dict(task)
    archive_payload["archivedAt"] = now_iso()
    if pr_result is not None:
        archive_payload["pr"] = pr_result
    write_json(archive_json_path, archive_payload)
    if handoff_path.exists():
        with file_lock(archive_md_path):
            atomic_write_text(archive_md_path, handoff_path.read_text(encoding="utf-8"))

    removed_selected = False
    remaining_tasks = []
    for item in payload.get("tasks", []):
        if not removed_selected and item is task:
            removed_selected = True
            continue
        remaining_tasks.append(item)
    payload["tasks"] = remaining_tasks
    manager.save_active_tasks(payload)
    manager.log_event(
        event,
        task_id=task["taskId"],
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=handoff_path.exists(),
        prUrl=(pr_result or {}).get("prUrl", task.get("prUrl", "")),
        prSearchUrl=(pr_result or {}).get("prSearchUrl", task.get("prSearchUrl", "")),
        prCreated=(pr_result or {}).get("created", False),
    )
    return {
        "projectId": manager.project_id,
        "taskId": task["taskId"],
        "archivedJson": str(archive_json_path),
        "archivedHandoff": str(archive_md_path) if archive_md_path.exists() else "",
        "removedFromActiveTasks": True,
        "projectStatePath": str(manager.project_state_path),
    }


def build_weekly_report(manager: SidecarManager, state: dict[str, Any], period: str, language: str = "en") -> str:
    active_tasks = state.get("activeTasks", [])
    lines = [
        f"# {tr(language, 'weekly_report')}: {manager.project_id}",
        "",
        f"- {tr(language, 'period')}: {period}",
        f"- {tr(language, 'generated_at')}: {now_iso()}",
        f"- {tr(language, 'sidecar_path')}: {manager.sidecar_root}",
        "",
        f"## {tr(language, 'snapshot')}",
        f"- {tr(language, 'active_tasks')}: {state.get('activeTaskCount', 0)}",
        f"- {tr(language, 'current_branch')}: {state.get('currentBranch') or 'unknown'}",
        "",
        f"## {tr(language, 'active_work')}",
    ]
    if active_tasks:
        for task in active_tasks:
            lines.extend(
                [
                    f"- {task.get('taskId')}: {task.get('goal') or tr(language, 'goal_not_recorded')}",
                    f"  {tr(language, 'status')}: {task.get('status') or 'active'}; {tr(language, 'suggested_next_step')}: {task.get('nextStep') or tr(language, 'none')}",
                ]
            )
    else:
        lines.append(f"- {tr(language, 'no_active_tasks')}")

    lines.extend(["", f"## {tr(language, 'human_note')}", tr(language, "weekly_human_note")])
    return "\n".join(lines) + "\n"


def read_events(manager: SidecarManager, since: datetime | None = None, until: datetime | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    if not manager.events_path.exists():
        return [], ["events.jsonl is missing; report uses current sidecar snapshot only."]
    events: list[dict[str, Any]] = []
    malformed = 0
    try:
        lines = manager.events_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as exc:
        return [], [f"events.jsonl could not be read: {short_text(str(exc), max_len=200)}"]
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(event, dict):
            malformed += 1
            continue
        if datetime_in_range(str(event.get("timestamp") or ""), since, until):
            events.append(event)
    if malformed:
        notes.append(f"{malformed} malformed event line(s) were ignored.")
    if not events:
        notes.append("No events matched the requested period; metrics may be sparse.")
    return events, notes


def percent(part: int, total: int) -> float:
    return round((part / total) * 100, 1) if total else 0.0


def latest_numeric(events: list[dict[str, Any]], field: str) -> int | None:
    for event in reversed(events):
        value = event.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return None


def current_coverage_metrics(manager: SidecarManager, payload: dict[str, Any]) -> dict[str, Any]:
    tasks = payload.get("tasks", [])
    active_tasks = [task for task in tasks if task.get("status", "active") in VALID_STATUSES]
    worktrees, worktree_error = parse_git_worktree_list(manager.git.repo_root)
    worktree_paths = {str(Path(item.get("path", "")).resolve()) for item in worktrees if item.get("path")}
    active_without_worktree = 0
    tracked_worktrees = 0
    for task in active_tasks:
        raw_path = str(task.get("worktreePath") or "")
        resolved = str(Path(raw_path).resolve()) if raw_path else ""
        if raw_path and resolved in worktree_paths:
            tracked_worktrees += 1
        else:
            active_without_worktree += 1
    git_worktrees = len(worktrees)
    untracked = max(git_worktrees - tracked_worktrees, 0)
    return {
        "gitWorktrees": git_worktrees,
        "activeSidecarTasks": len(active_tasks),
        "trackedWorktrees": tracked_worktrees,
        "untrackedWorktrees": untracked,
        "activeTasksWithoutWorktree": active_without_worktree,
        "coverageSource": "current git worktree list + active-tasks.json",
        "worktreeError": worktree_error,
    }


def build_eval_report_payload(
    manager: SidecarManager,
    period: str,
    since_text: str,
    until_text: str,
) -> dict[str, Any]:
    since = parse_datetime_filter(since_text)
    until = parse_datetime_filter(until_text)
    payload = manager.load_active_tasks()
    events, notes = read_events(manager, since, until)
    action_counts: dict[str, int] = {}
    for event in events:
        name = str(event.get("event") or "unknown")
        action_counts[name] = action_counts.get(name, 0) + 1

    tracked_actions = ["resume", "handoff", "load-handoff", "audit-context", "audit-project", "finish", "resume-query", "resolve-task"]
    usage_counts = {
        "totalEvents": len(events),
        "actionCounts": dict(sorted(action_counts.items())),
        **{f"{name}Count": action_counts.get(name, 0) for name in tracked_actions},
    }

    handoff_events = [event for event in events if event.get("handoffAvailable") is not None]
    stale_events = [event for event in events if event.get("stale") is not None]
    validation_events = [event for event in events if event.get("validationPresent") is not None]
    safety_events = [event for event in events if event.get("safetyRulesPresent") is not None]
    blocked_tasks = [task for task in payload.get("tasks", []) if task.get("status") == "blocked" or task.get("blocker")]
    recovery_metrics = {
        "handoffAvailabilityObservations": len(handoff_events),
        "handoffAvailableCount": sum(1 for event in handoff_events if event.get("handoffAvailable") is True),
        "handoffMissingCount": sum(1 for event in handoff_events if event.get("handoffAvailable") is False),
        "handoffAvailabilityRate": percent(sum(1 for event in handoff_events if event.get("handoffAvailable") is True), len(handoff_events)),
        "staleObservations": len(stale_events),
        "staleCount": sum(1 for event in stale_events if event.get("stale") is True),
        "staleRate": percent(sum(1 for event in stale_events if event.get("stale") is True), len(stale_events)),
        "missingValidationCount": sum(1 for event in validation_events if event.get("validationPresent") is False),
        "missingSafetyRulesCount": sum(1 for event in safety_events if event.get("safetyRulesPresent") is False),
        "blockedTaskCount": len(blocked_tasks),
    }

    routing_events = [event for event in events if event.get("event") in {"resolve-task", "resume-query"}]
    resolved_count = sum(1 for event in routing_events if event.get("resolved") is True)
    disambiguation_count = sum(1 for event in routing_events if event.get("needsDisambiguation") is True)
    failed_count = sum(1 for event in routing_events if event.get("resolved") is False and not event.get("needsDisambiguation"))
    confidences = [float(event.get("confidence")) for event in routing_events if isinstance(event.get("confidence"), (int, float))]
    routing_metrics = {
        "routingEventCount": len(routing_events),
        "resolvedCount": resolved_count,
        "disambiguationCount": disambiguation_count,
        "failedOrNoMatchCount": failed_count,
        "resolvedRate": percent(resolved_count, len(routing_events)),
        "averageConfidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
    }

    load_handoff_events = [event for event in events if event.get("event") == "load-handoff"]

    def distribution(field: str, event_list: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in event_list:
            value = str(event.get(field) or "unspecified")
            counts[value] = counts.get(value, 0) + 1
        return dict(sorted(counts.items()))

    mode_counts = distribution("loadMode", load_handoff_events)
    full_load_count = mode_counts.get("full", 0)
    handoff_loading_metrics = {
        "loadHandoffCount": len(load_handoff_events),
        "modeCounts": mode_counts,
        "compactCount": mode_counts.get("compact", 0),
        "sectionCount": mode_counts.get("section", 0),
        "fullCount": full_load_count,
        "fullLoadRate": percent(full_load_count, len(load_handoff_events)),
        "reasonCodeCounts": distribution("reasonCode", load_handoff_events),
        "sectionCounts": distribution("section", [event for event in load_handoff_events if event.get("section")]),
        "threadRoleCounts": distribution("threadRole", load_handoff_events),
        "compactInsufficientCount": sum(1 for event in load_handoff_events if event.get("reasonCode") == "compact-insufficient"),
    }

    coverage_metrics = current_coverage_metrics(manager, payload)
    for key in ["gitWorktrees", "sidecarActiveTasks", "untrackedWorktrees", "activeTasksWithoutWorktree"]:
        latest = latest_numeric(events, key)
        if latest is not None:
            coverage_metrics[f"latestEvent{key[0].upper()}{key[1:]}"] = latest

    rebuild_values = [int(event.get("estimatedRebuildMinutes")) for event in events if isinstance(event.get("estimatedRebuildMinutes"), int)]
    duplicate_reports = [event for event in events if event.get("duplicateScan") is not None]
    first_step_reports = [event for event in events if event.get("firstStepCorrect") is not None]
    proxy_efficiency = {
        "estimatedRebuildMinutesReports": len(rebuild_values),
        "estimatedRebuildMinutesTotal": sum(rebuild_values),
        "estimatedRebuildMinutesAverage": round(sum(rebuild_values) / len(rebuild_values), 1) if rebuild_values else 0.0,
        "duplicateScanReports": len(duplicate_reports),
        "duplicateScanCount": sum(1 for event in duplicate_reports if event.get("duplicateScan") is True),
        "firstStepCorrectReports": len(first_step_reports),
        "firstStepCorrectCount": sum(1 for event in first_step_reports if event.get("firstStepCorrect") is True),
        "firstStepCorrectRate": percent(sum(1 for event in first_step_reports if event.get("firstStepCorrect") is True), len(first_step_reports)),
        "tokenSavingsClaimed": False,
    }

    if not rebuild_values:
        notes.append("No estimated rebuild minutes were recorded.")
    if not duplicate_reports:
        notes.append("No duplicate scan self-reports were recorded.")
    if not first_step_reports:
        notes.append("No first-step-correct self-reports were recorded.")
    if coverage_metrics.get("worktreeError"):
        notes.append(f"Git worktree coverage had an error: {short_text(str(coverage_metrics['worktreeError']), max_len=200)}")

    return {
        "projectId": manager.project_id,
        "period": period,
        "since": since_text,
        "until": until_text,
        "generatedAt": now_iso(),
        "usageCounts": usage_counts,
        "recoveryMetrics": recovery_metrics,
        "routingMetrics": routing_metrics,
        "handoffLoadingMetrics": handoff_loading_metrics,
        "coverageMetrics": coverage_metrics,
        "proxyEfficiencyMetrics": proxy_efficiency,
        "dataQualityNotes": unique_nonempty(notes),
        "reportPaths": {},
    }


def build_eval_report_markdown(report: dict[str, Any]) -> str:
    usage = report["usageCounts"]
    recovery = report["recoveryMetrics"]
    routing = report["routingMetrics"]
    handoff_loading = report.get("handoffLoadingMetrics", {})
    coverage = report["coverageMetrics"]
    efficiency = report["proxyEfficiencyMetrics"]
    action_counts = usage.get("actionCounts", {})
    lines = [
        f"# Workflow Evaluation Report: {report['projectId']}",
        "",
        "## Summary",
        f"- Period: {report['period']}",
        f"- Since: {report['since'] or 'not specified'}",
        f"- Until: {report['until'] or 'not specified'}",
        f"- Generated At: {report['generatedAt']}",
        "- Scope: workflow proxy metrics only; this report does not claim exact token savings or code correctness.",
        "",
        "## Usage",
        f"- Total events: {usage['totalEvents']}",
    ]
    lines.extend([f"- {name}: {count}" for name, count in action_counts.items()] or ["- No events recorded."])
    lines.extend(
        [
            "",
            "## Recovery Health",
            f"- Handoff availability: {recovery['handoffAvailableCount']}/{recovery['handoffAvailabilityObservations']} ({recovery['handoffAvailabilityRate']}%)",
            f"- Stale observations: {recovery['staleCount']}/{recovery['staleObservations']} ({recovery['staleRate']}%)",
            f"- Missing validation observations: {recovery['missingValidationCount']}",
            f"- Missing safety rule observations: {recovery['missingSafetyRulesCount']}",
            f"- Blocked active tasks: {recovery['blockedTaskCount']}",
            "",
            "## Routing Health",
            f"- Routing events: {routing['routingEventCount']}",
            f"- Resolved: {routing['resolvedCount']} ({routing['resolvedRate']}%)",
            f"- Needs disambiguation: {routing['disambiguationCount']}",
            f"- Failed/no match: {routing['failedOrNoMatchCount']}",
            f"- Average confidence: {routing['averageConfidence']}",
            "",
            "## Handoff Loading",
            f"- Load-handoff events: {handoff_loading.get('loadHandoffCount', 0)}",
            f"- Compact / section / full: {handoff_loading.get('compactCount', 0)} / {handoff_loading.get('sectionCount', 0)} / {handoff_loading.get('fullCount', 0)}",
            f"- Full load rate: {handoff_loading.get('fullLoadRate', 0.0)}%",
            f"- Compact-insufficient count: {handoff_loading.get('compactInsufficientCount', 0)}",
            f"- Reasons: {json.dumps(handoff_loading.get('reasonCodeCounts', {}), ensure_ascii=False)}",
            f"- Sections: {json.dumps(handoff_loading.get('sectionCounts', {}), ensure_ascii=False)}",
            f"- Thread roles: {json.dumps(handoff_loading.get('threadRoleCounts', {}), ensure_ascii=False)}",
            "",
            "## Coverage",
            f"- Git worktrees: {coverage['gitWorktrees']}",
            f"- Active sidecar tasks: {coverage['activeSidecarTasks']}",
            f"- Tracked worktrees: {coverage['trackedWorktrees']}",
            f"- Untracked worktrees: {coverage['untrackedWorktrees']}",
            f"- Active tasks without worktree: {coverage['activeTasksWithoutWorktree']}",
            "",
            "## Proxy Efficiency",
            f"- Estimated rebuild minutes reports: {efficiency['estimatedRebuildMinutesReports']}",
            f"- Estimated rebuild minutes total: {efficiency['estimatedRebuildMinutesTotal']}",
            f"- Duplicate scan reports/count: {efficiency['duplicateScanReports']}/{efficiency['duplicateScanCount']}",
            f"- First-step-correct reports/count: {efficiency['firstStepCorrectReports']}/{efficiency['firstStepCorrectCount']} ({efficiency['firstStepCorrectRate']}%)",
            "- Exact token savings claimed: no",
            "",
            "## Data Quality Notes",
        ]
    )
    lines.extend([f"- {note}" for note in report.get("dataQualityNotes", [])] or ["- No notable data quality issues."])
    return "\n".join(lines) + "\n"


VISUAL_ACTIVE_STATUSES = {"active", "paused", "blocked", "review", "validation"}
VISUAL_LEGEND = {
    "healthy": "handoff, validation, safety rules, clean worktree, current snapshot, and no blocker",
    "attention": "needs a light follow-up such as dirty worktree, recommended action, inferred routing review, missing alias, or minor missing field",
    "blocked": "blocked status, blocker, stale snapshot, or missing handoff/validation/safety rules",
    "archived": "archived context shown only when includeArchive is enabled",
}
VISUAL_TEXT = {
    "en": {
        "title": "Project Visualization",
        "generated_at": "Generated At",
        "sidecar": "Sidecar",
        "canonical_repo": "Canonical Repo",
        "project_graph": "Project Graph",
        "legend": "Legend",
        "details": "Details",
        "task": "Task",
        "parent_task": "Parent Task",
        "phase": "Phase",
        "worktree": "Worktree",
        "thread_role": "Thread Role",
        "thread_label": "Thread Label",
        "routing": "Routing",
        "health": "Health",
        "handoff": "Handoff",
        "validation": "Validation",
        "safety": "Safety",
        "dirty_stale": "Dirty/Stale",
        "action": "Action",
        "needs_attention": "Needs Attention",
        "archive_summary": "Archive Summary",
        "archived_hidden": "Archived hidden",
        "archived_visible": "Archived visible",
        "archived_total": "Archived total",
        "warnings": "Warnings",
        "none": "None.",
        "missing": "missing",
        "needs_review": "needs review",
        "legend_healthy": VISUAL_LEGEND["healthy"],
        "legend_attention": VISUAL_LEGEND["attention"],
        "legend_blocked": VISUAL_LEGEND["blocked"],
        "legend_archived": VISUAL_LEGEND["archived"],
    },
    "zh-CN": {
        "title": "项目可视化",
        "generated_at": "生成时间",
        "sidecar": "Sidecar 路径",
        "canonical_repo": "规范仓库",
        "project_graph": "项目关系图",
        "legend": "图例",
        "details": "详情",
        "task": "任务",
        "worktree": "Worktree",
        "thread_role": "线程角色",
        "thread_label": "线程标签",
        "health": "健康度",
        "handoff": "Handoff",
        "validation": "Validation",
        "safety": "Safety",
        "dirty_stale": "Dirty/Stale",
        "action": "建议行动",
        "needs_attention": "需要关注",
        "archive_summary": "归档摘要",
        "archived_hidden": "已隐藏归档",
        "archived_visible": "已显示归档",
        "archived_total": "归档总数",
        "warnings": "警告",
        "none": "无。",
        "missing": "缺失",
        "needs_review": "需要检查",
        "legend_healthy": "handoff、validation、safety rules 已记录，worktree 干净，快照未过期且无 blocker",
        "legend_attention": "需要轻量跟进，例如 dirty worktree、recommended action、缺 alias 或次要字段缺失",
        "legend_blocked": "blocked 状态、存在 blocker、stale 快照，或缺 handoff/validation/safety rules",
        "legend_archived": "仅在 includeArchive 启用时显示的归档上下文",
    },
}


def visual_text(language: str, key: str) -> str:
    language = normalize_language(language)
    return VISUAL_TEXT.get(language, VISUAL_TEXT["en"]).get(key, VISUAL_TEXT["en"].get(key, key))


def visual_legend(language: str) -> dict[str, str]:
    return {
        "healthy": visual_text(language, "legend_healthy"),
        "attention": visual_text(language, "legend_attention"),
        "blocked": visual_text(language, "legend_blocked"),
        "archived": visual_text(language, "legend_archived"),
    }


def visual_node_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def mermaid_label(value: str, max_len: int = 48) -> str:
    value = short_text(value or "unknown", max_len=max_len)
    return value.replace("\\", "\\\\").replace('"', "'").replace("[", "(").replace("]", ")")


def markdown_cell(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value if str(item).strip())
    text = str(value if value not in (None, "") else "none")
    return text.replace("\n", " ").replace("|", "\\|")


def task_validation_present(task: dict[str, Any]) -> bool:
    validation = task.get("validation") or {}
    return bool(
        validation.get("validatedAt")
        or validation.get("commands")
        or validation.get("results")
        or validation.get("notes")
    )


def visual_health_for_row(row: dict[str, Any]) -> str:
    status = str(row.get("taskStatus") or "").strip()
    if status == "archived":
        return "archived"
    if (
        status == "blocked"
        or row.get("blocker")
        or row.get("stale")
        or not row.get("handoffAvailable")
        or not row.get("validationPresent")
        or not row.get("safetyRulesPresent")
    ):
        return "blocked"
    if row.get("dirty") or row.get("recommendedAction") or row.get("routingNeedsReview") or not row.get("aliases"):
        return "attention"
    return "healthy"


def thread_role_for_row(row: dict[str, Any]) -> str:
    if row.get("threadRole"):
        return str(row.get("threadRole"))
    status = row.get("taskStatus", "")
    if status == "archived":
        return "primary-execution"
    if status == "review":
        return "review"
    return "primary-execution"


def thread_display_label_for_row(row: dict[str, Any]) -> str:
    return str(row.get("threadLabel") or row.get("threadRole") or thread_role_for_row(row))


def load_archived_tasks(manager: SidecarManager) -> list[dict[str, Any]]:
    manager.ensure_layout()
    archived: list[dict[str, Any]] = []
    for path in sorted(manager.archive_dir.glob("*.json")):
        payload = read_json(path, {})
        if isinstance(payload, dict):
            item = dict(payload)
            item["_archivePath"] = str(path)
            archived.append(item)
    return archived


def base_visual_row_from_task(task: dict[str, Any], *, archived: bool = False) -> dict[str, Any]:
    status = "archived" if archived else str(task.get("status") or "active")
    handoff_available = bool(task.get("_handoffAvailable", False))
    row = {
        "taskId": task.get("taskId", ""),
        "branch": task.get("branch", ""),
        "worktreePath": task.get("worktreePath", ""),
        "environmentType": "worktree" if task.get("worktreePath") else "project-level",
        "threadId": "",
        "threadRole": task.get("threadRole", "") or "primary-execution",
        "threadLabel": task.get("threadLabel", ""),
        "threadDisplayLabel": task.get("threadDisplayLabel", "") or task.get("threadLabel", "") or task.get("threadRole", "") or "primary-execution",
        "threadPurpose": task.get("threadPurpose", ""),
        "continuePhrase": task.get("continuePhrase", ""),
        "compactReceipt": task.get("compactReceipt", ""),
        "parentTaskId": task.get("parentTaskId", ""),
        "phase": task.get("phase", ""),
        "routingStatus": task.get("routingStatus", ""),
        "routingConfidence": task.get("routingConfidence", None),
        "routingNeedsReview": bool(task.get("routingNeedsReview", False)),
        "routingEvidence": task.get("routingEvidence", []),
        "routingCandidates": task.get("routingCandidates", []),
        "taskStatus": status,
        "health": "archived" if archived else "attention",
        "handoffAvailable": handoff_available,
        "validationPresent": task_validation_present(task),
        "safetyRulesPresent": bool(task.get("safetyRules")),
        "dirty": bool(task.get("dirtyFiles") or []),
        "dirtyFiles": task.get("dirtyFiles") or [],
        "stale": False,
        "staleReasons": [],
        "blocker": task.get("blocker", ""),
        "nextStep": task.get("nextStep", ""),
        "aliases": task.get("aliases", []),
        "recommendedAction": "",
        "recommendedActionType": "",
        "sidecarHit": True,
        "archived": archived,
        "handoffPath": task.get("_handoffPath", ""),
        "archivePath": task.get("_archivePath", ""),
    }
    row["health"] = visual_health_for_row(row)
    return row


def visual_rows_for_task_threads(base_row: dict[str, Any], task: dict[str, Any]) -> list[dict[str, Any]]:
    threads = ensure_task_threads(
        task,
        mutate=False,
        handoff_available=bool(base_row.get("handoffAvailable")),
        handoff_path=str(base_row.get("handoffPath") or task.get("_handoffPath") or ""),
    )
    rows: list[dict[str, Any]] = []
    for thread in threads:
        row = dict(base_row)
        worktree_path = str(thread.get("worktreePath") or "")
        row.update(
            {
                "threadId": thread.get("threadId", ""),
                "threadRole": thread.get("threadRole", "") or "primary-execution",
                "threadLabel": thread.get("threadLabel", ""),
                "threadDisplayLabel": thread_display_label(thread),
                "threadPurpose": thread.get("threadPurpose", ""),
                "worktreePath": worktree_path,
                "environmentType": thread.get("environmentType", "") or ("worktree" if worktree_path else "project-level"),
                "nextStep": thread.get("nextStep", "") or row.get("nextStep", ""),
                "continuePhrase": thread.get("continuePhrase", "") or row.get("continuePhrase", ""),
                "compactReceipt": thread.get("compactReceipt", "") or row.get("compactReceipt", ""),
                "handoffAvailable": bool(thread.get("handoffAvailable", row.get("handoffAvailable"))),
                "handoffPath": thread.get("handoffPath", "") or row.get("handoffPath", ""),
            }
        )
        if not worktree_path:
            row["dirty"] = False
            row["dirtyFiles"] = []
            row["stale"] = False
            row["staleReasons"] = []
        row["health"] = visual_health_for_row(row)
        rows.append(row)
    return rows


def build_visual_project_payload(manager: SidecarManager, include_archive: bool, language: str) -> dict[str, Any]:
    payload = manager.load_active_tasks()
    tasks = payload.get("tasks", [])
    state = manager.write_project_state(tasks)
    worktrees, worktree_error = parse_git_worktree_list(manager.git.repo_root)

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in worktrees:
        path = item.get("path", "")
        if not path:
            continue
        try:
            wt_manager = SidecarManager(
                Path(path),
                project_id_override=manager.project_id,
                base_branch_override=manager.git.base_branch,
            )
            audit = audit_context_payload(wt_manager, payload, language)
            row = worktree_audit_row(item, audit, wt_manager)
            task = audit.get("task") or {}
            row["aliases"] = task.get("aliases", [])
            row["parentTaskId"] = task.get("parentTaskId", "")
            row["phase"] = task.get("phase", "")
            row["threadRole"] = task.get("threadRole", "")
            row["threadLabel"] = task.get("threadLabel", "")
            row["threadPurpose"] = task.get("threadPurpose", "")
            row["continuePhrase"] = task.get("continuePhrase", "")
            row["compactReceipt"] = task.get("compactReceipt", "")
            row["routingStatus"] = task.get("routingStatus", "")
            row["routingConfidence"] = task.get("routingConfidence", None)
            row["routingNeedsReview"] = bool(task.get("routingNeedsReview", False))
            row["routingEvidence"] = task.get("routingEvidence", [])
            row["routingCandidates"] = task.get("routingCandidates", [])
            row["threadRole"] = thread_role_for_row(row)
            row["threadDisplayLabel"] = thread_display_label_for_row(row)
            row["handoffPath"] = audit.get("handoffPath", "")
            if task:
                rows.extend(visual_rows_for_task_threads(row, task))
            else:
                rows.append(row)
        except Exception as exc:
            errors.append({"worktreePath": path, "error": short_text(str(exc), max_len=500)})

    worktree_paths = {str(Path(row["worktreePath"]).resolve()) for row in rows if row.get("worktreePath")}
    covered_task_ids = {str(row.get("taskId") or "") for row in rows if row.get("taskId")}
    active_tasks = [task for task in tasks if task.get("status", "active") in VISUAL_ACTIVE_STATUSES]
    dogfood_candidates, _ = dogfood_hygiene_records(manager, payload)
    active_without_worktree: list[dict[str, Any]] = []
    for task in active_tasks:
        task_id = str(task.get("taskId") or "")
        if task_id in covered_task_ids:
            continue
        raw_path = str(task.get("worktreePath") or "")
        resolved = str(Path(raw_path).resolve()) if raw_path else ""
        has_worktree = bool(raw_path and resolved in worktree_paths)
        missing_recorded_worktree = bool(raw_path and not has_worktree)
        if missing_recorded_worktree:
            active_without_worktree.append(
                {
                    "taskId": task.get("taskId", ""),
                    "branch": task.get("branch", ""),
                    "worktreePath": raw_path,
                    "status": task.get("status", ""),
                    "updatedAt": task.get("updatedAt", ""),
                }
            )
        task_copy = dict(task)
        task_copy["_handoffPath"] = str(manager.handoff_path_for(task)) if task.get("taskId") else ""
        task_copy["_handoffAvailable"] = bool(task_copy["_handoffPath"] and Path(task_copy["_handoffPath"]).exists())
        row = base_visual_row_from_task(task_copy)
        if has_worktree:
            row["recommendedAction"] = ""
            row["recommendedActionType"] = ""
        elif missing_recorded_worktree:
            row["recommendedAction"] = "active task points to a missing worktree"
            row["recommendedActionType"] = "cleanup-or-recover-missing-worktree"
            row["health"] = "blocked" if row.get("taskStatus") == "blocked" or not row.get("handoffAvailable") else "attention"
        rows.extend(visual_rows_for_task_threads(row, task_copy))

    recommended_actions, _, cleanup_prompts = build_hub_action_prompts(manager, rows, active_without_worktree, language, dogfood_candidates)
    actions_by_key: dict[str, dict[str, Any]] = {}
    for action in recommended_actions:
        keys = [action.get("taskId", "")]
        if action.get("recommendedActionType") != "archive-stale-dogfood-record":
            keys.extend([action.get("worktreePath", ""), action.get("branch", "")])
        for key in keys:
            if key:
                actions_by_key.setdefault(str(key), action)

    task_rows: list[dict[str, Any]] = []
    for row in rows:
        action = (
            actions_by_key.get(str(row.get("taskId") or ""))
            or actions_by_key.get(str(row.get("worktreePath") or ""))
            or actions_by_key.get(str(row.get("branch") or ""))
        )
        if action:
            row["recommendedAction"] = action.get("reason", "")
            row["recommendedActionType"] = action.get("recommendedActionType", "")
        row["health"] = visual_health_for_row(row)
        row["threadRole"] = thread_role_for_row(row)
        row["threadDisplayLabel"] = thread_display_label_for_row(row)
        task_rows.append(
            {
                "taskId": row.get("taskId", "") or row.get("branch", "") or Path(str(row.get("worktreePath") or "")).name or "unknown",
                "branch": row.get("branch", ""),
                "worktreePath": row.get("worktreePath", ""),
                "environmentType": row.get("environmentType", "") or ("worktree" if row.get("worktreePath") else "project-level"),
                "threadId": row.get("threadId", ""),
                "threadRole": row.get("threadRole", "primary-execution"),
                "threadLabel": row.get("threadLabel", ""),
                "threadDisplayLabel": row.get("threadDisplayLabel", "") or row.get("threadLabel", "") or row.get("threadRole", ""),
                "threadPurpose": row.get("threadPurpose", ""),
                "parentTaskId": row.get("parentTaskId", ""),
                "phase": row.get("phase", ""),
                "routingStatus": row.get("routingStatus", ""),
                "routingConfidence": row.get("routingConfidence", None),
                "routingNeedsReview": bool(row.get("routingNeedsReview", False)),
                "routingEvidence": row.get("routingEvidence", []),
                "routingCandidates": row.get("routingCandidates", []),
                "taskStatus": row.get("taskStatus", ""),
                "health": row.get("health", "attention"),
                "handoffAvailable": bool(row.get("handoffAvailable")),
                "validationPresent": bool(row.get("validationPresent")),
                "safetyRulesPresent": bool(row.get("safetyRulesPresent")),
                "dirty": bool(row.get("dirty")),
                "stale": bool(row.get("stale")),
                "blocker": row.get("blocker", ""),
                "recommendedAction": row.get("recommendedAction", ""),
                "recommendedActionType": row.get("recommendedActionType", ""),
                "aliases": row.get("aliases", []),
                "nextStep": row.get("nextStep", ""),
                "sidecarHit": bool(row.get("sidecarHit")),
                "archived": False,
            }
        )

    archived_tasks = load_archived_tasks(manager)
    archived_rows: list[dict[str, Any]] = []
    if include_archive:
        for task in archived_tasks:
            if task.get("taskId"):
                archived_rows.append(base_visual_row_from_task(task, archived=True))
        task_rows.extend(archived_rows)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen_nodes: set[str] = set()
    for row in task_rows:
        task_key = row.get("taskId") or row.get("branch") or row.get("worktreePath") or "unknown"
        task_id = visual_node_id("task", str(task_key))
        parent_task_key = str(row.get("parentTaskId") or "").strip()
        parent_task_id = visual_node_id("task", parent_task_key) if parent_task_key else ""
        environment_path = str(row.get("worktreePath") or "")
        environment_label = Path(environment_path).name if environment_path else ""
        environment_id = visual_node_id("environment", environment_path) if environment_path else ""
        role = str(row.get("threadRole") or "primary-execution")
        role_label = str(row.get("threadDisplayLabel") or row.get("threadLabel") or role)
        role_id = visual_node_id("thread", str(row.get("threadId") or f"{task_key}:{role_label}"))
        node_specs = [
            {"id": task_id, "type": "task", "label": short_text(str(task_key), max_len=40), "health": row.get("health", "attention"), "details": row},
            {
                "id": role_id,
                "type": "thread",
                "label": role_label,
                "health": row.get("health", "attention"),
                "details": {"taskId": task_key, "threadId": row.get("threadId", ""), "threadRole": role, "threadLabel": row.get("threadLabel", ""), "displayLabel": role_label},
            },
        ]
        if environment_path:
            node_specs.append(
                {
                    "id": environment_id,
                    "type": "environment",
                    "label": short_text(environment_label, max_len=40),
                    "health": row.get("health", "attention"),
                    "details": {"environmentType": row.get("environmentType", "worktree"), "worktreePath": environment_path, "branch": row.get("branch", ""), "dirty": row.get("dirty", False), "stale": row.get("stale", False)},
                }
            )
        if parent_task_key:
            parent_details = {"taskId": parent_task_key, "childrenInView": [task_key], "type": "parentTask"}
            node_specs.insert(
                0,
                {
                    "id": parent_task_id,
                    "type": "task",
                    "label": short_text(parent_task_key, max_len=40),
                    "health": row.get("health", "attention"),
                    "details": parent_details,
                },
            )
        for spec in node_specs:
            if spec["id"] not in seen_nodes:
                nodes.append(spec)
                seen_nodes.add(spec["id"])
        if parent_task_key:
            edges.append({"from": parent_task_id, "to": task_id, "label": "child task"})
        edges.append({"from": task_id, "to": role_id, "label": "owned by"})
        if environment_path:
            edges.append({"from": role_id, "to": environment_id, "label": "uses"})

    needs_attention = []
    for row in task_rows:
        if row.get("health") not in {"attention", "blocked"}:
            continue
        reason = (
            row.get("recommendedAction")
            or ("blocked" if row.get("blocker") else "")
            or ("stale" if row.get("stale") else "")
            or ("missing handoff" if not row.get("handoffAvailable") else "")
            or ("missing validation" if not row.get("validationPresent") else "")
            or ("missing safety rules" if not row.get("safetyRulesPresent") else "")
            or ("dirty worktree" if row.get("dirty") else "")
            or ("routing needs review" if row.get("routingNeedsReview") else "")
            or ("missing alias" if not row.get("aliases") else "")
        )
        needs_attention.append(
            {
                "taskId": row.get("taskId", ""),
                "branch": row.get("branch", ""),
                "health": row.get("health", ""),
                "reason": reason,
                "recommendedActionType": row.get("recommendedActionType", ""),
                "threadId": row.get("threadId", ""),
                "threadRole": row.get("threadRole", ""),
                "threadLabel": row.get("threadLabel", ""),
                "environmentType": row.get("environmentType", ""),
                "worktreePath": row.get("worktreePath", ""),
            }
        )

    summary_counts = {
        "visibleTasks": len(task_rows),
        "visibleThreads": len({str(row.get("threadId") or f"{row.get('taskId')}:{row.get('threadDisplayLabel')}") for row in task_rows}),
        "visibleEnvironments": len({str(row.get("worktreePath") or "") for row in task_rows if row.get("worktreePath")}),
        "activeTasks": sum(1 for row in task_rows if row.get("taskStatus") == "active"),
        "pausedTasks": sum(1 for row in task_rows if row.get("taskStatus") == "paused"),
        "blockedTasks": sum(1 for row in task_rows if row.get("taskStatus") == "blocked"),
        "reviewTasks": sum(1 for row in task_rows if row.get("taskStatus") == "review"),
        "archivedVisible": sum(1 for row in task_rows if row.get("archived")),
        "healthy": sum(1 for row in task_rows if row.get("health") == "healthy"),
        "attention": sum(1 for row in task_rows if row.get("health") == "attention"),
        "blocked": sum(1 for row in task_rows if row.get("health") == "blocked"),
        "archived": sum(1 for row in task_rows if row.get("health") == "archived"),
        "gitWorktrees": len(worktrees),
        "sidecarActiveTasks": len(active_tasks),
        "recommendedActions": len(recommended_actions),
        "cleanupPrompts": len(cleanup_prompts),
        "worktreeAuditErrors": len(errors),
    }
    archive_summary = {
        "includeArchive": include_archive,
        "archivedHidden": 0 if include_archive else len(archived_tasks),
        "archivedTotal": len(archived_tasks),
        "archivedVisible": len(archived_rows),
    }
    warnings: list[str] = []
    if worktree_error:
        warnings.append(f"Git worktree inventory error: {short_text(worktree_error, max_len=200)}")
    if errors:
        warnings.append(f"{len(errors)} worktree audit error(s) were omitted from the graph.")

    return {
        "projectId": manager.project_id,
        "generatedAt": now_iso(),
        "language": normalize_language(language),
        "sidecarRoot": str(manager.sidecar_root),
        "canonicalRepoRoot": str(manager.git.repo_root),
        "baseBranch": manager.git.base_branch,
        "projectContext": {
            "id": visual_node_id("project", manager.project_id),
            "label": manager.project_id,
            "sidecarRoot": str(manager.sidecar_root),
            "canonicalRepoRoot": str(manager.git.repo_root),
            "baseBranch": manager.git.base_branch,
            "threadRole": "hub",
        },
        "summaryCounts": summary_counts,
        "nodes": nodes,
        "edges": edges,
        "taskRows": task_rows,
        "legend": visual_legend(language),
        "needsAttention": needs_attention,
        "archiveSummary": archive_summary,
        "recommendedActions": recommended_actions,
        "cleanupPrompts": cleanup_prompts,
        "warnings": warnings,
        "errors": errors,
        "projectStatus": {
            "activeTaskCount": state.get("activeTaskCount", 0),
            "currentBranch": state.get("currentBranch", ""),
        },
        "reportPaths": {},
    }


def build_visual_project_markdown(report: dict[str, Any]) -> str:
    language = str(report.get("language") or "en")
    lines = [
        f"# {visual_text(language, 'title')}: {report['projectId']}",
        "",
        f"- {visual_text(language, 'generated_at')}: {report['generatedAt']}",
        f"- {visual_text(language, 'sidecar')}: {report['sidecarRoot']}",
        f"- {visual_text(language, 'canonical_repo')}: {report['canonicalRepoRoot']}",
        "- Project is context; the main graph is Task -> Thread -> Environment(optional).",
        "",
        f"## {visual_text(language, 'project_graph')}",
        "",
        "```mermaid",
        "graph LR",
    ]
    for node in report.get("nodes", []):
        label = mermaid_label(f"{node.get('label', 'unknown')} [{node.get('health', 'attention')}]")
        lines.append(f'  {node["id"]}["{label}"]')
    for edge in report.get("edges", []):
        label = mermaid_label(edge.get("label", ""), max_len=24)
        lines.append(f'  {edge["from"]} -->|"{label}"| {edge["to"]}')
    lines.extend(
        [
            "  classDef healthy fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20;",
            "  classDef attention fill:#fff8e1,stroke:#f9a825,color:#4e342e;",
            "  classDef blocked fill:#ffebee,stroke:#c62828,color:#4a0000;",
            "  classDef archived fill:#eeeeee,stroke:#757575,color:#424242;",
        ]
    )
    for node in report.get("nodes", []):
        health = node.get("health", "attention")
        if health in VISUAL_LEGEND:
            lines.append(f"  class {node['id']} {health};")
    lines.extend(["```", "", f"## {visual_text(language, 'legend')}"])
    for health, description in report.get("legend", {}).items():
        lines.append(f"- `{health}`: {description}")
    lines.extend(
        [
            "",
            f"## {visual_text(language, 'details')}",
            "",
            f"| {visual_text(language, 'task')} | {visual_text(language, 'parent_task')} | {visual_text(language, 'phase')} | Environment | {visual_text(language, 'thread_role')} | {visual_text(language, 'thread_label')} | Continue | {visual_text(language, 'routing')} | {visual_text(language, 'health')} | {visual_text(language, 'handoff')} | {visual_text(language, 'validation')} | {visual_text(language, 'safety')} | {visual_text(language, 'dirty_stale')} | {visual_text(language, 'action')} |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report.get("taskRows", []):
        dirty_stale = f"dirty={bool_label(bool(row.get('dirty')))}, stale={bool_label(bool(row.get('stale')))}"
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(row.get("taskId") or row.get("branch") or "unknown"),
                    markdown_cell(row.get("parentTaskId", "")),
                    markdown_cell(row.get("phase", "")),
                    markdown_cell(Path(str(row.get("worktreePath") or "")).name or "project-level / none"),
                    markdown_cell(row.get("threadRole", "")),
                    markdown_cell(row.get("threadLabel", "")),
                    markdown_cell(row.get("continuePhrase", "")),
                    markdown_cell(f"{row.get('routingStatus') or 'none'}; review={bool_label(bool(row.get('routingNeedsReview')))}"),
                    markdown_cell(row.get("health", "")),
                    markdown_cell(bool_label(bool(row.get("handoffAvailable")))),
                    markdown_cell(bool_label(bool(row.get("validationPresent")))),
                    markdown_cell(bool_label(bool(row.get("safetyRulesPresent")))),
                    markdown_cell(dirty_stale),
                    markdown_cell(row.get("recommendedAction") or row.get("blocker") or "none"),
                ]
            )
            + " |"
        )
    lines.extend(["", f"## {visual_text(language, 'needs_attention')}"])
    needs_attention = report.get("needsAttention", [])
    if needs_attention:
        for item in needs_attention:
            label = item.get("taskId") or item.get("branch") or Path(str(item.get("worktreePath") or "")).name
            lines.append(f"- `{label or 'unknown'}`: {item.get('health')} - {item.get('reason') or visual_text(language, 'needs_review')}")
    else:
        lines.append(f"- {visual_text(language, 'none')}")
    archive = report.get("archiveSummary", {})
    lines.extend(
        [
            "",
            f"## {visual_text(language, 'archive_summary')}",
            f"- {visual_text(language, 'archived_hidden')}: {archive.get('archivedHidden', 0)}",
            f"- {visual_text(language, 'archived_visible')}: {archive.get('archivedVisible', 0)}",
            f"- {visual_text(language, 'archived_total')}: {archive.get('archivedTotal', 0)}",
        ]
    )
    if report.get("warnings"):
        lines.extend(["", f"## {visual_text(language, 'warnings')}"])
        lines.extend([f"- {warning}" for warning in report.get("warnings", [])])
    return "\n".join(lines) + "\n"


def normalize_query_text(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)
    return " ".join(value.split())


def query_tokens(value: str) -> set[str]:
    return {token for token in normalize_query_text(value).split() if token}


def generated_task_aliases(task: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ["taskId", "branch", "goal"]:
        if task.get(field):
            values.append(str(task[field]))
    worktree_path = str(task.get("worktreePath") or "").strip()
    if worktree_path:
        path = Path(worktree_path)
        values.append(path.name)
        if path.parent.name:
            values.append(f"{path.parent.name} {path.name}")
    for area in task.get("touchedAreas") or []:
        values.append(str(area))
    branch = str(task.get("branch") or "")
    if branch:
        values.extend(part for part in re.split(r"[/_-]+", branch) if len(part) >= 3)
    goal = str(task.get("goal") or "")
    if goal:
        values.extend(" ".join(goal.split()[index : index + 3]) for index in range(max(0, len(goal.split()) - 2)))
    return unique_normalized_nonempty(values, limit=30)


def task_handoff_summary(manager: SidecarManager, task: dict[str, Any]) -> str:
    path = manager.handoff_path_for(task)
    if not path.exists():
        return ""
    try:
        return short_text(path.read_text(encoding="utf-8", errors="replace"), max_len=1200)
    except OSError:
        return ""


def dogfood_hygiene_handoff_text(manager: SidecarManager, task: dict[str, Any]) -> str:
    path = manager.handoff_path_for(task)
    if not path.exists():
        return ""
    try:
        return short_text(path.read_text(encoding="utf-8", errors="replace"), max_len=5000)
    except OSError:
        return ""


def dogfood_hygiene_blob(task: dict[str, Any], handoff_text: str = "") -> str:
    values: list[str] = [
        str(task.get("taskId") or ""),
        str(task.get("goal") or ""),
        str(task.get("threadRole") or ""),
        str(task.get("threadLabel") or ""),
        str(task.get("threadPurpose") or ""),
        str(task.get("blocker") or ""),
        str(task.get("lastThreadSummary") or ""),
        str(task.get("nextStep") or ""),
        str(task.get("status") or ""),
        handoff_text,
    ]
    values.extend(str(item) for item in task.get("aliases") or [])
    values.extend(str(item) for item in task.get("facts") or [])
    values.extend(str(item) for item in task.get("inferences") or [])
    values.extend(str(item) for item in task.get("unknowns") or [])
    validation = task.get("validation") or {}
    values.append(str(validation.get("notes") or ""))
    for item in validation.get("commands") or []:
        values.append(str(item.get("command") if isinstance(item, dict) else item))
    for item in validation.get("results") or []:
        values.append(str(item.get("result") if isinstance(item, dict) else item))
    return "\n".join(value for value in values if value).casefold()


def contains_any_term(text: str, terms: list[str]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        pattern = rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])"
        if re.search(pattern, text):
            matches.append(term)
    return matches


def dogfood_hygiene_archive_command(manager: SidecarManager, task_id: str) -> str:
    return " ".join(
        [
            "hygiene-dogfood",
            "--worktree",
            shlex.quote(str(manager.git.worktree_path)),
            "--project-id",
            shlex.quote(manager.project_id),
            "--confirm-archive",
            "--task-id",
            shlex.quote(task_id),
        ]
    )


def dogfood_hygiene_candidate_record(manager: SidecarManager, task: dict[str, Any]) -> dict[str, Any]:
    handoff_text = dogfood_hygiene_handoff_text(manager, task)
    blob = dogfood_hygiene_blob(task, handoff_text)
    scope_terms = contains_any_term(blob, DOGFOOD_HYGIENE_SCOPE_TERMS)
    failure_terms = contains_any_term(blob, DOGFOOD_HYGIENE_FAILURE_TERMS)
    pass_terms = contains_any_term(blob, DOGFOOD_HYGIENE_PASS_TERMS)
    scope_hit = str(task.get("threadRole") or "") == "dogfood" or bool(scope_terms)
    failure_hit = str(task.get("status") or "") == "blocked" or bool(task.get("blocker")) or bool(failure_terms)
    pass_hit = bool(pass_terms)

    evidence: list[str] = []
    if str(task.get("threadRole") or "") == "dogfood":
        evidence.append("threadRole is dogfood")
    if scope_terms:
        evidence.append(f"dogfood/smoke scope terms: {', '.join(scope_terms[:5])}")
    if str(task.get("status") or "") == "blocked":
        evidence.append("task status is blocked")
    if task.get("blocker"):
        evidence.append("task has blocker text")
    if failure_terms:
        evidence.append(f"old failure terms: {', '.join(failure_terms[:5])}")
    if pass_terms:
        evidence.append(f"later pass terms: {', '.join(pass_terms[:5])}")
    if handoff_text:
        evidence.append("handoff text was inspected")

    is_candidate = bool(scope_hit and failure_hit and pass_hit)
    task_id = str(task.get("taskId") or "")
    reason = (
        DOGFOOD_HYGIENE_ARCHIVE_REASON
        if is_candidate
        else "dogfood/smoke record lacks enough evidence for safe archive"
    )
    return {
        "taskId": task_id,
        "threadRole": task.get("threadRole", ""),
        "threadLabel": task.get("threadLabel", ""),
        "status": task.get("status", "active"),
        "branch": task.get("branch", ""),
        "worktreePath": task.get("worktreePath", ""),
        "blocker": task.get("blocker", ""),
        "updatedAt": task.get("updatedAt", ""),
        "reason": reason,
        "evidence": unique_nonempty(evidence, limit=8),
        "confidence": "high" if is_candidate else "low",
        "recommendedAction": "archive-stale-dogfood-record" if is_candidate else "",
        "archiveCommand": dogfood_hygiene_archive_command(manager, task_id) if is_candidate and task_id else "",
        "isCandidate": is_candidate,
        "scopeMatched": bool(scope_hit),
        "failureMatched": bool(failure_hit),
        "passMatched": bool(pass_hit),
        "handoffPath": str(manager.handoff_path_for(task)),
        "handoffAvailable": manager.handoff_path_for(task).exists(),
    }


def dogfood_hygiene_records(manager: SidecarManager, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    non_recommended: list[dict[str, Any]] = []
    for task in payload.get("tasks", []):
        record = dogfood_hygiene_candidate_record(manager, task)
        if record["isCandidate"]:
            candidates.append(record)
        elif record["scopeMatched"] and record["failureMatched"]:
            non_recommended.append(record)
    return candidates, non_recommended


def score_text_match(query: str, value: str) -> float:
    query_norm = normalize_query_text(query)
    value_norm = normalize_query_text(value)
    if not query_norm or not value_norm:
        return 0.0
    if query_norm == value_norm:
        return 1.0
    if query_norm in value_norm or value_norm in query_norm:
        return 0.86
    q_tokens = query_tokens(query_norm)
    v_tokens = query_tokens(value_norm)
    overlap = len(q_tokens & v_tokens) / len(q_tokens) if q_tokens else 0.0
    ratio = difflib.SequenceMatcher(None, query_norm, value_norm).ratio()
    return max(overlap, ratio * 0.72)


def score_task_candidate(manager: SidecarManager, task: dict[str, Any], query: str) -> dict[str, Any]:
    fields: list[tuple[str, str, float]] = []
    for alias in task.get("aliases") or []:
        fields.append(("aliases", str(alias), 1.0))
    if task.get("continuePhrase"):
        fields.append(("continuePhrase", str(task.get("continuePhrase")), 0.94))
    for alias in generated_task_aliases(task):
        fields.append(("generatedAliases", alias, 0.88))
    for field, weight in [
        ("taskId", 0.82),
        ("branch", 0.8),
        ("worktreePath", 0.74),
        ("goal", 0.62),
        ("lastThreadSummary", 0.52),
    ]:
        value = str(task.get(field) or "")
        if value:
            fields.append((field, Path(value).name if field == "worktreePath" else value, weight))
            if field == "worktreePath":
                fields.append((field, value, weight * 0.86))
    for area in task.get("touchedAreas") or []:
        fields.append(("touchedAreas", str(area), 0.46))
    summary = task_handoff_summary(manager, task)
    if summary:
        fields.append(("handoffSummary", summary, 0.4))

    best_score = 0.0
    matched_fields: list[dict[str, Any]] = []
    for field, value, weight in fields:
        raw = score_text_match(query, value)
        score = raw * weight
        if score >= 0.28:
            matched_fields.append({"field": field, "value": short_text(value, max_len=120), "score": round(score, 3)})
        best_score = max(best_score, score)

    q_tokens = query_tokens(query)
    combined = " ".join(str(task.get(field) or "") for field in ["taskId", "branch", "goal", "lastThreadSummary"])
    combined += " " + " ".join(str(item) for item in task.get("aliases") or [])
    combined += " " + str(task.get("continuePhrase") or "")
    combined += " " + " ".join(str(item) for item in task.get("touchedAreas") or [])
    combined_tokens = query_tokens(combined)
    token_score = (len(q_tokens & combined_tokens) / len(q_tokens)) if q_tokens else 0.0
    confidence = min(1.0, max(best_score, token_score * 0.78))
    matched_fields = sorted(matched_fields, key=lambda item: item["score"], reverse=True)[:5]
    return {
        "taskId": task.get("taskId", ""),
        "branch": task.get("branch", ""),
        "worktreePath": task.get("worktreePath", ""),
        "goal": task.get("goal", ""),
        "status": task.get("status", "active"),
        "parentTaskId": task.get("parentTaskId", ""),
        "phase": task.get("phase", ""),
        "threadRole": task.get("threadRole", ""),
        "threadLabel": task.get("threadLabel", ""),
        "threadPurpose": task.get("threadPurpose", ""),
        "continuePhrase": task.get("continuePhrase", ""),
        "routingStatus": task.get("routingStatus", ""),
        "routingNeedsReview": bool(task.get("routingNeedsReview", False)),
        "confidence": round(confidence, 3),
        "matchedFields": matched_fields,
    }


def read_active_tasks_payload(manager: SidecarManager) -> dict[str, Any]:
    payload = read_json(
        manager.active_tasks_path,
        {"version": SIDECAR_VERSION, "projectId": manager.project_id, "tasks": []},
    )
    if not isinstance(payload, dict):
        payload = {"version": SIDECAR_VERSION, "projectId": manager.project_id, "tasks": []}
    payload.setdefault("version", SIDECAR_VERSION)
    payload.setdefault("projectId", manager.project_id)
    payload.setdefault("tasks", [])
    for task in payload.get("tasks", []):
        if isinstance(task, dict):
            normalize_task_pr_fields(task)
    return payload


def resolve_task_from_payload(manager: SidecarManager, payload: dict[str, Any], query: str, language: str = "en") -> dict[str, Any]:
    candidates = [
        score_task_candidate(manager, task, query)
        for task in payload.get("tasks", [])
        if task.get("status", "active") in VALID_STATUSES
    ]
    candidates = sorted(candidates, key=lambda item: item.get("confidence", 0.0), reverse=True)
    top = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    top_score = float((top or {}).get("confidence", 0.0))
    second_score = float((second or {}).get("confidence", 0.0))
    high_confidence_unique = top_score >= 0.9 and (not second or second_score < 0.9)
    clearly_best = bool(top and top_score >= 0.72 and (top_score - second_score >= 0.14 or high_confidence_unique))
    question = ""
    if not candidates:
        question = tr(language, "resolver_no_match", query=query)
    elif not clearly_best:
        names = [
            f"{item.get('branch') or item.get('taskId')} ({item.get('confidence')})"
            for item in candidates[:3]
        ]
        question = tr(language, "resolver_disambiguation", query=query, candidates=", ".join(names))
    routing_status = "confirmed" if clearly_best else ("ambiguous" if candidates else "provisional")
    return {
        "resolved": clearly_best,
        "confidence": top_score if top else 0.0,
        "routingStatus": routing_status,
        "routingConfidence": top_score if top else 0.0,
        "routingNeedsReview": not clearly_best,
        "routingEvidence": [
            f"query matched {field.get('field')} with score {field.get('score')}"
            for field in (top.get("matchedFields", []) if top else [])[:3]
        ],
        "taskId": top.get("taskId", "") if top else "",
        "branch": top.get("branch", "") if top else "",
        "worktreePath": top.get("worktreePath", "") if top else "",
        "matchedFields": top.get("matchedFields", []) if top else [],
        "candidates": candidates[:5],
        "routingCandidates": candidates[:5] if not clearly_best else [],
        "disambiguationQuestion": question,
    }


def resolve_task_from_manager(manager: SidecarManager, query: str, language: str = "en") -> dict[str, Any]:
    return resolve_task_from_payload(manager, manager.load_active_tasks(), query, language)


def task_by_id(manager: SidecarManager, payload: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for task in payload.get("tasks", []):
        if task.get("taskId") == task_id:
            normalize_task_pr_fields(task, manager.git.pr_search_url)
            return task
    return None


def find_project_configs_for_path(path: Path) -> list[dict[str, Any]]:
    projects_root = Path.home() / ".codex" / "projects"
    if not projects_root.exists():
        return []
    target = path
    with contextlib.suppress(OSError):
        target = path.resolve()
    matches: list[dict[str, Any]] = []
    for config_path in projects_root.glob("*/config.json"):
        payload = read_json(config_path, {})
        roots = []
        for key in ["canonicalRepoRoot", "repoRoot", "currentWorktreePath", "lastWorktreePath"]:
            if payload.get(key):
                roots.append(payload[key])
        roots.extend(payload.get("knownWorktreeRoots") or [])
        roots.extend(payload.get("projectContainerRoots") or [])
        matched_root = ""
        for root in roots:
            try:
                root_path = Path(str(root)).resolve()
            except OSError:
                continue
            try:
                if target == root_path or root_path in target.parents or target in root_path.parents:
                    matched_root = str(root_path)
                    break
            except ValueError:
                continue
        if matched_root:
            matches.append(
                {
                    "projectId": payload.get("projectId") or config_path.parent.name,
                    "configPath": str(config_path),
                    "canonicalRepoRoot": payload.get("canonicalRepoRoot") or payload.get("repoRoot") or "",
                    "currentWorktreePath": payload.get("currentWorktreePath") or payload.get("lastWorktreePath") or "",
                    "knownWorktreeRoots": payload.get("knownWorktreeRoots") or [],
                    "matchedRoot": matched_root,
                }
            )
    return matches


def find_project_config_by_id(project_id: str) -> list[dict[str, Any]]:
    slug = slugify(project_id)
    config_path = Path.home() / ".codex" / "projects" / slug / "config.json"
    payload = read_json(config_path, {})
    if not payload:
        return []
    return [
        {
            "projectId": payload.get("projectId") or slug,
            "configPath": str(config_path),
            "canonicalRepoRoot": payload.get("canonicalRepoRoot") or payload.get("repoRoot") or "",
            "currentWorktreePath": payload.get("currentWorktreePath") or payload.get("lastWorktreePath") or "",
            "knownWorktreeRoots": payload.get("knownWorktreeRoots") or [],
            "matchedRoot": "project-id",
        }
    ]


def project_alias_text(project_id: str, payload: dict[str, Any]) -> str:
    values = [
        project_id,
        project_id.replace("-", " "),
        project_id.replace("_", " "),
        str(payload.get("canonicalRepoRoot") or payload.get("repoRoot") or ""),
        str(payload.get("currentWorktreePath") or payload.get("lastWorktreePath") or ""),
        str(payload.get("remoteUrl") or ""),
    ]
    repo_root = str(payload.get("canonicalRepoRoot") or payload.get("repoRoot") or "")
    if repo_root:
        values.append(Path(repo_root).name)
    remote = str(payload.get("remoteUrl") or "")
    if remote:
        remote_name = re.sub(r"\.git$", "", remote.rstrip("/").split("/")[-1])
        values.extend([remote_name, remote_name.replace("-", " "), remote_name.replace("_", " ")])
    if project_id in {"hyper-h-agent-workflow-hub", "hyper-h-context-handoff", "agent-workflow-hub", "context-handoff"}:
        values.extend(["awh", "agent workflow hub", "context handoff"])
    return " ".join(value for value in values if value)


def all_project_config_matches() -> list[dict[str, Any]]:
    projects_root = Path.home() / ".codex" / "projects"
    if not projects_root.exists():
        return []
    matches: list[dict[str, Any]] = []
    for config_path in projects_root.glob("*/config.json"):
        payload = read_json(config_path, {})
        if not isinstance(payload, dict):
            continue
        project_id = str(payload.get("projectId") or config_path.parent.name)
        matches.append(
            {
                "projectId": project_id,
                "configPath": str(config_path),
                "canonicalRepoRoot": payload.get("canonicalRepoRoot") or payload.get("repoRoot") or "",
                "currentWorktreePath": payload.get("currentWorktreePath") or payload.get("lastWorktreePath") or "",
                "knownWorktreeRoots": payload.get("knownWorktreeRoots") or [],
                "remoteUrl": payload.get("remoteUrl") or "",
                "matchedRoot": "query",
                "aliasText": project_alias_text(project_id, payload),
            }
        )
    return matches


def find_project_configs_by_query(query: str) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for match in all_project_config_matches():
        score = score_text_match(query, str(match.get("aliasText") or ""))
        token_overlap = 0.0
        query_token_set = query_tokens(query)
        alias_token_set = query_tokens(str(match.get("aliasText") or ""))
        if query_token_set:
            token_overlap = len(query_token_set & alias_token_set) / len(query_token_set)
        confidence = round(max(score, token_overlap * 0.92), 3)
        project_id = str(match.get("projectId") or "")
        alias_text = str(match.get("aliasText") or "")
        if "agent workflow hub" in normalize_query_text(query) or "awh" in query_tokens(query):
            if project_id in {"hyper-h-agent-workflow-hub", "agent-workflow-hub", "context-handoff", "hyper-h-context-handoff"}:
                confidence = min(1.0, confidence + 0.28)
            elif "agent workflow hub" in normalize_query_text(alias_text):
                confidence = min(1.0, confidence + 0.08)
        if confidence >= 0.42:
            item = dict(match)
            item.pop("aliasText", None)
            item["confidence"] = confidence
            item["matchedFields"] = ["projectId", "repoRoot", "remoteUrl"]
            scored.append(item)
    return sorted(scored, key=lambda item: item.get("confidence", 0.0), reverse=True)[:5]


def project_resolution_from_manager(manager: SidecarManager, status: str, *, candidates: list[dict[str, Any]] | None = None, evidence: list[str] | None = None) -> dict[str, Any]:
    confidence = 1.0 if status == "confirmed" else 0.78
    return {
        "resolvedProject": True,
        "routingStatus": status,
        "routingConfidence": confidence,
        "routingNeedsReview": status != "confirmed",
        "projectCandidates": candidates or [],
        "routingEvidence": evidence or [],
        "projectId": manager.project_id,
        "worktreePath": str(manager.git.worktree_path),
        "canonicalRepoRoot": str(manager.git.repo_root),
        "nonGitWorktree": not manager.git.is_git_worktree,
    }


def project_id_from_git_identity(git: GitContext) -> str:
    remote_url = git.remote_url.strip()
    if remote_url:
        normalized = remote_url
        if normalized.startswith("git@github.com:"):
            normalized = normalized.replace("git@github.com:", "https://github.com/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/#?]+)", normalized)
        if match:
            owner = match.group("owner")
            repo = match.group("repo")
            if owner.casefold() == "hyper-h" and repo in {"context-handoff", "Agent-Workflow-Hub", "agent-workflow-hub"}:
                return "hyper-h-agent-workflow-hub"
            return slugify(f"{owner}-{repo}")
        return slugify(normalized)
    if git.common_dir:
        common_dir = git.common_dir
        name = common_dir.parent.name if common_dir.name == ".git" else common_dir.name
        return slugify(name)
    return slugify(git.repo_root.name)


def best_worktree_path_from_project_match(match: dict[str, Any], fallback: Path) -> str:
    candidates: list[str] = []
    candidates.extend(str(item) for item in match.get("knownWorktreeRoots") or [])
    for key in ["currentWorktreePath", "canonicalRepoRoot"]:
        if match.get(key):
            candidates.append(str(match[key]))
    candidates = unique_normalized_nonempty(candidates)
    for candidate in candidates:
        ok, _ = detect_git_repo(Path(candidate))
        if ok:
            return candidate
    return candidates[0] if candidates else str(fallback)


def storage_anchor_from_project_match(match: dict[str, Any], fallback: Path) -> str:
    fallback_text = str(fallback)
    fallback_is_git, _ = detect_git_repo(fallback)
    if fallback_text and not fallback_is_git:
        return fallback_text
    candidates = [
        str(match.get("canonicalRepoRoot") or ""),
        str(match.get("currentWorktreePath") or ""),
        *[str(item) for item in match.get("knownWorktreeRoots") or []],
    ]
    for candidate in unique_normalized_nonempty(candidates):
        if candidate:
            return candidate
    return str(fallback)


def infer_orientation_scope(role: str, query: str, explicit_scope: str = "") -> str:
    if explicit_scope:
        return explicit_scope
    normalized = normalize_query_text(query)
    project_terms = [
        "整个",
        "全局",
        "项目",
        "研究路线",
        "路线图",
        "整体",
        "roadmap",
        "overall",
        "project direction",
        "project-level",
        "project level",
        "whole project",
    ]
    if role in {"research", "discussion", "hub"} and any(term in normalized for term in project_terms):
        return "project-level"
    if role == "hub":
        return "project-level"
    return "task-level"


def is_project_level_scope(scope: str) -> bool:
    return scope == "project-level"


def project_level_task_resolution(manager: SidecarManager, query: str, base_resolution: dict[str, Any]) -> dict[str, Any]:
    candidates = base_resolution.get("candidates", []) or []
    return {
        "resolved": False,
        "confidence": 0.0,
        "routingStatus": "provisional",
        "routingConfidence": 0.0,
        "routingNeedsReview": False,
        "routingEvidence": [
            "project-level orientation keeps feature task matches as related candidates",
            "project-level orientation does not use ambiguous task candidates as the target",
        ],
        "taskId": provisional_task_id_for_query(query),
        "branch": "",
        "worktreePath": "",
        "matchedFields": [],
        "candidates": [],
        "routingCandidates": [],
        "relatedCandidates": candidates[:5],
        "disambiguationQuestion": "",
    }


def unique_candidate_list(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = str(candidate.get("taskId") or json.dumps(candidate, ensure_ascii=False, sort_keys=True))
        if key not in unique:
            unique[key] = candidate
    return list(unique.values())[:5]


def mark_project_resolution_storage_anchor(resolution: dict[str, Any], storage_anchor: str, scope: str) -> dict[str, Any]:
    updated = dict(resolution)
    updated.update(
        {
            "worktreePath": "",
            "storageAnchor": storage_anchor,
            "storageAnchorIsGitWorktree": bool(detect_git_repo(Path(storage_anchor))[0]),
            "orientationScope": scope,
            "routingEvidence": unique_normalized_nonempty(
                [
                    *updated.get("routingEvidence", []),
                    "project-level orientation uses storage anchor instead of feature worktree target",
                ],
                limit=20,
            ),
        }
    )
    return updated


def make_manager_for_query(args: argparse.Namespace, language: str = "en") -> tuple[SidecarManager | None, dict[str, Any]]:
    worktree = Path(getattr(args, "worktree", None) or os.getcwd())
    ok, _ = detect_git_repo(worktree)
    explicit_project_id = getattr(args, "project_id", "") or ""
    if ok:
        manager = make_manager(args)
        return manager, {"resolvedProject": True, "projectCandidates": []}
    matches = find_project_config_by_id(explicit_project_id) if explicit_project_id else find_project_configs_for_path(worktree)
    if len(matches) == 1:
        resolved_path = best_worktree_path_from_project_match(matches[0], worktree)
        manager = SidecarManager(
            Path(resolved_path),
            project_id_override=getattr(args, "project_id", "") or str(matches[0].get("projectId") or ""),
            base_branch_override=getattr(args, "base_branch", "") or "",
        )
        return manager, {"resolvedProject": True, "projectCandidates": matches}
    return None, {
        "resolvedProject": False,
        "projectCandidates": matches,
        "disambiguationQuestion": tr(language, "resolver_project_multiple")
        if matches
        else tr(language, "resolver_project_missing"),
    }


def make_manager_for_orientation(args: argparse.Namespace, language: str = "en") -> tuple[SidecarManager | None, dict[str, Any]]:
    worktree = Path(getattr(args, "worktree", None) or os.getcwd())
    ok, _ = detect_git_repo(worktree)
    explicit_project_id = getattr(args, "project_id", "") or ""
    query = getattr(args, "query", "") or ""
    role = normalize_thread_role(getattr(args, "role", "") or "")
    scope = infer_orientation_scope(role, query, getattr(args, "scope", "") or "")
    if ok:
        initial_manager = make_manager(args)
        canonical_project_id = explicit_project_id or project_id_from_git_identity(initial_manager.git)
        manager = SidecarManager(
            worktree,
            project_id_override=canonical_project_id,
            base_branch_override=getattr(args, "base_branch", "") or "",
        )
        resolution = project_resolution_from_manager(
            manager,
            "confirmed",
            evidence=["current path is a Git worktree", "project identity resolved from Git remote/common-dir for thread orientation"],
        )
        if is_project_level_scope(scope):
            config = read_json(manager.config_path, {})
            storage_anchor = str(config.get("canonicalRepoRoot") or manager.git.repo_root)
            resolution = mark_project_resolution_storage_anchor(resolution, storage_anchor, scope)
        return manager, resolution

    matches = find_project_config_by_id(explicit_project_id) if explicit_project_id else find_project_configs_for_path(worktree)
    if len(matches) == 1:
        resolved_path = storage_anchor_from_project_match(matches[0], worktree) if is_project_level_scope(scope) else best_worktree_path_from_project_match(matches[0], worktree)
        manager = SidecarManager(
            Path(resolved_path),
            project_id_override=explicit_project_id or str(matches[0].get("projectId") or ""),
            base_branch_override=getattr(args, "base_branch", "") or "",
        )
        resolution = project_resolution_from_manager(
            manager,
            "inferred",
            candidates=matches,
            evidence=["non-Git path matched one known sidecar project"],
        )
        if is_project_level_scope(scope):
            storage_anchor = storage_anchor_from_project_match(matches[0], worktree)
            resolution = mark_project_resolution_storage_anchor(resolution, storage_anchor, scope)
        return manager, resolution
    if len(matches) > 1:
        return None, {
            "resolvedProject": False,
            "routingStatus": "ambiguous",
            "routingConfidence": 0.0,
            "routingNeedsReview": True,
            "projectCandidates": matches,
            "disambiguationQuestion": tr(language, "resolver_project_multiple"),
            "nonGitWorktree": True,
        }

    query_matches = find_project_configs_by_query(query)
    if query_matches:
        top = query_matches[0]
        second = query_matches[1] if len(query_matches) > 1 else None
        top_score = float(top.get("confidence", 0.0))
        second_score = float((second or {}).get("confidence", 0.0))
        clearly_best = top_score >= 0.62 and (not second or top_score - second_score >= 0.12 or top_score >= 0.88)
        if clearly_best:
            resolved_path = storage_anchor_from_project_match(top, worktree) if is_project_level_scope(scope) else best_worktree_path_from_project_match(top, worktree)
            manager = SidecarManager(
                Path(resolved_path),
                project_id_override=explicit_project_id or str(top.get("projectId") or ""),
                base_branch_override=getattr(args, "base_branch", "") or "",
            )
            resolution = project_resolution_from_manager(
                manager,
                "inferred",
                candidates=query_matches[:3],
                evidence=[f"query matched sidecar project {top.get('projectId')} with confidence {top_score}"],
            )
            if is_project_level_scope(scope):
                storage_anchor = storage_anchor_from_project_match(top, worktree)
                resolution = mark_project_resolution_storage_anchor(resolution, storage_anchor, scope)
            return manager, resolution
        return None, {
            "resolvedProject": False,
            "routingStatus": "ambiguous",
            "routingConfidence": top_score,
            "routingNeedsReview": True,
            "projectCandidates": query_matches[:5],
            "disambiguationQuestion": tr(language, "resolver_project_multiple"),
            "nonGitWorktree": True,
        }

    return None, {
        "resolvedProject": False,
        "routingStatus": "provisional",
        "routingConfidence": 0.0,
        "routingNeedsReview": True,
        "projectCandidates": [],
        "disambiguationQuestion": tr(language, "resolver_project_missing"),
        "nonGitWorktree": not ok,
    }


def make_manager(args: argparse.Namespace) -> SidecarManager:
    return SidecarManager(
        Path(getattr(args, "worktree", None) or os.getcwd()),
        project_id_override=getattr(args, "project_id", "") or "",
        base_branch_override=getattr(args, "base_branch", "") or "",
    )


def resolve_language(args: argparse.Namespace, manager: SidecarManager) -> str:
    explicit = getattr(args, "language", None)
    if explicit:
        return normalize_language(explicit)
    config = manager.sidecar_config()
    return normalize_language(config.get("preferredLanguage") or "en")


def orient_thread_label(role: str, query: str, explicit: str = "") -> str:
    if explicit:
        return short_text(explicit, max_len=120)
    prefix = {
        "hub": "Hub",
        "discussion": "Discussion",
        "research": "Research",
        "primary-execution": "Execution",
        "review": "Review",
        "validation": "Validation",
        "dogfood": "Dogfood",
        "explainer": "Explainer",
    }.get(role, role or "Thread")
    return short_text(f"{prefix} - {query}", max_len=120)


def orient_thread_purpose(role: str, query: str, explicit: str = "") -> str:
    if explicit:
        return short_text(explicit, max_len=320)
    purpose = {
        "hub": f"Maintain project-wide workflow map and route work for {query}.",
        "discussion": f"Shape internal project, product, and engineering tradeoffs for {query}.",
        "research": f"Research external evidence, prior art, ecosystem context, and feasibility for {query}.",
        "primary-execution": f"Implement and validate the task related to {query}.",
        "review": f"Review quality, correctness, risks, and readiness for {query}.",
        "validation": f"Validate behavior, tests, benchmarks, or runtime evidence for {query}.",
        "dogfood": f"Reproduce and report workflow feedback for {query}.",
        "explainer": f"Explain architecture, history, or onboarding context for {query}.",
    }.get(role, f"Orient a {role or 'thread'} thread for {query}.")
    return short_text(purpose, max_len=320)


def provisional_task_id_for_query(query: str) -> str:
    return slugify(query) or "provisional-thread-task"


def role_external_skills(role: str) -> list[dict[str, Any]]:
    if role == "primary-execution":
        return [
            {
                "skill": "domain-specific implementation skills when relevant",
                "roles": ["primary-execution"],
                "reason": "Advisory during startup; use only after the user asks to begin implementation and the task domain clearly benefits from a specialist workflow.",
                "fallback": "Continue with repo-local investigation, implementation, and validation.",
            }
        ]
    skills = []
    for item in ROLE_EXTERNAL_SKILLS.get(role, []):
        copy = dict(item)
        reason = str(copy.get("reason") or "")
        if "Advisory during startup" not in reason:
            copy["reason"] = f"Advisory during startup; use only after the user asks to begin the work. {reason}".strip()
        skills.append(copy)
    return skills


def orient_recommended_next_action(task_resolution: dict[str, Any], attach: bool, attach_requires_confirmation: bool, orientation_scope: str = "task-level") -> str:
    if not attach:
        return "wait-for-user-direction"
    if is_project_level_scope(orientation_scope):
        return "attach-project-thread"
    if task_resolution.get("resolved"):
        return "resume-query"
    if attach:
        return "attach-thread"
    if task_resolution.get("routingStatus") == "provisional":
        return "orient-thread --attach --confirm-route" if attach_requires_confirmation else "orient-thread --attach"
    return "resolve-task"


def orient_next_cli_commands(
    manager: SidecarManager,
    args: argparse.Namespace,
    role: str,
    label: str,
    purpose: str,
    task_resolution: dict[str, Any],
    attach_requires_confirmation: bool,
    orientation_scope: str = "task-level",
    project_resolution: dict[str, Any] | None = None,
) -> list[str]:
    if not getattr(args, "attach", False):
        return []
    return orient_optional_next_cli_commands(manager, args, role, label, purpose, task_resolution, attach_requires_confirmation, orientation_scope, project_resolution)


def orient_optional_next_cli_commands(
    manager: SidecarManager,
    args: argparse.Namespace,
    role: str,
    label: str,
    purpose: str,
    task_resolution: dict[str, Any],
    attach_requires_confirmation: bool,
    orientation_scope: str = "task-level",
    project_resolution: dict[str, Any] | None = None,
) -> list[str]:
    project_resolution = project_resolution or {}
    command_anchor = str(project_resolution.get("storageAnchor") or manager.git.worktree_path)
    quoted_worktree = shlex.quote(command_anchor)
    quoted_project = shlex.quote(manager.project_id)
    quoted_query = shlex.quote(args.query)
    commands: list[str] = []
    if task_resolution.get("resolved") and not is_project_level_scope(orientation_scope):
        commands.append(f"resume-query --worktree {quoted_worktree} --project-id {quoted_project} --query {quoted_query}")
    attach_parts = [
        "orient-thread",
        "--worktree",
        quoted_worktree,
        "--project-id",
        quoted_project,
        "--role",
        shlex.quote(role),
        "--query",
        quoted_query,
        "--thread-label",
        shlex.quote(label),
        "--thread-purpose",
        shlex.quote(purpose),
        "--attach",
    ]
    if orientation_scope:
        attach_parts.extend(["--scope", shlex.quote(orientation_scope)])
    if attach_requires_confirmation:
        attach_parts.append("--confirm-route")
    if getattr(args, "task_id", None) or task_resolution.get("taskId"):
        attach_parts.extend(["--task-id", shlex.quote(str(getattr(args, "task_id", "") or task_resolution.get("taskId") or ""))])
    if getattr(args, "parent_task_id", None):
        attach_parts.extend(["--parent-task-id", shlex.quote(args.parent_task_id)])
    if getattr(args, "phase", None):
        attach_parts.extend(["--phase", shlex.quote(args.phase)])
    commands.append(" ".join(attach_parts))
    return commands


def orient_attach_args(args: argparse.Namespace, role: str, label: str, purpose: str, task_resolution: dict[str, Any], orientation_scope: str = "task-level") -> argparse.Namespace:
    return argparse.Namespace(
        task_id=getattr(args, "task_id", None) or task_resolution.get("taskId") or provisional_task_id_for_query(args.query),
        status="active",
        parent_task_id=getattr(args, "parent_task_id", None),
        phase=getattr(args, "phase", None),
        thread_id=getattr(args, "thread_id", None),
        thread_role=role,
        thread_label=label,
        thread_purpose=purpose,
        confirm_route=getattr(args, "confirm_route", False),
        routing_evidence=[f"orient-thread query: {args.query}", f"orientationScope {orientation_scope}"],
        goal=f"Thread orientation for {args.query}",
        aliases=None,
        next_step="Save a sidecar handoff with durable findings before stopping.",
        blocker=None,
        thread_summary=None,
        pr_url=None,
        touched_areas=None,
        facts=None,
        inferences=None,
        unknowns=None,
        safety_rules=None,
        validation_commands=None,
        validation_results=None,
        validation_tests=None,
        validation_manual=None,
        validation_notes=None,
        validation_at=None,
    )


def orient_task_resolution(manager: SidecarManager, payload: dict[str, Any], query: str, language: str) -> dict[str, Any]:
    resolution = resolve_task_from_payload(manager, payload, query, language)
    if resolution.get("resolved"):
        top_score = float(resolution.get("confidence", 0.0) or 0.0)
        matched_fields = resolution.get("matchedFields", []) or []
        strong_fields = {"aliases", "taskId", "branch", "worktreePath"}
        strong_match = any(str(field.get("field") or "") in strong_fields and float(field.get("score", 0.0) or 0.0) >= 0.72 for field in matched_fields)
        if top_score < 0.84 and not strong_match:
            candidates = resolution.get("candidates", [])
            return {
                "resolved": False,
                "confidence": top_score,
                "routingStatus": "provisional",
                "routingConfidence": top_score,
                "routingNeedsReview": True,
                "routingEvidence": [
                    "query did not strongly match an alias, taskId, branch, or worktree; using provisional orientation"
                ],
                "taskId": provisional_task_id_for_query(query),
                "branch": manager.git.branch,
                "worktreePath": str(manager.git.worktree_path),
                "matchedFields": matched_fields,
                "candidates": candidates[:5],
                "routingCandidates": candidates[:5],
                "disambiguationQuestion": "",
            }
    return resolution


NON_GIT_WORKTREE_GUIDANCE = "Current path is not a Git worktree. Use resume-query with a task nickname or provide a real worktree path."


def allow_non_git_worktree(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "allow_non_git_worktree", False))


def guarded_non_git_write_response(manager: SidecarManager, action: str) -> dict[str, Any]:
    return {
        "projectId": manager.project_id,
        "action": action,
        "guarded": True,
        "nonGitWorktree": True,
        "createdOrUpdated": False,
        "repoMutated": False,
        "sidecarMutated": False,
        "worktreePath": str(manager.git.worktree_path),
        "guidance": NON_GIT_WORKTREE_GUIDANCE,
    }


def task_has_non_git_unknown_warning(manager: SidecarManager, task: dict[str, Any]) -> bool:
    if manager.git.is_git_worktree:
        return False
    return str(task.get("branch") or "") == "unknown" and str(task.get("worktreePath") or "") == str(manager.git.worktree_path)


def cmd_init(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    manager.ensure_layout()
    payload = manager.load_active_tasks()
    manager.log_event("setup", started_at=started_at, sidecar_hit=True, scan_scope="sidecar-layout")
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "sidecarRoot": str(manager.sidecar_root),
                "activeTasksPath": str(manager.active_tasks_path),
                "projectStatePath": str(manager.project_state_path),
                "reportsDir": str(manager.reports_dir),
                "taskCount": len(payload.get("tasks", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    manager = make_manager(args)
    snapshot = {
        "projectId": manager.project_id,
        "projectIdSource": manager.project_id_source,
        "repoRoot": str(manager.git.repo_root),
        "isGitWorktree": manager.git.is_git_worktree,
        "branch": manager.git.branch,
        "baseBranch": manager.git.base_branch,
        "worktreePath": str(manager.git.worktree_path),
        "gitCommonDir": str(manager.git.common_dir) if manager.git.common_dir else "",
        "remoteUrl": manager.git.remote_url,
        "headSha": manager.git.head_sha,
        "upstream": manager.git.upstream,
        "gitStatusSummary": manager.git.git_status_summary,
        "recentCommits": manager.git.recent_commits,
        "touchedFiles": manager.git.touched_files,
        "dirtyFiles": manager.git.dirty_files,
        "dirtyFingerprint": manager.git.dirty_fingerprint,
        "touchedAreas": manager.default_touched_areas(),
        "prUrl": manager.git.pr_url,
        "prSearchUrl": manager.git.pr_search_url,
        "stableDocs": stable_doc_status(manager.git.repo_root),
    }
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    payload = manager.load_active_tasks()
    task, conflicts = manager.find_task(payload)
    provisional = False
    if task is None:
        provisional = True
        task = manager.default_task()
    else:
        normalize_task_pr_fields(task, manager.git.pr_search_url)

    handoff_path = manager.handoff_path_for(task)
    handoff_available = handoff_path.exists()
    output = {
        "projectId": manager.project_id,
        "taskId": task["taskId"],
        "status": task.get("status", "active"),
        "goal": task.get("goal", ""),
        "branch": task.get("branch", manager.git.branch),
        "worktreePath": task.get("worktreePath", str(manager.git.worktree_path)),
        "prUrl": task.get("prUrl", ""),
        "prSearchUrl": task.get("prSearchUrl") or manager.git.pr_search_url,
        "touchedAreas": task.get("touchedAreas", []),
        "nextStep": task.get("nextStep", ""),
        "blocker": task.get("blocker", ""),
        "lastThreadSummary": task.get("lastThreadSummary", ""),
        "handoffPath": str(handoff_path),
        "handoffAvailable": handoff_available,
        "stableDocs": stable_doc_status(manager.git.repo_root),
        "gitStatusSummary": manager.git.git_status_summary,
        "recentCommits": manager.git.recent_commits,
        "touchedFiles": manager.git.touched_files,
        "conflicts": conflicts,
        "provisional": provisional,
        "missingContext": [],
    }

    if provisional:
        output["missingContext"].append("sidecar task not found; using provisional task based on current branch")
    if not handoff_available:
        output["missingContext"].append("latest handoff file not found")
    for doc in output["stableDocs"]:
        if doc["exists"] != "true":
            output["missingContext"].append(f"missing stable doc: {doc['name']}")

    manager.log_event(
        "intake",
        task_id=task["taskId"],
        started_at=started_at,
        sidecar_hit=not provisional,
        handoff_available=handoff_available,
        estimatedRebuildMinutes=args.estimated_rebuild_minutes if args.estimated_rebuild_minutes is not None else None,
        duplicateScan=args.duplicate_scan,
        firstStepCorrect=args.first_step_correct,
        notes=args.notes or "",
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_start_feature(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    if not manager.git.is_git_worktree and not allow_non_git_worktree(args):
        print(json.dumps(guarded_non_git_write_response(manager, "start-feature"), ensure_ascii=False, indent=2))
        return 0
    payload = manager.load_active_tasks()
    route = route_guard_for_write(manager, payload, args, "start-feature")
    if route.get("routeStatus") in {"mismatch", "ambiguous"}:
        print(json.dumps({"projectId": manager.project_id, "action": "start-feature", **route}, ensure_ascii=False, indent=2))
        return 0
    tasks = payload.get("tasks", [])
    branch_matches = [item for item in tasks if item.get("branch") == manager.git.branch]
    worktree_matches = [item for item in tasks if item.get("worktreePath") == str(manager.git.worktree_path)]
    candidates = sorted(branch_matches, key=lambda item: item.get("updatedAt", ""), reverse=True)
    if not candidates and worktree_matches:
        conflicts = [item.get("taskId", "<unknown>") for item in worktree_matches]
        task = sorted(worktree_matches, key=lambda item: item.get("updatedAt", ""), reverse=True)[0]
        snapshot = manager.task_snapshot(task, conflicts)
        snapshot.update(
            {
                "createdOrUpdated": False,
                "requestedBranch": manager.git.branch,
                "resolution": "Current worktree already has an active task for another branch; finish or hand off that task before starting a new branch in this worktree.",
            }
        )
        manager.log_event(
            "start",
            task_id=task["taskId"],
            started_at=started_at,
            sidecar_hit=True,
            handoff_available=snapshot["handoffAvailable"],
            conflict=True,
            requestedBranch=manager.git.branch,
        )
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    explicit_task_id = bool(getattr(args, "task_id", None))
    task = task_by_id(manager, payload, slugify(args.task_id)) if explicit_task_id else None
    if task is None and not explicit_task_id:
        task = candidates[0] if candidates else None
    conflicts = [] if explicit_task_id else [item.get("taskId", "<unknown>") for item in candidates[1:]]
    sidecar_hit = task is not None
    task = manager.upsert_task(payload, task, args, route=route)
    current_thread = upsert_current_thread(task, args)
    manager.save_active_tasks(payload)
    snapshot = manager.task_snapshot(task, conflicts)
    manager.log_event(
        "start",
        task_id=task["taskId"],
        started_at=started_at,
        sidecar_hit=sidecar_hit,
        handoff_available=snapshot["handoffAvailable"],
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_alias_task(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    payload = manager.load_active_tasks()
    task = task_by_id(manager, payload, slugify(args.task_id)) if getattr(args, "task_id", None) else None
    conflicts: list[str] = []
    if task is None:
        task, conflicts = manager.find_task(payload)
    if task is None:
        raise SystemExit("no matching task to alias")

    before = list(task.get("aliases") or [])
    add_aliases = normalized_note_list(getattr(args, "aliases", None), limit=20, max_len=80)
    remove_keys = {normalized_dedupe_key(item) for item in (getattr(args, "remove_aliases", None) or []) if item.strip()}
    aliases = unique_normalized_nonempty([*before, *add_aliases], limit=20)
    if remove_keys:
        aliases = [item for item in aliases if normalized_dedupe_key(item) not in remove_keys]
    task["aliases"] = aliases
    task["updatedAt"] = now_iso()
    manager.save_active_tasks(payload)
    manager.log_event(
        "alias-task",
        task_id=task.get("taskId", ""),
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=manager.handoff_path_for(task).exists(),
        aliasesAdded=[item for item in aliases if normalized_dedupe_key(item) not in {normalized_dedupe_key(old) for old in before}],
        aliasesRemoved=[item for item in before if normalized_dedupe_key(item) in remove_keys],
    )
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "taskId": task.get("taskId", ""),
                "aliases": aliases,
                "removedAliases": [item for item in before if normalized_dedupe_key(item) in remove_keys],
                "conflicts": conflicts,
                "activeTasksPath": str(manager.active_tasks_path),
                "repoMutated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_attach_thread(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    if not manager.git.is_git_worktree and not allow_non_git_worktree(args):
        print(json.dumps(guarded_non_git_write_response(manager, "attach-thread"), ensure_ascii=False, indent=2))
        return 0
    payload = manager.load_active_tasks()
    route = route_guard_for_write(manager, payload, args, "attach-thread")
    if route.get("routeStatus") in {"mismatch", "ambiguous"}:
        print(json.dumps({"projectId": manager.project_id, "action": "attach-thread", **route}, ensure_ascii=False, indent=2))
        return 0
    task = task_by_id(manager, payload, slugify(args.task_id)) if getattr(args, "task_id", None) else None
    conflicts: list[str] = []
    if task is None:
        task, conflicts = manager.find_task(payload)
    sidecar_hit = task is not None
    task = manager.upsert_task(payload, task, args, route=route)
    manager.save_active_tasks(payload)
    manager.log_event(
        "attach-thread",
        task_id=task.get("taskId", ""),
        started_at=started_at,
        sidecar_hit=sidecar_hit,
        handoff_available=manager.handoff_path_for(task).exists(),
        threadRole=task.get("threadRole", ""),
        phase=task.get("phase", ""),
        routingStatus=task.get("routingStatus", ""),
        routingNeedsReview=bool(task.get("routingNeedsReview", False)),
    )
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "taskId": task.get("taskId", ""),
                "parentTaskId": task.get("parentTaskId", ""),
                "phase": task.get("phase", ""),
                "threadRole": task.get("threadRole", ""),
                "threadLabel": task.get("threadLabel", ""),
                "threadPurpose": task.get("threadPurpose", ""),
                "threadId": current_thread.get("threadId", ""),
                "threads": compact_thread_entries(ensure_task_threads(task, mutate=False)),
                "continuePhrase": task.get("continuePhrase", ""),
                "routingStatus": task.get("routingStatus", ""),
                "routingConfidence": task.get("routingConfidence", None),
                "routingNeedsReview": bool(task.get("routingNeedsReview", False)),
                "routingEvidence": task.get("routingEvidence", []),
                "routingCandidates": task.get("routingCandidates", []),
                "conflicts": conflicts,
                "activeTasksPath": str(manager.active_tasks_path),
                "repoMutated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_orient_thread(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    requested_role = getattr(args, "role", "") or ""
    role = normalize_thread_role(requested_role)
    warnings: list[str] = []
    if requested_role and role != slugify(requested_role):
        warnings.append(f"threadRole alias normalized: {requested_role} -> {role}")
    if role not in VALID_THREAD_ROLES:
        warnings.append(f"Unknown threadRole preserved as-is: {role}")

    language = normalize_language(getattr(args, "language", "") or "en")
    orientation_scope = infer_orientation_scope(role, getattr(args, "query", "") or "", getattr(args, "scope", "") or "")
    manager, project_resolution = make_manager_for_orientation(args, language)
    if manager is None:
        output = {
            "action": "orient-thread",
            "repoMutated": False,
            "sidecarMutated": False,
            "projectId": "",
            "projectResolution": project_resolution,
            "threadRole": role,
            "threadLabel": orient_thread_label(role, args.query, getattr(args, "thread_label", "") or ""),
            "threadPurpose": orient_thread_purpose(role, args.query, getattr(args, "thread_purpose", "") or ""),
            "orientationScope": orientation_scope,
            "query": args.query,
            "taskResolution": {
                "resolved": False,
                "routingStatus": "provisional",
                "taskId": provisional_task_id_for_query(args.query),
                "candidates": [],
                "disambiguationQuestion": project_resolution.get("disambiguationQuestion", ""),
            },
            "roleBoundary": ROLE_BOUNDARIES.get(role, ROLE_BOUNDARIES["discussion"]),
            "startupProtocol": ORIENT_STARTUP_PROTOCOL,
            "recommendedNextAction": "ask-disambiguation",
            "nextCliCommands": [],
            "optionalNextCliCommands": [],
            "handoffRequirements": ORIENT_HANDOFF_REQUIREMENTS,
            "hubReceiptExpected": ORIENT_HUB_RECEIPT_FIELDS,
            "suggestedExternalSkills": role_external_skills(role),
            "warnings": warnings,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    language = normalize_language(getattr(args, "language", "") or "en")
    read_only_payload = read_active_tasks_payload(manager)
    base_task_resolution = orient_task_resolution(manager, read_only_payload, args.query, language)
    task_resolution = (
        project_level_task_resolution(manager, args.query, base_task_resolution)
        if is_project_level_scope(orientation_scope)
        else base_task_resolution
    )
    if getattr(args, "task_id", None):
        payload = read_only_payload
        task = task_by_id(manager, payload, slugify(args.task_id))
        if task and not is_project_level_scope(orientation_scope):
            task_resolution = {
                "resolved": True,
                "confidence": 1.0,
                "routingStatus": "confirmed",
                "routingConfidence": 1.0,
                "routingNeedsReview": False,
                "routingEvidence": [f"explicit --task-id matched {slugify(args.task_id)}"],
                "taskId": task.get("taskId", ""),
                "branch": task.get("branch", ""),
                "worktreePath": task.get("worktreePath", ""),
                "matchedFields": [{"field": "taskId", "value": task.get("taskId", ""), "score": 1.0}],
                "candidates": [score_task_candidate(manager, task, args.query)],
                "routingCandidates": [],
                "disambiguationQuestion": "",
            }
        elif is_project_level_scope(orientation_scope):
            task_resolution["taskId"] = slugify(args.task_id)
            if task:
                task_resolution["relatedCandidates"] = unique_candidate_list([score_task_candidate(manager, task, args.query), *task_resolution.get("relatedCandidates", [])])
                task_resolution["routingEvidence"] = unique_normalized_nonempty(
                    [
                        *task_resolution.get("routingEvidence", []),
                        f"explicit --task-id {slugify(args.task_id)} used as project-level task id; existing task git scope was not treated as route target",
                    ],
                    limit=20,
                )
    if not task_resolution.get("resolved"):
        task_resolution["taskId"] = getattr(args, "task_id", None) or provisional_task_id_for_query(args.query)
        if is_project_level_scope(orientation_scope):
            task_resolution["branch"] = ""
            task_resolution["worktreePath"] = ""
        else:
            task_resolution.setdefault("branch", manager.git.branch)
            task_resolution.setdefault("worktreePath", str(manager.git.worktree_path))

    label = orient_thread_label(role, args.query, getattr(args, "thread_label", "") or "")
    purpose = orient_thread_purpose(role, args.query, getattr(args, "thread_purpose", "") or "")
    project_status = project_resolution.get("routingStatus", "confirmed")
    task_status = task_resolution.get("routingStatus", "provisional")
    attach_requested = bool(getattr(args, "attach", False))
    attach_requires_confirmation = bool(
        project_status != "confirmed"
        or task_status in {"ambiguous", "mismatch"}
        or project_resolution.get("nonGitWorktree")
    )
    if is_project_level_scope(orientation_scope):
        attach_requires_confirmation = False
    attach_allowed = attach_requested and (not attach_requires_confirmation or bool(getattr(args, "confirm_route", False)))
    sidecar_mutated = False
    attach_result: dict[str, Any] = {}

    if attach_requested and not attach_allowed:
        warnings.append("Attach refused: inferred, ambiguous, mismatch, or non-Git-derived route requires --confirm-route.")
    elif attach_allowed:
        payload = manager.load_active_tasks()
        task = task_by_id(manager, payload, slugify(getattr(args, "task_id", "") or task_resolution.get("taskId", "")))
        if task is None and task_resolution.get("resolved"):
            task = task_by_id(manager, payload, task_resolution.get("taskId", ""))
        route_status = "confirmed" if bool(getattr(args, "confirm_route", False)) else str(task_resolution.get("routingStatus") or project_status or "confirmed")
        if route_status == "confirmed" and project_status != "confirmed":
            route_status = "inferred"
        if is_project_level_scope(orientation_scope):
            route_status = "confirmed" if bool(getattr(args, "confirm_route", False)) else "provisional"
        route = route_result(
            route_status,
            routingNeedsReview=False if is_project_level_scope(orientation_scope) and bool(getattr(args, "confirm_route", False)) else project_status != "confirmed" or task_resolution.get("routingNeedsReview", False),
            routingConfidence=min(
                float(project_resolution.get("routingConfidence", 1.0) or 0.0),
                float(task_resolution.get("routingConfidence", task_resolution.get("confidence", 0.75)) or 0.0),
            ),
            routingEvidence=unique_normalized_nonempty(
                [
                    *project_resolution.get("routingEvidence", []),
                    *task_resolution.get("routingEvidence", []),
                    f"orient-thread role {role}",
                    f"orientationScope {orientation_scope}",
                ],
                limit=20,
            ),
            routingCandidates=task_resolution.get("routingCandidates", []) or task_resolution.get("relatedCandidates", []) or task_resolution.get("candidates", [])[:5],
        )
        attach_args = orient_attach_args(args, role, label, purpose, task_resolution, orientation_scope)
        if is_project_level_scope(orientation_scope):
            attach_args.project_level_orientation = True
            attach_args.storage_anchor = str(project_resolution.get("storageAnchor") or manager.git.worktree_path)
        task = manager.upsert_task(
            payload,
            task,
            attach_args,
            route=route,
        )
        current_thread = upsert_current_thread(task, attach_args)
        if is_project_level_scope(orientation_scope):
            task["orientationScope"] = orientation_scope
            task["storageAnchor"] = str(project_resolution.get("storageAnchor") or manager.git.worktree_path)
            task["branch"] = ""
            task["worktreePath"] = ""
            task["repoRoot"] = str(project_resolution.get("storageAnchor") or manager.git.repo_root)
            task["headSha"] = ""
            task["upstream"] = ""
            task["dirtyFiles"] = []
            task["dirtyFingerprint"] = ""
            if project_resolution.get("storageAnchor"):
                task["routingEvidence"] = unique_normalized_nonempty(
                    [
                        *task.get("routingEvidence", []),
                        "project-level task stores storageAnchor only; branch/worktree scope intentionally left empty",
                    ],
                    limit=30,
                )
            current_thread = upsert_current_thread(task, attach_args)
        manager.save_active_tasks(payload)
        sidecar_mutated = True
        attach_result = {
            "taskId": task.get("taskId", ""),
            "threadId": current_thread.get("threadId", ""),
            "threadRole": task.get("threadRole", ""),
            "threadLabel": task.get("threadLabel", ""),
            "threadPurpose": task.get("threadPurpose", ""),
            "threads": compact_thread_entries(ensure_task_threads(task, mutate=False)),
            "routingStatus": task.get("routingStatus", ""),
            "routingConfidence": task.get("routingConfidence", None),
            "routingNeedsReview": bool(task.get("routingNeedsReview", False)),
            "orientationScope": task.get("orientationScope", ""),
            "storageAnchor": task.get("storageAnchor", ""),
            "activeTasksPath": str(manager.active_tasks_path),
        }
        task_resolution["taskId"] = task.get("taskId", task_resolution.get("taskId", ""))

    recommended_action = orient_recommended_next_action(task_resolution, attach_requested, attach_requires_confirmation, orientation_scope)
    output = {
        "action": "orient-thread",
        "repoMutated": False,
        "sidecarMutated": sidecar_mutated,
        "projectId": manager.project_id,
        "sidecarRoot": str(manager.sidecar_root),
        "projectResolution": project_resolution,
        "threadRole": role,
        "requestedRole": requested_role,
        "threadLabel": label,
        "threadPurpose": purpose,
        "orientationScope": orientation_scope,
        "query": args.query,
        "taskResolution": task_resolution,
        "roleBoundary": ROLE_BOUNDARIES.get(role, ROLE_BOUNDARIES["discussion"]),
        "startupProtocol": ORIENT_STARTUP_PROTOCOL,
        "recommendedNextAction": recommended_action,
        "nextCliCommands": orient_next_cli_commands(manager, args, role, label, purpose, task_resolution, attach_requires_confirmation, orientation_scope, project_resolution),
        "optionalNextCliCommands": [] if attach_requested else orient_optional_next_cli_commands(manager, args, role, label, purpose, task_resolution, attach_requires_confirmation, orientation_scope, project_resolution),
        "handoffRequirements": ORIENT_HANDOFF_REQUIREMENTS,
        "hubReceiptExpected": ORIENT_HUB_RECEIPT_FIELDS,
        "suggestedExternalSkills": role_external_skills(role),
        "warnings": warnings,
    }
    if attach_result:
        output["attached"] = attach_result

    if sidecar_mutated:
        manager.log_event(
            "orient-thread",
            task_id=task_resolution.get("taskId", ""),
            started_at=started_at,
            sidecar_hit=bool(task_resolution.get("resolved")),
            handoff_available=None,
            scan_scope="thread-orientation",
            role=role,
            query=args.query,
            resolvedProject=bool(project_resolution.get("resolvedProject")),
            resolvedTask=bool(task_resolution.get("resolved")),
            routingStatus=task_resolution.get("routingStatus", project_resolution.get("routingStatus", "")),
            orientationScope=orientation_scope,
            sidecarMutated=sidecar_mutated,
            suggestedExternalSkillCount=len(role_external_skills(role)),
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_resolve_task(args: argparse.Namespace) -> int:
    language = normalize_language(getattr(args, "language", "") or "en")
    manager, project_resolution = make_manager_for_query(args, language)
    if manager is None:
        print(
            json.dumps(
                {
                    "resolved": False,
                    "confidence": 0.0,
                    "projectResolution": project_resolution,
                    "candidates": [],
                    "disambiguationQuestion": project_resolution.get("disambiguationQuestion", ""),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    language = resolve_language(args, manager)
    result = resolve_task_from_manager(manager, args.query, language)
    result.update(
        {
            "projectId": manager.project_id,
            "projectResolution": project_resolution,
            "sidecarRoot": str(manager.sidecar_root),
        }
    )
    manager.log_event(
        "resolve-task",
        task_id=result.get("taskId", ""),
        sidecar_hit=bool(result.get("resolved")),
        handoff_available=None,
        scan_scope="sidecar-task-resolver",
        query=args.query,
        resolved=bool(result.get("resolved")),
        needsDisambiguation=bool(result.get("disambiguationQuestion")),
        confidence=result.get("confidence", 0.0),
        candidateCount=len(result.get("candidates", [])),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_resume_query(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    language = normalize_language(getattr(args, "language", "") or "en")
    manager, project_resolution = make_manager_for_query(args, language)
    if manager is None:
        print(
            json.dumps(
                {
                    "resolved": False,
                    "confidence": 0.0,
                    "projectResolution": project_resolution,
                    "candidates": [],
                    "disambiguationQuestion": project_resolution.get("disambiguationQuestion", ""),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    language = resolve_language(args, manager)
    resolution = resolve_task_from_manager(manager, args.query, language)
    if not resolution.get("resolved"):
        resolution.update({"projectId": manager.project_id, "projectResolution": project_resolution})
        manager.log_event(
            "resume-query",
            started_at=started_at,
            task_id=resolution.get("taskId", ""),
            sidecar_hit=False,
            handoff_available=None,
            scan_scope="sidecar-task-resolver",
            query=args.query,
            resolved=False,
            needsDisambiguation=bool(resolution.get("disambiguationQuestion")),
            confidence=resolution.get("confidence", 0.0),
            candidateCount=len(resolution.get("candidates", [])),
        )
        print(json.dumps(resolution, ensure_ascii=False, indent=2))
        return 0

    resolved_manager = SidecarManager(
        Path(resolution.get("worktreePath") or manager.git.worktree_path),
        project_id_override=getattr(args, "project_id", "") or manager.project_id,
        base_branch_override=getattr(args, "base_branch", "") or manager.git.base_branch,
    )
    language = resolve_language(args, resolved_manager)
    payload = resolved_manager.load_active_tasks()
    task = task_by_id(resolved_manager, payload, resolution.get("taskId", ""))
    conflicts: list[str] = []
    if task is None:
        task, conflicts = resolved_manager.find_task(payload)
    sidecar_hit = task is not None
    if task is None:
        task = resolved_manager.default_task()
    resume = build_resume_payload(resolved_manager, task, conflicts, sidecar_hit, language)
    output = {
        "resolved": True,
        "confidence": resolution.get("confidence", 0.0),
        "query": args.query,
        "projectId": resolved_manager.project_id,
        "projectResolution": project_resolution,
        "taskId": task.get("taskId", ""),
        "parentTaskId": task.get("parentTaskId", ""),
        "phase": task.get("phase", ""),
        "threadRole": task.get("threadRole", ""),
        "threadLabel": task.get("threadLabel", ""),
        "threadPurpose": task.get("threadPurpose", ""),
        "continuePhrase": task.get("continuePhrase", ""),
        "compactReceipt": task.get("compactReceipt", ""),
        "routingStatus": task.get("routingStatus", resolution.get("routingStatus", "")),
        "routingConfidence": task.get("routingConfidence", resolution.get("routingConfidence", resolution.get("confidence", 0.0))),
        "routingNeedsReview": bool(task.get("routingNeedsReview", resolution.get("routingNeedsReview", False))),
        "routingEvidence": task.get("routingEvidence", resolution.get("routingEvidence", [])),
        "branch": resolved_manager.git.branch,
        "worktreePath": str(resolved_manager.git.worktree_path),
        "cd": str(resolved_manager.git.worktree_path),
        "headSha": resolved_manager.git.head_sha,
        "dirty": bool(resolved_manager.git.dirty_files),
        "dirtyFiles": resolved_manager.git.dirty_files,
        "nextStep": task.get("nextStep", ""),
        "blocker": task.get("blocker", ""),
        "validation": task.get("validation", {}),
        "safetyRules": task.get("safetyRules", []),
        "matchedFields": resolution.get("matchedFields", []),
        "resume": resume,
        "startThreadSummary": resume.get("startThreadSummary", ""),
    }
    resolved_manager.log_event(
        "resume-query",
        started_at=started_at,
        task_id=task.get("taskId", ""),
        sidecar_hit=sidecar_hit,
        handoff_available=resume.get("handoffAvailable"),
        scan_scope="sidecar-task-resolver",
        query=args.query,
        resolved=True,
        needsDisambiguation=False,
        confidence=resolution.get("confidence", 0.0),
        candidateCount=len(resolution.get("candidates", [])),
        stale=bool((resume.get("stale") or {}).get("isStale")),
        validationPresent=bool((task.get("validation") or {}).get("validatedAt") or (task.get("validation") or {}).get("commands") or (task.get("validation") or {}).get("results") or (task.get("validation") or {}).get("notes")),
        safetyRulesPresent=bool(task.get("safetyRules")),
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_resume_feature(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    payload = manager.load_active_tasks()
    task, conflicts = manager.find_task(payload)
    sidecar_hit = task is not None
    if task is None:
        task = manager.default_task()

    snapshot = build_resume_payload(manager, task, conflicts, sidecar_hit, language)
    manager.log_event(
        "resume",
        task_id=task["taskId"],
        started_at=started_at,
        sidecar_hit=sidecar_hit,
        handoff_available=snapshot["handoffAvailable"],
        estimatedRebuildMinutes=args.estimated_rebuild_minutes if args.estimated_rebuild_minutes is not None else None,
        duplicateScan=args.duplicate_scan,
        firstStepCorrect=args.first_step_correct,
        notes=args.notes or "",
        stale=bool((snapshot.get("stale") or {}).get("isStale")),
        validationPresent=bool((task.get("validation") or {}).get("validatedAt") or (task.get("validation") or {}).get("commands") or (task.get("validation") or {}).get("results") or (task.get("validation") or {}).get("notes")),
        safetyRulesPresent=bool(task.get("safetyRules")),
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def build_resume_payload(
    manager: SidecarManager,
    task: dict[str, Any],
    conflicts: list[str],
    sidecar_hit: bool,
    language: str,
) -> dict[str, Any]:
    snapshot = manager.task_snapshot(task, conflicts)
    stale = stale_detection(task, manager.git)
    snapshot.update(
        {
            "stableDocs": stable_doc_status(manager.git.repo_root),
            "gitStatusSummary": manager.git.git_status_summary,
            "recentCommits": manager.git.recent_commits,
            "touchedFiles": manager.git.touched_files,
            "headSha": manager.git.head_sha,
            "upstream": manager.git.upstream,
            "dirtyFiles": manager.git.dirty_files,
            "dirtyFingerprint": manager.git.dirty_fingerprint,
            "nonGitWorktree": not manager.git.is_git_worktree,
            "warnings": [],
            "stale": stale,
            "startThreadSummary": build_start_thread_summary(manager, task, snapshot["handoffAvailable"], stale, language),
            "missingContext": [],
            "provisional": not sidecar_hit,
        }
    )
    if not sidecar_hit:
        snapshot["missingContext"].append("sidecar task not found; using provisional task based on current branch")
    if not manager.git.is_git_worktree:
        snapshot["warnings"].append("Current path is not a Git worktree; prefer resume-query with a task nickname or provide a real worktree path.")
        snapshot["guidance"] = NON_GIT_WORKTREE_GUIDANCE
        snapshot["missingContext"].append("current path is not a Git worktree")
    if task_has_non_git_unknown_warning(manager, task):
        snapshot["warnings"].append("Matched task has branch=unknown on a non-Git path; this may be a historical container task and was not automatically cleaned.")
    if not snapshot["handoffAvailable"]:
        snapshot["missingContext"].append("latest handoff file not found")
    for doc in snapshot["stableDocs"]:
        if doc["exists"] != "true":
            snapshot["missingContext"].append(f"missing stable doc: {doc['name']}")
    return snapshot


def audit_context_payload(manager: SidecarManager, payload: dict[str, Any] | None = None, language: str = "en") -> dict[str, Any]:
    payload = payload or manager.load_active_tasks()
    task, conflicts = manager.find_task(payload)
    sidecar_hit = task is not None
    if task is None:
        task = manager.default_task()

    handoff_path = manager.handoff_path_for(task)
    handoff_available = handoff_path.exists()
    stale = stale_detection(task, manager.git)
    validation = task.get("validation") or {}
    missing_validation = not (
        validation.get("validatedAt")
        or validation.get("commands")
        or validation.get("results")
        or validation.get("notes")
    )
    missing_safety_rules = not bool(task.get("safetyRules"))
    missing_handoff = not handoff_available
    dirty_worktree = bool(manager.git.dirty_files)

    findings: list[dict[str, Any]] = []
    if missing_handoff:
        findings.append({"kind": "missing-handoff", "message": tr(language, "finding_missing_handoff")})
    if stale["isStale"]:
        findings.append({"kind": "stale", "message": tr(language, "finding_stale"), "details": stale})
    if missing_validation:
        findings.append({"kind": "missing-validation", "message": tr(language, "finding_missing_validation")})
    if missing_safety_rules:
        findings.append({"kind": "missing-safety-rules", "message": tr(language, "finding_missing_safety_rules")})
    if dirty_worktree:
        findings.append({"kind": "dirty-worktree", "message": tr(language, "finding_dirty_worktree"), "files": manager.git.dirty_files})
    if not sidecar_hit:
        findings.append({"kind": "missing-task", "message": tr(language, "finding_missing_task")})
    warnings: list[str] = []
    if not manager.git.is_git_worktree:
        warnings.append("Current path is not a Git worktree; prefer resume-query with a task nickname or provide a real worktree path.")
    if task_has_non_git_unknown_warning(manager, task):
        warnings.append("Matched task has branch=unknown on a non-Git path; this may be a historical container task and was not automatically cleaned.")

    backfill_prompts = []
    if missing_handoff:
        backfill_prompts.append(tr(language, "prompt_handoff"))
    if missing_validation:
        backfill_prompts.append(tr(language, "prompt_validation"))
    if missing_safety_rules:
        backfill_prompts.append(tr(language, "prompt_safety"))
    if stale["isStale"]:
        backfill_prompts.append(tr(language, "prompt_stale"))
    if not task.get("facts"):
        backfill_prompts.append(tr(language, "prompt_facts"))
    if not task.get("unknowns"):
        backfill_prompts.append(tr(language, "prompt_unknowns"))

    return {
        "projectId": manager.project_id,
        "projectIdSource": manager.project_id_source,
        "taskId": task.get("taskId", ""),
        "task": task,
        "sidecarRoot": str(manager.sidecar_root),
        "handoffPath": str(handoff_path),
        "checks": {
            "sidecarHit": sidecar_hit,
            "handoffAvailable": handoff_available,
            "stale": stale,
            "validationPresent": not missing_validation,
            "safetyRulesPresent": not missing_safety_rules,
            "dirtyWorktree": dirty_worktree,
        },
        "findings": findings,
        "backfillPrompts": unique_nonempty(backfill_prompts),
        "warnings": warnings,
        "nonGitWorktree": not manager.git.is_git_worktree,
        "conflicts": conflicts,
    }


def cmd_audit_context(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    payload = manager.load_active_tasks()
    output = audit_context_payload(manager, payload, language)
    task = output["task"]
    output.pop("task", None)
    manager.log_event(
        "audit-context",
        task_id=task.get("taskId", ""),
        started_at=started_at,
        sidecar_hit=output["checks"]["sidecarHit"],
        handoff_available=output["checks"]["handoffAvailable"],
        stale=output["checks"]["stale"]["isStale"],
        validationPresent=output["checks"]["validationPresent"],
        safetyRulesPresent=output["checks"]["safetyRulesPresent"],
        findingCount=len(output["findings"]),
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def project_id_canonicalization(args: argparse.Namespace, manager: SidecarManager) -> dict[str, Any]:
    requested = (getattr(args, "project_id", "") or os.environ.get("CONTEXT_HANDOFF_PROJECT_ID", "") or "").strip()
    canonical = manager.project_id
    return {
        "requested": requested,
        "canonical": canonical,
        "changed": bool(requested and requested != canonical),
    }


def worktree_audit_row(worktree_info: dict[str, str], audit: dict[str, Any], manager: SidecarManager) -> dict[str, Any]:
    task = audit.get("task") or {}
    checks = audit.get("checks") or {}
    stale = checks.get("stale") or {}
    path = worktree_info.get("path") or str(manager.git.worktree_path)
    branch = worktree_info.get("branch") or manager.git.branch
    sidecar_hit = bool(checks.get("sidecarHit"))
    row: dict[str, Any] = {
        "branch": branch,
        "worktreePath": path,
        "headSha": manager.git.head_sha or worktree_info.get("headSha", ""),
        "dirty": bool(checks.get("dirtyWorktree")),
        "dirtyFiles": manager.git.dirty_files,
        "sidecarHit": sidecar_hit,
        "taskId": task.get("taskId", ""),
        "taskStatus": task.get("status", "") if sidecar_hit else "missing",
        "parentTaskId": task.get("parentTaskId", ""),
        "phase": task.get("phase", ""),
        "threadRole": task.get("threadRole", ""),
        "threadLabel": task.get("threadLabel", ""),
        "threadPurpose": task.get("threadPurpose", ""),
        "routingStatus": task.get("routingStatus", ""),
        "routingConfidence": task.get("routingConfidence", None),
        "routingNeedsReview": bool(task.get("routingNeedsReview", False)),
        "routingEvidence": task.get("routingEvidence", []),
        "routingCandidates": task.get("routingCandidates", []),
        "handoffAvailable": bool(checks.get("handoffAvailable")),
        "validationPresent": bool(checks.get("validationPresent")),
        "safetyRulesPresent": bool(checks.get("safetyRulesPresent")),
        "stale": bool(stale.get("isStale")),
        "staleReasons": stale.get("reasons", []),
        "nextStep": task.get("nextStep", ""),
        "blocker": task.get("blocker", ""),
        "findings": audit.get("findings", []),
        "backfillPrompts": audit.get("backfillPrompts", []),
        "conflicts": audit.get("conflicts", []),
    }
    if not sidecar_hit:
        row["provisionalTaskStatus"] = task.get("status", "")
    return row


HUB_RECEIPT_FIELDS = ["taskId", "status", "handoffPath", "nextStep", "blocker", "validation", "risks"]


def audit_row_action_reasons(row: dict[str, Any], language: str) -> list[str]:
    reasons: list[str] = []
    if not row.get("sidecarHit"):
        reasons.append(tr(language, "action_reason_missing_task"))
    if row.get("stale"):
        reasons.append(tr(language, "action_reason_stale"))
    if not row.get("handoffAvailable"):
        reasons.append(tr(language, "action_reason_missing_handoff"))
    if not row.get("validationPresent"):
        reasons.append(tr(language, "action_reason_missing_validation"))
    if not row.get("safetyRulesPresent"):
        reasons.append(tr(language, "action_reason_missing_safety"))
    if row.get("dirty"):
        reasons.append(tr(language, "action_reason_dirty_worktree"))
    return unique_nonempty(reasons)


def recommended_action_type(row: dict[str, Any]) -> str:
    if not row.get("sidecarHit"):
        return "backfill-existing-or-new-thread"
    if row.get("stale"):
        return "refresh-stale-task"
    return "backfill-existing-thread"


def thread_prompt_key(row: dict[str, Any]) -> str:
    return row.get("branch") or row.get("worktreePath") or row.get("taskId") or "unknown"


def build_hub_action_prompts(
    manager: SidecarManager,
    rows: list[dict[str, Any]],
    active_without_worktree: list[dict[str, Any]],
    language: str,
    dogfood_hygiene_candidates: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], list[dict[str, Any]]]:
    recommended_actions: list[dict[str, Any]] = []
    thread_prompts_by_branch: dict[str, dict[str, str]] = {}
    for candidate in dogfood_hygiene_candidates or []:
        recommended_actions.append(
            {
                "branch": candidate.get("branch", ""),
                "worktreePath": candidate.get("worktreePath", ""),
                "taskId": candidate.get("taskId", ""),
                "reason": candidate.get("reason", DOGFOOD_HYGIENE_ARCHIVE_REASON),
                "reasons": [candidate.get("reason", DOGFOOD_HYGIENE_ARCHIVE_REASON)],
                "recommendedActionType": "archive-stale-dogfood-record",
                "prompt": f"Run {candidate.get('archiveCommand', '')} after human confirmation.",
                "archiveCommand": candidate.get("archiveCommand", ""),
                "evidence": candidate.get("evidence", []),
                "hubReceiptExpected": HUB_RECEIPT_FIELDS,
            }
        )
    for row in rows:
        reasons = audit_row_action_reasons(row, language)
        if not reasons:
            continue
        branch = row.get("branch") or "unknown"
        worktree_path = row.get("worktreePath") or ""
        reason_text = "; ".join(reasons)
        old_prompt = tr(
            language,
            "old_thread_backfill_prompt",
            project_id=manager.project_id,
            branch=branch,
            worktree_path=worktree_path,
            reasons=reason_text,
        )
        new_prompt = tr(
            language,
            "new_thread_execution_prompt",
            project_id=manager.project_id,
            branch=branch,
            worktree_path=worktree_path,
            reasons=reason_text,
        )
        action: dict[str, Any] = {
            "branch": branch,
            "worktreePath": worktree_path,
            "taskId": row.get("taskId", ""),
            "reason": reason_text,
            "reasons": reasons,
            "recommendedActionType": recommended_action_type(row),
            "oldThreadBackfillPrompt": old_prompt,
            "newExecutionThreadPrompt": new_prompt,
            "hubReceiptExpected": HUB_RECEIPT_FIELDS,
        }
        if row.get("stale"):
            action["staleRefreshPrompt"] = tr(
                language,
                "stale_refresh_prompt",
                project_id=manager.project_id,
                branch=branch,
                worktree_path=worktree_path,
            )
        recommended_actions.append(action)
        thread_prompts_by_branch[thread_prompt_key(row)] = {
            "oldThreadBackfillPrompt": old_prompt,
            "newExecutionThreadPrompt": new_prompt,
        }
        if row.get("stale"):
            thread_prompts_by_branch[thread_prompt_key(row)]["staleRefreshPrompt"] = action["staleRefreshPrompt"]

    cleanup_prompts: list[dict[str, Any]] = []
    for task in active_without_worktree:
        cleanup_prompts.append(
            {
                "taskId": task.get("taskId", ""),
                "branch": task.get("branch", ""),
                "worktreePath": task.get("worktreePath", ""),
                "reason": tr(language, "cleanup_reason_missing_worktree"),
                "prompt": tr(
                    language,
                    "cleanup_prompt",
                    project_id=manager.project_id,
                    task_id=task.get("taskId", ""),
                    branch=task.get("branch", ""),
                    worktree_path=task.get("worktreePath", ""),
                ),
                "hubReceiptExpected": HUB_RECEIPT_FIELDS,
            }
        )
    return recommended_actions, thread_prompts_by_branch, cleanup_prompts


def recent_merged_prs(manager: SidecarManager, limit: int = 8) -> dict[str, Any]:
    status = gh_status()
    result: dict[str, Any] = {
        "source": "gh pr list",
        "available": bool(status.get("available")),
        "authenticated": bool(status.get("authenticated")),
        "prs": [],
        "message": status.get("message", ""),
    }
    if not status.get("available") or not status.get("authenticated"):
        return result
    command = [
        status["path"],
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        str(limit),
        "--json",
        "number,title,url,mergedAt,headRefName,baseRefName",
    ]
    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        proc = subprocess.run(
            command,
            cwd=str(manager.git.repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["message"] = short_text(str(exc), max_len=300)
        return result
    if proc.returncode != 0 or suspicious_cli_output(proc.stdout + proc.stderr):
        result["message"] = short_text("\n".join([proc.stdout.strip(), proc.stderr.strip()]).strip(), max_len=500)
        return result
    try:
        parsed = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        result["message"] = f"failed to parse gh PR JSON: {short_text(str(exc), max_len=200)}"
        return result
    if isinstance(parsed, list):
        result["prs"] = parsed
        result["message"] = "merged PRs collected"
    return result


def task_is_historical_baseline_candidate(manager: SidecarManager, task: dict[str, Any], hub_task_id: str) -> bool:
    if task.get("taskId") == hub_task_id:
        return False
    task_path = str(task.get("worktreePath") or "")
    task_repo = str(task.get("repoRoot") or "")
    current_worktree = str(manager.git.worktree_path)
    current_repo = str(manager.git.repo_root)
    same_worktree = bool(task_path and resolved_path_text(task_path) == resolved_path_text(current_worktree))
    same_repo = bool(task_repo and resolved_path_text(task_repo) == resolved_path_text(current_repo))
    same_branch = bool(task.get("branch") and task.get("branch") == manager.git.branch)
    hub_like = str(task.get("threadRole") or "") == "hub"
    return same_worktree or same_repo or same_branch or hub_like


def stale_historical_sidecar_records(manager: SidecarManager, tasks: list[dict[str, Any]], hub_task_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("status", "active") not in VALID_STATUSES:
            continue
        if not task_is_historical_baseline_candidate(manager, task, hub_task_id):
            continue
        stale = stale_detection(task, manager.git)
        if not stale.get("isStale"):
            continue
        records.append(
            {
                "taskId": task.get("taskId", ""),
                "status": task.get("status", "active"),
                "branch": task.get("branch", ""),
                "worktreePath": task.get("worktreePath", ""),
                "threadRole": task.get("threadRole", ""),
                "phase": task.get("phase", ""),
                "updatedAt": task.get("updatedAt", ""),
                "reasons": stale.get("reasons", []),
                "recordedHeadSha": stale.get("recordedHeadSha", ""),
                "currentHeadSha": stale.get("currentHeadSha", ""),
                "recordedDirtyFingerprint": stale.get("recordedDirtyFingerprint", ""),
                "currentDirtyFingerprint": stale.get("currentDirtyFingerprint", ""),
            }
        )
    return records


def audit_project_summary_for_rebaseline(manager: SidecarManager, payload: dict[str, Any], language: str) -> dict[str, Any]:
    worktrees, worktree_error = parse_git_worktree_list(manager.git.repo_root)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in worktrees:
        path = item.get("path", "")
        if not path:
            continue
        try:
            wt_manager = SidecarManager(
                Path(path),
                project_id_override=manager.project_id,
                base_branch_override=manager.git.base_branch,
            )
            audit = audit_context_payload(wt_manager, payload, language)
            rows.append(worktree_audit_row(item, audit, wt_manager))
        except Exception as exc:
            errors.append({"worktreePath": path, "error": short_text(str(exc), max_len=500)})
    active_tasks = [task for task in payload.get("tasks", []) if task.get("status", "active") in VALID_STATUSES]
    summary = {
        "gitWorktrees": len(worktrees),
        "sidecarActiveTasks": len(active_tasks),
        "staleTasks": sum(1 for row in rows if row.get("stale")),
        "missingHandoff": sum(1 for row in rows if not row.get("handoffAvailable")),
        "missingValidation": sum(1 for row in rows if not row.get("validationPresent")),
        "missingSafetyRules": sum(1 for row in rows if not row.get("safetyRulesPresent")),
        "dirtyWorktrees": sum(1 for row in rows if row.get("dirty")),
        "worktreeAuditErrors": len(errors),
    }
    return {
        "summaryCounts": summary,
        "branchesNeedingBackfill": unique_nonempty(
            [
                row.get("branch", "")
                for row in rows
                if row.get("stale")
                or not row.get("handoffAvailable")
                or not row.get("validationPresent")
                or not row.get("safetyRulesPresent")
            ]
        ),
        "worktreeError": worktree_error,
        "errors": errors,
    }


def rebaseline_hub_args(manager: SidecarManager, args: argparse.Namespace, payload: dict[str, Any], archived_count: int, stale_count: int) -> argparse.Namespace:
    goal = (
        args.goal
        or "maintain Agent Workflow Hub as an agent-native development workflow layer for Codex worktrees"
    )
    next_step = (
        args.next_step
        or "Run visualize-project after rebaseline and use audit-project/rebaseline-project after major merges or stale sidecar signals."
    )
    command_text = "rebaseline-project --update-current-hub-task"
    if args.confirm_archive_stale:
        command_text += " --confirm-archive-stale"
    facts = [
        f"Current canonical repo is {manager.git.repo_root}.",
        f"Current worktree is {manager.git.worktree_path}.",
        f"Current branch is {manager.git.branch}.",
        f"Current HEAD is {manager.git.head_sha or 'unknown'}.",
        f"Active sidecar task count before rebaseline was {len(payload.get('tasks', []))}.",
        f"Archived sidecar task count before rebaseline was {archived_count}.",
        f"Detected {stale_count} stale historical sidecar record(s) before confirmed archival.",
    ]
    facts.extend([f"Recent commit: {commit}" for commit in manager.git.recent_commits[:3]])
    return argparse.Namespace(
        task_id=args.hub_task_id,
        status="active",
        parent_task_id="",
        phase="follow-up",
        thread_role="hub",
        thread_label=args.thread_label or "Agent Workflow Hub project hub",
        thread_purpose="Maintain the current project workflow baseline, task inventory, validation state, and follow-up routing.",
        confirm_route=True,
        routing_evidence=["project baseline explicitly refreshed by rebaseline-project"],
        goal=goal,
        aliases=["agent workflow hub main", "project hub", "current baseline"],
        next_step=next_step,
        blocker="",
        thread_summary="Project baseline refreshed from current Git and sidecar state.",
        pr_url="",
        touched_areas=["skills", "sidecar", "project hub"],
        facts=facts,
        inferences=[
            "Current project baseline should be represented by the hub task at the current canonical HEAD.",
            "Stale historical sidecar records may reflect older merged or abandoned work and should not dominate project visualization.",
        ],
        unknowns=[
            "Whether each stale historical sidecar task was merged, abandoned, or still needs recovery unless explicitly confirmed.",
        ],
        safety_rules=[
            "Do not automatically delete worktrees or repository files during rebaseline.",
            "Archive stale active sidecar tasks only when explicitly confirmed.",
            "Keep dynamic workflow state under the local sidecar, not in the target repository.",
        ],
        validation_commands=[command_text],
        validation_results=["rebaseline-project refreshed the current hub task and wrote a fresh handoff"],
        validation_at=now_iso(),
        validation_tests=None,
        validation_manual=None,
        validation_notes="Rebaseline is a workflow-state refresh, not proof of code correctness.",
        current_objective=goal,
        done=["Refreshed current project hub baseline from Git and sidecar state."],
        not_done=["Run visualize-project and review stale historical records with human confirmation."],
        risks=["Archiving stale sidecar tasks without human review could hide still-relevant work."],
        key_files=[],
        estimated_rebuild_minutes=None,
        duplicate_scan=False,
        first_step_correct=False,
        notes="",
    )


def write_rebaseline_handoff(manager: SidecarManager, task: dict[str, Any], hub_args: argparse.Namespace, language: str) -> str:
    handoff_path = manager.handoff_path_for(task)
    with file_lock(handoff_path):
        atomic_write_text(handoff_path, build_handoff_markdown(task, hub_args, manager, language))
    return str(handoff_path)


def cmd_audit_project(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    payload = manager.load_active_tasks()
    tasks = payload.get("tasks", [])
    state = manager.write_project_state(tasks)
    worktrees, worktree_error = parse_git_worktree_list(manager.git.repo_root)

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for item in worktrees:
        path = item.get("path", "")
        if not path:
            continue
        try:
            wt_manager = SidecarManager(
                Path(path),
                project_id_override=getattr(args, "project_id", "") or manager.project_id,
                base_branch_override=getattr(args, "base_branch", "") or manager.git.base_branch,
            )
            audit = audit_context_payload(wt_manager, payload, language)
            rows.append(worktree_audit_row(item, audit, wt_manager))
        except Exception as exc:  # Keep hub inventory resilient across broken worktrees.
            errors.append({"worktreePath": path, "error": short_text(str(exc), max_len=500)})

    worktree_paths = {str(Path(row["worktreePath"]).resolve()) for row in rows if row.get("worktreePath")}
    active_tasks = [task for task in tasks if task.get("status", "active") in VALID_STATUSES]
    active_without_worktree = []
    for task in active_tasks:
        raw_path = str(task.get("worktreePath") or "")
        resolved = str(Path(raw_path).resolve()) if raw_path else ""
        if not raw_path or resolved not in worktree_paths:
            active_without_worktree.append(
                {
                    "taskId": task.get("taskId", ""),
                    "branch": task.get("branch", ""),
                    "worktreePath": raw_path,
                    "status": task.get("status", ""),
                    "updatedAt": task.get("updatedAt", ""),
                }
            )

    untracked = [
        {
            "branch": row.get("branch", ""),
            "worktreePath": row.get("worktreePath", ""),
            "headSha": row.get("headSha", ""),
            "dirty": row.get("dirty", False),
            "sidecarHit": False,
            "taskStatus": "missing",
            "provisionalTaskStatus": row.get("provisionalTaskStatus", ""),
            "backfillPrompts": row.get("backfillPrompts", []),
        }
        for row in rows
        if not row.get("sidecarHit")
    ]
    branches_needing_backfill = unique_nonempty(
        [
            row.get("branch", "")
            for row in rows
            if (not row.get("sidecarHit"))
            or (not row.get("handoffAvailable"))
            or (not row.get("validationPresent"))
            or (not row.get("safetyRulesPresent"))
            or row.get("stale")
        ]
    )
    backfill_by_branch = {
        row.get("branch") or row.get("worktreePath"): row.get("backfillPrompts", [])
        for row in rows
        if row.get("backfillPrompts")
    }
    missing_handoff = sum(1 for row in rows if not row.get("handoffAvailable"))
    missing_validation = sum(1 for row in rows if not row.get("validationPresent"))
    missing_safety = sum(1 for row in rows if not row.get("safetyRulesPresent"))
    dogfood_candidates, dogfood_non_recommended = dogfood_hygiene_records(manager, payload)
    summary_counts = {
        "gitWorktrees": len(worktrees),
        "sidecarActiveTasks": len(active_tasks),
        "trackedWorktrees": sum(1 for row in rows if row.get("sidecarHit")),
        "untrackedWorktrees": len(untracked),
        "dirtyWorktrees": sum(1 for row in rows if row.get("dirty")),
        "staleTasks": sum(1 for row in rows if row.get("stale")),
        "missingHandoff": missing_handoff,
        "missingValidation": missing_validation,
        "missingSafetyRules": missing_safety,
        "activeTasksWithoutWorktree": len(active_without_worktree),
        "worktreeAuditErrors": len(errors),
        "staleDogfoodRecords": len(dogfood_candidates),
    }
    recommended_actions, thread_prompts_by_branch, cleanup_prompts = build_hub_action_prompts(
        manager,
        rows,
        active_without_worktree,
        language,
        dogfood_candidates,
    )

    output = {
        "projectId": manager.project_id,
        "projectIdSource": manager.project_id_source,
        "projectIdCanonicalization": project_id_canonicalization(args, manager),
        "sidecarRoot": str(manager.sidecar_root),
        "projectStatePath": str(manager.project_state_path),
        "canonicalWorktree": str(manager.git.worktree_path),
        "canonicalRepoRoot": str(manager.git.repo_root),
        "baseBranch": manager.git.base_branch,
        "summaryCounts": summary_counts,
        "worktrees": rows,
        "untrackedWorktrees": untracked,
        "activeTasksWithoutWorktree": active_without_worktree,
        "branchesNeedingBackfill": branches_needing_backfill,
        "backfillPromptsByBranch": backfill_by_branch,
        "recommendedActions": recommended_actions,
        "threadPromptsByBranch": thread_prompts_by_branch,
        "cleanupPrompts": cleanup_prompts,
        "dogfoodHygiene": {
            "candidateRecords": dogfood_candidates,
            "nonRecommendedRecords": dogfood_non_recommended,
            "requiresConfirmation": True,
        },
        "projectStatus": {
            "activeTaskCount": state.get("activeTaskCount", 0),
            "activeTasks": state.get("activeTasks", []),
        },
        "warnings": [],
        "errors": errors,
    }
    if worktree_error:
        output["errors"].append({"worktreePath": str(manager.git.repo_root), "error": short_text(worktree_error, max_len=500)})
    if summary_counts["gitWorktrees"] != summary_counts["sidecarActiveTasks"]:
        output["warnings"].append(tr(language, "warning_worktree_count"))
    if output["projectIdCanonicalization"]["changed"]:
        output["warnings"].append(
            tr(
                language,
                "warning_project_id_canonicalized",
                requested=output["projectIdCanonicalization"]["requested"],
                canonical=output["projectIdCanonicalization"]["canonical"],
            )
        )

    manager.log_event(
        "audit-project",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=None,
        scan_scope="git-worktree-inventory",
        gitWorktrees=summary_counts["gitWorktrees"],
        sidecarActiveTasks=summary_counts["sidecarActiveTasks"],
        untrackedWorktrees=summary_counts["untrackedWorktrees"],
        staleTasks=summary_counts["staleTasks"],
        staleDogfoodRecords=summary_counts["staleDogfoodRecords"],
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_rebaseline_project(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    if not manager.git.is_git_worktree and not allow_non_git_worktree(args):
        print(json.dumps(guarded_non_git_write_response(manager, "rebaseline-project"), ensure_ascii=False, indent=2))
        return 0
    language = resolve_language(args, manager)
    payload = manager.load_active_tasks()
    tasks = payload.get("tasks", [])
    active_before_count = len(tasks)
    archived_before = load_archived_tasks(manager)
    stale_records = stale_historical_sidecar_records(manager, tasks, args.hub_task_id)
    audit_summary = audit_project_summary_for_rebaseline(manager, payload, language)
    merged_prs = recent_merged_prs(manager, limit=args.pr_limit)

    archived_results: list[dict[str, Any]] = []
    if args.confirm_archive_stale and stale_records:
        stale_ids = {record["taskId"] for record in stale_records}
        for task in list(payload.get("tasks", [])):
            if task.get("taskId") in stale_ids:
                archived_results.append(
                    archive_task(
                        manager,
                        payload,
                        task,
                        event="rebaseline-archive-stale",
                        started_at=started_at,
                    )
                )
        payload = manager.load_active_tasks()
        tasks = payload.get("tasks", [])

    hub_task = task_by_id(manager, payload, slugify(args.hub_task_id))
    hub_handoff_path = ""
    hub_updated = False
    if args.update_current_hub_task:
        hub_args = rebaseline_hub_args(manager, args, payload, len(archived_before), len(stale_records))
        hub_task = manager.upsert_task(
            payload,
            hub_task,
            hub_args,
            route=route_result(
                "confirmed",
                routingNeedsReview=False,
                routingEvidence=["project baseline explicitly refreshed by rebaseline-project"],
            ),
        )
        hub_handoff_path = write_rebaseline_handoff(manager, hub_task, hub_args, language)
        manager.save_active_tasks(payload)
        hub_updated = True

    recommendations = []
    if stale_records and not args.confirm_archive_stale:
        recommendations.append("Review staleHistoricalSidecarRecords and rerun with --confirm-archive-stale only after human confirmation.")
    if not hub_updated:
        recommendations.append("Rerun with --update-current-hub-task to create or refresh the current project hub baseline task and handoff.")
    recommendations.append("Run visualize-project after rebaseline to verify the project map shows the current baseline task.")
    if audit_summary.get("summaryCounts", {}).get("missingValidation"):
        recommendations.append("Backfill validation for tasks that remain active after the baseline refresh.")
    if audit_summary.get("summaryCounts", {}).get("missingSafetyRules"):
        recommendations.append("Backfill safetyRules for tasks that remain active after the baseline refresh.")

    output = {
        "projectId": manager.project_id,
        "action": "rebaseline-project",
        "sidecarRoot": str(manager.sidecar_root),
        "repoMutated": False,
        "sidecarMutated": bool(archived_results or hub_updated),
        "canonicalRepo": {
            "worktree": str(manager.git.worktree_path),
            "repoRoot": str(manager.git.repo_root),
            "branch": manager.git.branch,
            "headSha": manager.git.head_sha,
            "upstream": manager.git.upstream,
            "dirtyFiles": manager.git.dirty_files,
            "dirtyFingerprint": manager.git.dirty_fingerprint,
        },
        "gitFacts": {
            "recentCommits": manager.git.recent_commits,
            "recentMergedPrs": merged_prs,
        },
        "inferredProjectBaseline": {
            "taskId": args.hub_task_id,
            "threadRole": "hub",
            "threadLabel": args.thread_label or "Agent Workflow Hub project hub",
            "phase": "follow-up",
            "goal": args.goal or "maintain Agent Workflow Hub as an agent-native development workflow layer for Codex worktrees",
            "worktreePath": str(manager.git.worktree_path),
            "headSha": manager.git.head_sha,
        },
        "userConfirmedChanges": {
            "archiveStaleConfirmed": bool(args.confirm_archive_stale),
            "updateCurrentHubTaskConfirmed": bool(args.update_current_hub_task),
            "archivedTaskIds": [item.get("taskId", "") for item in archived_results],
            "updatedHubTaskId": hub_task.get("taskId", "") if hub_updated and hub_task else "",
            "handoffPath": hub_handoff_path,
        },
        "staleHistoricalSidecarRecords": stale_records,
        "activeTaskCountBefore": active_before_count,
        "activeTaskCountAfter": len(payload.get("tasks", [])),
        "archivedTaskCountBefore": len(archived_before),
        "archivedByRebaseline": archived_results,
        "auditProjectFindings": audit_summary,
        "recommendations": unique_nonempty(recommendations),
        "nextCommands": {
            "visualizeProject": f"visualize-project --worktree {manager.git.worktree_path} --project-id {manager.project_id}",
            "confirmArchiveStale": f"rebaseline-project --worktree {manager.git.worktree_path} --project-id {manager.project_id} --confirm-archive-stale --update-current-hub-task",
            "updateCurrentHubTask": f"rebaseline-project --worktree {manager.git.worktree_path} --project-id {manager.project_id} --update-current-hub-task",
        },
    }
    manager.log_event(
        "rebaseline-project",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=bool(hub_handoff_path),
        scan_scope="project-rebaseline",
        staleHistoricalTasks=len(stale_records),
        archivedStaleTasks=len(archived_results),
        hubTaskUpdated=hub_updated,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_hygiene_dogfood(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    payload = manager.load_active_tasks()
    candidates, non_recommended = dogfood_hygiene_records(manager, payload)
    archived: list[dict[str, Any]] = []
    sidecar_mutated = False

    if args.confirm_archive:
        if not args.task_id:
            raise SystemExit("--confirm-archive requires --task-id")
        task_id = slugify(args.task_id)
        task = task_by_id(manager, payload, task_id)
        if task is None:
            raise SystemExit(f"task not found for hygiene archive: {task_id}")
        record = dogfood_hygiene_candidate_record(manager, task)
        if not record.get("isCandidate"):
            raise SystemExit(
                f"task {task_id} is not an eligible stale dogfood/smoke record; run hygiene-dogfood without --confirm-archive first"
            )
        task["hygieneArchiveReason"] = DOGFOOD_HYGIENE_ARCHIVE_REASON
        task["hygieneArchivedBy"] = "hygiene-dogfood"
        task["hygieneEvidence"] = record.get("evidence", [])
        task["hygieneArchivedAt"] = now_iso()
        archive_result = archive_task(
            manager,
            payload,
            task,
            event="hygiene-dogfood-archive",
            started_at=started_at,
        )
        archive_result["reason"] = DOGFOOD_HYGIENE_ARCHIVE_REASON
        archive_result["evidence"] = record.get("evidence", [])
        archived.append(archive_result)
        sidecar_mutated = True
        payload = manager.load_active_tasks()
        candidates, non_recommended = dogfood_hygiene_records(manager, payload)
    else:
        manager.log_event(
            "hygiene-dogfood",
            started_at=started_at,
            sidecar_hit=True,
            scan_scope="sidecar-dogfood-hygiene",
            candidateCount=len(candidates),
            nonRecommendedCount=len(non_recommended),
        )

    output = {
        "projectId": manager.project_id,
        "action": "hygiene-dogfood",
        "sidecarRoot": str(manager.sidecar_root),
        "checkedAt": now_iso(),
        "candidateRecords": candidates,
        "nonRecommendedRecords": non_recommended,
        "archived": archived,
        "requiresConfirmation": True,
        "sidecarMutated": sidecar_mutated,
        "repoMutated": False,
        "guidance": (
            "Report-only by default. Archive exactly one stale dogfood/smoke record with "
            "--confirm-archive --task-id <id> after human confirmation."
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    if not manager.git.is_git_worktree and not allow_non_git_worktree(args):
        print(json.dumps(guarded_non_git_write_response(manager, "handoff"), ensure_ascii=False, indent=2))
        return 0
    language = resolve_language(args, manager)
    payload = manager.load_active_tasks()
    route = route_guard_for_write(manager, payload, args, "handoff")
    if route.get("routeStatus") in {"mismatch", "ambiguous"}:
        print(json.dumps({"projectId": manager.project_id, "action": "handoff", **route}, ensure_ascii=False, indent=2))
        return 0
    task = task_by_id(manager, payload, slugify(args.task_id)) if getattr(args, "task_id", None) else None
    if task is None:
        task, _ = manager.find_task(payload)
    sidecar_hit = task is not None
    task = manager.upsert_task(payload, task, args, route=route)

    handoff_path = manager.handoff_path_for(task)
    continue_phrase = generate_continue_phrase(task, language, getattr(args, "continue_phrase", "") or "")
    compact_receipt = build_compact_receipt(task, args, continue_phrase, handoff_path, language)
    task["continuePhrase"] = continue_phrase
    task["compactReceipt"] = compact_receipt
    task["receiptUpdatedAt"] = now_iso()
    current_thread = upsert_current_thread(
        task,
        args,
        handoff_available=True,
        handoff_path=str(handoff_path),
        compact_receipt=compact_receipt,
        continue_phrase=continue_phrase,
    )
    handoff_content = build_handoff_markdown(task, args, manager, language)
    with file_lock(handoff_path):
        atomic_write_text(handoff_path, handoff_content)
    manager.save_active_tasks(payload)

    manager.log_event(
        "handoff",
        task_id=task["taskId"],
        started_at=started_at,
        sidecar_hit=sidecar_hit,
        handoff_available=True,
        estimatedRebuildMinutes=args.estimated_rebuild_minutes if args.estimated_rebuild_minutes is not None else None,
        duplicateScan=args.duplicate_scan,
        firstStepCorrect=args.first_step_correct,
        notes=args.notes or "",
    )

    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "taskId": task["taskId"],
                "status": task["status"],
                "routingStatus": task.get("routingStatus", ""),
                "routingNeedsReview": bool(task.get("routingNeedsReview", False)),
                "continuePhrase": continue_phrase,
                "compactReceipt": compact_receipt,
                "userFacingReceipt": build_user_facing_receipt(task, args, continue_phrase, compact_receipt),
                "machineReceipt": {
                    "projectId": manager.project_id,
                    "taskId": task["taskId"],
                    "threadId": current_thread.get("threadId", ""),
                    "threadRole": task.get("threadRole", ""),
                    "threadLabel": task.get("threadLabel", ""),
                    "handoffPath": str(handoff_path),
                    "routingStatus": task.get("routingStatus", ""),
                },
                "handoffPath": str(handoff_path),
                "activeTasksPath": str(manager.active_tasks_path),
                "updatedAt": task["updatedAt"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_load_handoff(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    payload = manager.load_active_tasks()
    mode = getattr(args, "mode", "compact") or "compact"
    section = getattr(args, "section", "") or ""
    reason = getattr(args, "reason", "resume") or "resume"
    reason_note = getattr(args, "reason_note", "") or ""
    if mode == "section" and not section:
        raise SystemExit("load-handoff --mode section requires --section")
    task, resolved_by, resolution = task_for_load_handoff(manager, payload, args, language)
    if resolved_by == "query" and not resolution.get("resolved"):
        output = {
            "projectId": manager.project_id,
            "mode": mode,
            "section": section if mode == "section" else "",
            "reasonCode": reason,
            "reasonNotePresent": bool(reason_note.strip()),
            "resolvedBy": resolved_by,
            "resolution": resolution,
            "handoffAvailable": False,
            "contentReturned": False,
            "contentChars": 0,
            "content": "",
            "repoMutated": False,
            "sidecarMutated": False,
        }
        manager.log_event(
            "load-handoff",
            started_at=started_at,
            task_id=resolution.get("taskId", ""),
            sidecar_hit=False,
            handoff_available=False,
            scan_scope="sidecar-handoff-load",
            threadRole="",
            loadMode=mode,
            section=section if mode == "section" else "",
            reasonCode=reason,
            reasonNotePresent=bool(reason_note.strip()),
            contentReturned=False,
            contentChars=0,
            resolvedBy=resolved_by,
            resolved=False,
            needsDisambiguation=bool(resolution.get("disambiguationQuestion")),
            candidateCount=len(resolution.get("candidates", [])),
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    selected_thread, thread_candidates, thread_resolved_by = select_handoff_thread(task, args)
    explicit_thread_selector = thread_resolved_by in {"thread-id", "thread-role"}
    if explicit_thread_selector and task and len(thread_candidates) != 1:
        output = {
            "projectId": manager.project_id,
            "taskId": task.get("taskId", ""),
            "mode": mode,
            "section": section if mode == "section" else "",
            "reasonCode": reason,
            "reasonNotePresent": bool(reason_note.strip()),
            "resolvedBy": resolved_by,
            "resolution": resolution,
            "threadResolvedBy": thread_resolved_by,
            "selectedThread": {},
            "threadCandidates": compact_thread_entries(thread_candidates),
            "handoffAvailable": manager.handoff_path_for(task).exists(),
            "contentReturned": False,
            "contentChars": 0,
            "content": "",
            "repoMutated": False,
            "sidecarMutated": False,
            "disambiguationQuestion": "Multiple or zero matching threads; rerun with --thread-id from threadCandidates.",
        }
        manager.log_event(
            "load-handoff",
            started_at=started_at,
            task_id=task.get("taskId", ""),
            sidecar_hit=True,
            handoff_available=output.get("handoffAvailable"),
            scan_scope="sidecar-handoff-load",
            threadRole=getattr(args, "thread_role", "") or "",
            loadMode=mode,
            section=section if mode == "section" else "",
            reasonCode=reason,
            reasonNotePresent=bool(reason_note.strip()),
            contentReturned=False,
            contentChars=0,
            resolvedBy=resolved_by,
            threadResolvedBy=thread_resolved_by,
            candidateCount=len(thread_candidates),
        )
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    output = build_load_handoff_output(
        manager,
        task,
        mode=mode,
        section=section,
        reason=reason,
        reason_note=reason_note,
        resolved_by=resolved_by,
        resolution=resolution,
        language=language,
        selected_thread=selected_thread,
        thread_candidates=thread_candidates,
    )
    manager.log_event(
        "load-handoff",
        started_at=started_at,
        task_id=output.get("taskId", ""),
        sidecar_hit=bool(task),
        handoff_available=output.get("handoffAvailable"),
        scan_scope="sidecar-handoff-load",
        threadRole=output.get("threadRole", ""),
        loadMode=mode,
        section=section if mode == "section" else "",
        reasonCode=reason,
        reasonNotePresent=bool(reason_note.strip()),
        contentReturned=bool(output.get("contentReturned")),
        contentChars=int(output.get("contentChars") or 0),
        resolvedBy=resolved_by,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    payload = manager.load_active_tasks()
    task, _ = manager.find_task(payload)
    if task is None:
        raise SystemExit("no matching task to archive")

    result = archive_task(manager, payload, task, event="archive", started_at=started_at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_finish_feature(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    payload = manager.load_active_tasks()
    task, _ = manager.find_task(payload)
    if task is None:
        raise SystemExit("no matching task to finish")

    if args.pr_url:
        task["prUrl"] = args.pr_url
    task["status"] = "review"
    task["updatedAt"] = now_iso()
    pr_result = try_create_pr(task, manager, args)
    if pr_result.get("prUrl"):
        task["prUrl"] = pr_result["prUrl"]

    result = archive_task(
        manager,
        payload,
        task,
        event="finish",
        started_at=started_at,
        pr_result=pr_result,
    )
    result["pr"] = pr_result
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_project_status(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    payload = manager.load_active_tasks()
    state = manager.write_project_state(payload.get("tasks", []))
    output = {
        "projectId": manager.project_id,
        "sidecarRoot": str(manager.sidecar_root),
        "projectStatePath": str(manager.project_state_path),
        "state": state,
    }
    manager.log_event(
        "project-status",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=None,
        scan_scope="project-state",
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_weekly_report(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    payload = manager.load_active_tasks()
    state = manager.write_project_state(payload.get("tasks", []))
    period = safe_filename_label(args.period or default_weekly_period(), "weekly-report")
    report_name = f"{period}-{manager.project_id}.md"
    report_path = manager.reports_dir / report_name
    with file_lock(report_path):
        atomic_write_text(report_path, build_weekly_report(manager, state, period, language))
    notification = tr(language, "weekly_ready", path=report_path)
    manager.log_event(
        "weekly-report",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=None,
        scan_scope="project-state",
        reportPath=str(report_path),
    )
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "reportPath": str(report_path),
                "notification": notification,
                "fullReportPastedByDefault": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_eval_report(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    period = safe_filename_label(args.period or default_weekly_period(), "eval-report")
    report_base = f"eval-{period}-{manager.project_id}"
    json_path = manager.reports_dir / f"{report_base}.json"
    markdown_path = manager.reports_dir / f"{report_base}.md"
    report = build_eval_report_payload(
        manager,
        period,
        args.since or "",
        args.until or "",
    )
    report["reportPaths"] = {
        "markdown": str(markdown_path),
        "json": str(json_path),
    }
    with file_lock(json_path):
        atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with file_lock(markdown_path):
        atomic_write_text(markdown_path, build_eval_report_markdown(report))
    manager.log_event(
        "eval-report",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=None,
        scan_scope="workflow-eval",
        reportMarkdownPath=str(markdown_path),
        reportJsonPath=str(json_path),
    )
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "period": period,
                "since": args.since or "",
                "until": args.until or "",
                "reportPaths": report["reportPaths"],
                "fullReportPastedByDefault": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_visualize_project(args: argparse.Namespace) -> int:
    from project_hub_dashboard import build_visual_project_html

    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    report_base = "project-hub-dashboard"
    json_path = manager.reports_dir / f"{report_base}.json"
    markdown_path = manager.reports_dir / f"{report_base}.md"
    html_path = manager.reports_dir / f"{report_base}.html"
    for old_report in manager.reports_dir.glob(f"visual-*-{manager.project_id}.*"):
        if old_report.suffix.lower() in {".json", ".md", ".html"}:
            try:
                old_report.unlink()
            except OSError:
                pass
    report = build_visual_project_payload(manager, bool(args.include_archive), language)
    report["reportPaths"] = {
        "markdown": str(markdown_path),
        "json": str(json_path),
        "html": str(html_path),
    }
    report["dashboardPath"] = str(html_path)
    report["dashboardUrl"] = html_path.resolve().as_uri()
    with file_lock(json_path):
        atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with file_lock(markdown_path):
        atomic_write_text(markdown_path, build_visual_project_markdown(report))
    with file_lock(html_path):
        atomic_write_text(html_path, build_visual_project_html(report))
    manager.log_event(
        "visualize-project",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=None,
        scan_scope="project-visualization",
        reportMarkdownPath=str(markdown_path),
        reportJsonPath=str(json_path),
        reportHtmlPath=str(html_path),
        visibleTasks=report.get("summaryCounts", {}).get("visibleTasks", 0),
        needsAttentionCount=len(report.get("needsAttention", [])),
    )
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "dashboardPath": report["dashboardPath"],
                "dashboardUrl": report["dashboardUrl"],
                "reportPaths": report["reportPaths"],
                "summaryCounts": report.get("summaryCounts", {}),
                "needsAttentionCount": len(report.get("needsAttention", [])),
                "archiveSummary": report.get("archiveSummary", {}),
                "fullJsonPastedByDefault": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def issue_output(manager: SidecarManager, args: argparse.Namespace, *, create: bool, language: str = "en") -> dict[str, Any]:
    title, body = build_issue_text(manager, args, language)
    sensitive_findings = sensitive_issue_findings(title, body)
    config = manager.sidecar_config()
    dogfood_enabled = bool(config.get("dogfoodIssueMode"))
    output: dict[str, Any] = {
        "projectId": manager.project_id,
        "dogfoodIssueMode": dogfood_enabled,
        "creationAuthorization": "explicit-create-action" if create else ("dogfoodIssueMode" if dogfood_enabled else "draft-only"),
        "created": False,
        "draftOnly": True,
        "title": title,
        "body": body,
        "labels": DOGFOOD_ISSUE_LABELS,
        "sensitiveFindings": sensitive_findings,
        "guidance": tr(language, "issue_draft_guidance"),
    }
    if not create:
        return output
    result = try_create_issue(manager, title, body, args)
    output.update(result)
    output["draftOnly"] = not result.get("created", False)
    return output


def cmd_draft_issue(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    output = issue_output(manager, args, create=False, language=language)
    manager.log_event(
        "draft-issue",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=None,
        scan_scope="dogfood-issue",
        created=False,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_create_issue(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = make_manager(args)
    language = resolve_language(args, manager)
    output = issue_output(manager, args, create=True, language=language)
    manager.log_event(
        "create-issue",
        started_at=started_at,
        sidecar_hit=True,
        handoff_available=None,
        scan_scope="dogfood-issue",
        created=output.get("created", False),
        draftOnly=output.get("draftOnly", True),
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_enable_dogfood_issue_mode(args: argparse.Namespace) -> int:
    manager = make_manager(args)
    manager.save_sidecar_config(dogfoodIssueMode=True)
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "dogfoodIssueMode": True,
                "configPath": str(manager.config_path),
                "repoMutated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_disable_dogfood_issue_mode(args: argparse.Namespace) -> int:
    manager = make_manager(args)
    manager.save_sidecar_config(dogfoodIssueMode=False)
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "dogfoodIssueMode": False,
                "configPath": str(manager.config_path),
                "repoMutated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    worktree = Path(args.worktree or os.getcwd())
    manager = make_manager(args)
    git_executable = find_git_executable()
    git_repo_ok, git_repo_root = detect_git_repo(worktree)
    gh = gh_status()
    v2_paths = [
        manager.active_tasks_path,
        manager.project_state_path,
        manager.handoffs_dir,
        manager.archive_dir,
        manager.reports_dir,
        manager.events_path,
    ]
    existing_v2_paths = [path for path in v2_paths if path.exists()]
    sidecar_layout_ok = all(path.exists() for path in v2_paths)
    checks = [
        {"name": "python", "ok": True, "detail": sys.version.split()[0]},
        {"name": "git", "ok": bool(git_executable), "detail": git_executable or "not found"},
        {"name": "git-repository", "ok": git_repo_ok, "detail": git_repo_root or "not a git repository"},
        {
            "name": "sidecar-layout",
            "ok": sidecar_layout_ok,
            "detail": f"{len(existing_v2_paths)}/{len(v2_paths)} V2 paths exist under {manager.sidecar_root}",
        },
        {"name": "gh-installed", "ok": gh["available"], "detail": gh["path"] or gh["message"]},
        {"name": "gh-authenticated", "ok": gh["authenticated"], "detail": gh["message"]},
    ]
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "mutatedSystemState": False,
                "checks": checks,
                "guidance": [
                    "Run setup to create the local sidecar layout if sidecar checks fail.",
                    "Install and authenticate GitHub CLI only if you want automatic PR creation.",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_setup(args: argparse.Namespace) -> int:
    return cmd_init(args)


def cmd_set_language(args: argparse.Namespace) -> int:
    manager = make_manager(args)
    language = normalize_language(args.language)
    manager.save_sidecar_config(preferredLanguage=language)
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "preferredLanguage": language,
                "configPath": str(manager.config_path),
                "repoMutated": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Context handoff sidecar manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser, *, require_language: bool = False) -> None:
        subparser.add_argument("--worktree", help="Target worktree path. Defaults to current directory.")
        subparser.add_argument("--project-id", help="Override sidecar projectId for multi-worktree projects.")
        subparser.add_argument("--base-branch", help="Override and persist the feature base branch for this sidecar project.")
        subparser.add_argument("--language", choices=sorted(SUPPORTED_LANGUAGES), required=require_language, help="Human-facing output language.")
        subparser.add_argument("--allow-non-git-worktree", action="store_true", help="Opt in to writing task state for a non-Git directory.")

    def add_task_update_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--task-id")
        subparser.add_argument("--status", choices=sorted(VALID_STATUSES))
        subparser.add_argument("--parent-task-id")
        subparser.add_argument("--phase")
        subparser.add_argument("--thread-id")
        subparser.add_argument("--thread-role")
        subparser.add_argument("--thread-label")
        subparser.add_argument("--thread-purpose")
        subparser.add_argument("--continue-phrase")
        subparser.add_argument("--confirm-route", action="store_true")
        subparser.add_argument("--routing-evidence", action="append")
        subparser.add_argument("--goal")
        subparser.add_argument("--alias", dest="aliases", action="append")
        subparser.add_argument("--next-step")
        subparser.add_argument("--blocker")
        subparser.add_argument("--thread-summary")
        subparser.add_argument("--pr-url")
        subparser.add_argument("--touched-area", dest="touched_areas", action="append")
        subparser.add_argument("--fact", dest="facts", action="append")
        subparser.add_argument("--inference", dest="inferences", action="append")
        subparser.add_argument("--unknown", dest="unknowns", action="append")
        subparser.add_argument("--safety-rule", dest="safety_rules", action="append")
        subparser.add_argument("--validation-command", dest="validation_commands", action="append")
        subparser.add_argument("--validation-result", dest="validation_results", action="append")
        subparser.add_argument("--validation-at")

    def add_issue_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--title", "--issue-title", dest="issue_title", required=True)
        subparser.add_argument("--fact", dest="facts", action="append")
        subparser.add_argument("--inference", dest="inferences", action="append")
        subparser.add_argument("--unknown", dest="unknowns", action="append")
        subparser.add_argument("--reproduction", action="append")
        subparser.add_argument("--suggested-fix", dest="suggested_fix", action="append")
        subparser.add_argument("--priority", default="triage-needed")
        subparser.add_argument("--allow-duplicate", action="store_true")

    init_parser = subparsers.add_parser("init", help="Initialize the sidecar layout for the current worktree")
    add_common(init_parser)
    init_parser.set_defaults(func=cmd_init)

    setup_parser = subparsers.add_parser("setup", help="Safely initialize the local V2 sidecar layout")
    add_common(setup_parser)
    setup_parser.set_defaults(func=cmd_setup)

    snapshot_parser = subparsers.add_parser("snapshot", help="Print current git/worktree facts for the current worktree")
    add_common(snapshot_parser)
    snapshot_parser.set_defaults(func=cmd_snapshot)

    intake_parser = subparsers.add_parser("intake", help="Resolve the current task and print intake JSON")
    add_common(intake_parser)
    intake_parser.add_argument("--estimated-rebuild-minutes", type=int)
    intake_parser.add_argument("--duplicate-scan", action="store_true")
    intake_parser.add_argument("--first-step-correct", action="store_true")
    intake_parser.add_argument("--notes", default="")
    intake_parser.set_defaults(func=cmd_intake)

    start_parser = subparsers.add_parser("start-feature", help="Create or update the active task for this branch")
    add_common(start_parser)
    add_task_update_args(start_parser)
    start_parser.set_defaults(func=cmd_start_feature)

    alias_parser = subparsers.add_parser("alias-task", help="Add or remove human-friendly aliases for a task")
    add_common(alias_parser)
    alias_parser.add_argument("--task-id", help="Task id to edit. Defaults to current branch/worktree task.")
    alias_parser.add_argument("--alias", dest="aliases", action="append", help="Alias to add. Can be repeated.")
    alias_parser.add_argument("--remove-alias", dest="remove_aliases", action="append", help="Alias to remove. Can be repeated.")
    alias_parser.set_defaults(func=cmd_alias_task)

    attach_parser = subparsers.add_parser("attach-thread", help="Attach thread metadata, parent task, phase, and routing review fields to a task")
    add_common(attach_parser)
    add_task_update_args(attach_parser)
    attach_parser.set_defaults(func=cmd_attach_thread)

    orient_parser = subparsers.add_parser("orient-thread", help="Orient a new thread by role and query without mutating sidecar by default")
    add_common(orient_parser)
    orient_parser.add_argument("--role", required=True, help="Thread role or role alias, for example research, discussion, execution, or project-hub.")
    orient_parser.add_argument("--query", required=True, help="Topic, task, or project phrase used for project and task routing.")
    orient_parser.add_argument("--scope", choices=["project-level", "task-level", "worktree-level"], help="Orientation scope. Project-level avoids binding feature worktrees.")
    orient_parser.add_argument("--task-id", help="Optional task id hint to attach or route to.")
    orient_parser.add_argument("--parent-task-id", help="Optional parent task id for attach mode.")
    orient_parser.add_argument("--phase", help="Optional task phase for attach mode.")
    orient_parser.add_argument("--thread-id", help="Optional internal thread id to update in attach mode.")
    orient_parser.add_argument("--thread-label", help="Optional human label for this thread.")
    orient_parser.add_argument("--thread-purpose", help="Optional concise purpose for this thread.")
    orient_parser.add_argument("--attach", action="store_true", help="Write thread metadata to sidecar when the route is safe or confirmed.")
    orient_parser.add_argument("--confirm-route", action="store_true", help="Confirm inferred/non-Git/ambiguous route before attach writes sidecar.")
    orient_parser.set_defaults(func=cmd_orient_thread)

    resolve_parser = subparsers.add_parser("resolve-task", help="Resolve a natural-language query to a sidecar task")
    add_common(resolve_parser)
    resolve_parser.add_argument("--query", required=True, help="Natural-language task query, alias, branch, or worktree hint.")
    resolve_parser.set_defaults(func=cmd_resolve_task)

    resume_parser = subparsers.add_parser("resume-feature", help="Resolve the current task and print compact resume JSON")
    add_common(resume_parser)
    resume_parser.add_argument("--estimated-rebuild-minutes", type=int)
    resume_parser.add_argument("--duplicate-scan", action="store_true")
    resume_parser.add_argument("--first-step-correct", action="store_true")
    resume_parser.add_argument("--notes", default="")
    resume_parser.set_defaults(func=cmd_resume_feature)

    resume_query_parser = subparsers.add_parser("resume-query", help="Resolve a natural-language query and resume the matched task")
    add_common(resume_query_parser)
    resume_query_parser.add_argument("--query", required=True, help="Natural-language task query, alias, branch, or worktree hint.")
    resume_query_parser.set_defaults(func=cmd_resume_query)

    audit_parser = subparsers.add_parser("audit-context", help="Audit current sidecar context for staleness and missing trust fields")
    add_common(audit_parser)
    audit_parser.set_defaults(func=cmd_audit_context)

    audit_project_parser = subparsers.add_parser("audit-project", help="Audit all git worktrees for project hub inventory")
    add_common(audit_project_parser)
    audit_project_parser.set_defaults(func=cmd_audit_project)

    rebaseline_parser = subparsers.add_parser("rebaseline-project", help="Refresh the current project hub baseline without blindly rewriting sidecar history")
    add_common(rebaseline_parser)
    rebaseline_parser.add_argument("--hub-task-id", default="agent-workflow-hub-main", help="Task id for the current project hub baseline.")
    rebaseline_parser.add_argument("--thread-label", default="Agent Workflow Hub project hub", help="Thread label for the current hub task.")
    rebaseline_parser.add_argument("--goal", default="maintain Agent Workflow Hub as an agent-native development workflow layer for Codex worktrees")
    rebaseline_parser.add_argument("--next-step")
    rebaseline_parser.add_argument("--pr-limit", type=int, default=8, help="Recent merged PRs to inspect when GitHub CLI is authenticated.")
    rebaseline_parser.add_argument("--update-current-hub-task", action="store_true", help="Create or update the current project hub task and handoff.")
    rebaseline_parser.add_argument("--confirm-archive-stale", action="store_true", help="Archive stale historical active sidecar tasks after human confirmation.")
    rebaseline_parser.set_defaults(func=cmd_rebaseline_project)

    hygiene_dogfood_parser = subparsers.add_parser("hygiene-dogfood", help="Inspect stale dogfood/smoke sidecar records and optionally archive one confirmed candidate")
    add_common(hygiene_dogfood_parser)
    hygiene_dogfood_parser.add_argument("--task-id", help="Task id to archive when used with --confirm-archive.")
    hygiene_dogfood_parser.add_argument("--confirm-archive", action="store_true", help="Archive one eligible stale dogfood/smoke record after human confirmation.")
    hygiene_dogfood_parser.set_defaults(func=cmd_hygiene_dogfood)

    handoff_parser = subparsers.add_parser("handoff", help="Update the current task and write the latest handoff")
    add_common(handoff_parser)
    add_task_update_args(handoff_parser)
    handoff_parser.add_argument("--current-objective")
    handoff_parser.add_argument("--validation-tests")
    handoff_parser.add_argument("--validation-manual")
    handoff_parser.add_argument("--validation-notes")
    handoff_parser.add_argument("--estimated-rebuild-minutes", type=int)
    handoff_parser.add_argument("--duplicate-scan", action="store_true")
    handoff_parser.add_argument("--first-step-correct", action="store_true")
    handoff_parser.add_argument("--notes", default="")
    handoff_parser.add_argument("--done", action="append")
    handoff_parser.add_argument("--not-done", dest="not_done", action="append")
    handoff_parser.add_argument("--risk", dest="risks", action="append")
    handoff_parser.add_argument("--key-file", dest="key_files", action="append")
    handoff_parser.set_defaults(func=cmd_handoff)

    load_handoff_parser = subparsers.add_parser("load-handoff", help="Load compact, section, or explicit full handoff content from sidecar state")
    add_common(load_handoff_parser)
    load_handoff_parser.add_argument("--query", help="Natural-language task query, continue phrase, alias, branch, or worktree hint.")
    load_handoff_parser.add_argument("--task-id", help="Task id to load. Takes precedence over --query.")
    load_handoff_parser.add_argument("--thread-id", help="Optional internal thread id used to select thread metadata.")
    load_handoff_parser.add_argument("--thread-role", help="Optional thread role used to select thread metadata.")
    load_handoff_parser.add_argument("--mode", choices=sorted(LOAD_HANDOFF_MODES), default="compact", help="Load compact receipt by default; section/full require explicit mode.")
    load_handoff_parser.add_argument("--section", choices=sorted(LOAD_HANDOFF_SECTIONS), default="", help="Handoff section to load when --mode section is used.")
    load_handoff_parser.add_argument("--reason", choices=sorted(LOAD_HANDOFF_REASONS), default="resume", help="Audit reason for this handoff load.")
    load_handoff_parser.add_argument("--reason-note", default="", help="Short optional note; only presence is recorded in events.")
    load_handoff_parser.set_defaults(func=cmd_load_handoff)

    archive_parser = subparsers.add_parser("archive", help="Archive the current task and remove it from active tasks")
    add_common(archive_parser)
    archive_parser.set_defaults(func=cmd_archive)

    finish_parser = subparsers.add_parser("finish-feature", help="Finish and archive the current task")
    add_common(finish_parser)
    finish_parser.add_argument("--create-pr", action="store_true", help="Create a PR with gh when gh is available and authenticated")
    finish_parser.add_argument("--draft", action="store_true", help="Create a draft PR when used with --create-pr")
    finish_parser.add_argument("--base", help="PR base branch. Defaults to task or git base branch.")
    finish_parser.add_argument("--pr-title")
    finish_parser.add_argument("--pr-body")
    finish_parser.add_argument("--pr-url")
    finish_parser.add_argument("--validation", default="")
    finish_parser.set_defaults(func=cmd_finish_feature)

    project_status_parser = subparsers.add_parser("project-status", help="Print compact project status JSON")
    add_common(project_status_parser)
    project_status_parser.set_defaults(func=cmd_project_status)

    weekly_report_parser = subparsers.add_parser("weekly-report", help="Write a human-facing Markdown report into the sidecar")
    add_common(weekly_report_parser)
    weekly_report_parser.add_argument("--period", help="Report period label. Defaults to ISO week.")
    weekly_report_parser.set_defaults(func=cmd_weekly_report)

    eval_report_parser = subparsers.add_parser("eval-report", help="Write lightweight workflow evaluation Markdown and JSON reports")
    add_common(eval_report_parser)
    eval_report_parser.add_argument("--period", help="Report period label. Defaults to ISO week.")
    eval_report_parser.add_argument("--since", help="Include events at or after this date/datetime.")
    eval_report_parser.add_argument("--until", help="Include events at or before this date/datetime.")
    eval_report_parser.set_defaults(func=cmd_eval_report)

    visualize_project_parser = subparsers.add_parser("visualize-project", help="Write project visualization Markdown and JSON reports")
    add_common(visualize_project_parser)
    visualize_project_parser.add_argument("--include-archive", action="store_true", help="Include archived tasks in the visualization.")
    visualize_project_parser.set_defaults(func=cmd_visualize_project)

    draft_issue_parser = subparsers.add_parser("draft-issue", help="Generate a dogfood issue draft without requiring gh")
    add_common(draft_issue_parser)
    add_issue_args(draft_issue_parser)
    draft_issue_parser.set_defaults(func=cmd_draft_issue)

    create_issue_parser = subparsers.add_parser("create-issue", help="Create a dogfood issue when explicitly allowed and safe")
    add_common(create_issue_parser)
    add_issue_args(create_issue_parser)
    create_issue_parser.set_defaults(func=cmd_create_issue)

    enable_issue_parser = subparsers.add_parser("enable-dogfood-issue-mode", help="Allow dogfood issue creation for this local sidecar project")
    add_common(enable_issue_parser)
    enable_issue_parser.set_defaults(func=cmd_enable_dogfood_issue_mode)

    disable_issue_parser = subparsers.add_parser("disable-dogfood-issue-mode", help="Return dogfood issue handling to draft-only mode")
    add_common(disable_issue_parser)
    disable_issue_parser.set_defaults(func=cmd_disable_dogfood_issue_mode)

    set_language_parser = subparsers.add_parser("set-language", help="Persist the human-facing output language in local sidecar config")
    add_common(set_language_parser, require_language=True)
    set_language_parser.set_defaults(func=cmd_set_language)

    doctor_parser = subparsers.add_parser("doctor", help="Report environment readiness without changing global state")
    add_common(doctor_parser)
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
