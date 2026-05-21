#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = {"active", "paused", "blocked", "review"}


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


class SidecarManager:
    def __init__(self, worktree: Path):
        self.worktree = worktree.resolve()
        self.git = self._detect_git_context()
        self.project_id = slugify(self.git.repo_root.name)
        self.sidecar_root = Path.home() / ".codex" / "projects" / self.project_id
        self.active_tasks_path = self.sidecar_root / "active-tasks.json"
        self.handoffs_dir = self.sidecar_root / "handoffs"
        self.archive_dir = self.sidecar_root / "archive"
        self.events_path = self.sidecar_root / "events.jsonl"

    def _detect_git_context(self) -> GitContext:
        rc, repo_root, _ = run_git(["rev-parse", "--show-toplevel"], self.worktree)
        if rc != 0 or not repo_root:
            repo_root = str(self.worktree)
        repo_root_path = Path(repo_root).resolve()

        rc, branch, _ = run_git(["branch", "--show-current"], repo_root_path)
        if rc != 0 or not branch:
            branch = "unknown"

        rc, base_branch, _ = run_git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            repo_root_path,
        )
        if rc != 0 or not base_branch:
            base_branch = "main"
        if "/" in base_branch:
            base_branch = base_branch.split("/")[-1]

        rc, recent_commits_raw, _ = run_git(
            ["log", "--oneline", "-5"],
            repo_root_path,
        )
        recent_commits = [line for line in recent_commits_raw.splitlines() if line] if rc == 0 else []

        rc, status_raw, _ = run_git(["status", "--short"], repo_root_path)
        status_lines = [line for line in status_raw.splitlines() if line] if rc == 0 else []
        touched_files = [line[3:] for line in status_lines if len(line) >= 4]

        pr_url = ""
        rc, remote_url, _ = run_git(["remote", "get-url", "origin"], repo_root_path)
        if rc == 0 and remote_url:
            pr_url = self._guess_pr_url(remote_url, branch)

        return GitContext(
            repo_root=repo_root_path,
            branch=branch,
            base_branch=base_branch,
            worktree_path=self.worktree,
            recent_commits=recent_commits,
            touched_files=touched_files,
            git_status_summary=status_lines,
            pr_url=pr_url,
        )

    def _guess_pr_url(self, remote_url: str, branch: str) -> str:
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
        if not self.active_tasks_path.exists():
            write_json(
                self.active_tasks_path,
                {"version": 1, "projectId": self.project_id, "tasks": []},
            )

    def load_active_tasks(self) -> dict[str, Any]:
        self.ensure_layout()
        payload = read_json(self.active_tasks_path, {"version": 1, "projectId": self.project_id, "tasks": []})
        payload.setdefault("version", 1)
        payload.setdefault("projectId", self.project_id)
        payload.setdefault("tasks", [])
        return payload

    def save_active_tasks(self, payload: dict[str, Any]) -> None:
        write_json(self.active_tasks_path, payload)

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
            "touchedAreas": self.default_touched_areas(),
            "nextStep": "",
            "blocker": "",
            "lastThreadSummary": "",
            "updatedAt": now_iso(),
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
    pr_url = task.get("prUrl") or manager.git.pr_url or ""
    validation_tests = args.validation_tests or "not run"
    validation_manual = args.validation_manual or "not run"
    validation_notes = args.validation_notes or ""
    current_objective = args.current_objective or task.get("goal") or "待补充当前目标"

    lines = [
        f"# Handoff: {task['taskId']}",
        "",
        "## Meta",
        f"- Goal: {task.get('goal') or '待补充目标'}",
        f"- Status: {task.get('status') or 'active'}",
        f"- Branch: {task.get('branch') or manager.git.branch}",
        f"- Base Branch: {task.get('baseBranch') or manager.git.base_branch}",
        f"- Worktree: {task.get('worktreePath') or str(manager.git.worktree_path)}",
        f"- PR: {pr_url or 'None'}",
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
    lines.extend(["", "## Suggested Next Step", f"- {task.get('nextStep') or '待补充下一步'}"])
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
    lines.extend(["", "## Thread Summary", task.get("lastThreadSummary") or "待补充 thread 摘要", ""])
    return "\n".join(lines)


def cmd_init(args: argparse.Namespace) -> int:
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    manager.ensure_layout()
    payload = manager.load_active_tasks()
    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "sidecarRoot": str(manager.sidecar_root),
                "activeTasksPath": str(manager.active_tasks_path),
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
        "stableDocs": stable_doc_status(manager.git.repo_root),
    }
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def cmd_intake(args: argparse.Namespace) -> int:
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
    task, conflicts = manager.find_task(payload)
    provisional = False
    if task is None:
        provisional = True
        task = manager.default_task()

    handoff_path = manager.handoffs_dir / f"{task['taskId']}.md"
    handoff_available = handoff_path.exists()
    output = {
        "projectId": manager.project_id,
        "taskId": task["taskId"],
        "status": task.get("status", "active"),
        "goal": task.get("goal", ""),
        "branch": task.get("branch", manager.git.branch),
        "worktreePath": task.get("worktreePath", str(manager.git.worktree_path)),
        "prUrl": task.get("prUrl", ""),
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

    append_jsonl(
        manager.events_path,
        {
            "timestamp": now_iso(),
            "projectId": manager.project_id,
            "taskId": task["taskId"],
            "event": "intake",
            "handoffAvailable": handoff_available,
            "estimatedRebuildMinutes": args.estimated_rebuild_minutes if args.estimated_rebuild_minutes is not None else None,
            "duplicateScan": args.duplicate_scan,
            "firstStepCorrect": args.first_step_correct,
            "notes": args.notes or "",
        },
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
    task, _ = manager.find_task(payload)
    tasks = payload.get("tasks", [])
    if task is None:
        task = manager.default_task()
        tasks.append(task)

    if args.task_id:
        task["taskId"] = slugify(args.task_id)
    if args.status:
        if args.status not in VALID_STATUSES:
            raise SystemExit(f"invalid status: {args.status}")
        task["status"] = args.status
    if args.goal is not None:
        task["goal"] = short_text(args.goal)
    if args.next_step is not None:
        task["nextStep"] = short_text(args.next_step)
    if args.blocker is not None:
        task["blocker"] = short_text(args.blocker)
    if args.thread_summary is not None:
        task["lastThreadSummary"] = short_text(args.thread_summary, max_len=320)
    if args.pr_url is not None:
        task["prUrl"] = args.pr_url
    elif not task.get("prUrl"):
        task["prUrl"] = manager.git.pr_url
    if args.touched_areas:
        task["touchedAreas"] = [short_text(area, max_len=80) for area in args.touched_areas[:8]]
    elif not task.get("touchedAreas"):
        task["touchedAreas"] = manager.default_touched_areas()

    task["branch"] = manager.git.branch
    task["baseBranch"] = manager.git.base_branch
    task["worktreePath"] = str(manager.git.worktree_path)
    task["updatedAt"] = now_iso()

    handoff_path = manager.handoffs_dir / f"{task['taskId']}.md"
    handoff_content = build_handoff_markdown(task, args, manager)
    handoff_path.write_text(handoff_content, encoding="utf-8")
    manager.save_active_tasks(payload)

    append_jsonl(
        manager.events_path,
        {
            "timestamp": now_iso(),
            "projectId": manager.project_id,
            "taskId": task["taskId"],
            "event": "handoff",
            "handoffAvailable": True,
            "estimatedRebuildMinutes": args.estimated_rebuild_minutes if args.estimated_rebuild_minutes is not None else None,
            "duplicateScan": args.duplicate_scan,
            "firstStepCorrect": args.first_step_correct,
            "notes": args.notes or "",
        },
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
    manager = SidecarManager(Path(args.worktree or os.getcwd()))
    payload = manager.load_active_tasks()
    task, _ = manager.find_task(payload)
    if task is None:
        raise SystemExit("no matching task to archive")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_base = f"{task['taskId']}-{timestamp}"
    archive_json_path = manager.archive_dir / f"{archive_base}.json"
    archive_md_path = manager.archive_dir / f"{archive_base}.md"
    handoff_path = manager.handoffs_dir / f"{task['taskId']}.md"

    write_json(archive_json_path, task)
    if handoff_path.exists():
        archive_md_path.write_text(handoff_path.read_text(encoding="utf-8"), encoding="utf-8")

    payload["tasks"] = [item for item in payload.get("tasks", []) if item.get("taskId") != task.get("taskId")]
    manager.save_active_tasks(payload)

    print(
        json.dumps(
            {
                "projectId": manager.project_id,
                "taskId": task["taskId"],
                "archivedJson": str(archive_json_path),
                "archivedHandoff": str(archive_md_path) if archive_md_path.exists() else "",
                "removedFromActiveTasks": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worktree context reuse v1 sidecar manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--worktree", help="Target worktree path. Defaults to current directory.")

    init_parser = subparsers.add_parser("init", help="Initialize the sidecar layout for the current worktree")
    add_common(init_parser)
    init_parser.set_defaults(func=cmd_init)

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

    handoff_parser = subparsers.add_parser("handoff", help="Update the current task and write the latest handoff")
    add_common(handoff_parser)
    handoff_parser.add_argument("--task-id")
    handoff_parser.add_argument("--status", choices=sorted(VALID_STATUSES))
    handoff_parser.add_argument("--goal")
    handoff_parser.add_argument("--next-step")
    handoff_parser.add_argument("--blocker")
    handoff_parser.add_argument("--thread-summary")
    handoff_parser.add_argument("--pr-url")
    handoff_parser.add_argument("--current-objective")
    handoff_parser.add_argument("--validation-tests")
    handoff_parser.add_argument("--validation-manual")
    handoff_parser.add_argument("--validation-notes")
    handoff_parser.add_argument("--estimated-rebuild-minutes", type=int)
    handoff_parser.add_argument("--duplicate-scan", action="store_true")
    handoff_parser.add_argument("--first-step-correct", action="store_true")
    handoff_parser.add_argument("--notes", default="")
    handoff_parser.add_argument("--touched-area", dest="touched_areas", action="append")
    handoff_parser.add_argument("--done", action="append")
    handoff_parser.add_argument("--not-done", dest="not_done", action="append")
    handoff_parser.add_argument("--risk", dest="risks", action="append")
    handoff_parser.add_argument("--key-file", dest="key_files", action="append")
    handoff_parser.set_defaults(func=cmd_handoff)

    archive_parser = subparsers.add_parser("archive", help="Archive the current task and remove it from active tasks")
    add_common(archive_parser)
    archive_parser.set_defaults(func=cmd_archive)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
