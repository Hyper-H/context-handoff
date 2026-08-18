import {
  AlertTriangle,
  FolderGit2,
  GitBranch,
  Maximize2,
  RefreshCw,
  Search,
  createIcons,
} from "lucide";

import type { CodexTask, ProjectHubPayload, WorkItem } from "../src/types.js";
import { HubBridge, payloadFromToolResult, type LocalUiState } from "./bridge.js";
import {
  countCodexTasks,
  parseProjectHubPayload,
  reconcileSelection,
  selectedEntities,
  taskEnvironmentLabel,
  visibleWorkItems,
} from "./model.js";


const appRoot = document.querySelector<HTMLElement>("#app");
if (!appRoot) {
  throw new Error("AWH Project Hub root element is missing.");
}
const app: HTMLElement = appRoot;

const bridge = new HubBridge();
let payload: ProjectHubPayload | undefined;
let ui: LocalUiState = bridge.loadLocalState();
let error = "";
let stale = false;
let refreshing = false;
let fullscreenRequested = false;

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function icon(name: string, extra = ""): string {
  return `<i class="icon ${extra}" data-lucide="${name}" aria-hidden="true"></i>`;
}

function healthBadge(health: string): string {
  return `<span class="health health-${escapeHtml(health)}">${escapeHtml(health)}</span>`;
}

function hydrate(value: unknown): void {
  try {
    payload = parseProjectHubPayload(value);
    const selection = reconcileSelection(payload, ui);
    ui = { ...ui, ...selection };
    bridge.saveLocalState(ui);
    error = "";
    stale = false;
  } catch (cause) {
    error = cause instanceof Error ? cause.message : String(cause);
  }
  render();
}

function renderInline(data: ProjectHubPayload): string {
  return `
    <section class="inline-launcher" aria-busy="${refreshing}">
      <div class="launcher-head">
        <div>
          <p class="eyebrow">Agent Workflow Hub</p>
          <h1>${escapeHtml(data.project.projectId)}</h1>
          <p class="muted small">Updated ${escapeHtml(data.project.generatedAt)} · Base ${escapeHtml(data.project.baseBranch)}</p>
        </div>
        ${healthBadge(data.project.health)}
      </div>
      <div class="summary-strip">
        <div class="summary-item"><span class="summary-value">${data.workItems.length}</span><span class="muted small">Work Items</span></div>
        <div class="summary-item"><span class="summary-value">${countCodexTasks(data)}</span><span class="muted small">Codex Tasks</span></div>
        <div class="summary-item"><span class="summary-value">${data.needsAttention.length}</span><span class="muted small">Need attention</span></div>
      </div>
      ${error ? `<div class="status-banner error">${escapeHtml(error)}</div>` : ""}
      <div class="toolbar-actions">
        <button id="refresh-inline" class="icon-button" type="button" title="Refresh Hub" aria-label="Refresh Hub">${icon("refresh-cw", "refresh-icon")}</button>
        <button id="open-fullscreen" class="primary-button" type="button">${icon("maximize-2")}<span>Open fullscreen</span></button>
      </div>
    </section>`;
}

function renderWorkItem(item: WorkItem): string {
  return `
    <button class="list-row ${item.workItemId === ui.workItemId ? "active" : ""}" type="button" data-work-item="${escapeHtml(item.workItemId)}">
      <div class="row-head"><span class="row-title">${escapeHtml(item.title)}</span>${healthBadge(item.health)}</div>
      <p class="row-subtitle">${escapeHtml(item.workItemId)} · ${item.codexTasks.length} Codex Task${item.codexTasks.length === 1 ? "" : "s"}</p>
      ${item.blocker ? `<p class="blocker">${escapeHtml(item.blocker)}</p>` : ""}
    </button>`;
}

function renderCodexTask(task: CodexTask): string {
  const environment = task.environment;
  return `
    <button class="list-row ${task.taskKey === ui.taskKey ? "active" : ""}" type="button" data-codex-task="${escapeHtml(task.taskKey)}">
      <div class="row-head"><span class="row-title">${escapeHtml(task.label)}</span><span class="role-badge">${escapeHtml(task.role)}</span></div>
      <p class="row-subtitle">${escapeHtml(task.purpose || "No purpose recorded")}</p>
      <div class="task-meta">
        <span>${icon("folder-git-2")} ${escapeHtml(taskEnvironmentLabel(task))}</span>
        ${environment?.dirty ? `<span class="health health-attention">dirty</span>` : ""}
        ${environment?.stale ? `<span class="health health-attention">stale</span>` : ""}
      </div>
    </button>`;
}

function field(label: string, value: unknown, machine = false): string {
  const resolved = String(value ?? "").trim() || "Not recorded";
  return `<div class="detail-field"><span class="detail-label">${escapeHtml(label)}</span><span class="detail-value ${machine ? "machine" : ""}">${escapeHtml(resolved)}</span></div>`;
}

function renderDetails(item?: WorkItem, task?: CodexTask): string {
  if (!item) {
    return `<div class="empty">Select a Work Item to inspect details.</div>`;
  }
  const environment = task?.environment;
  return `
    <div class="detail-section">
      <div class="row-head"><h2>${escapeHtml(item.title)}</h2>${healthBadge(item.health)}</div>
      <div class="detail-grid">
        ${field("Status", item.status)}
        ${field("Work Item key", item.workItemId, true)}
        ${field("Validation", item.validationPresent ? "Present" : "Missing")}
        ${field("Handoff", item.handoffAvailable ? "Available" : "Missing")}
      </div>
    </div>
    ${item.blocker ? `<div class="detail-section"><h3>Blocker</h3><p class="blocker">${escapeHtml(item.blocker)}</p></div>` : ""}
    <div class="detail-section"><h3>Next step</h3><p class="detail-value">${escapeHtml(item.nextStep || "Not recorded")}</p></div>
    <div class="detail-section">
      <h3>Codex Task</h3>
      <div class="detail-grid">
        ${field("Label", task?.label)}
        ${field("Role", task?.role)}
        ${field("Thread key", task?.threadId, true)}
        ${field("Codex task key", task?.codexThreadId, true)}
      </div>
      <p class="detail-value">${escapeHtml(task?.purpose || "No purpose recorded")}</p>
    </div>
    <div class="detail-section">
      <h3>Environment</h3>
      <div class="detail-grid">
        ${field("Type", environment?.type || "No environment")}
        ${field("Branch", environment?.branch)}
        ${field("Worktree", environment?.worktreePath, true)}
        ${field("State", environment ? `${environment.dirty ? "dirty" : "clean"}${environment.stale ? ", stale" : ""}` : "Not applicable")}
      </div>
    </div>
    <div class="detail-section">
      <h3>Routing</h3>
      <div class="detail-grid">
        ${field("Status", item.routing.status)}
        ${field("Needs review", item.routing.needsReview ? "Yes" : "No")}
      </div>
      <p class="detail-value small">${escapeHtml(item.routing.evidence.join(" · ") || "No routing evidence recorded")}</p>
    </div>`;
}

function renderFullscreen(data: ProjectHubPayload): string {
  const filtered = visibleWorkItems(data.workItems, { query: ui.query, health: ui.health });
  const { workItem, codexTask } = selectedEntities(data, ui);
  return `
    <section class="workspace" aria-busy="${refreshing}">
      <header class="toolbar">
        <div>
          <p class="eyebrow">AWH Project Hub</p>
          <h1>${escapeHtml(data.project.projectId)}</h1>
          <p class="muted small">${data.workItems.length} Work Items · ${countCodexTasks(data)} Codex Tasks · Updated ${escapeHtml(data.project.generatedAt)}</p>
        </div>
        <div class="toolbar-actions">
          <label class="search-wrap">${icon("search")}<span class="sr-only"></span><input id="hub-search" type="search" value="${escapeHtml(ui.query)}" placeholder="Search work items and tasks" aria-label="Search work items and tasks"></label>
          <select id="health-filter" aria-label="Filter by health">
            ${["all", "healthy", "attention", "blocked", "archived"].map((value) => `<option value="${value}" ${ui.health === value ? "selected" : ""}>${value === "all" ? "All health" : value}</option>`).join("")}
          </select>
          <button id="refresh-full" class="icon-button" type="button" title="Refresh Hub" aria-label="Refresh Hub">${icon("refresh-cw", "refresh-icon")}</button>
        </div>
      </header>
      <div class="status-banner ${error ? "error" : ""}">
        ${error ? `${icon("alert-triangle")} ${escapeHtml(error)}${stale ? " Last successful data is still shown." : ""}` : `${healthBadge(data.project.health)} ${data.needsAttention.length} item${data.needsAttention.length === 1 ? "" : "s"} need attention.`}
      </div>
      <div class="hub-grid">
        <section class="pane" aria-label="Work Items">
          <div class="pane-title"><h2>Work Items <span class="muted">${filtered.length}</span></h2></div>
          <div class="list">${filtered.length ? filtered.map(renderWorkItem).join("") : `<div class="empty">No Work Items match the current filter.</div>`}</div>
        </section>
        <section class="pane" aria-label="Codex Tasks">
          <div class="pane-title"><h2>Codex Tasks <span class="muted">${workItem?.codexTasks.length ?? 0}</span></h2></div>
          <div class="list">${workItem?.codexTasks.length ? workItem.codexTasks.map(renderCodexTask).join("") : `<div class="empty">This Work Item has no registered Codex Tasks.</div>`}</div>
        </section>
        <aside class="pane details-pane" aria-label="Project Hub details">
          <div class="pane-title"><h2>Details</h2></div>
          ${renderDetails(workItem, codexTask)}
        </aside>
      </div>
    </section>`;
}

function bindEvents(): void {
  document.querySelector("#open-fullscreen")?.addEventListener("click", async () => {
    try {
      await bridge.requestFullscreen();
      fullscreenRequested = true;
      error = "";
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    }
    render();
  });
  for (const id of ["refresh-inline", "refresh-full"]) {
    document.querySelector(`#${id}`)?.addEventListener("click", () => void refresh());
  }
  document.querySelector<HTMLInputElement>("#hub-search")?.addEventListener("input", (event) => {
    ui.query = (event.target as HTMLInputElement).value;
    bridge.saveLocalState(ui);
    render();
    document.querySelector<HTMLInputElement>("#hub-search")?.focus();
  });
  document.querySelector<HTMLSelectElement>("#health-filter")?.addEventListener("change", (event) => {
    ui.health = (event.target as HTMLSelectElement).value as LocalUiState["health"];
    bridge.saveLocalState(ui);
    render();
  });
  for (const element of document.querySelectorAll<HTMLElement>("[data-work-item]")) {
    element.addEventListener("click", () => {
      if (!payload) return;
      ui.workItemId = element.dataset.workItem ?? "";
      ui.taskKey = payload.workItems.find((item) => item.workItemId === ui.workItemId)?.codexTasks[0]?.taskKey ?? "";
      bridge.saveLocalState(ui);
      render();
    });
  }
  for (const element of document.querySelectorAll<HTMLElement>("[data-codex-task]")) {
    element.addEventListener("click", () => {
      ui.taskKey = element.dataset.codexTask ?? "";
      bridge.saveLocalState(ui);
      render();
    });
  }
}

async function refresh(): Promise<void> {
  if (!payload || refreshing) return;
  refreshing = true;
  error = "";
  render();
  try {
    const result = await bridge.callTool("get_awh_project_hub", {
      worktreePath: payload.canonicalRepoRoot,
      projectId: payload.project.projectId,
    });
    const next = parseProjectHubPayload(payloadFromToolResult(result));
    payload = next;
    const selection = reconcileSelection(next, ui);
    ui = { ...ui, ...selection };
    bridge.saveLocalState(ui);
    stale = false;
  } catch (cause) {
    error = cause instanceof Error ? cause.message : String(cause);
    stale = true;
  } finally {
    refreshing = false;
    render();
  }
}

function render(): void {
  if (!payload) {
    app.innerHTML = `<section class="fatal"><h1>AWH Project Hub could not load</h1><p>${escapeHtml(error || "Waiting for the opening tool result.")}</p><p class="small">Static fallback: run <span class="machine">visualize-project</span> with $agent-workflow-hub.</p></section>`;
    return;
  }
  const fullscreen = fullscreenRequested || bridge.displayMode() === "fullscreen";
  app.innerHTML = fullscreen ? renderFullscreen(payload) : renderInline(payload);
  createIcons({ icons: { AlertTriangle, FolderGit2, GitBranch, Maximize2, RefreshCw, Search } });
  bindEvents();
}

bridge.onToolResult((result) => {
  const value = payloadFromToolResult(result);
  if (value) hydrate(value);
});

const initial = bridge.initialPayload();
if (initial) {
  hydrate(initial);
} else {
  render();
}
void bridge.initialize().catch((cause) => {
  error = cause instanceof Error ? cause.message : String(cause);
  render();
});
