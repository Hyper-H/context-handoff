from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "agent-workflow-hub" / "scripts" / "context_sidecar.py"
PYTHON = Path(os.environ.get("AWH_TEST_PYTHON", os.sys.executable))


class ProjectHubStaticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.repo = Path(self.temp.name) / "repo"
        self.home.mkdir()
        self.repo.mkdir()
        self.env = dict(os.environ)
        self.env.update({"HOME": str(self.home), "USERPROFILE": str(self.home)})
        self.run_process(["git", "init", "-b", "main"], cwd=self.repo)
        self.run_process(["git", "config", "user.name", "AWH Test"], cwd=self.repo)
        self.run_process(["git", "config", "user.email", "awh@example.test"], cwd=self.repo)
        (self.repo / "README.md").write_text("fixture\n", encoding="utf-8")
        self.run_process(["git", "add", "README.md"], cwd=self.repo)
        self.run_process(["git", "commit", "-m", "fixture"], cwd=self.repo)

    def run_process(self, command, *, cwd=None):
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

    def run_cli(self, action):
        return self.run_process(
            [
                str(PYTHON),
                str(SCRIPT),
                action,
                "--worktree",
                str(self.repo),
                "--project-id",
                "awh-project-hub-test",
                "--language",
                "en",
            ]
        )

    @property
    def reports_dir(self):
        return self.home / ".codex" / "projects" / "awh-project-hub-test" / "reports"

    def test_project_hub_payload_is_json_and_does_not_write_reports(self):
        result = self.run_cli("project-hub-payload")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["schemaVersion"], "awh.project-hub/v1")
        self.assertEqual(payload["project"]["projectId"], payload["projectId"])
        self.assertFalse(list(self.reports_dir.glob("visual-*")))

    def test_visualize_project_still_writes_markdown_json_and_html(self):
        result = self.run_cli("visualize-project")
        output = json.loads(result.stdout)

        for key in ("markdown", "json", "html"):
            self.assertTrue(Path(output["reportPaths"][key]).is_file())
        html = Path(output["reportPaths"]["html"]).read_text(encoding="utf-8")
        self.assertIn("awh.project-hub/v1", html)
        self.assertIn("Project Hub", html)


if __name__ == "__main__":
    unittest.main()
