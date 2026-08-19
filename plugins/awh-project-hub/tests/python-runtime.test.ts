import assert from "node:assert/strict";
import test from "node:test";

import {
  PythonRuntimeError,
  resolvePythonRuntime,
  type PythonCandidate,
  type PythonProbe,
} from "../src/python-runtime.js";


const validProbe = (executable: string, minor = 12): PythonProbe => ({
  executable,
  version: [3, minor],
});

test("skips the Windows Store alias and uses the next discovered interpreter", async () => {
  const probed: string[] = [];
  const runtime = await resolvePythonRuntime({
    platform: "win32",
    env: {},
    readInstalledRuntime: async () => undefined,
    discoverWindowsPaths: async () => [
      "C:/Users/demo/AppData/Local/Microsoft/WindowsApps/python.exe",
      "D:/Python/python.exe",
    ],
    probe: async (candidate) => {
      probed.push(candidate.command);
      return candidate.command === "D:/Python/python.exe"
        ? validProbe("D:/Python/python.exe")
        : undefined;
    },
  });

  assert.equal(runtime.command, "D:/Python/python.exe");
  assert.deepEqual(runtime.argsPrefix, []);
  assert.ok(!probed.some((value) => value.includes("WindowsApps")));
});

test("prefers AWH_PYTHON over active environments and installed configuration", async () => {
  const candidates: PythonCandidate[] = [];
  const runtime = await resolvePythonRuntime({
    platform: "win32",
    env: {
      AWH_PYTHON: "D:/explicit/python.exe",
      VIRTUAL_ENV: "D:/venv",
      CONDA_PREFIX: "D:/conda",
    },
    readInstalledRuntime: async () => "D:/installed/python.exe",
    discoverWindowsPaths: async () => {
      throw new Error("PATH discovery should not run after a successful explicit candidate");
    },
    probe: async (candidate) => {
      candidates.push(candidate);
      return validProbe(candidate.command);
    },
  });

  assert.equal(runtime.command, "D:/explicit/python.exe");
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0]?.source, "AWH_PYTHON");
});

test("supports the Windows launcher argument prefix", async () => {
  const runtime = await resolvePythonRuntime({
    platform: "win32",
    env: {},
    readInstalledRuntime: async () => undefined,
    discoverWindowsPaths: async () => [],
    probe: async (candidate) => candidate.command === "py"
      ? validProbe("C:/Python313/python.exe", 13)
      : undefined,
  });

  assert.equal(runtime.command, "C:/Python313/python.exe");
  assert.deepEqual(runtime.argsPrefix, []);
  assert.equal(runtime.source, "Windows py launcher");
});

test("uses the installer binding before platform discovery", async () => {
  const runtime = await resolvePythonRuntime({
    platform: "win32",
    env: {},
    readInstalledRuntime: async () => "D:/anaconda/python.exe",
    discoverWindowsPaths: async () => {
      throw new Error("PATH discovery should not run after the installer binding succeeds");
    },
    probe: async (candidate) => validProbe(candidate.command, 10),
  });

  assert.equal(runtime.command, "D:/anaconda/python.exe");
  assert.equal(runtime.source, "AWH installer");
});

test("returns an actionable bounded error when no Python 3.10 runtime exists", async () => {
  await assert.rejects(
    () => resolvePythonRuntime({
      platform: "linux",
      env: { AWH_PYTHON: "/opt/python-old" },
      readInstalledRuntime: async () => undefined,
      probe: async (candidate) => candidate.command === "/opt/python-old"
        ? validProbe("/opt/python-old", 9)
        : undefined,
    }),
    (error: unknown) => error instanceof PythonRuntimeError
      && /Python 3\.10 or later was not found/.test(error.message)
      && /AWH_PYTHON/.test(error.message)
      && error.message.length < 700,
  );
});
