from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "skills" / "agent-workflow-hub" / "scripts" / "context_sidecar.py"
SERVER = ROOT / "plugins" / "awh-project-hub" / "dist" / "server.mjs"
PROJECT_ID = "awh-project-hub-e2e"


class McpClient:
    def __init__(self, env: dict[str, str]) -> None:
        self.process = subprocess.Popen(
            ["node", str(SERVER)],
            cwd=SERVER.parent.parent,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.request_id = 0
        self.closed = False

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.request_id += 1
        self.process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                assert self.process.stderr is not None
                raise AssertionError(f"MCP server stopped: {self.process.stderr.read()}")
            message = json.loads(line)
            if message.get("id") != self.request_id:
                continue
            if "error" in message:
                raise AssertionError(f"MCP error: {message['error']}")
            return message["result"]

    def notify(self, method: str, params: dict[str, object] | None = None) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }) + "\n")
        self.process.stdin.flush()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.process.wait(timeout=10)
        if self.process.returncode != 0:
            assert self.process.stderr is not None
            raise AssertionError(self.process.stderr.read())
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()


class ProjectHubEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.home = Path(self.temp_dir.name) / "home"
        self.repo = Path(self.temp_dir.name) / "repo"
        self.home.mkdir()
        self.repo.mkdir()
        self.env = dict(os.environ)
        self.env.update({
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "AWH_PYTHON": sys.executable,
            "AWH_SIDECAR_SCRIPT": str(SIDECAR),
        })
        self.run_process(["git", "init", "-b", "main"], cwd=self.repo)
        self.run_process(["git", "config", "user.name", "AWH Test"], cwd=self.repo)
        self.run_process(["git", "config", "user.email", "awh@example.test"], cwd=self.repo)
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.run_process(["git", "add", "README.md"], cwd=self.repo)
        self.run_process(["git", "commit", "-m", "fixture"], cwd=self.repo)

    def run_process(self, command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd or ROOT,
            env=self.env,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )

    def run_cli(self, action: str, *extra: str) -> dict[str, object]:
        result = self.run_process([
            sys.executable,
            str(SIDECAR),
            action,
            "--worktree",
            str(self.repo),
            "--project-id",
            PROJECT_ID,
            *extra,
        ])
        return json.loads(result.stdout)

    @property
    def active_tasks_path(self) -> Path:
        return self.home / ".codex" / "projects" / PROJECT_ID / "active-tasks.json"

    def test_real_sidecar_data_refreshes_without_restarting_mcp(self) -> None:
        started = self.run_cli(
            "start-feature",
            "--task-id", "hub-work-item",
            "--goal", "Ship the fullscreen Project Hub",
            "--status", "blocked",
            "--blocker", "Waiting for desktop validation",
            "--next-step", "Open the MCP App",
            "--thread-role", "primary-execution",
            "--thread-label", "Hub execution",
            "--thread-purpose", "Build and validate the plugin",
            "--validation-command", "python -m unittest",
            "--validation-result", "focused checks passed",
            "--validation-at", "2026-08-18T12:00:00+08:00",
        )
        self.assertEqual(started["task"]["taskId"], "hub-work-item")

        sidecar = json.loads(self.active_tasks_path.read_text(encoding="utf-8"))
        task = next(item for item in sidecar["tasks"] if item["taskId"] == "hub-work-item")
        task["threads"] = [
            {
                "threadId": "discussion-task",
                "codexThreadId": "codex-discussion",
                "threadLabel": "Hub discussion",
                "threadRole": "discussion",
                "threadPurpose": "Confirm the read-only product boundary",
                "environmentType": "none",
                "worktreePath": "",
            },
            {
                "threadId": "execution-task",
                "codexThreadId": "codex-execution",
                "threadLabel": "Hub execution",
                "threadRole": "primary-execution",
                "threadPurpose": "Build and validate the plugin",
                "environmentType": "worktree",
                "worktreePath": str(self.repo),
            },
        ]
        self.active_tasks_path.write_text(
            json.dumps(sidecar, indent=2) + "\n",
            encoding="utf-8",
        )

        static_result = self.run_cli("visualize-project")
        self.assertTrue(Path(static_result["reportPaths"]["html"]).is_file())

        client = McpClient(self.env)
        self.addCleanup(client.close)
        initialized = client.request("initialize", {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "awh-e2e", "version": "1.0.0"},
        })
        self.assertEqual(initialized["serverInfo"]["name"], "awh-project-hub")
        client.notify("notifications/initialized")

        tools = client.request("tools/list")["tools"]
        self.assertEqual(
            sorted(tool["name"] for tool in tools),
            ["get_awh_project_hub", "open_awh_project_hub"],
        )
        resources = client.request("resources/list")["resources"]
        resource = client.request("resources/read", {"uri": resources[0]["uri"]})
        self.assertEqual(resource["contents"][0]["mimeType"], "text/html;profile=mcp-app")

        opened = client.request("tools/call", {
            "name": "open_awh_project_hub",
            "arguments": {"worktreePath": str(self.repo), "projectId": PROJECT_ID},
        })
        payload = opened["_meta"]["awhProjectHub"]
        work_item = next(item for item in payload["workItems"] if item["workItemId"] == "hub-work-item")
        self.assertEqual(work_item["health"], "blocked")
        self.assertEqual(work_item["blocker"], "Waiting for desktop validation")
        self.assertEqual(
            [task["role"] for task in work_item["codexTasks"]],
            ["discussion", "primary-execution"],
        )
        self.assertIsNone(work_item["codexTasks"][0]["environment"])
        self.assertEqual(
            Path(work_item["codexTasks"][1]["environment"]["worktreePath"]),
            self.repo,
        )

        self.run_cli(
            "start-feature",
            "--task-id", "hub-work-item",
            "--status", "active",
            "--blocker", "Desktop refresh confirmed",
        )
        refreshed = client.request("tools/call", {
            "name": "get_awh_project_hub",
            "arguments": {"worktreePath": str(self.repo), "projectId": PROJECT_ID},
        })
        refreshed_item = next(
            item for item in refreshed["_meta"]["awhProjectHub"]["workItems"]
            if item["workItemId"] == "hub-work-item"
        )
        self.assertEqual(refreshed_item["blocker"], "Desktop refresh confirmed")


if __name__ == "__main__":
    unittest.main()
