from __future__ import annotations

import json
from datetime import datetime, timezone


payload = {
    "schemaVersion": "awh.project-hub/v1",
    "project": {
        "projectId": "stdio-fixture",
        "baseBranch": "main",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "health": "attention",
    },
    "summary": {"visibleTasks": 1},
    "workItems": [{
        "workItemId": "work-item-1",
        "title": "MCP contract fixture",
        "status": "active",
        "health": "attention",
        "codexTasks": [{
            "taskKey": "thread-1",
            "threadId": "thread-1",
            "codexThreadId": "codex-task-1",
            "label": "Execution",
            "role": "primary-execution",
            "purpose": "Exercise the MCP contract",
            "status": "active",
            "environment": {
                "type": "worktree",
                "worktreePath": "C:/fixture",
                "branch": "codex/fixture",
                "dirty": False,
                "stale": False,
                "dirtyFiles": [],
            },
        }],
        "blocker": "",
        "nextStep": "Validate",
        "validationPresent": True,
        "handoffAvailable": True,
        "routing": {
            "status": "confirmed",
            "confidence": 1,
            "needsReview": False,
            "evidence": ["fixture"],
        },
        "machine": {"taskId": "work-item-1"},
    }],
    "needsAttention": [{"taskId": "work-item-1"}],
    "warnings": [],
    "canonicalRepoRoot": "C:/fixture",
    "sidecarRoot": "C:/sidecar",
}

print(json.dumps(payload))
