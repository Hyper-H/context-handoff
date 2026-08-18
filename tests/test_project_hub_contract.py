from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "agent-workflow-hub" / "scripts" / "context_sidecar.py"


def load_sidecar():
    spec = importlib.util.spec_from_file_location("awh_context_sidecar", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectHubContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sidecar = load_sidecar()

    def test_maps_work_item_threads_and_environment_without_renaming_keys(self):
        report = {
            "projectId": "demo",
            "baseBranch": "main",
            "generatedAt": "2026-08-17T12:00:00+08:00",
            "summaryCounts": {"visibleTasks": 1, "blocked": 1},
            "taskRows": [
                {
                    "taskId": "wi-1",
                    "goal": "Ship hub",
                    "taskStatus": "blocked",
                    "health": "blocked",
                    "threads": [
                        {
                            "threadId": "thr-1",
                            "codexThreadId": "codex-1",
                            "threadLabel": "Execution",
                            "threadRole": "primary-execution",
                            "threadPurpose": "Build it",
                            "environmentType": "worktree",
                            "worktreePath": "C:/repo/wt",
                        }
                    ],
                    "branch": "codex/hub",
                    "dirty": True,
                    "dirtyFiles": ["changed.py"],
                    "stale": False,
                    "blocker": "Needs review",
                    "nextStep": "Review",
                    "validationPresent": True,
                    "handoffAvailable": True,
                }
            ],
            "needsAttention": [{"taskId": "wi-1"}],
            "warnings": [],
        }

        contract = self.sidecar.build_project_hub_contract(report)
        work_item = contract["workItems"][0]
        codex_task = work_item["codexTasks"][0]

        self.assertEqual(contract["schemaVersion"], "awh.project-hub/v1")
        self.assertEqual(work_item["workItemId"], "wi-1")
        self.assertEqual(codex_task["taskKey"], "thr-1")
        self.assertEqual(codex_task["threadId"], "thr-1")
        self.assertEqual(codex_task["codexThreadId"], "codex-1")
        self.assertEqual(codex_task["role"], "primary-execution")
        self.assertEqual(codex_task["environment"]["worktreePath"], "C:/repo/wt")
        self.assertTrue(codex_task["environment"]["dirty"])
        self.assertEqual(codex_task["environment"]["dirtyFiles"], ["changed.py"])

    def test_synthesizes_legacy_codex_task_without_mutating_source(self):
        row = {
            "taskId": "legacy",
            "taskStatus": "active",
            "health": "attention",
            "threadRole": "research",
            "threadLabel": "Research",
            "threadPurpose": "Investigate",
            "worktreePath": "",
        }
        report = {
            "projectId": "demo",
            "baseBranch": "main",
            "generatedAt": "now",
            "summaryCounts": {},
            "taskRows": [row],
            "needsAttention": [],
            "warnings": [],
        }

        contract = self.sidecar.build_project_hub_contract(report)
        task = contract["workItems"][0]["codexTasks"][0]

        self.assertEqual(task["role"], "research")
        self.assertIsNone(task["environment"])
        self.assertNotIn("threads", row)

    def test_preserves_multiple_threads_for_one_work_item(self):
        report = {
            "projectId": "demo",
            "baseBranch": "main",
            "generatedAt": "now",
            "summaryCounts": {},
            "needsAttention": [],
            "warnings": [],
            "taskRows": [
                {
                    "taskId": "wi",
                    "taskStatus": "active",
                    "health": "healthy",
                    "threads": [
                        {
                            "threadId": "a",
                            "threadRole": "discussion",
                            "worktreePath": "",
                        },
                        {
                            "threadId": "b",
                            "threadRole": "primary-execution",
                            "worktreePath": "C:/wt",
                        },
                    ],
                }
            ],
        }

        contract = self.sidecar.build_project_hub_contract(report)
        tasks = contract["workItems"][0]["codexTasks"]

        self.assertEqual([task["taskKey"] for task in tasks], ["a", "b"])
        self.assertEqual([task["role"] for task in tasks], ["discussion", "primary-execution"])
        self.assertIsNone(tasks[0]["environment"])
        self.assertEqual(tasks[1]["environment"]["worktreePath"], "C:/wt")


if __name__ == "__main__":
    unittest.main()
