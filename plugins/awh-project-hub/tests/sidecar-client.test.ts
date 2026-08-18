import assert from "node:assert/strict";
import test from "node:test";

import { SidecarClient, SidecarError, type SpawnRequest } from "../src/sidecar-client.js";
import { fixturePayload } from "./fixtures.js";


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
  assert.deepEqual(calls[0]?.args, [
    "C:/skill/context_sidecar.py",
    "project-hub-payload",
    "--worktree",
    "C:/repo",
    "--project-id",
    "demo",
  ]);
  assert.equal(calls[0]?.timeoutMs, 30_000);
});

test("uses the bundled sidecar adapter by default", async () => {
  const calls: SpawnRequest[] = [];
  const client = new SidecarClient({
    run: async (request) => {
      calls.push(request);
      return { code: 0, stdout: JSON.stringify(fixturePayload), stderr: "" };
    },
    python: "python",
  });

  await client.getProjectHub({ worktreePath: "C:/repo" });

  assert.match(calls[0]!.args[0]!, /[\\/]sidecar[\\/]context_sidecar\.py$/);
  assert.doesNotMatch(calls[0]!.args[0]!, /\.codex[\\/]skills/);
});

test("requires an explicit worktree route", async () => {
  const client = new SidecarClient({ run: async () => ({ code: 0, stdout: "{}", stderr: "" }) });
  await assert.rejects(() => client.getProjectHub({}), /worktreePath is required/);
});

test("reports invalid JSON without copying stdout", async () => {
  const client = new SidecarClient({
    run: async () => ({ code: 0, stdout: "secret invalid output", stderr: "" }),
  });
  await assert.rejects(
    () => client.getProjectHub({ worktreePath: "C:/repo" }),
    (error: unknown) => error instanceof SidecarError
      && /invalid JSON/.test(error.message)
      && !error.message.includes("secret"),
  );
});

test("bounds process error details", async () => {
  const client = new SidecarClient({
    run: async () => ({ code: 2, stdout: "", stderr: `failure ${"x".repeat(5000)}` }),
  });
  await assert.rejects(
    () => client.getProjectHub({ worktreePath: "C:/repo" }),
    (error: unknown) => error instanceof SidecarError && error.message.length < 1100,
  );
});
