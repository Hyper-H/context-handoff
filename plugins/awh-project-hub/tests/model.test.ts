import assert from "node:assert/strict";
import test from "node:test";

import { fixturePayload } from "./fixtures.js";
import {
  parseProjectHubPayload,
  reconcileSelection,
  taskEnvironmentLabel,
  visibleWorkItems,
} from "../web/model.js";


test("validates the project hub v1 payload", () => {
  assert.equal(parseProjectHubPayload(fixturePayload).schemaVersion, "awh.project-hub/v1");
  assert.throws(() => parseProjectHubPayload({ ...fixturePayload, schemaVersion: "wrong" }));
});

test("filters work items by text and health", () => {
  const result = visibleWorkItems(fixturePayload.workItems, { query: "execution", health: "blocked" });
  assert.deepEqual(result.map((item) => item.workItemId), ["blocked-item"]);
});

test("reconciles selection after refresh", () => {
  assert.deepEqual(reconcileSelection(fixturePayload, { workItemId: "gone", taskKey: "gone" }), {
    workItemId: "blocked-item",
    taskKey: "thr-1",
  });
});

test("keeps no-environment codex tasks visible", () => {
  assert.equal(taskEnvironmentLabel(fixturePayload.workItems[1]!.codexTasks[0]!), "No environment");
});

test("labels project-level tasks without inheriting a work item branch", () => {
  const payload = structuredClone(fixturePayload);
  const task = payload.workItems[0]!.codexTasks[0]!;
  task.environment = {
    type: "project-level",
    worktreePath: "",
    branch: "codex/should-not-display",
    dirty: false,
    stale: false,
    dirtyFiles: [],
  };

  assert.equal(taskEnvironmentLabel(task), "project-level");
});
