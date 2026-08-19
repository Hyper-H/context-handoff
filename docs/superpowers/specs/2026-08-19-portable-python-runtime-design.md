# Portable Python Runtime Design

## Problem

The AWH Project Hub MCP server starts correctly, but its Python sidecar currently defaults to the bare `python` command. On Windows this can resolve to the Microsoft Store alias under `Microsoft\WindowsApps`, which exits with code 9009 even when a usable Conda or CPython interpreter exists elsewhere. Existing tests set `AWH_PYTHON`, so they did not exercise the installed-plugin path.

## Goal

Make the local plugin reliably select an existing Python 3.10+ interpreter on Windows, macOS, and Linux without hard-coding a developer machine path. When no usable interpreter exists, return an actionable bounded error instead of a raw process exit code.

## Runtime Contract

Interpreter selection uses this precedence:

1. An explicit `SidecarClient` test or embedding override.
2. `AWH_PYTHON`.
3. An active `VIRTUAL_ENV` or `CONDA_PREFIX`.
4. The interpreter recorded by the AWH installer.
5. On Windows, the Python launcher (`py -3`) and every non-`WindowsApps` result from `where.exe python`.
6. Platform commands (`python3`, then `python`).

Every production candidate is probed with a short Python command that returns `sys.executable` and the version. Candidates that cannot start, return code 9009, point at `Microsoft\WindowsApps`, emit invalid probe output, or are older than Python 3.10 are rejected. The first successful result is cached for the MCP server lifetime.

Discovery is bounded. It does not scan the whole disk, modify PATH, download Python, or require administrator rights.

## Installation Contract

`install.py` writes a machine-local `dist/runtime/python.json` into the copied personal plugin. The file records `sys.executable` and is not created in the tracked source plugin. Dry-run performs no writes. Reinstallation replaces the prior local binding with the interpreter running the new installation.

The marketplace remains unchanged except for the existing AWH entry. The plugin cachebuster is updated through the plugin-creator helper before reinstalling.

## Components

- `plugins/awh-project-hub/src/python-runtime.ts`: collect, probe, deduplicate, and cache interpreter candidates.
- `plugins/awh-project-hub/src/sidecar-client.ts`: request a resolved runtime and prepend launcher arguments such as `py -3` before the sidecar script.
- `install.py`: atomically write the installed runtime binding after copying the plugin.
- Focused Node and Python tests: cover precedence, Windows Store alias rejection, fallback, version failure, installer output, dry-run, and the no-`AWH_PYTHON` path.

## Error Handling

If discovery fails, the MCP tool returns a short error stating that Python 3.10+ was not found and naming the supported remedies: rerun the AWH installer with a valid Python or set `AWH_PYTHON` to an absolute interpreter path. Candidate output and environment contents are not copied into the error.

Sidecar application failures remain distinct from interpreter-discovery failures. A valid Python that runs the sidecar and receives a nonzero application exit is not silently replaced with another interpreter.

## Validation

1. Unit-test candidate ordering, launcher argument prefixes, alias rejection, cached resolution, and bounded errors.
2. Verify installer and dry-run behavior in temporary directories.
3. Build the plugin and run its MCP/UI suite.
4. Reinstall with `D:\anaconda_new\python.exe install.py --skip-skills`.
5. Start the installed MCP server with `AWH_PYTHON` removed and confirm `open_awh_project_hub` returns a real `awh.project-hub/v1` payload.
6. Revalidate the source and installed plugin and open a fresh Codex task for user acceptance.

## Boundaries

- Keep the UI read-only.
- Keep sidecar data authoritative.
- Preserve the static `visualize-project` fallback.
- Do not modify unrelated `docs/paper` or `docs/research` files.
- Do not bundle Python or add automatic downloads in this change.
