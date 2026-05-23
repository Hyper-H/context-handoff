#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = {"active", "paused", "blocked", "review"}
SIDECAR_VERSION = 2
GH_AUTH_STATUS_TIMEOUT_SECONDS = 15


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
        "goal": task.get("goal", ""),
        "branch": task.get("branch", ""),
        "baseBranch": task.get("baseBranch", ""),
        "worktreePath": task.get("worktreePath", ""),
        "prUrl": pr_url,
        "prSearchUrl": pr_search_url,
        "touchedAreas": task.get("touchedAreas", []),
        "nextStep": task.get("nextStep", ""),
        "blocker": task.get("blocker", ""),
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


def safe_filename_label(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip(".-_")
    return value or fallback


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
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def detect_git_repo(worktree: Path) -> tuple[bool, str]:
    rc, repo_root, _ = run_git(["rev-parse", "--show-toplevel"], worktree)
    if rc != 0 or not repo_root:
        return False, ""
    return True, str(Path(repo_root).resolve())


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


@dataclass
class GitContext:
    repo_root: Path
    branch: str
    base_branch: str
    worktree_path: Path
    recent_commits: list[str]
    touched_files: list[str]
    git_status_summary: list[str]
    pr_url: str
    pr_search_url: str


class SidecarManager:
    def __init__(self, worktree: Path):
        self.worktree = worktree.resolve()
        self.git = self._detect_git_context()
        self.project_id = slugify(self.git.repo_root.name)
        self.sidecar_root = Path.home() / ".codex" / "projects" / self.project_id
        self.active_tasks_path = self.sidecar_root / "active-tasks.json"
        self.project_state_path = self.sidecar_root / "project-state.json"
        self.handoffs_dir = self.sidecar_root / "handoffs"
        self.archive_dir = self.sidecar_root / "archive"
        self.reports_dir = self.sidecar_root / "reports"
        self.events_path = self.sidecar_root / "events.jsonl"

    def _detect_git_context(self) -> GitContext:
        rc, repo_root, _ = run_git(["rev-parse", "--show-toplevel"], self.worktree)
        if rc != 0 or not repo_root:
            repo_root = str(self.worktree)
        repo_root_path = Path(repo_root).resolve()

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

        rc, recent_commits_raw, _ = run_git(
            ["log", "--oneline", "-5"],
            repo_root_path,
        )
        recent_commits = [line for line in recent_commits_raw.splitlines() if line] if rc == 0 else []

        rc, status_raw, _ = run_git(["status", "--short"], repo_root_path)
        status_lines = [line for line in status_raw.splitlines() if line] if rc == 0 else []
        touched_files = [line[3:] for line in status_lines if len(line) >= 4]
        pr_search_url = ""
        rc, remote_url, _ = run_git(["remote", "get-url", "origin"], repo_root_path)
        if rc == 0 and remote_url:
            pr_search_url = self._guess_pr_search_url(remote_url, branch)

        return GitContext(
            repo_root=repo_root_path,
            branch=branch,
            base_branch=base_branch,
            worktree_path=self.worktree,
            recent_commits=recent_commits,
            touched_files=touched_files,
            git_status_summary=status_lines,
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
        if not self.active_tasks_path.exists():
            write_json(
                self.active_tasks_path,
                {"version": SIDECAR_VERSION, "projectId": self.project_id, "tasks": []},
            )

    def load_active_tasks(self) -> dict[str, Any]:
        self.ensure_layout()
        payload = read_json(
            self.active_tasks_path,
            {"version": SIDECAR_VERSION, "projectId": self.project_id, "tasks": []},
        )
        payload.setdefault("version", SIDECAR_VERSION)
        payload.setdefault("projectId", self.project_id)
        payload.setdefault("tasks", [])
        for task in payload.get("tasks", []):
            normalize_task_pr_fields(task)
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
            "repoRoot": str(self.git.repo_root),
            "sidecarRoot": str(self.sidecar_root),
            "updatedAt": now_iso(),
            "activeTaskCount": len(active_like_tasks),
            "activeTasks": active_like_tasks,
            "currentBranch": self.git.branch,
            "currentWorktree": str(self.git.worktree_path),
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
            "goal": "",
            "branch": self.git.branch,
            "baseBranch": self.git.base_branch,
            "worktreePath": str(self.git.worktree_path),
            "prUrl": self.git.pr_url,
            "prSearchUrl": self.git.pr_search_url,
            "touchedAreas": self.default_touched_areas(),
            "nextStep": "",
            "blocker": "",
            "lastThreadSummary": "",
            "updatedAt": now_iso(),
        }

    def upsert_task(
        self,
        payload: dict[str, Any],
        task: dict[str, Any] | None,
        args: argparse.Namespace,
        *,
        default_status: str = "active",
    ) -> dict[str, Any]:
        tasks = payload.setdefault("tasks", [])
        if task is None:
            task = self.default_task()
            tasks.append(task)

        if getattr(args, "task_id", None):
            task["taskId"] = slugify(args.task_id)
        elif task.get("branch") and task.get("branch") != self.git.branch:
            task["taskId"] = self.task_id_for_branch()
        if getattr(args, "status", None):
            task["status"] = args.status
        elif not task.get("status"):
            task["status"] = default_status
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

        task["branch"] = self.git.branch
        task["baseBranch"] = self.git.base_branch
        task["worktreePath"] = str(self.git.worktree_path)
        task["updatedAt"] = now_iso()
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


def build_handoff_markdown(task: dict[str, Any], args: argparse.Namespace, manager: SidecarManager) -> str:
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
    validation_tests = args.validation_tests or "not run"
    validation_manual = args.validation_manual or "not run"
    validation_notes = args.validation_notes or ""
    current_objective = args.current_objective or task.get("goal") or "Current objective not recorded."

    lines = [
        f"# Handoff: {task['taskId']}",
        "",
        "## Meta",
        f"- Goal: {task.get('goal') or 'Goal not recorded.'}",
        f"- Status: {task.get('status') or 'active'}",
        f"- Branch: {task.get('branch') or manager.git.branch}",
        f"- Base Branch: {task.get('baseBranch') or manager.git.base_branch}",
        f"- Worktree: {task.get('worktreePath') or str(manager.git.worktree_path)}",
        f"- PR: {pr_url or 'None'}",
        f"- PR Search: {pr_search_url or 'None'}",
        f"- Updated At: {task.get('updatedAt') or now_iso()}",
        "",
        "## Current Objective",
        current_objective,
        "",
        "## Done",
    ]
    lines.extend([f"- {item}" for item in done_items] or ["- None"])
    lines.extend(["", "## Not Done"])
    lines.extend([f"- {item}" for item in not_done_items] or ["- None"])
    lines.extend(["", "## Blocker", f"- {task.get('blocker') or 'None'}", "", "## Touched Areas"])
    lines.extend([f"- {item}" for item in touched_areas] or ["- None"])
    lines.extend(["", "## Key Files"])
    lines.extend([f"- {item}" for item in key_files] or ["- None"])
    lines.extend(["", "## Suggested Next Step", f"- {task.get('nextStep') or 'Next step not recorded.'}"])
    lines.extend(
        [
            "",
            "## Validation Status",
            f"- Tests: {validation_tests}",
            f"- Manual Check: {validation_manual}",
            f"- Notes: {validation_notes or 'None'}",
            "",
            "## Risks",
        ]
    )
    lines.extend([f"- {item}" for item in risk_items] or ["- None"])
    lines.extend(["", "## Thread Summary", task.get("lastThreadSummary") or "Thread summary not recorded.", ""])
    return "\n".join(lines)


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
    return {
        "available": True,
        "authenticated": proc.returncode == 0,
        "path": gh_path,
        "message": output or ("authenticated" if proc.returncode == 0 else "not authenticated"),
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
        archive_md_path.write_text(handoff_path.read_text(encoding="utf-8"), encoding="utf-8")

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


def build_weekly_report(manager: SidecarManager, state: dict[str, Any], period: str) -> str:
    active_tasks = state.get("activeTasks", [])
    lines = [
        f"# Weekly Report: {manager.project_id}",
        "",
        f"- Period: {period}",
        f"- Generated At: {now_iso()}",
        f"- Sidecar: {manager.sidecar_root}",
        "",
        "## Snapshot",
        f"- Active tasks: {state.get('activeTaskCount', 0)}",
        f"- Current branch: {state.get('currentBranch') or 'unknown'}",
        "",
        "## Active Work",
    ]
    if active_tasks:
        for task in active_tasks:
            lines.extend(
                [
                    f"- {task.get('taskId')}: {task.get('goal') or 'No goal recorded'}",
                    f"  Status: {task.get('status') or 'active'}; next step: {task.get('nextStep') or 'None'}",
                ]
            )
    else:
        lines.append("- No active tasks recorded.")

    lines.extend(["", "## Human Note", "Use this report as a short project update. Agents should prefer `project-state.json` plus latest handoff for compact context."])
    return "\n".join(lines) + "\n"


def cmd_init(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
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
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    snapshot = {
        "projectId": manager.project_id,
        "repoRoot": str(manager.git.repo_root),
        "branch": manager.git.branch,
        "baseBranch": manager.git.base_branch,
        "worktreePath": str(manager.git.worktree_path),
        "gitStatusSummary": manager.git.git_status_summary,
        "recentCommits": manager.git.recent_commits,
        "touchedFiles": manager.git.touched_files,
        "touchedAreas": manager.default_touched_areas(),
        "prUrl": manager.git.pr_url,
        "prSearchUrl": manager.git.pr_search_url,
        "stableDocs": stable_doc_status(manager.git.repo_root),
    }
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
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
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
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
    task = candidates[0] if candidates else None
    conflicts = [item.get("taskId", "<unknown>") for item in candidates[1:]]
    sidecar_hit = task is not None
    task = manager.upsert_task(payload, task, args)
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


def cmd_resume_feature(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
    task, conflicts = manager.find_task(payload)
    sidecar_hit = task is not None
    if task is None:
        task = manager.default_task()

    snapshot = manager.task_snapshot(task, conflicts)
    snapshot.update(
        {
            "stableDocs": stable_doc_status(manager.git.repo_root),
            "gitStatusSummary": manager.git.git_status_summary,
            "recentCommits": manager.git.recent_commits,
            "touchedFiles": manager.git.touched_files,
            "missingContext": [],
            "provisional": not sidecar_hit,
        }
    )
    if not sidecar_hit:
        snapshot["missingContext"].append("sidecar task not found; using provisional task based on current branch")
    if not snapshot["handoffAvailable"]:
        snapshot["missingContext"].append("latest handoff file not found")
    for doc in snapshot["stableDocs"]:
        if doc["exists"] != "true":
            snapshot["missingContext"].append(f"missing stable doc: {doc['name']}")

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
    )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
    task, _ = manager.find_task(payload)
    sidecar_hit = task is not None
    task = manager.upsert_task(payload, task, args)

    handoff_path = manager.handoff_path_for(task)
    handoff_content = build_handoff_markdown(task, args, manager)
    handoff_path.write_text(handoff_content, encoding="utf-8")
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
                "handoffPath": str(handoff_path),
                "activeTasksPath": str(manager.active_tasks_path),
                "updatedAt": task["updatedAt"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
    task, _ = manager.find_task(payload)
    if task is None:
        raise SystemExit("no matching task to archive")

    result = archive_task(manager, payload, task, event="archive", started_at=started_at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_finish_feature(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
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
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
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
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
    state = manager.write_project_state(payload.get("tasks", []))
    period = safe_filename_label(args.period or default_weekly_period(), "weekly-report")
    report_name = f"{period}-{manager.project_id}.md"
    report_path = manager.reports_dir / report_name
    report_path.write_text(build_weekly_report(manager, state, period), encoding="utf-8")
    notification = f"Weekly context report is ready: {report_path}"
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


def cmd_doctor(args: argparse.Namespace) -> int:
    worktree = Path(args.worktree or os.getcwd())
    manager = SidecarManager(worktree)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Context handoff sidecar manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--worktree", help="Target worktree path. Defaults to current directory.")

    def add_task_update_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--task-id")
        subparser.add_argument("--status", choices=sorted(VALID_STATUSES))
        subparser.add_argument("--goal")
        subparser.add_argument("--next-step")
        subparser.add_argument("--blocker")
        subparser.add_argument("--thread-summary")
        subparser.add_argument("--pr-url")
        subparser.add_argument("--touched-area", dest="touched_areas", action="append")

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

    resume_parser = subparsers.add_parser("resume-feature", help="Resolve the current task and print compact resume JSON")
    add_common(resume_parser)
    resume_parser.add_argument("--estimated-rebuild-minutes", type=int)
    resume_parser.add_argument("--duplicate-scan", action="store_true")
    resume_parser.add_argument("--first-step-correct", action="store_true")
    resume_parser.add_argument("--notes", default="")
    resume_parser.set_defaults(func=cmd_resume_feature)

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

    doctor_parser = subparsers.add_parser("doctor", help="Report environment readiness without changing global state")
    add_common(doctor_parser)
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
