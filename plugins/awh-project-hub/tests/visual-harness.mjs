import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";


const execFileAsync = promisify(execFile);
const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const widgetPath = path.join(pluginRoot, "dist", "widget.html");
const worktreePath = path.resolve(process.argv[2] ?? path.resolve(pluginRoot, "..", ".."));
const projectId = process.argv[3] ?? "";
const python = process.env.AWH_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
const sidecarScript = process.env.AWH_SIDECAR_SCRIPT
  ?? path.join(pluginRoot, "dist", "sidecar", "context_sidecar.py");

async function payload() {
  const args = [sidecarScript, "project-hub-payload", "--worktree", worktreePath];
  if (projectId) args.push("--project-id", projectId);
  const { stdout } = await execFileAsync(python, args, {
    timeout: 30_000,
    windowsHide: true,
    maxBuffer: 1024 * 1024,
  });
  return JSON.parse(stdout);
}

function hostScript(initialPayload) {
  const serialized = JSON.stringify(initialPayload).replaceAll("<", "\\u003c");
  return `<script>
    window.openai = {
      displayMode: "inline",
      toolResponseMetadata: { awhProjectHub: ${serialized} },
      widgetState: {},
      requestDisplayMode: async ({ mode }) => { window.openai.displayMode = mode; },
      setWidgetState: (state) => { window.openai.widgetState = state; },
      callTool: async () => {
        const response = await fetch("/payload", { cache: "no-store" });
        return { _meta: { awhProjectHub: await response.json() } };
      }
    };
  </script>`;
}

function wrapperHtml() {
  return `<!doctype html>
  <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>AWH Project Hub Harness</title>
      <style>html,body,iframe{border:0;height:100%;margin:0;padding:0;width:100%;}iframe{display:block;}</style>
    </head>
    <body>
      <iframe id="widget" src="/widget" title="AWH Project Hub"></iframe>
      <script>
        const frame = document.querySelector("#widget");
        window.addEventListener("message", async (event) => {
          if (event.source !== frame.contentWindow) return;
          const message = event.data;
          if (!message || message.jsonrpc !== "2.0" || message.id === undefined) return;
          let result = {};
          if (message.method === "tools/call") {
            const response = await fetch("/payload", { cache: "no-store" });
            result = { _meta: { awhProjectHub: await response.json() } };
          }
          event.source.postMessage({ jsonrpc: "2.0", id: message.id, result }, "*");
        }, { passive: true });
      </script>
    </body>
  </html>`;
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.url === "/payload") {
      response.writeHead(200, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
      response.end(JSON.stringify(await payload()));
      return;
    }
    if (request.url === "/widget") {
      const widget = await readFile(widgetPath, "utf8");
      const html = widget.replace("<head>", `<head>${hostScript(await payload())}`);
      response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
      response.end(html);
      return;
    }
    response.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" });
    response.end(wrapperHtml());
  } catch (error) {
    response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    response.end(error instanceof Error ? error.stack : String(error));
  }
});

server.listen(0, "0.0.0.0", () => {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not resolve harness address.");
  process.stdout.write(`http://127.0.0.1:${address.port}/\n`);
});
