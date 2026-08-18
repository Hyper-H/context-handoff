import { execFile } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ProjectHubPayloadSchema, type ProjectHubPayload, type ProjectLocator } from "./types.js";


export interface ProcessResult {
  code: number;
  stdout: string;
  stderr: string;
}

export interface SpawnRequest {
  command: string;
  args: string[];
  timeoutMs: number;
  maxBuffer: number;
}

export type ProcessRunner = (request: SpawnRequest) => Promise<ProcessResult>;

export class SidecarError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SidecarError";
  }
}

function bounded(value: string, limit = 1024): string {
  return value.replace(/[\r\n\t]+/g, " ").trim().slice(0, limit);
}

export const defaultRunner: ProcessRunner = (request) => new Promise((resolve, reject) => {
  execFile(
    request.command,
    request.args,
    { timeout: request.timeoutMs, maxBuffer: request.maxBuffer, windowsHide: true },
    (error, stdout, stderr) => {
      if (error && "killed" in error && error.killed) {
        reject(new SidecarError("AWH sidecar request timed out."));
        return;
      }
      const code = error && "code" in error && typeof error.code === "number" ? error.code : 0;
      resolve({ code, stdout: String(stdout), stderr: String(stderr) });
    },
  );
});

export interface SidecarClientOptions {
  run?: ProcessRunner;
  python?: string;
  script?: string;
}

export class SidecarClient {
  private readonly run: ProcessRunner;
  private readonly python: string;
  private readonly script: string;

  constructor(options: SidecarClientOptions = {}) {
    this.run = options.run ?? defaultRunner;
    this.python = options.python ?? process.env.AWH_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
    this.script = options.script ?? process.env.AWH_SIDECAR_SCRIPT ?? path.join(
      path.dirname(fileURLToPath(import.meta.url)), "sidecar", "context_sidecar.py",
    );
  }

  async getProjectHub(locator: ProjectLocator): Promise<ProjectHubPayload> {
    const worktreePath = locator.worktreePath?.trim();
    if (!worktreePath) {
      throw new SidecarError("worktreePath is required to resolve an AWH project.");
    }
    const args = [this.script, "project-hub-payload", "--worktree", worktreePath];
    if (locator.projectId?.trim()) {
      args.push("--project-id", locator.projectId.trim());
    }
    let result: ProcessResult;
    try {
      result = await this.run({ command: this.python, args, timeoutMs: 30_000, maxBuffer: 1024 * 1024 });
    } catch (error) {
      if (error instanceof SidecarError) {
        throw error;
      }
      throw new SidecarError("AWH sidecar request failed to start.");
    }
    if (result.code !== 0) {
      const detail = bounded(result.stderr);
      throw new SidecarError(`AWH sidecar exited with code ${result.code}${detail ? `: ${detail}` : "."}`);
    }
    let raw: unknown;
    try {
      raw = JSON.parse(result.stdout);
    } catch {
      throw new SidecarError("AWH sidecar returned invalid JSON.");
    }
    const parsed = ProjectHubPayloadSchema.safeParse(raw);
    if (!parsed.success) {
      throw new SidecarError(`AWH sidecar returned an unsupported payload: ${bounded(parsed.error.message, 700)}`);
    }
    return parsed.data;
  }
}
