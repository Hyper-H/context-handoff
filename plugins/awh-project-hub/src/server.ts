import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  registerAppResource,
  registerAppTool,
  RESOURCE_MIME_TYPE,
} from "@modelcontextprotocol/ext-apps/server";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { SidecarClient } from "./sidecar-client.js";
import type { ProjectHubPayload, ProjectLocator } from "./types.js";


export const WIDGET_URI = "ui://awh-project-hub/main-v1.html";
const SERVER_VERSION = "0.1.0";

export interface HubDataSource {
  getProjectHub(locator: ProjectLocator): Promise<ProjectHubPayload>;
}

export interface ServerOptions {
  dataSource?: HubDataSource;
  widgetHtml?: string;
}

function widgetPath(): string {
  return path.join(path.dirname(fileURLToPath(import.meta.url)), "widget.html");
}

function toolResult(payload: ProjectHubPayload, render: boolean) {
  const result = {
    content: [{ type: "text" as const, text: `Loaded ${payload.workItems.length} AWH work items.` }],
    structuredContent: {
      schemaVersion: payload.schemaVersion,
      project: payload.project,
      summary: payload.summary,
    },
    _meta: {
      awhProjectHub: payload,
      ...(render ? { "openai/outputTemplate": WIDGET_URI } : {}),
    },
  };
  return result;
}

export function createAwhServer(options: ServerOptions = {}): McpServer {
  const dataSource = options.dataSource ?? new SidecarClient();
  const widgetHtml = options.widgetHtml ?? readFileSync(widgetPath(), "utf8");
  const server = new McpServer({ name: "awh-project-hub", version: SERVER_VERSION });

  registerAppResource(server, "AWH Project Hub", WIDGET_URI, {}, async () => ({
    contents: [{
      uri: WIDGET_URI,
      mimeType: RESOURCE_MIME_TYPE,
      text: widgetHtml,
      _meta: {
        ui: {
          prefersBorder: false,
          csp: { connectDomains: [], resourceDomains: [] },
        },
        "openai/widgetDescription": "Read-only AWH Project Hub with Work Items, Codex Tasks, Roles, Environments, health, blockers, and details.",
      },
    }],
  }));

  const inputSchema = {
    worktreePath: z.string().min(1).describe("Absolute AWH Git worktree path."),
    projectId: z.string().min(1).optional().describe("Optional stable AWH sidecar project id."),
  };
  const annotations = {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  };

  registerAppTool(server, "get_awh_project_hub", {
    title: "Refresh AWH Project Hub",
    description: "Use this when the AWH Project Hub widget needs fresh read-only sidecar and Git worktree data.",
    inputSchema,
    annotations,
    _meta: {},
  }, async (locator) => toolResult(await dataSource.getProjectHub(locator), false));

  registerAppTool(server, "open_awh_project_hub", {
    title: "Open AWH Project Hub",
    description: "Use this when the user wants to inspect the current AWH project in an inline launcher or fullscreen read-only Hub.",
    inputSchema,
    annotations,
    _meta: {
      ui: { resourceUri: WIDGET_URI },
      "openai/outputTemplate": WIDGET_URI,
      "openai/toolInvocation/invoking": "Loading AWH Project Hub",
      "openai/toolInvocation/invoked": "AWH Project Hub ready",
    },
  }, async (locator) => toolResult(await dataSource.getProjectHub(locator), true));

  return server;
}

export async function main(): Promise<void> {
  const server = createAwhServer();
  await server.connect(new StdioServerTransport());
}

const entry = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (entry === import.meta.url) {
  main().catch((error: unknown) => {
    process.stderr.write(`AWH Project Hub MCP failed: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
