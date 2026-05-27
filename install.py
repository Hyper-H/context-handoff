#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


SKILL_NAME = "context-handoff"


def default_codex_home() -> Path:
    return Path.home() / ".codex"


def copy_skill(source: Path, destination: Path, dry_run: bool) -> None:
    if not source.exists():
        raise SystemExit(f"skill source not found: {source}")
    if not (source / "SKILL.md").exists():
        raise SystemExit(f"skill source is missing SKILL.md: {source}")

    print(f"Installing {SKILL_NAME} skill")
    print(f"Source: {source}")
    print(f"Target: {destination}")
    if dry_run:
        print("Dry run only; no files were changed.")
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
    print("Installed successfully.")
    print("Restart or refresh Codex if the skill list does not update immediately.")
    print("GitHub CLI is optional; run `Use $context-handoff to run doctor for this project.` to check readiness.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the context-handoff Codex skill package.")
    parser.add_argument(
        "--codex-home",
        default=str(default_codex_home()),
        help="Codex home directory. Defaults to ~/.codex.",
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
    source = repo_root / "skills" / SKILL_NAME
    destination = Path(args.codex_home).expanduser().resolve() / "skills" / SKILL_NAME
    copy_skill(source, destination, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
