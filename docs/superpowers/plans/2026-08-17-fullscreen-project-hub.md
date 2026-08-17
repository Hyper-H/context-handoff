# Fullscreen Project Hub MCP App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and install a read-only local AWH Project Hub MCP App with a compact inline launcher, a fullscreen operational view backed by live sidecar data, and the existing static dashboard as fallback.

**Architecture:** Extend the existing Python visualization payload with a versioned `Project -> Work Item -> Codex Task -> Environment` contract while preserving legacy fields. A repository-owned Codex plugin runs a bundled Node stdio MCP server, invokes the Python sidecar CLI for every data request, and serves a vanilla MCP Apps widget. The widget keeps only presentation state; `install.py` copies the built plugin into the personal plugin source and safely updates the personal marketplace.

**Tech Stack:** Python 3.11+ standard library, Node.js/TypeScript, `@modelcontextprotocol/sdk` 1.30.x, `@modelcontextprotocol/ext-apps` 1.7.x, Zod 4.x, esbuild 0.28.x, Lucide 1.31.x, Node test runner, Python `unittest`, Codex desktop MCP Apps runtime.

---

## File Map

- `skills/agent-workflow-hub/scripts/context_sidecar.py`: canonical payload construction and read-only `project-hub-payload` CLI action.
- `skills/context-handoff/scripts/context_sidecar.py`: compatibility mirror of the canonical CLI.
- `skills/agent-workflow-hub/scripts/project_hub_dashboard.py`: existing static fallback shell; reads the new contract while preserving current controls.
- `skills/context-handoff/scripts/project_hub_dashboard.py`: compatibility mirror of the static fallback.
- `tests/test_project_hub_contract.py`: payload mapping and read-only behavior.
- `tests/test_project_hub_static.py`: static Markdown/JSON/HTML regression coverage.
- `plugins/awh-project-hub/.codex-plugin/plugin.json`: installable plugin metadata.
- `plugins/awh-project-hub/.mcp.json`: plugin-local stdio MCP declaration.
- `plugins/awh-project-hub/package.json`, `pnpm-lock.yaml`, `tsconfig.json`: reproducible Node workspace.
- `plugins/awh-project-hub/scripts/build.mjs`: bundles the server and produces a self-contained widget HTML resource.
- `plugins/awh-project-hub/src/sidecar-client.ts`: Python executable/script resolution and payload invocation.
- `plugins/awh-project-hub/src/server.ts`: MCP resource and two read-only tool registrations.
- `plugins/awh-project-hub/web/model.ts`: payload validation, selection reconciliation, and view filtering.
- `plugins/awh-project-hub/web/bridge.ts`: MCP Apps bridge plus `window.openai` display-mode compatibility.
- `plugins/awh-project-hub/web/app.ts`: inline/fullscreen DOM renderer and event wiring.
- `plugins/awh-project-hub/web/styles.css`: responsive operational UI.
- `plugins/awh-project-hub/web/widget.html`: widget document template.
- `plugins/awh-project-hub/tests/*.test.ts`: sidecar client, MCP contract, and UI model tests.
- `plugins/awh-project-hub/dist/server.mjs`, `dist/widget.html`: committed install artifacts.
- `install.py`: AWH skill/plugin installation and marketplace-safe update flow.
- `tests/test_install.py`: dry-run, copy, marketplace preservation, and idempotency tests.
- `README.md`, `README.zh-CN.md`: install, launch, refresh, static fallback, and review boundary.

### Task 1: Add The Canonical Project Hub Contract

**Files:**
- Create: `tests/test_project_hub_contract.py`
- Modify: `skills/agent-workflow-hub/scripts/context_sidecar.py`
- Modify: `skills/context-handoff/scripts/context_sidecar.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_project_hub_contract.py` with fixture-driven tests that import the script module and exercise a pure mapping function:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "agent-workflow-hub" / "scripts" / "context_sidecar.py"


def load_sidecar():
    spec = importlib.util.spec_from_file_location("awh_context_sidecar", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ProjectHubContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sidecar = load_sidecar()

    def test_maps_work_item_threads_and_environment_without_renaming_keys(self):
        report = {
            "projectId": "demo",
            "baseBranch": "main",
            "generatedAt": "2026-08-17T12:00:00+08:00",
            "summaryCounts": {"visibleTasks": 1, "blocked": 1},
            "taskRows": [{
                "taskId": "wi-1",
                "goal": "Ship hub",
                "taskStatus": "blocked",
                "health": "blocked",
                "threads": [{
                    "threadId": "thr-1",
                    "codexThreadId": "codex-1",
                    "threadLabel": "Execution",
                    "threadRole": "primary-execution",
                    "threadPurpose": "Build it",
                    "environmentType": "worktree",
                    "worktreePath": "C:/repo/wt",
                }],
                "branch": "codex/hub",
                "dirty": True,
                "stale": False,
                "blocker": "Needs review",
                "nextStep": "Review",
                "validationPresent": True,
                "handoffAvailable": True,
            }],
            "needsAttention": [{"taskId": "wi-1"}],
            "warnings": [],
        }

        contract = self.sidecar.build_project_hub_contract(report)
        work_item = contract["workItems"][0]
        codex_task = work_item["codexTasks"][0]

        self.assertEqual(contract["schemaVersion"], "awh.project-hub/v1")
        self.assertEqual(work_item["workItemId"], "wi-1")
        self.assertEqual(codex_task["taskKey"], "thr-1")
        self.assertEqual(codex_task["codexThreadId"], "codex-1")
        self.assertEqual(codex_task["role"], "primary-execution")
        self.assertEqual(codex_task["environment"]["worktreePath"], "C:/repo/wt")
        self.assertTrue(codex_task["environment"]["dirty"])

    def test_synthesizes_legacy_codex_task_without_mutating_source(self):
        row = {
            "taskId": "legacy",
            "taskStatus": "active",
            "health": "attention",
            "threadRole": "research",
            "threadLabel": "Research",
            "threadPurpose": "Investigate",
            "worktreePath": "",
        }
        report = {
            "projectId": "demo", "baseBranch": "main", "generatedAt": "now",
            "summaryCounts": {}, "taskRows": [row], "needsAttention": [], "warnings": [],
        }
        contract = self.sidecar.build_project_hub_contract(report)
        task = contract["workItems"][0]["codexTasks"][0]
        self.assertEqual(task["role"], "research")
        self.assertIsNone(task["environment"])
        self.assertNotIn("threads", row)

    def test_preserves_multiple_threads_for_one_work_item(self):
        report = {
            "projectId": "demo", "baseBranch": "main", "generatedAt": "now",
            "summaryCounts": {}, "needsAttention": [], "warnings": [],
            "taskRows": [{
                "taskId": "wi", "taskStatus": "active", "health": "healthy",
                "threads": [
                    {"threadId": "a", "threadRole": "discussion", "worktreePath": ""},
                    {"threadId": "b", "threadRole": "primary-execution", "worktreePath": "C:/wt"},
                ],
            }],
        }
        contract = self.sidecar.build_project_hub_contract(report)
        self.assertEqual([t["taskKey"] for t in contract["workItems"][0]["codexTasks"]], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_project_hub_contract -v
```

Expected: three failures/errors because `build_project_hub_contract` does not exist and current rows do not preserve `threads[]`.

- [ ] **Step 3: Preserve thread registry data in visual rows and implement the pure contract mapper**

In `base_visual_row_from_task`, include `goal` and a normalized copy of `threads`. In `build_visual_project_payload`, copy `threads` from the sidecar task into each audited row. Add pure helpers near the visualization functions:

```python
PROJECT_HUB_SCHEMA_VERSION = "awh.project-hub/v1"


def project_hub_environment(thread: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    worktree_path = str(thread.get("worktreePath") or row.get("worktreePath") or "")
    environment_type = str(thread.get("environmentType") or ("worktree" if worktree_path else ""))
    if not worktree_path and not environment_type:
        return None
    return {
        "type": environment_type or "worktree",
        "worktreePath": worktree_path,
        "branch": row.get("branch", ""),
        "dirty": bool(row.get("dirty")),
        "stale": bool(row.get("stale")),
        "dirtyFiles": list(row.get("dirtyFiles") or []),
    }


def project_hub_codex_tasks(row: dict[str, Any]) -> list[dict[str, Any]]:
    threads = [dict(item) for item in row.get("threads", []) if isinstance(item, dict)]
    if not threads and any(row.get(key) for key in ("threadRole", "threadLabel", "threadPurpose")):
        threads = [{
            "threadId": f"legacy:{row.get('taskId', 'unknown')}",
            "codexThreadId": "",
            "threadRole": row.get("threadRole", "primary-execution"),
            "threadLabel": row.get("threadLabel", ""),
            "threadPurpose": row.get("threadPurpose", ""),
            "environmentType": "worktree" if row.get("worktreePath") else "",
            "worktreePath": row.get("worktreePath", ""),
        }]
    return [{
        "taskKey": str(thread.get("threadId") or thread.get("codexThreadId") or f"thread:{index}"),
        "threadId": str(thread.get("threadId") or ""),
        "codexThreadId": str(thread.get("codexThreadId") or ""),
        "label": str(thread.get("threadLabel") or thread.get("threadRole") or "Codex Task"),
        "role": str(thread.get("threadRole") or "primary-execution"),
        "purpose": str(thread.get("threadPurpose") or ""),
        "status": str(thread.get("phase") or row.get("taskStatus") or ""),
        "environment": project_hub_environment(thread, row),
    } for index, thread in enumerate(threads)]


def build_project_hub_contract(report: dict[str, Any]) -> dict[str, Any]:
    work_items = []
    for source in report.get("taskRows", []):
        row = dict(source)
        work_items.append({
            "workItemId": str(row.get("taskId") or "unknown"),
            "title": str(row.get("goal") or humanize_identifier(str(row.get("taskId") or "unknown"))),
            "status": str(row.get("taskStatus") or "missing"),
            "health": str(row.get("health") or "attention"),
            "codexTasks": project_hub_codex_tasks(row),
            "blocker": str(row.get("blocker") or ""),
            "nextStep": str(row.get("nextStep") or ""),
            "validationPresent": bool(row.get("validationPresent")),
            "handoffAvailable": bool(row.get("handoffAvailable")),
            "routing": {
                "status": str(row.get("routingStatus") or ""),
                "confidence": row.get("routingConfidence"),
                "needsReview": bool(row.get("routingNeedsReview")),
                "evidence": list(row.get("routingEvidence") or []),
            },
            "machine": row,
        })
    health = "blocked" if any(item["health"] == "blocked" for item in work_items) else (
        "attention" if any(item["health"] == "attention" for item in work_items) else "healthy"
    )
    return {
        "schemaVersion": PROJECT_HUB_SCHEMA_VERSION,
        "project": {
            "projectId": report.get("projectId", ""),
            "baseBranch": report.get("baseBranch", ""),
            "generatedAt": report.get("generatedAt", ""),
            "health": health,
        },
        "summary": dict(report.get("summaryCounts") or {}),
        "workItems": work_items,
        "needsAttention": list(report.get("needsAttention") or []),
        "warnings": list(report.get("warnings") or []),
    }
```

After the existing report dictionary is assigned in `build_visual_project_payload`, merge the contract before returning so legacy keys remain available:

```python
report.update(build_project_hub_contract(report))
return report
```

Apply the same functional change to the compatibility script.

- [ ] **Step 4: Run contract tests and mirror consistency check**

Run:

```powershell
python -m unittest tests.test_project_hub_contract -v
git diff --no-index skills/agent-workflow-hub/scripts/context_sidecar.py skills/context-handoff/scripts/context_sidecar.py
```

Expected: tests pass; diff command exits `0` with no output.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_project_hub_contract.py skills/agent-workflow-hub/scripts/context_sidecar.py skills/context-handoff/scripts/context_sidecar.py
git commit -m "feat: add project hub data contract"
```

### Task 2: Add A Read-Only Payload Action And Preserve Static Reports

**Files:**
- Create: `tests/test_project_hub_static.py`
- Modify: `skills/agent-workflow-hub/scripts/context_sidecar.py`
- Modify: `skills/context-handoff/scripts/context_sidecar.py`
- Modify: `skills/agent-workflow-hub/scripts/project_hub_dashboard.py`
- Modify: `skills/context-handoff/scripts/project_hub_dashboard.py`

- [ ] **Step 1: Write failing CLI/static regression tests**

Create a temporary Git repository and isolated sidecar home in `tests/test_project_hub_static.py`. Patch `USERPROFILE`/`HOME`, invoke the CLI through `subprocess.run`, and assert:

```python
def test_project_hub_payload_is_json_and_does_not_write_reports(self):
    result = self.run_cli("project-hub-payload", "--worktree", str(self.repo))
    payload = json.loads(result.stdout)
    self.assertEqual(payload["schemaVersion"], "awh.project-hub/v1")
    self.assertEqual(payload["project"]["projectId"], payload["projectId"])
    self.assertFalse(list(self.sidecar_root.rglob("visual-*.html")))

def test_visualize_project_still_writes_markdown_json_and_html(self):
    result = self.run_cli("visualize-project", "--worktree", str(self.repo))
    output = json.loads(result.stdout)
    for key in ("markdown", "json", "html"):
        self.assertTrue(Path(output["reportPaths"][key]).is_file())
    html = Path(output["reportPaths"]["html"]).read_text(encoding="utf-8")
    self.assertIn("awh.project-hub/v1", html)
    self.assertIn("Project Hub", html)
```

- [ ] **Step 2: Run the tests and verify the new action fails**

```powershell
python -m unittest tests.test_project_hub_static -v
```

Expected: the payload action test fails with an invalid action; the existing static generation test may pass except for the new schema assertion.

- [ ] **Step 3: Make payload construction explicitly non-persisting**

Change the builder signature and its state write:

```python
def build_visual_project_payload(
    manager: SidecarManager,
    include_archive: bool,
    language: str,
    *,
    persist_project_state: bool = True,
) -> dict[str, Any]:
    payload = manager.load_active_tasks()
    tasks = payload.get("tasks", [])
    state = manager.write_project_state(tasks) if persist_project_state else {
        "activeTaskCount": len(tasks),
        "currentBranch": manager.git.branch,
    }
```

Add the read-only command:

```python
def cmd_project_hub_payload(args: argparse.Namespace) -> int:
    manager = make_manager(args)
    report = build_visual_project_payload(
        manager,
        bool(args.include_archive),
        resolve_language(args, manager),
        persist_project_state=False,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0
```

Register `project-hub-payload` with common arguments and `--include-archive`. Do not write reports or log a sidecar event from this action.

- [ ] **Step 4: Embed the contract in static HTML and update hierarchy copy without removing legacy controls**

Set `dashboardVersion` to `v4.0`, retain the embedded payload, and update visible hierarchy strings from `Task -> Worktree -> Thread` to `Work Item -> Codex Task -> Environment`. Do not remove search, health filters, details, archive behavior, route spotlight, or report paths. Copy the resulting file to the compatibility skill and run:

```powershell
python -m unittest tests.test_project_hub_contract tests.test_project_hub_static -v
git diff --check
```

Expected: all tests pass and `git diff --check` is clean.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_project_hub_static.py skills/agent-workflow-hub/scripts/context_sidecar.py skills/context-handoff/scripts/context_sidecar.py skills/agent-workflow-hub/scripts/project_hub_dashboard.py skills/context-handoff/scripts/project_hub_dashboard.py
git commit -m "feat: expose read-only project hub payload"
```

### Task 3: Scaffold And Validate The Repository-Owned Plugin

**Files:**
- Create: `plugins/awh-project-hub/.codex-plugin/plugin.json`
- Create: `plugins/awh-project-hub/.mcp.json`
- Create: `plugins/awh-project-hub/package.json`
- Create: `plugins/awh-project-hub/pnpm-lock.yaml`
- Create: `plugins/awh-project-hub/tsconfig.json`
- Create: `plugins/awh-project-hub/scripts/build.mjs`
- Create: `plugins/awh-project-hub/web/widget.html`
- Create: `plugins/awh-project-hub/web/styles.css`
- Create: `plugins/awh-project-hub/web/app.ts`
- Create: `plugins/awh-project-hub/src/server.ts`

- [ ] **Step 1: Use the plugin scaffold helper for the required manifest/MCP structure**

Run from the plugin-creator skill directory:

```powershell
python scripts/create_basic_plugin.py awh-project-hub --path C:\Users\48123\.codex\worktrees\5f2a\AWH\plugins --with-mcp
```

Do not generate a repo marketplace. The personal marketplace is owned by `install.py` in Task 6.

- [ ] **Step 2: Replace scaffold metadata and MCP placeholder with the exact local contract**

Use this `.mcp.json`:

```json
{
  "mcpServers": {
    "awh-project-hub": {
      "cwd": ".",
      "command": "node",
      "args": ["./dist/server.mjs"]
    }
  }
}
```

Use plugin name/version `awh-project-hub` / `0.1.0`, developer `Hyper-H`, repository `https://github.com/Hyper-H/Agent-Workflow-Hub`, category `Productivity`, capabilities `Interactive` and `Read`, and default prompts no longer than 128 characters. Keep `mcpServers: "./.mcp.json"`; do not add `.app.json` because this plugin provides its app through MCP resources rather than a connected app id.

- [ ] **Step 3: Add reproducible package/build configuration**

Use scripts and pinned major/minor dependencies:

```json
{
  "name": "awh-project-hub",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "node scripts/build.mjs",
    "check": "tsc --noEmit",
    "test": "tsx --test tests/*.test.ts",
    "validate": "pnpm run check && pnpm run test && pnpm run build"
  },
  "dependencies": {
    "@modelcontextprotocol/ext-apps": "^1.7.5",
    "@modelcontextprotocol/sdk": "^1.30.0",
    "lucide": "^1.31.0",
    "zod": "^4.4.3"
  },
  "devDependencies": {
    "@types/node": "^24.0.0",
    "esbuild": "^0.28.2",
    "tsx": "^4.20.0",
    "typescript": "^7.0.2"
  }
}
```

If TypeScript 7 is incompatible with the current SDK type declarations, pin the newest compatible 6.x version discovered by `pnpm view typescript versions --json`; record the chosen exact version in the lockfile rather than weakening type checks.

The build script must bundle `src/server.ts` for Node, bundle `web/app.ts` and CSS for browsers, HTML-escape closing script tags, replace explicit `<!-- AWH_STYLE -->` and `<!-- AWH_SCRIPT -->` markers, and write `dist/server.mjs` plus `dist/widget.html`.

- [ ] **Step 4: Install dependencies and verify the expected initial failure**

```powershell
cd plugins/awh-project-hub
pnpm install
pnpm run check
```

Expected: dependency installation succeeds; type check fails because server/UI modules are only minimal shells and required exports are not implemented yet.

- [ ] **Step 5: Validate the plugin structure and commit the scaffold**

```powershell
python C:\Users\48123\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py C:\Users\48123\.codex\worktrees\5f2a\AWH\plugins\awh-project-hub
git add plugins/awh-project-hub
git commit -m "build: scaffold project hub plugin"
```

Expected: plugin manifest validation passes even though application tests are not implemented.

### Task 4: Implement The Sidecar Client And MCP Contract

**Files:**
- Create: `plugins/awh-project-hub/src/types.ts`
- Create: `plugins/awh-project-hub/src/sidecar-client.ts`
- Modify: `plugins/awh-project-hub/src/server.ts`
- Create: `plugins/awh-project-hub/tests/sidecar-client.test.ts`
- Create: `plugins/awh-project-hub/tests/server.test.ts`

- [ ] **Step 1: Write failing sidecar client tests**

Test an injected process runner so failures are deterministic:

```typescript
test("passes the project route and returns a validated v1 payload", async () => {
  const calls: SpawnRequest[] = [];
  const client = new SidecarClient({
    run: async (request) => {
      calls.push(request);
      return { code: 0, stdout: JSON.stringify(fixturePayload), stderr: "" };
    },
    python: "python",
    script: "C:/skill/context_sidecar.py",
  });
  const payload = await client.getProjectHub({ worktreePath: "C:/repo", projectId: "demo" });
  assert.equal(payload.schemaVersion, "awh.project-hub/v1");
  assert.deepEqual(calls[0].args, [
    "C:/skill/context_sidecar.py", "project-hub-payload", "--worktree", "C:/repo", "--project-id", "demo",
  ]);
});

test("reports timeout without copying process output", async () => {
  const client = new SidecarClient({
    run: async () => { throw new ProcessTimeoutError("secret long stdout"); },
    python: "python",
    script: "C:/skill/context_sidecar.py",
  });
  await assert.rejects(
    () => client.getProjectHub({ worktreePath: "C:/repo" }),
    (error: unknown) => error instanceof SidecarError
      && /timed out/i.test(error.message)
      && !error.message.includes("secret long stdout"),
  );
});

test("reports invalid JSON with a bounded stderr summary", async () => {
  const client = new SidecarClient({
    run: async () => ({ code: 0, stdout: "not-json", stderr: "parse warning" }),
    python: "python",
    script: "C:/skill/context_sidecar.py",
  });
  await assert.rejects(
    () => client.getProjectHub({ worktreePath: "C:/repo" }),
    (error: unknown) => error instanceof SidecarError
      && /invalid JSON/i.test(error.message)
      && error.message.length < 1024,
  );
});
```

Also test resolution order: `AWH_PYTHON` / `AWH_SIDECAR_SCRIPT`, then the installed skill under the user's Codex home, with `python` on Windows and `python3` elsewhere.

- [ ] **Step 2: Write failing in-memory MCP tests**

Use SDK `InMemoryTransport` and `Client` to assert:

```typescript
const { server, close } = await startTestServer({ getProjectHub: async () => fixturePayload });
const tools = await client.listTools();
assert.deepEqual(tools.tools.map((tool) => tool.name).sort(), [
  "get_awh_project_hub", "open_awh_project_hub",
]);
assert.equal(tools.tools[0].annotations?.readOnlyHint, true);

const resources = await client.listResources();
assert.equal(resources.resources[0].uri, "ui://awh-project-hub/main-v1.html");
const resource = await client.readResource({ uri: resources.resources[0].uri });
assert.equal(resource.contents[0].mimeType, "text/html;profile=mcp-app");

const opened = await client.callTool({
  name: "open_awh_project_hub",
  arguments: { worktreePath: "C:/repo", projectId: "demo" },
});
assert.equal(opened.structuredContent?.schemaVersion, "awh.project-hub/v1");
assert.deepEqual(opened._meta?.awhProjectHub, fixturePayload);
```

Assert the render tool has `_meta.ui.resourceUri` and `openai/outputTemplate`; the data tool must not attach a UI resource.

- [ ] **Step 3: Run tests and verify they fail**

```powershell
cd plugins/awh-project-hub
pnpm test
```

Expected: failures for missing `SidecarClient`, server factory, tools, and resource.

- [ ] **Step 4: Implement client and server**

Implement a Zod payload schema that requires `schemaVersion`, `project`, `summary`, `workItems`, `needsAttention`, and `warnings` while passing through machine fields. Use `execFile` with a 15-second timeout, a 1 MiB stdout bound, and a 1 KiB sanitized stderr summary.

In `server.ts`, register the resource with `registerAppResource`, `RESOURCE_MIME_TYPE`, empty CSP domains, `prefersBorder: false`, and `openai/widgetDescription`. Register both tools with exact read-only annotations. Return:

```typescript
{
  content: [{ type: "text", text: `Loaded ${payload.workItems.length} AWH work items.` }],
  structuredContent: {
    schemaVersion: payload.schemaVersion,
    project: payload.project,
    summary: payload.summary,
  },
  _meta: { awhProjectHub: payload, "openai/outputTemplate": WIDGET_URI }
}
```

Only the render tool descriptor gets `ui.resourceUri`. Export a testable server factory; the production entry point connects `StdioServerTransport` and writes no non-protocol text to stdout.

- [ ] **Step 5: Run checks and commit**

```powershell
pnpm run check
pnpm test
pnpm run build
git add plugins/awh-project-hub
git commit -m "feat: add project hub MCP server"
```

Expected: type check, MCP tests, and build pass; `dist/server.mjs` and `dist/widget.html` exist.

### Task 5: Build The Inline Launcher And Fullscreen Read-Only UI

**Files:**
- Create: `plugins/awh-project-hub/web/model.ts`
- Create: `plugins/awh-project-hub/web/bridge.ts`
- Modify: `plugins/awh-project-hub/web/app.ts`
- Modify: `plugins/awh-project-hub/web/styles.css`
- Modify: `plugins/awh-project-hub/web/widget.html`
- Create: `plugins/awh-project-hub/tests/model.test.ts`
- Create: `plugins/awh-project-hub/tests/bridge.test.ts`

- [ ] **Step 1: Write failing pure UI model tests**

Cover filtering and selection without a browser DOM:

```typescript
test("filters work items by text and health", () => {
  const result = visibleWorkItems(fixturePayload.workItems, { query: "execution", health: "blocked" });
  assert.deepEqual(result.map((item) => item.workItemId), ["blocked-item"]);
});

test("reconciles selection after refresh", () => {
  assert.deepEqual(reconcileSelection(fixturePayload, { workItemId: "gone", taskKey: "gone" }), {
    workItemId: fixturePayload.workItems[0].workItemId,
    taskKey: fixturePayload.workItems[0].codexTasks[0].taskKey,
  });
});

test("keeps no-environment codex tasks visible", () => {
  assert.equal(taskEnvironmentLabel(noEnvironmentTask), "No environment");
});
```

- [ ] **Step 2: Write failing bridge tests**

Inject a fake parent window and `window.openai` compatibility object. Assert `ui/initialize`, `ui/notifications/initialized`, `tools/call`, `ui/notifications/tool-result`, fullscreen requests, and local widget-state persistence. Assert tool payload authority never comes from saved widget state.

- [ ] **Step 3: Implement model and bridge, then run unit tests**

The bridge API must expose:

```typescript
export interface HubBridge {
  initialize(): Promise<void>;
  onToolResult(listener: (result: ToolResult) => void): () => void;
  callTool(name: string, args: Record<string, unknown>): Promise<ToolResult>;
  requestFullscreen(): Promise<void>;
  displayMode(): "inline" | "pip" | "fullscreen";
  loadLocalState(): LocalUiState;
  saveLocalState(state: LocalUiState): void;
}
```

Use bridge `tools/call` first and `window.openai.callTool` only as a compatibility fallback. Use `window.openai.requestDisplayMode({ mode: "fullscreen" })` for the launcher command.

Run:

```powershell
pnpm test
```

Expected: model and bridge tests pass.

- [ ] **Step 4: Implement the operational UI**

Render two stable modes from the same app:

- Inline: project, health badge, visible Work Item count, attention count, generated time, icon refresh, and `Open fullscreen`.
- Fullscreen: top toolbar, Work Item pane, Codex Task pane with Role on every row, and detail pane with environment/worktree, health, blocker, validation, handoff, routing, and machine keys.

Use Lucide icons for refresh, search, fullscreen, alert, branch, folder/worktree, and close/return controls. Give unfamiliar icons tooltips and accessible labels. Keep cards at 8px radius or less, avoid nested cards, use fixed responsive panel tracks, and collapse details below content under 800px. No font size may scale with viewport width; letter spacing stays zero.

Refresh must keep the last successful payload visible, set `aria-busy`, call `get_awh_project_hub` with the current locator, validate the returned `_meta.awhProjectHub`, atomically replace the payload, reconcile selection, and display a stale warning on failure.

- [ ] **Step 5: Build, inspect artifact content, and commit**

```powershell
pnpm run validate
rg -n "Open fullscreen|Work Items|Codex Tasks|Role|Environment|requestDisplayMode|get_awh_project_hub" dist/widget.html
git add plugins/awh-project-hub
git commit -m "feat: add fullscreen project hub UI"
```

Expected: all checks pass and the bundled HTML contains the required UI and bridge behavior.

### Task 6: Extend The Installer Without Damaging Personal Marketplace State

**Files:**
- Modify: `install.py`
- Create: `tests/test_install.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing installer tests**

Use temporary source, Codex home, personal plugin home, and marketplace paths. Cover:

```python
def test_installs_plugin_and_preserves_unrelated_marketplace_entries(self):
    self.write_marketplace({
        "name": "personal",
        "interface": {"displayName": "My Plugins"},
        "plugins": [{"name": "keep-me", "source": {"source": "local", "path": "./plugins/keep-me"},
                     "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                     "category": "Other"}],
    })
    run_install(self.args())
    installed = json.loads(self.marketplace.read_text(encoding="utf-8"))
    self.assertEqual(installed["interface"]["displayName"], "My Plugins")
    self.assertEqual([item["name"] for item in installed["plugins"]], ["keep-me", "awh-project-hub"])
    self.assertTrue((self.plugin_home / "awh-project-hub" / "dist" / "server.mjs").is_file())

def test_reinstall_replaces_only_awh_entry_and_files(self):
    run_install(self.args())
    marker = self.plugin_home / "awh-project-hub" / "obsolete.txt"
    marker.write_text("remove", encoding="utf-8")
    run_install(self.args())
    installed = json.loads(self.marketplace.read_text(encoding="utf-8"))
    self.assertFalse(marker.exists())
    self.assertEqual(
        [item["name"] for item in installed["plugins"]].count("awh-project-hub"),
        1,
    )

def test_dry_run_changes_nothing(self):
    before = self.marketplace.read_bytes() if self.marketplace.exists() else None
    run_install(self.args(dry_run=True))
    after = self.marketplace.read_bytes() if self.marketplace.exists() else None
    self.assertEqual(after, before)
    self.assertFalse((self.plugin_home / "awh-project-hub").exists())

def test_rejects_missing_built_artifacts(self):
    (self.source_plugin / "dist" / "server.mjs").unlink()
    with self.assertRaisesRegex(SystemExit, "dist/server.mjs"):
        run_install(self.args())
```

- [ ] **Step 2: Run tests and verify they fail**

```powershell
python -m unittest tests.test_install -v
```

Expected: failures because the installer has no plugin or marketplace support.

- [ ] **Step 3: Implement explicit installer paths and safe JSON update**

Add arguments:

```text
--plugin-home      default: ~/plugins
--marketplace-path default: ~/.agents/plugins/marketplace.json
--skip-plugin      install skills only
```

Add pure helpers `load_marketplace`, `awh_marketplace_entry`, and `upsert_plugin_entry`. Seed a missing marketplace as:

```python
{"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
```

The AWH entry must be:

```python
{
    "name": "awh-project-hub",
    "source": {"source": "local", "path": "./plugins/awh-project-hub"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}
```

Preserve every unrelated key and entry. Write JSON through a temporary file followed by `replace`. Validate that source has `.codex-plugin/plugin.json`, `.mcp.json`, `dist/server.mjs`, and `dist/widget.html` before copying. Repeated runs replace only the AWH destination tree and AWH entry.

- [ ] **Step 4: Run installer tests and plugin validation**

```powershell
python -m unittest tests.test_install -v
python install.py --dry-run
python C:\Users\48123\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins/awh-project-hub
```

Expected: tests and validation pass; dry run lists skill, plugin, and marketplace targets without writing.

- [ ] **Step 5: Commit**

```powershell
git add install.py tests/test_install.py .gitignore
git commit -m "feat: install AWH project hub plugin"
```

### Task 7: Add End-To-End Automated Validation And User Documentation

**Files:**
- Create: `tests/test_project_hub_e2e.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `skills/agent-workflow-hub/SKILL.md`
- Modify: `skills/context-handoff/SKILL.md`

- [ ] **Step 1: Write the failing end-to-end test**

The test must create a temporary Git repo and isolated sidecar, start a feature with two registered threads, call `project-hub-payload`, call `visualize-project`, then start the bundled MCP server over stdio and issue `initialize`, `tools/list`, `resources/list`, and `tools/call` JSON-RPC requests. Assert real returned data contains Work Item, both Codex Tasks, both Roles, environment/worktree, blocker, health, and details. Modify sidecar through the existing CLI, call the data tool again, and assert the new value appears without restarting the MCP process.

- [ ] **Step 2: Run the test and fix integration-only failures**

```powershell
python -m unittest tests.test_project_hub_e2e -v
```

Expected after fixes: pass with no network and no writes outside temporary sidecar/plugin fixtures.

- [ ] **Step 3: Document exact install and inspection workflow**

Add concise English and Chinese sections with these commands:

```powershell
python install.py
codex plugin add awh-project-hub@personal
```

Explain that plugin metadata changes require reinstall and a new Codex task, recommend pinning one AWH Hub Task, give the prompt `Open the AWH Project Hub for this worktree`, explain inline/fullscreen/refresh behavior, confirm the native composer remains the Q&A surface, link the static `visualize-project` fallback, and state that all state-changing UI actions are deferred.

Update both skill packages so `visualize-project` remains documented as the static fallback and the MCP App is optional rather than required for workflow state.

- [ ] **Step 4: Run the full focused suite**

```powershell
python -m unittest discover -s tests -v
pnpm --dir plugins/awh-project-hub run validate
python C:\Users\48123\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py plugins/awh-project-hub
git diff --no-index skills/agent-workflow-hub/scripts/context_sidecar.py skills/context-handoff/scripts/context_sidecar.py
git diff --no-index skills/agent-workflow-hub/scripts/project_hub_dashboard.py skills/context-handoff/scripts/project_hub_dashboard.py
git diff --check
```

Expected: every command passes; compatibility mirrors are identical.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_project_hub_e2e.py README.md README.zh-CN.md skills/agent-workflow-hub/SKILL.md skills/context-handoff/SKILL.md plugins/awh-project-hub/dist
git commit -m "test: validate project hub app end to end"
```

### Task 8: Install And Validate In Codex Desktop

**Files:**
- Modify only if validation reveals a defect in files owned by Tasks 1-7.
- Side effects: personal plugin directory, personal marketplace entry, installed plugin registration, local sidecar reports, screenshots under a temporary or Codex artifact directory.

- [ ] **Step 1: Install source and register the plugin**

```powershell
python install.py
codex plugin add awh-project-hub@personal
codex plugin list
```

Expected: `awh-project-hub` is installed from the local personal marketplace. The installed manifest and `.mcp.json` point to the copied built artifacts.

- [ ] **Step 2: Open a new Codex task and verify MCP startup**

Start a new task in this worktree, invoke `open_awh_project_hub` with the absolute worktree path, and confirm there is no MCP startup error. Verify the inline launcher is nonblank and reports the real project summary.

- [ ] **Step 3: Verify fullscreen interaction and live refresh**

Use the in-app browser/Codex component surface to click `Open fullscreen`. Verify visible Work Items, Codex Tasks, Role on every Codex Task, Environment/worktree, health, blockers, and details. Make one safe sidecar-only change through an existing CLI fixture/task command, click refresh, and verify the changed value appears while search/filter/selection remain UI-local.

- [ ] **Step 4: Verify responsive rendering, runtime health, composer, and fallback**

Capture desktop and narrow viewport screenshots. Inspect DOM, console errors, and text overflow/overlap. Exit fullscreen and ask a project question in the native composer. Run `visualize-project`, open the generated HTML, and verify the static dashboard still renders.

- [ ] **Step 5: Fix defects, rerun focused tests, and stop at the review boundary**

For any defect, add or strengthen the smallest automated regression test before the fix. Rebuild, reinstall with the plugin cachebuster helper when metadata or bundled assets changed, and repeat the affected desktop check. Do not add task creation, status changes, blocker edits, routing edits, or any other state-changing UI controls.

Run final checks:

```powershell
python -m unittest discover -s tests -v
pnpm --dir plugins/awh-project-hub run validate
git status --short
```

Expected: tests pass; only intentional implementation changes remain; desktop evidence proves all eight definition-of-done items.

### Task 9: Save The Compact AWH Handoff

**Files:**
- Sidecar handoff only under `%USERPROFILE%/.codex/projects/hyper-h-agent-workflow-hub/`; no tracked dynamic state.

- [ ] **Step 1: Audit current context**

```powershell
python C:\Users\48123\.codex\skills\agent-workflow-hub\scripts\context_sidecar.py audit-context --worktree C:\Users\48123\.codex\worktrees\5f2a\AWH --language zh-CN
```

- [ ] **Step 2: Save a compact handoff with exact validation evidence**

Run `handoff` with:

- result: plugin installed; inline/fullscreen/static paths verified;
- validation commands and exact pass results;
- blocker/risk: state-changing UI intentionally deferred;
- safety rules: preserve sidecar authority, static fallback, machine keys, and `docs/paper` / `docs/research`;
- next step: user reviews read-only UI before authorizing mutation tools;
- continue phrase: `继续 AWH 全屏 Project Hub 写操作评审`.

- [ ] **Step 3: Return the compact receipt and exact inspection steps**

Lead with result, validation, blocker/risk, next step, and `下次请说：继续 AWH 全屏 Project Hub 写操作评审`. Include task id, branch, handoff path, installed plugin path, static dashboard path, and exact Codex task prompt only as secondary details.
