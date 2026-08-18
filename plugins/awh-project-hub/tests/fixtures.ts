import type { ProjectHubPayload } from "../src/types.js";


export const fixturePayload: ProjectHubPayload = {
  schemaVersion: "awh.project-hub/v1",
  project: {
    projectId: "demo",
    baseBranch: "main",
    generatedAt: "2026-08-18T00:00:00+08:00",
    health: "blocked",
  },
  summary: { visibleTasks: 2 },
  workItems: [
    {
      workItemId: "blocked-item",
      title: "Execution blocker",
      status: "blocked",
      health: "blocked",
      codexTasks: [
        {
          taskKey: "thr-1",
          threadId: "thr-1",
          codexThreadId: "codex-1",
          label: "Primary execution",
          role: "primary-execution",
          purpose: "Implement the hub",
          status: "active",
          environment: {
            type: "worktree",
            worktreePath: "C:/repo",
            branch: "codex/hub",
            dirty: false,
            stale: false,
            dirtyFiles: [],
          },
        },
      ],
      blocker: "Review required",
      nextStep: "Review",
      validationPresent: true,
      handoffAvailable: true,
      routing: { status: "confirmed", confidence: 1, needsReview: false, evidence: ["fixture"] },
      machine: { taskId: "blocked-item" },
    },
    {
      workItemId: "research-item",
      title: "Research route",
      status: "active",
      health: "healthy",
      codexTasks: [
        {
          taskKey: "thr-2",
          threadId: "thr-2",
          codexThreadId: "",
          label: "Research",
          role: "research",
          purpose: "Collect evidence",
          status: "active",
          environment: null,
        },
      ],
      blocker: "",
      nextStep: "Continue",
      validationPresent: false,
      handoffAvailable: false,
      routing: { status: "confirmed", confidence: 1, needsReview: false, evidence: [] },
      machine: { taskId: "research-item" },
    },
  ],
  needsAttention: [{ taskId: "blocked-item" }],
  warnings: [],
  canonicalRepoRoot: "C:/repo",
  sidecarRoot: "C:/sidecar",
};
