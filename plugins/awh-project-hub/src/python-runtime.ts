import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";


export interface PythonCandidate {
  command: string;
  argsPrefix: string[];
  source: string;
}

export interface PythonProbe {
  executable: string;
  version: [number, number];
}

export interface PythonCommand extends PythonCandidate {}

export interface PythonRuntimeOptions {
  platform?: NodeJS.Platform;
  env?: NodeJS.ProcessEnv;
  readInstalledRuntime?: () => Promise<string | undefined>;
  discoverWindowsPaths?: () => Promise<string[]>;
  probe?: (candidate: PythonCandidate) => Promise<PythonProbe | undefined>;
}

interface InstalledRuntime {
  schemaVersion?: unknown;
  executable?: unknown;
}

const MINIMUM_VERSION: [number, number] = [3, 10];
const PROBE_CODE = "import json,sys; print(json.dumps({'executable':sys.executable,'version':[sys.version_info.major,sys.version_info.minor]}))";

export class PythonRuntimeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PythonRuntimeError";
  }
}

function execute(command: string, args: string[], timeoutMs = 5_000): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      command,
      args,
      { timeout: timeoutMs, maxBuffer: 64 * 1024, windowsHide: true },
      (error, stdout) => {
        if (error) {
          reject(error);
        } else {
          resolve(stdout);
        }
      },
    );
  });
}

async function defaultProbe(candidate: PythonCandidate): Promise<PythonProbe | undefined> {
  try {
    const stdout = await execute(candidate.command, [...candidate.argsPrefix, "-c", PROBE_CODE]);
    const line = stdout.trim().split(/\r?\n/).at(-1);
    if (!line) return undefined;
    const value = JSON.parse(line) as { executable?: unknown; version?: unknown };
    if (typeof value.executable !== "string"
      || !Array.isArray(value.version)
      || value.version.length < 2
      || !value.version.slice(0, 2).every(Number.isInteger)) {
      return undefined;
    }
    return {
      executable: value.executable,
      version: [value.version[0] as number, value.version[1] as number],
    };
  } catch {
    return undefined;
  }
}

async function defaultReadInstalledRuntime(): Promise<string | undefined> {
  const runtimePath = path.join(
    path.dirname(fileURLToPath(import.meta.url)),
    "runtime",
    "python.json",
  );
  try {
    const value = JSON.parse(await readFile(runtimePath, "utf8")) as InstalledRuntime;
    return value.schemaVersion === 1 && typeof value.executable === "string"
      ? value.executable
      : undefined;
  } catch {
    return undefined;
  }
}

async function defaultDiscoverWindowsPaths(env: NodeJS.ProcessEnv): Promise<string[]> {
  try {
    const windowsDirectory = env.SystemRoot || env.WINDIR;
    const whereCommand = windowsDirectory
      ? path.join(windowsDirectory, "System32", "where.exe")
      : "where.exe";
    const stdout = await execute(whereCommand, ["python"]);
    return stdout.split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  } catch {
    return [];
  }
}

function isWindowsStoreAlias(command: string): boolean {
  return /[\\/]Microsoft[\\/]WindowsApps[\\/]/i.test(command);
}

function supportsMinimumVersion(version: [number, number]): boolean {
  return version[0] > MINIMUM_VERSION[0]
    || (version[0] === MINIMUM_VERSION[0] && version[1] >= MINIMUM_VERSION[1]);
}

function environmentCandidate(env: NodeJS.ProcessEnv, name: string, source: string): PythonCandidate | undefined {
  const command = env[name]?.trim();
  return command ? { command, argsPrefix: [], source } : undefined;
}

export async function resolvePythonRuntime(options: PythonRuntimeOptions = {}): Promise<PythonCommand> {
  const platform = options.platform ?? process.platform;
  const env = options.env ?? process.env;
  const platformPath = platform === "win32" ? path.win32 : path.posix;
  const probe = options.probe ?? defaultProbe;
  const readInstalledRuntime = options.readInstalledRuntime ?? defaultReadInstalledRuntime;
  const discoverWindowsPaths = options.discoverWindowsPaths ?? (() => defaultDiscoverWindowsPaths(env));
  const seen = new Set<string>();
  const checked: string[] = [];

  const tryCandidate = async (candidate?: PythonCandidate): Promise<PythonCommand | undefined> => {
    if (!candidate || isWindowsStoreAlias(candidate.command)) return undefined;
    const identity = `${candidate.command}\0${candidate.argsPrefix.join("\0")}`
      .replaceAll("\\", "/")
      .toLocaleLowerCase();
    if (seen.has(identity)) return undefined;
    seen.add(identity);
    checked.push(candidate.source);
    const result = await probe(candidate);
    if (!result || isWindowsStoreAlias(result.executable) || !supportsMinimumVersion(result.version)) {
      return undefined;
    }
    return { command: result.executable, argsPrefix: [], source: candidate.source };
  };

  const initial = [
    environmentCandidate(env, "AWH_PYTHON", "AWH_PYTHON"),
    env.VIRTUAL_ENV
      ? { command: platformPath.join(env.VIRTUAL_ENV, platform === "win32" ? "Scripts/python.exe" : "bin/python"), argsPrefix: [], source: "VIRTUAL_ENV" }
      : undefined,
    env.CONDA_PREFIX
      ? { command: platformPath.join(env.CONDA_PREFIX, platform === "win32" ? "python.exe" : "bin/python"), argsPrefix: [], source: "CONDA_PREFIX" }
      : undefined,
  ];
  for (const candidate of initial) {
    const result = await tryCandidate(candidate);
    if (result) return result;
  }

  const installed = await readInstalledRuntime();
  const installedResult = await tryCandidate(installed
    ? { command: installed, argsPrefix: [], source: "AWH installer" }
    : undefined);
  if (installedResult) return installedResult;

  if (platform === "win32") {
    const launcher = await tryCandidate({ command: "py", argsPrefix: ["-3"], source: "Windows py launcher" });
    if (launcher) return launcher;
    for (const command of await discoverWindowsPaths()) {
      const result = await tryCandidate({ command, argsPrefix: [], source: "Windows PATH" });
      if (result) return result;
    }
  }

  for (const command of ["python3", "python"]) {
    const result = await tryCandidate({ command, argsPrefix: [], source: `${command} command` });
    if (result) return result;
  }

  const sources = [...new Set(checked)].join(", ");
  throw new PythonRuntimeError(
    `Python 3.10 or later was not found. Checked: ${sources || "configured and platform Python locations"}. `
    + "Rerun the AWH installer with a valid Python interpreter or set AWH_PYTHON to its absolute path.",
  );
}
