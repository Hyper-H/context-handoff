import type { ProjectHubPayload } from "../src/types.js";


export interface ToolResult {
  structuredContent?: Record<string, unknown>;
  _meta?: Record<string, unknown>;
}

export interface LocalUiState {
  query: string;
  health: "all" | "healthy" | "attention" | "blocked" | "archived";
  workItemId: string;
  taskKey: string;
}

interface OpenAIHost {
  displayMode?: "inline" | "pip" | "fullscreen";
  toolResponseMetadata?: Record<string, unknown>;
  widgetState?: unknown;
  callTool?: (name: string, args: Record<string, unknown>) => Promise<ToolResult>;
  requestDisplayMode?: (input: { mode: "inline" | "pip" | "fullscreen" }) => Promise<unknown>;
  setWidgetState?: (state: LocalUiState) => void;
}

declare global {
  interface Window {
    openai?: OpenAIHost;
  }
}

const DEFAULT_STATE: LocalUiState = {
  query: "",
  health: "all",
  workItemId: "",
  taskKey: "",
};

const RPC_TIMEOUT_MS = 45_000;

export class HubBridge {
  private nextId = 0;
  private initialized?: Promise<void>;
  private readonly pending = new Map<number, {
    resolve: (value: ToolResult) => void;
    reject: (reason: unknown) => void;
    timer: number;
  }>();
  private readonly listeners = new Set<(result: ToolResult) => void>();

  constructor() {
    window.addEventListener("message", (event) => this.receive(event), { passive: true });
  }

  initialize(): Promise<void> {
    this.initialized ??= this.rpcRequest("ui/initialize", {
      appInfo: { name: "awh-project-hub-widget", version: "0.1.0" },
      appCapabilities: {},
      protocolVersion: "2026-01-26",
    }).then(() => {
      this.notify("ui/notifications/initialized", {});
    });
    return this.initialized;
  }

  onToolResult(listener: (result: ToolResult) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<ToolResult> {
    try {
      await this.initialize();
      return await this.rpcRequest("tools/call", { name, arguments: args });
    } catch (bridgeError) {
      if (window.openai?.callTool) {
        return window.openai.callTool(name, args);
      }
      throw bridgeError;
    }
  }

  async requestFullscreen(): Promise<void> {
    if (!window.openai?.requestDisplayMode) {
      throw new Error("This host does not expose fullscreen display mode.");
    }
    await window.openai.requestDisplayMode({ mode: "fullscreen" });
  }

  displayMode(): "inline" | "pip" | "fullscreen" {
    return window.openai?.displayMode ?? "inline";
  }

  initialPayload(): ProjectHubPayload | undefined {
    return window.openai?.toolResponseMetadata?.awhProjectHub as ProjectHubPayload | undefined;
  }

  loadLocalState(): LocalUiState {
    const state = window.openai?.widgetState;
    if (!state || typeof state !== "object") {
      return { ...DEFAULT_STATE };
    }
    const candidate = state as Partial<LocalUiState>;
    const allowedHealth = ["all", "healthy", "attention", "blocked", "archived"];
    return {
      query: typeof candidate.query === "string" ? candidate.query : "",
      health: allowedHealth.includes(candidate.health ?? "")
        ? candidate.health as LocalUiState["health"]
        : "all",
      workItemId: typeof candidate.workItemId === "string" ? candidate.workItemId : "",
      taskKey: typeof candidate.taskKey === "string" ? candidate.taskKey : "",
    };
  }

  saveLocalState(state: LocalUiState): void {
    window.openai?.setWidgetState?.({ ...state });
  }

  private receive(event: MessageEvent): void {
    if (event.source !== window.parent) {
      return;
    }
    const message = event.data as {
      jsonrpc?: string;
      id?: number;
      method?: string;
      params?: ToolResult;
      result?: ToolResult;
      error?: unknown;
    };
    if (!message || message.jsonrpc !== "2.0") {
      return;
    }
    if (typeof message.id === "number") {
      const pending = this.pending.get(message.id);
      if (!pending) {
        return;
      }
      window.clearTimeout(pending.timer);
      this.pending.delete(message.id);
      if (message.error) {
        pending.reject(message.error);
      } else {
        pending.resolve(message.result ?? {});
      }
      return;
    }
    if (message.method === "ui/notifications/tool-result") {
      for (const listener of this.listeners) {
        listener(message.params ?? {});
      }
    }
  }

  private notify(method: string, params: Record<string, unknown>): void {
    window.parent.postMessage({ jsonrpc: "2.0", method, params }, "*");
  }

  private rpcRequest(method: string, params: Record<string, unknown>): Promise<ToolResult> {
    return new Promise((resolve, reject) => {
      const id = ++this.nextId;
      const timer = window.setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out.`));
      }, RPC_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
    });
  }
}

export function payloadFromToolResult(result: ToolResult): unknown {
  return result._meta?.awhProjectHub;
}
