# Portable Python Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the installed AWH Project Hub locate and validate an existing Python 3.10+ runtime without relying on a bare `python` command.

**Architecture:** Add a focused runtime resolver that gathers bounded candidates, probes each interpreter, rejects Windows Store aliases, and caches the selected command. The installer records its own interpreter in a machine-local file, while discovery remains a fallback for direct plugin use.

**Tech Stack:** TypeScript, Node.js child processes and filesystem APIs, Python 3.10+, `unittest`, MCP stdio.

---

### Task 1: Specify Runtime Discovery With Failing Tests

**Files:**
- Create: `plugins/awh-project-hub/tests/python-runtime.test.ts`
- Create: `plugins/awh-project-hub/src/python-runtime.ts`

- [ ] **Step 1: Write candidate and probe tests**

Cover explicit environment precedence, `VIRTUAL_ENV`, `CONDA_PREFIX`, installed config, `py -3`, multiple `where.exe python` results, `Microsoft\\WindowsApps` rejection, Python versions below 3.10, and cached resolution. Use injected file readers, PATH discovery, and process probes so tests are platform-independent.

```ts
const runtime = await resolvePythonRuntime({
  platform: "win32",
  env: {},
  readInstalledConfig: async () => undefined,
  discoverWindowsPaths: async () => [
    "C:/Users/demo/AppData/Local/Microsoft/WindowsApps/python.exe",
    "D:/Python/python.exe",
  ],
  probe: async (candidate) => candidate.command.startsWith("D:/")
    ? { executable: candidate.command, version: [3, 12] }
    : undefined,
});
assert.equal(runtime.command, "D:/Python/python.exe");
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `pnpm exec tsx --test tests/python-runtime.test.ts`

Expected: FAIL because `src/python-runtime.ts` does not exist or does not export the resolver.

- [ ] **Step 3: Implement candidate collection and probing**

Define `PythonCommand`, `PythonProbe`, `PythonRuntimeOptions`, and `resolvePythonRuntime()`. Normalize paths for deduplication, reject Windows Store aliases before probing, validate Python 3.10+, and return a bounded actionable `PythonRuntimeError` when no candidate works.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `pnpm exec tsx --test tests/python-runtime.test.ts`

Expected: all runtime discovery tests pass.

### Task 2: Integrate Discovery Into SidecarClient

**Files:**
- Modify: `plugins/awh-project-hub/src/sidecar-client.ts`
- Modify: `plugins/awh-project-hub/tests/sidecar-client.test.ts`

- [ ] **Step 1: Write a failing integration test**

Assert that a resolved launcher command prepends arguments correctly:

```ts
const client = new SidecarClient({
  resolvePython: async () => ({ command: "py", argsPrefix: ["-3"] }),
  run: async (request) => {
    calls.push(request);
    return { code: 0, stdout: JSON.stringify(fixturePayload), stderr: "" };
  },
});
await client.getProjectHub({ worktreePath: "C:/repo" });
assert.deepEqual(calls[0]?.args.slice(0, 2), ["-3", expectedSidecarPath]);
```

- [ ] **Step 2: Run the integration test and verify it fails**

Run: `pnpm exec tsx --test tests/sidecar-client.test.ts`

Expected: FAIL because `resolvePython` is not supported.

- [ ] **Step 3: Resolve and cache the runtime before sidecar execution**

Keep explicit `python` overrides for tests and embeddings. Production construction delegates to `resolvePythonRuntime()`. Preserve current timeout, bounded stderr handling, payload validation, and worktree routing.

- [ ] **Step 4: Run the integration test and verify it passes**

Run: `pnpm exec tsx --test tests/sidecar-client.test.ts`

Expected: all sidecar-client tests pass.

### Task 3: Record the Installer Interpreter

**Files:**
- Modify: `install.py`
- Modify: `tests/test_install.py`

- [ ] **Step 1: Write failing installer tests**

Assert that a normal plugin installation creates `dist/runtime/python.json` containing `Path(sys.executable).resolve()`, reinstall replaces stale content, and dry-run creates no runtime file.

```python
runtime = json.loads((plugin_dir / "dist/runtime/python.json").read_text())
self.assertEqual(runtime["schemaVersion"], 1)
self.assertEqual(Path(runtime["executable"]), Path(sys.executable).resolve())
```

- [ ] **Step 2: Run installer tests and verify they fail**

Run: `D:\\anaconda_new\\python.exe -m unittest tests.test_install -v`

Expected: FAIL because the runtime binding is absent.

- [ ] **Step 3: Write the runtime binding atomically**

After `copy_plugin`, write `dist/runtime/python.json` with `write_json_atomic()`. Use the interpreter running `install.py`; do not modify the tracked source `.mcp.json` or marketplace schema. Dry-run only reports the planned binding.

- [ ] **Step 4: Run installer tests and verify they pass**

Run: `D:\\anaconda_new\\python.exe -m unittest tests.test_install -v`

Expected: five or more installer tests pass.

### Task 4: Build, Reinstall, and Prove the Real No-Env Path

**Files:**
- Modify generated artifacts: `plugins/awh-project-hub/dist/server.mjs`
- Modify cachebuster: `plugins/awh-project-hub/.codex-plugin/plugin.json`

- [ ] **Step 1: Run the complete focused suite**

Run: `pnpm run validate`

Run: `D:\\anaconda_new\\python.exe -m unittest tests.test_project_hub_contract tests.test_install tests.test_project_hub_e2e -v`

Expected: all Node and Python tests pass.

- [ ] **Step 2: Update cachebuster and reinstall**

Run: `D:\\anaconda_new\\python.exe C:\\Users\\48123\\.codex\\skills\\.system\\plugin-creator\\scripts\\update_plugin_cachebuster.py plugins/awh-project-hub`

Run: `D:\\anaconda_new\\python.exe install.py --skip-skills`

Expected: the installed plugin contains a valid `dist/runtime/python.json` pointing to `D:\\anaconda_new\\python.exe`.

- [ ] **Step 3: Smoke-test the installed MCP server without `AWH_PYTHON`**

Start `C:\\Users\\48123\\plugins\\awh-project-hub\\dist\\server.mjs` with `AWH_PYTHON` removed, send MCP `initialize`, `tools/list`, and `tools/call` requests, and verify `open_awh_project_hub` returns `awh.project-hub/v1` metadata from real sidecar data.

- [ ] **Step 4: Validate both plugin directories**

Run `plugin-creator/scripts/validate_plugin.py` against the repo plugin and installed plugin.

Expected: both pass.

- [ ] **Step 5: Commit and open a Chinese PR**

Commit only the related spec, plan, runtime resolver, installer, tests, and generated plugin artifacts. Push `codex/fullscreen-project-hub`, then create a PR targeting `main` with a Chinese title, Chinese summary, validation evidence, and the Windows code-9009 root cause.
