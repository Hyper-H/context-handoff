from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

from install import run_install


class InstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.source_root = self.root / "source"
        self.codex_home = self.root / "codex"
        self.plugin_home = self.root / "plugins"
        self.marketplace = self.root / ".agents" / "plugins" / "marketplace.json"
        self.installed_runtime = (
            self.plugin_home / "awh-project-hub" / "dist" / "runtime" / "python.json"
        )

        for skill_name in ("agent-workflow-hub", "context-handoff"):
            skill_dir = self.source_root / "skills" / skill_name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {skill_name}\n---\n",
                encoding="utf-8",
            )

        self.source_plugin = self.source_root / "plugins" / "awh-project-hub"
        required_files = (
            ".codex-plugin/plugin.json",
            ".mcp.json",
            "dist/server.mjs",
            "dist/sidecar/context_sidecar.py",
            "dist/widget.html",
        )
        for relative_path in required_files:
            target = self.source_plugin / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}\n", encoding="utf-8")

    def args(
        self,
        *,
        dry_run: bool = False,
        skip_skills: bool = False,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            codex_home=str(self.codex_home),
            plugin_home=str(self.plugin_home),
            marketplace_path=str(self.marketplace),
            dry_run=dry_run,
            skip_plugin=False,
            skip_skills=skip_skills,
        )

    def write_marketplace(self, value: dict[str, object]) -> None:
        self.marketplace.parent.mkdir(parents=True, exist_ok=True)
        self.marketplace.write_text(
            json.dumps(value, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_installs_plugin_and_preserves_unrelated_marketplace_entries(self) -> None:
        self.write_marketplace({
            "name": "personal",
            "interface": {"displayName": "My Plugins"},
            "plugins": [{
                "name": "keep-me",
                "source": {"source": "local", "path": "./plugins/keep-me"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                "category": "Other",
            }],
            "custom": {"preserve": True},
        })

        run_install(self.args(), repo_root=self.source_root)

        installed = json.loads(self.marketplace.read_text(encoding="utf-8"))
        self.assertEqual(installed["interface"]["displayName"], "My Plugins")
        self.assertEqual(installed["custom"], {"preserve": True})
        self.assertEqual(
            [item["name"] for item in installed["plugins"]],
            ["keep-me", "awh-project-hub"],
        )
        self.assertTrue(
            (self.plugin_home / "awh-project-hub" / "dist" / "server.mjs").is_file()
        )
        self.assertTrue(
            (self.plugin_home / "awh-project-hub" / "dist" / "sidecar" / "context_sidecar.py").is_file()
        )
        runtime = json.loads(self.installed_runtime.read_text(encoding="utf-8"))
        self.assertEqual(runtime["schemaVersion"], 1)
        self.assertEqual(Path(runtime["executable"]), Path(sys.executable).resolve())

    def test_reinstall_replaces_only_awh_entry_and_files(self) -> None:
        run_install(self.args(), repo_root=self.source_root)
        marker = self.plugin_home / "awh-project-hub" / "obsolete.txt"
        marker.write_text("remove", encoding="utf-8")
        self.installed_runtime.write_text(
            json.dumps({"schemaVersion": 1, "executable": "C:/stale/python.exe"}),
            encoding="utf-8",
        )

        run_install(self.args(), repo_root=self.source_root)

        installed = json.loads(self.marketplace.read_text(encoding="utf-8"))
        self.assertFalse(marker.exists())
        self.assertEqual(
            [item["name"] for item in installed["plugins"]].count("awh-project-hub"),
            1,
        )
        runtime = json.loads(self.installed_runtime.read_text(encoding="utf-8"))
        self.assertEqual(Path(runtime["executable"]), Path(sys.executable).resolve())

    def test_dry_run_changes_nothing(self) -> None:
        self.write_marketplace({"name": "personal", "plugins": []})
        before = self.marketplace.read_bytes()

        run_install(self.args(dry_run=True), repo_root=self.source_root)

        self.assertEqual(self.marketplace.read_bytes(), before)
        self.assertFalse((self.plugin_home / "awh-project-hub").exists())
        self.assertFalse(self.installed_runtime.exists())
        self.assertFalse(self.codex_home.exists())

    def test_rejects_missing_built_artifacts(self) -> None:
        (self.source_plugin / "dist" / "server.mjs").unlink()

        with self.assertRaisesRegex(SystemExit, "dist/server.mjs"):
            run_install(self.args(), repo_root=self.source_root)

    def test_skip_skills_installs_only_plugin(self) -> None:
        run_install(self.args(skip_skills=True), repo_root=self.source_root)

        self.assertFalse(self.codex_home.exists())
        self.assertTrue((self.plugin_home / "awh-project-hub" / "dist" / "server.mjs").is_file())
        installed = json.loads(self.marketplace.read_text(encoding="utf-8"))
        self.assertEqual(installed["plugins"][0]["name"], "awh-project-hub")


if __name__ == "__main__":
    unittest.main()
