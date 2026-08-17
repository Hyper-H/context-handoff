# Fullscreen Project Hub MCP Apps Design

## Status

Approved in conversation on 2026-08-17. This specification covers the read-only first version only. State-changing UI actions are explicitly deferred until a separate user review.

## Objective

Turn the existing Agent Workflow Hub Project Hub dashboard into an installable local Codex plugin that exposes an MCP Apps UI inside one pinned AWH Hub Task. The task keeps the native Codex composer for project questions, shows a compact inline launcher in the conversation, and can expand into a fullscreen operational view. The existing `visualize-project` Markdown, JSON, and static HTML outputs remain supported as a fallback.

## Confirmed Product Decisions

- Do not build a separate Codex client and do not patch the native sidebar.
- Host the primary UI inside one pinned AWH Hub Task. The native composer remains available.
- Use the user-facing hierarchy `Project -> Work Item -> Codex Task -> Environment`.
- Show `Role` on every Codex Task.
- Preserve existing sidecar `taskId`, `threadId`, `codexThreadId`, worktree, and routing keys for compatibility.
- Treat sidecar state as authoritative workflow state and Git as authoritative environment/worktree state.
- Keep the first version read-only apart from refresh, display-mode changes, selection, filtering, searching, and other UI-local interactions.
- Keep plugin source in this repository and install it into the user's personal plugin location through `install.py`.

## App Classification

The app is an `interactive-decoupled` MCP App with a vanilla bundled widget. It has separate data and render tools, a local stdio MCP transport, no authentication, no external network calls, and no public submission scope.

## Architecture

The implementation has four layers with one-way dependencies:

1. **Sidecar data layer**: Python code reads sidecar state and Git worktree facts and produces a versioned, renderer-neutral Project Hub payload.
2. **Render layer**: shared HTML/CSS/JavaScript assets render that payload. The static dashboard embeds the same payload contract, while the MCP widget receives it through tool results.
3. **MCP adapter**: a small Node stdio server registers the UI resource and read-only tools, invokes the Python data command on every request, and never stores authoritative project state.
4. **Plugin/install layer**: a repository-owned plugin manifest and personal marketplace installer make the MCP server available in Codex.

The dependency direction is `plugin -> MCP adapter -> Python payload command -> sidecar/Git`. The render layer consumes only the payload contract and host bridge APIs. It cannot read or write sidecar files directly.

## Repository Shape

The implementation will use these ownership boundaries:

- `plugins/awh-project-hub/.codex-plugin/plugin.json`: Codex plugin metadata.
- `plugins/awh-project-hub/.mcp.json`: local stdio MCP declaration with `cwd: "."` and a plugin-relative server entry point.
- `plugins/awh-project-hub/package.json` and lockfile: reproducible MCP Apps SDK and build dependencies.
- `plugins/awh-project-hub/src/server.ts`: resource and tool registration only.
- `plugins/awh-project-hub/src/sidecar-client.ts`: Python process invocation, timeout, JSON validation, and error mapping.
- `plugins/awh-project-hub/web/`: inline/fullscreen widget source and renderer modules.
- `plugins/awh-project-hub/dist/`: installable bundled server and widget artifacts produced by the build.
- `skills/agent-workflow-hub/scripts/context_sidecar.py`: a read-only Project Hub payload action and the existing `visualize-project` command.
- `skills/agent-workflow-hub/scripts/project_hub_dashboard.py`: static HTML shell using the shared payload contract.
- Mirrored compatibility files under `skills/context-handoff/` remain behaviorally identical.
- `install.py`: skill installation plus safe plugin copy, personal marketplace entry creation/update, and validation.
- `tests/`: Python payload/static fallback tests plus Node MCP/UI tests.

Generated dynamic task state remains under `%USERPROFILE%/.codex/projects/<project-id>/`; it is never written into tracked documentation.

## Canonical Data Contract

The renderer-neutral payload is versioned as `awh.project-hub/v1` and has this conceptual shape:

```json
{
  "schemaVersion": "awh.project-hub/v1",
  "project": {
    "projectId": "hyper-h-agent-workflow-hub",
    "baseBranch": "main",
    "generatedAt": "ISO-8601 timestamp",
    "health": "healthy|attention|blocked"
  },
  "summary": {},
  "workItems": [
    {
      "workItemId": "existing sidecar taskId",
      "title": "goal or humanized taskId",
      "status": "existing task status",
      "health": "healthy|attention|blocked|archived",
      "codexTasks": [
        {
          "taskKey": "existing threads[].threadId",
          "codexThreadId": "existing threads[].codexThreadId",
          "label": "existing threadLabel",
          "role": "existing threadRole",
          "purpose": "existing threadPurpose",
          "environment": {
            "type": "existing environmentType",
            "worktreePath": "existing worktreePath",
            "branch": "Git branch",
            "dirty": false,
            "stale": false
          }
        }
      ],
      "blocker": "",
      "nextStep": "",
      "validationPresent": true,
      "handoffAvailable": true,
      "routing": {}
    }
  ],
  "needsAttention": [],
  "warnings": []
}
```

Mapping rules are explicit:

- A **Work Item** is an existing sidecar task record; `workItemId` is its existing `taskId`.
- A **Codex Task** is an entry in the task's existing `threads[]` registry. Machine keys remain unchanged.
- A legacy task with only top-level `threadRole`/`threadLabel` fields receives one synthesized read-only Codex Task in the presentation payload; sidecar state is not rewritten.
- An **Environment** is optional. It comes from thread environment fields plus verified Git worktree facts. Missing environments are valid for project-level threads.
- Existing visualization fields such as `taskRows`, `nodes`, and `edges` may remain as a compatibility projection during migration, but new UI code reads `workItems`.

## MCP Resource And Tool Contract

The plugin exposes one versioned UI resource, `ui://awh-project-hub/main-v1.html`, with MCP Apps MIME type `text/html;profile=mcp-app`. Resource metadata uses an empty connect/resource domain allowlist because the first version is fully local, avoids `frameDomains`, and includes a widget description.

It exposes two tools:

### `get_awh_project_hub`

- Purpose: fetch fresh sidecar and Git data without forcing a widget re-render.
- Input: optional absolute `worktreePath` and optional `projectId`. When absent, use the project route captured by the opening tool or the current sidecar project resolution.
- Annotations: `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`, `openWorldHint: false`.
- Output: concise summary in `structuredContent`; full validated payload in widget-only `_meta.awhProjectHub`.

### `open_awh_project_hub`

- Purpose: render the inline Project Hub launcher for a resolved project.
- Input: the same project locator fields.
- Metadata: `_meta.ui.resourceUri` points to the versioned UI resource and `_meta["openai/outputTemplate"]` mirrors it as a compatibility alias.
- Annotations: the same read-only/idempotent annotations.
- Output: initial summary plus the same widget-only payload, so the launcher does not require a second request.

Every refresh calls `get_awh_project_hub`, which starts a fresh Python payload process. The MCP server holds no canonical cache. The model can fetch data independently of rendering, satisfying the decoupled tool pattern.

## Host Integration

The widget uses the MCP Apps bridge for tool results and component-initiated `tools/call`. It uses `window.openai` only for Codex/ChatGPT host extensions:

- `window.openai.requestDisplayMode({ mode: "fullscreen" })` opens the main fullscreen view.
- `window.openai.displayMode` determines whether to render the compact launcher or full workspace.
- `window.openai.setWidgetState(...)` may persist only UI-local search, filter, selection, and panel state.
- `window.openai.callTool(...)` is a compatibility fallback when the standard bridge helper is unavailable.

The widget does not send follow-up messages, replace the native composer, or store workflow state. Exiting fullscreen returns the user to the same pinned Hub Task and its native composer.

## User Interface

### Inline Launcher

The inline surface is intentionally compact. It shows the project name, aggregate health, visible Work Item count, needs-attention count, generated time, a refresh icon, and a primary `Open fullscreen` command. It does not reproduce the dashboard in the conversation stream.

### Fullscreen Workspace

The fullscreen surface reuses the existing dashboard information architecture while correcting the hierarchy:

- Top bar: project identity, base branch, generated time, health totals, search, health filter, and refresh.
- Left pane: scannable Work Item list with status, health, blocker indicator, and task count.
- Center pane: Codex Tasks for the selected Work Item. Every row shows Role, label, purpose/status, and Environment summary.
- Right pane: selected Work Item or Codex Task details, including routing evidence, validation, handoff, blocker, next step, branch, worktree, dirty/stale state, and machine keys in a secondary technical section.
- Empty and missing-environment states are first-class, not errors.

The visual style stays close to the current quiet operational dashboard. It avoids marketing composition, nested cards, oversized headings, and decorative imagery. Fixed panel constraints and responsive breakpoints prevent content overlap. Narrow layouts collapse the detail pane below the task list without hiding machine-accessible information.

## Refresh And Local State

Refresh has one authoritative path:

1. Disable only the refresh control and mark the current view as refreshing.
2. Call `get_awh_project_hub` through the MCP Apps bridge.
3. Validate `schemaVersion` and the minimum project/work item structure.
4. Replace the rendered payload atomically.
5. Preserve a selected Work Item/Codex Task only when its machine key still exists.
6. Update the generated time and remove the refreshing state.

Search text, filters, selected keys, and panel expansion may persist in widget state. Sidecar records, health, blockers, tasks, roles, environments, validation, and routing data never persist in iframe state as authority.

## Error Handling

- MCP startup verifies that the bundled widget exists and resolves the Python executable and sidecar script before accepting calls.
- Python calls have a bounded timeout and capture only short stderr summaries. Long logs and sidecar contents are not copied into chat responses.
- A failed initial load renders a nonblank error surface with the failing boundary and the static dashboard recovery command.
- A failed refresh keeps the last successfully rendered payload, labels it as potentially stale, and exposes a retry control.
- One malformed Work Item or Codex Task becomes a warning and is omitted or normalized; it does not blank the whole app.
- Missing sidecar tasks, missing environments, detached worktrees, and audit warnings render as domain states.
- Tool errors use concise MCP errors for invalid input and successful tool results with warnings for partial project data.

## Installation

`install.py` remains the single repository entry point. In addition to installing both skills, it will:

1. Validate/build the repository plugin bundle.
2. Copy `plugins/awh-project-hub` to the personal plugin source directory resolved by the installer.
3. Create or update the default personal marketplace entry with `AVAILABLE`, `ON_INSTALL`, and `Productivity` metadata while preserving unrelated entries and marketplace display metadata.
4. Validate the installed plugin with the plugin validator contract.
5. Print the exact `codex plugin add awh-project-hub@<personal-marketplace-name>` command and state that a new Codex task is required after reinstall.

Repeated installation is idempotent for AWH-owned files and the AWH marketplace entry. It never deletes or rewrites unrelated marketplace entries. A dry run reports all destinations and commands without mutation.

## Static Fallback

`visualize-project` continues to emit Markdown, JSON, and HTML. The static HTML embeds the same `awh.project-hub/v1` payload and invokes the same pure renderer without MCP host APIs. Host-only controls are hidden or replaced with a note in static mode. Existing report links and sidecar report locations remain valid.

No MCP installation is required to use the static dashboard. A plugin or MCP failure therefore cannot remove the current Project Hub access path.

## Validation Strategy

### Payload Tests

- Map a sidecar task with multiple `threads[]` entries to one Work Item with multiple Codex Tasks.
- Preserve `taskId`, `threadId`, `codexThreadId`, Role, and environment keys.
- Synthesize one presentation-only Codex Task for legacy top-level thread fields.
- Keep no-environment threads valid.
- Represent health, blockers, validation, stale, dirty, handoff, and routing fields from fixtures.

### MCP Contract Tests

- Start the bundled stdio server and complete MCP initialization.
- Verify resource listing/read MIME type and versioned URI.
- Verify both tool descriptors, annotations, and render metadata.
- Verify repeated calls are read-only and return fresh fixture changes.
- Verify Python timeout, invalid JSON, missing script, and partial-data errors are concise and nonblank.

### Renderer Tests

- Render inline and fullscreen modes from fixtures.
- Verify Work Items, Codex Tasks, Roles, Environments, blockers, health, and details are visible.
- Verify refresh replaces payload without mutating stored authoritative state.
- Verify search/filter/selection are local and stable across a compatible refresh.
- Verify missing data, error, stale-data, and no-environment states.
- Verify desktop and narrow viewport layouts have no overlap or clipped controls.

### Static Regression Tests

- Run `visualize-project` against a temporary sidecar/Git fixture.
- Verify Markdown, JSON, and static HTML are produced.
- Open the static HTML and confirm the shared renderer shows the same hierarchy and key details without MCP host globals.

### Codex Desktop Verification

- Install the personal plugin and confirm its MCP server starts in a new task.
- In the pinned AWH Hub Task, invoke `open_awh_project_hub` and verify the inline launcher.
- Enter fullscreen and verify real sidecar Work Items, Codex Tasks, Roles, Environments, health, blockers, and details.
- Change only sidecar fixture/real workflow state through the existing CLI, refresh, and verify the iframe reflects the new authoritative data.
- Exit fullscreen and verify the native composer remains usable for a project question.
- Capture desktop and narrow viewport screenshots and inspect console/runtime errors.
- Re-run `visualize-project` and open the static fallback.

## Definition Of Done Mapping

1. Plugin validation, installation, MCP initialization, and tool/resource contract tests prove reliable local startup.
2. Desktop interaction proves the inline launcher and fullscreen transition.
3. Real sidecar rendering proves the required hierarchy, Roles, Environments, health, blockers, and details.
4. A sidecar change followed by widget refresh proves no iframe authority.
5. Exiting fullscreen and asking a project question proves the native composer remains available.
6. Static generation and browser rendering tests prove fallback preservation.
7. Focused automated tests plus Codex desktop screenshots and runtime checks provide validation evidence and exact inspection steps.
8. The absence of mutating tools and controls proves the implementation stops before state-changing UI actions.

## Non-Goals

- No native sidebar changes.
- No separate desktop client.
- No public hosting, tunnel, authentication, or app-directory submission.
- No task creation, status changes, blocker resolution, routing edits, handoff writes, or worktree operations from the UI.
- No migration or renaming of existing sidecar machine keys.
- No changes to `docs/paper` or `docs/research`.

## Documentation Basis

The implementation follows the current OpenAI MCP Apps guidance for versioned UI resources, `text/html;profile=mcp-app`, decoupled data/render tools, `_meta.ui.resourceUri`, read-only annotations, CSP allowlists, MCP Apps bridge tool calls, and `window.openai.requestDisplayMode`. Canonical references:

- https://developers.openai.com/apps-sdk/build/mcp-server/
- https://developers.openai.com/apps-sdk/build/chatgpt-ui/
- https://developers.openai.com/apps-sdk/plan/tools/
- https://developers.openai.com/apps-sdk/reference/

The official pages were unreachable from the current network during design review, so the contract was cross-checked against the locally installed OpenAI developer guidance snapshot. Implementation validation must re-check any version-sensitive API surface against the available SDK types and the installed Codex desktop runtime.
