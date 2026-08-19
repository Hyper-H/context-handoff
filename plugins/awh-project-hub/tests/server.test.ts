import assert from "node:assert/strict";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { once } from "node:events";
import path from "node:path";
import readline from "node:readline";
import test from "node:test";
import { fileURLToPath } from "node:url";


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

class StdioMcpClient {
  private readonly process: ChildProcessWithoutNullStreams;
  private readonly pending = new Map<number, {
    resolve: (value: Record<string, unknown>) => void;
    reject: (reason: unknown) => void;
  }>();
  private id = 0;

  constructor() {
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      AWH_SIDECAR_SCRIPT: path.join(root, "tests", "fixture-sidecar.py"),
    };
    delete env.AWH_PYTHON;
    if (process.env.AWH_TEST_PYTHON) env.AWH_PYTHON = process.env.AWH_TEST_PYTHON;
    this.process = spawn(process.execPath, [path.join(root, "dist", "server.mjs")], {
      cwd: root,
      env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const lines = readline.createInterface({ input: this.process.stdout, crlfDelay: Infinity });
    lines.on("line", (line) => {
      const message = JSON.parse(line) as {
        id?: number;
        result?: Record<string, unknown>;
        error?: { message?: string };
      };
      if (typeof message.id !== "number") return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message ?? "MCP error"));
      else pending.resolve(message.result ?? {});
    });
  }

  request(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return new Promise((resolve, reject) => {
      const id = ++this.id;
      this.pending.set(id, { resolve, reject });
      this.process.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
    });
  }

  notify(method: string, params: Record<string, unknown> = {}): void {
    this.process.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method, params })}\n`);
  }

  async close(): Promise<void> {
    this.process.stdin.end();
    if (this.process.exitCode === null) await once(this.process, "exit");
    assert.equal(this.process.exitCode, 0);
  }
}

test("stdio server exposes read-only tools and MCP App resource", async () => {
  const client = new StdioMcpClient();
  const initialized = await client.request("initialize", {
    protocolVersion: "2025-11-25",
    capabilities: {},
    clientInfo: { name: "awh-test", version: "1.0.0" },
  });
  assert.equal((initialized.serverInfo as { name: string }).name, "awh-project-hub");
  client.notify("notifications/initialized");

  const toolsResult = await client.request("tools/list");
  const tools = toolsResult.tools as Array<{
    name: string;
    annotations: Record<string, boolean>;
    _meta?: Record<string, unknown>;
  }>;
  assert.deepEqual(tools.map((tool) => tool.name).sort(), ["get_awh_project_hub", "open_awh_project_hub"]);
  for (const tool of tools) {
    assert.equal(tool.annotations.readOnlyHint, true);
    assert.equal(tool.annotations.destructiveHint, false);
    assert.equal(tool.annotations.openWorldHint, false);
    assert.equal(tool.annotations.idempotentHint, true);
  }
  const openTool = tools.find((tool) => tool.name === "open_awh_project_hub")!;
  assert.equal((openTool._meta?.ui as { resourceUri: string }).resourceUri, "ui://awh-project-hub/main-v1.html");

  const resourcesResult = await client.request("resources/list");
  const resources = resourcesResult.resources as Array<{ uri: string; mimeType?: string }>;
  assert.equal(resources[0]?.uri, "ui://awh-project-hub/main-v1.html");
  const resourceResult = await client.request("resources/read", { uri: resources[0]!.uri });
  const contents = resourceResult.contents as Array<{ mimeType: string; text: string }>;
  assert.equal(contents[0]?.mimeType, "text/html;profile=mcp-app");
  assert.match(contents[0]!.text, /Open fullscreen/);

  const openResult = await client.request("tools/call", {
    name: "open_awh_project_hub",
    arguments: { worktreePath: "C:/fixture", projectId: "stdio-fixture" },
  });
  const openMeta = openResult._meta as Record<string, unknown>;
  assert.equal(openMeta["openai/outputTemplate"], "ui://awh-project-hub/main-v1.html");
  assert.equal((openMeta.awhProjectHub as { workItems: unknown[] }).workItems.length, 1);

  const refreshResult = await client.request("tools/call", {
    name: "get_awh_project_hub",
    arguments: { worktreePath: "C:/fixture", projectId: "stdio-fixture" },
  });
  assert.equal((refreshResult._meta as Record<string, unknown>)["openai/outputTemplate"], undefined);
  assert.equal(((refreshResult._meta as Record<string, unknown>).awhProjectHub as { project: { projectId: string } }).project.projectId, "stdio-fixture");
  await client.close();
});
