import { z } from "zod";


export const EnvironmentSchema = z.object({
  type: z.string(),
  worktreePath: z.string(),
  branch: z.string(),
  dirty: z.boolean(),
  stale: z.boolean(),
  dirtyFiles: z.array(z.string()),
}).passthrough();

export const CodexTaskSchema = z.object({
  taskKey: z.string(),
  threadId: z.string(),
  codexThreadId: z.string(),
  label: z.string(),
  role: z.string(),
  purpose: z.string(),
  status: z.string(),
  environment: EnvironmentSchema.nullable(),
}).passthrough();

export const WorkItemSchema = z.object({
  workItemId: z.string(),
  title: z.string(),
  status: z.string(),
  health: z.enum(["healthy", "attention", "blocked", "archived"]),
  codexTasks: z.array(CodexTaskSchema),
  blocker: z.string(),
  nextStep: z.string(),
  validationPresent: z.boolean(),
  handoffAvailable: z.boolean(),
  routing: z.object({
    status: z.string(),
    confidence: z.unknown().nullable().optional(),
    needsReview: z.boolean(),
    evidence: z.array(z.string()),
  }).passthrough(),
  machine: z.record(z.string(), z.unknown()),
}).passthrough();

export const ProjectHubPayloadSchema = z.object({
  schemaVersion: z.literal("awh.project-hub/v1"),
  project: z.object({
    projectId: z.string(),
    baseBranch: z.string(),
    generatedAt: z.string(),
    health: z.enum(["healthy", "attention", "blocked"]),
  }).passthrough(),
  summary: z.record(z.string(), z.unknown()),
  workItems: z.array(WorkItemSchema),
  needsAttention: z.array(z.unknown()),
  warnings: z.array(z.string()),
  canonicalRepoRoot: z.string().optional(),
  sidecarRoot: z.string().optional(),
}).passthrough();

export type Environment = z.infer<typeof EnvironmentSchema>;
export type CodexTask = z.infer<typeof CodexTaskSchema>;
export type WorkItem = z.infer<typeof WorkItemSchema>;
export type ProjectHubPayload = z.infer<typeof ProjectHubPayloadSchema>;

export interface ProjectLocator {
  worktreePath?: string;
  projectId?: string;
}
