import {
  ProjectHubPayloadSchema,
  type CodexTask,
  type ProjectHubPayload,
  type WorkItem,
} from "../src/types.js";


export interface HubFilter {
  query: string;
  health: "all" | "healthy" | "attention" | "blocked" | "archived";
}

export interface HubSelection {
  workItemId: string;
  taskKey: string;
}

export function parseProjectHubPayload(value: unknown): ProjectHubPayload {
  return ProjectHubPayloadSchema.parse(value);
}

export function visibleWorkItems(items: WorkItem[], filter: HubFilter): WorkItem[] {
  const query = filter.query.trim().toLocaleLowerCase();
  return items.filter((item) => {
    if (filter.health !== "all" && item.health !== filter.health) {
      return false;
    }
    if (!query) {
      return true;
    }
    const searchable = [
      item.workItemId,
      item.title,
      item.status,
      item.blocker,
      item.nextStep,
      ...item.codexTasks.flatMap((task) => [
        task.taskKey,
        task.label,
        task.role,
        task.purpose,
        task.environment?.branch ?? "",
        task.environment?.worktreePath ?? "",
      ]),
    ].join(" ").toLocaleLowerCase();
    return searchable.includes(query);
  });
}

export function reconcileSelection(
  payload: ProjectHubPayload,
  requested: Partial<HubSelection>,
): HubSelection {
  const item = payload.workItems.find((candidate) => candidate.workItemId === requested.workItemId)
    ?? payload.workItems[0];
  if (!item) {
    return { workItemId: "", taskKey: "" };
  }
  const task = item.codexTasks.find((candidate) => candidate.taskKey === requested.taskKey)
    ?? item.codexTasks[0];
  return { workItemId: item.workItemId, taskKey: task?.taskKey ?? "" };
}

export function selectedEntities(
  payload: ProjectHubPayload,
  selection: HubSelection,
): { workItem?: WorkItem; codexTask?: CodexTask } {
  const workItem = payload.workItems.find((item) => item.workItemId === selection.workItemId);
  const codexTask = workItem?.codexTasks.find((task) => task.taskKey === selection.taskKey);
  return { workItem, codexTask };
}

export function taskEnvironmentLabel(task: CodexTask): string {
  if (!task.environment) {
    return "No environment";
  }
  if (task.environment.type !== "worktree") {
    return task.environment.type;
  }
  return task.environment.branch || task.environment.worktreePath || task.environment.type;
}

export function countCodexTasks(payload: ProjectHubPayload): number {
  return payload.workItems.reduce((total, item) => total + item.codexTasks.length, 0);
}
