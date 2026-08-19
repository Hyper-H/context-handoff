#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


SKILL_NAMES = ["agent-workflow-hub", "context-handoff"]
PLUGIN_NAME = "awh-project-hub"
PLUGIN_REQUIRED_FILES = (
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "dist/server.mjs",
    "dist/sidecar/context_sidecar.py",
    "dist/widget.html",
)


def default_codex_home() -> Path:
    return Path.home() / ".codex"


def default_plugin_home() -> Path:
    return Path.home() / "plugins"


def default_marketplace_path() -> Path:
    return Path.home() / ".agents" / "plugins" / "marketplace.json"


def copy_skill(skill_name: str, source: Path, destination: Path, dry_run: bool) -> None:
    if not source.exists():
        raise SystemExit(f"skill source not found: {source}")
    if not (source / "SKILL.md").exists():
        raise SystemExit(f"skill source is missing SKILL.md: {source}")

    print(f"Installing {skill_name} skill")
    print(f"Source: {source}")
    print(f"Target: {destination}")
    if dry_run:
        print("Dry run only; no files were changed.")
        print("")
        return

    if destination.exists():
        print("Existing installation found; replacing it with the bundled skill package.")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    print("")
    print(f"Installed {skill_name} successfully.")
    print("")


def validate_plugin_source(source: Path) -> None:
    for relative_path in PLUGIN_REQUIRED_FILES:
        if not (source / relative_path).is_file():
            raise SystemExit(f"plugin source is missing {relative_path}: {source}")


def load_marketplace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "name": "personal",
            "interface": {"displayName": "Personal"},
            "plugins": [],
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"failed to read marketplace JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"marketplace root must be a JSON object: {path}")
    plugins = value.get("plugins")
    if plugins is None:
        value["plugins"] = []
    elif not isinstance(plugins, list):
        raise SystemExit(f"marketplace plugins must be a JSON array: {path}")
    return value


def awh_marketplace_entry() -> dict[str, Any]:
    return {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }


def upsert_plugin_entry(marketplace: dict[str, Any]) -> dict[str, Any]:
    updated = dict(marketplace)
    plugins = marketplace.get("plugins", [])
    updated["plugins"] = [
        item
        for item in plugins
        if not isinstance(item, dict) or item.get("name") != PLUGIN_NAME
    ]
    updated["plugins"].append(awh_marketplace_entry())
    return updated


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            newline="\n",
        ) as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            temporary_path = Path(stream.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def copy_plugin(source: Path, destination: Path, dry_run: bool) -> None:
    validate_plugin_source(source)
    print(f"Installing {PLUGIN_NAME} plugin")
    print(f"Source: {source}")
    print(f"Target: {destination}")
    if dry_run:
        print("Dry run only; no files were changed.")
        print("")
        return
    if destination.exists():
        print("Existing plugin source found; replacing AWH-owned files.")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("node_modules", "__pycache__", "*.pyc"),
    )
    print("")


def install_python_runtime(plugin_dir: Path, dry_run: bool) -> None:
    executable = Path(sys.executable).resolve()
    runtime_path = plugin_dir / "dist" / "runtime" / "python.json"
    print(f"Python runtime: {executable}")
    if dry_run:
        print("Dry run only; Python runtime binding was not written.")
        print("")
        return
    write_json_atomic(runtime_path, {
        "schemaVersion": 1,
        "executable": str(executable),
    })
    print(f"Recorded Python runtime in {runtime_path}.")
    print("")


def install_marketplace_entry(path: Path, dry_run: bool) -> str:
    marketplace = load_marketplace(path)
    name = marketplace.get("name", "personal")
    if not isinstance(name, str) or not name.strip():
        raise SystemExit(f"marketplace name must be a non-empty string: {path}")
    updated = upsert_plugin_entry(marketplace)
    print(f"Personal marketplace: {path}")
    if dry_run:
        print("Dry run only; marketplace was not changed.")
    else:
        write_json_atomic(path, updated)
        print(f"Updated {PLUGIN_NAME} in marketplace {name}.")
    print("")
    return name


def run_install(args: argparse.Namespace, *, repo_root: Path) -> int:
    if not args.skip_skills:
        codex_home = Path(args.codex_home).expanduser().resolve()
        for skill_name in SKILL_NAMES:
            copy_skill(
                skill_name,
                repo_root / "skills" / skill_name,
                codex_home / "skills" / skill_name,
                args.dry_run,
            )

    if args.skip_plugin:
        return 0

    plugin_home = Path(args.plugin_home).expanduser().resolve()
    marketplace_path = Path(args.marketplace_path).expanduser().resolve()
    installed_plugin = plugin_home / PLUGIN_NAME
    copy_plugin(
        repo_root / "plugins" / PLUGIN_NAME,
        installed_plugin,
        args.dry_run,
    )
    install_python_runtime(installed_plugin, args.dry_run)
    marketplace_name = install_marketplace_entry(marketplace_path, args.dry_run)
    print("Register or reinstall the plugin with:")
    print(f"codex plugin add {PLUGIN_NAME}@{marketplace_name}")
    print("Open a new Codex task after installation so the MCP tools are refreshed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the Agent Workflow Hub and context-handoff Codex skill packages.")
    parser.add_argument(
        "--codex-home",
        default=str(default_codex_home()),
        help="Codex home directory. Defaults to ~/.codex.",
    )
    parser.add_argument(
        "--plugin-home",
        default=str(default_plugin_home()),
        help="Personal plugin source directory. Defaults to ~/plugins.",
    )
    parser.add_argument(
        "--marketplace-path",
        default=str(default_marketplace_path()),
        help="Personal marketplace JSON path. Defaults to ~/.agents/plugins/marketplace.json.",
    )
    parser.add_argument(
        "--skip-plugin",
        action="store_true",
        help="Install the skill packages without installing the Project Hub plugin.",
    )
    parser.add_argument(
        "--skip-skills",
        action="store_true",
        help="Install the Project Hub plugin without replacing existing skill packages.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be installed without changing files.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parent
    run_install(args, repo_root=repo_root)
    if not args.dry_run:
        print("Installed successfully.")
        print("Restart or refresh Codex if the skill list does not update immediately.")
        print("GitHub CLI is optional; run `Use $agent-workflow-hub to run doctor for this project.` to check readiness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
