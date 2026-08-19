"""Tests for explicit agent browser automation provisioning."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import browser_automation_steps
from lib import agent_cli
from lib.arg_parser import add_setup_arguments
from lib.config import SetupConfig
from lib.validation import validate_browser_automation_settings
from plugins.common import extend_agent_steps


def _config(*tools: str, browser_automation: str | None = "playwright") -> SetupConfig:
    return SetupConfig(
        host="example.test",
        username="agent",
        system_type="workstation_dev",
        agent_tools=list(tools),
        browser_automation=browser_automation,
    )


class BrowserAutomationConfigTests(unittest.TestCase):
    def test_parser_accepts_explicit_provider(self) -> None:
        parser = argparse.ArgumentParser()
        add_setup_arguments(parser, for_remote=True, include_host=False)

        args = parser.parse_args(
            ["--agent-tool", "codex", "--browser-automation", "playwright"]
        )

        self.assertEqual(args.agent_tools, ["codex"])
        self.assertEqual(args.browser_automation, "playwright")

    def test_config_serializes_provider_to_remote_and_saved_commands(self) -> None:
        config = _config("codex")

        self.assertIn("--browser-automation playwright", config.to_remote_args())
        self.assertIn("--browser-automation playwright", config.to_setup_command())
        self.assertEqual(config.to_dict()["browser_automation"], "playwright")

    def test_validation_requires_a_compatible_selected_agent(self) -> None:
        with self.assertRaisesRegex(ValueError, "codex or --agent-tool opencode"):
            validate_browser_automation_settings(_config("gh"))

        validate_browser_automation_settings(_config("codex", "opencode"))

    def test_browser_step_follows_payload_and_precedes_repositories(self) -> None:
        config = _config("codex")
        config.agent_payload = True
        config.agent_repos = ["https://github.com/example/project.git"]
        steps: list[tuple[str, object]] = []

        extend_agent_steps(config, steps)  # type: ignore[arg-type]

        names = [name for name, _function in steps]
        self.assertLess(
            names.index("Copying agent tool configuration"),
            names.index("Installing agent browser automation"),
        )
        self.assertLess(
            names.index("Installing agent browser automation"),
            names.index("Cloning agent repositories on target"),
        )


class BrowserAutomationProvisioningTests(unittest.TestCase):
    def test_runtime_verification_covers_mcp_and_executed_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package_path = root / "package.json"
            lock_path = root / "package-lock.json"
            package_path.write_text(
                json.dumps({"version": browser_automation_steps.PLAYWRIGHT_MCP_VERSION}),
                encoding="utf-8",
            )
            lock_value = {
                "packages": {
                    "node_modules/@playwright/mcp": {
                        "version": browser_automation_steps.PLAYWRIGHT_MCP_VERSION,
                        "integrity": browser_automation_steps.PLAYWRIGHT_MCP_INTEGRITY,
                    },
                    "node_modules/playwright": {
                        "version": browser_automation_steps.PLAYWRIGHT_VERSION,
                        "integrity": browser_automation_steps.PLAYWRIGHT_INTEGRITY,
                    },
                    "node_modules/playwright-core": {
                        "version": browser_automation_steps.PLAYWRIGHT_VERSION,
                        "integrity": browser_automation_steps.PLAYWRIGHT_CORE_INTEGRITY,
                    },
                }
            }
            lock_path.write_text(json.dumps(lock_value), encoding="utf-8")

            browser_automation_steps._verify_runtime_package(
                str(package_path),
                str(lock_path),
            )
            lock_value["packages"]["node_modules/playwright-core"]["integrity"] = "wrong"
            lock_path.write_text(json.dumps(lock_value), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "playwright-core"):
                browser_automation_steps._verify_runtime_package(
                    str(package_path),
                    str(lock_path),
                )

    def test_install_registers_only_selected_compatible_agents(self) -> None:
        config = _config("codex")
        targets = (
            "_install_runtime_package",
            "_write_launchers",
            "_install_browser",
            "_configure_codex",
            "_configure_opencode",
            "_run_smoke_test",
        )
        with (
            patch.object(browser_automation_steps, "is_dry_run", return_value=False),
            patch.object(browser_automation_steps, targets[0]) as runtime,
            patch.object(browser_automation_steps, targets[1]) as launchers,
            patch.object(browser_automation_steps, targets[2]) as browser,
            patch.object(browser_automation_steps, targets[3]) as codex,
            patch.object(browser_automation_steps, targets[4]) as opencode,
            patch.object(browser_automation_steps, targets[5]) as smoke,
        ):
            browser_automation_steps.install_browser_automation(config)

        runtime.assert_called_once_with()
        launchers.assert_called_once_with()
        browser.assert_called_once_with(config)
        codex.assert_called_once_with(config)
        opencode.assert_not_called()
        smoke.assert_called_once_with(config)

    def test_opencode_registration_merges_existing_configuration(self) -> None:
        config = _config("opencode")
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            config_dir = home / ".config" / "opencode"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "opencode.json"
            config_path.write_text(
                json.dumps({"theme": "system", "mcp": {"existing": {"enabled": True}}}),
                encoding="utf-8",
            )
            with (
                patch.object(browser_automation_steps, "_tool_available", return_value=True),
                patch.object(browser_automation_steps, "_user_home", return_value=str(home)),
                patch.object(browser_automation_steps, "_chown_path"),
            ):
                browser_automation_steps._configure_opencode(config)

            value = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(value["theme"], "system")
            self.assertTrue(value["mcp"]["existing"]["enabled"])
            self.assertEqual(
                value["mcp"]["playwright"],
                {
                    "type": "local",
                    "command": [browser_automation_steps.PLAYWRIGHT_MCP_WRAPPER],
                    "enabled": True,
                },
            )
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)

    def test_managed_mcp_launcher_is_headless_and_isolated(self) -> None:
        content = browser_automation_steps._MCP_WRAPPER_CONTENT

        self.assertIn("--headless", content)
        self.assertIn("--isolated", content)
        self.assertNotIn("--no-sandbox", content)


class BrowserAutomationDoctorTests(unittest.TestCase):
    def test_doctor_checks_registration_and_local_browser_smoke_test(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "home"
            home.mkdir()
            mcp_wrapper = root / "playwright-mcp"
            doctor_wrapper = root / "playwright-doctor"
            mcp_wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            doctor_wrapper.write_text("#!/bin/sh\necho browser-ready\n", encoding="utf-8")
            os.chmod(mcp_wrapper, 0o755)
            os.chmod(doctor_wrapper, 0o755)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            (codex_dir / "config.toml").write_text(
                "[mcp_servers.playwright]\n"
                f'command = "{mcp_wrapper}"\n',
                encoding="utf-8",
            )

            def tool_path(tool: str, _home: str) -> str | None:
                return "/tmp/codex" if tool == "codex" else None

            with (
                patch.object(agent_cli, "_BROWSER_MCP_WRAPPER", str(mcp_wrapper)),
                patch.object(agent_cli, "_BROWSER_DOCTOR_WRAPPER", str(doctor_wrapper)),
                patch.object(agent_cli, "_tool_path", side_effect=tool_path),
            ):
                result = agent_cli.inspect_browser_automation(str(home))

        self.assertTrue(result["installed"])
        self.assertTrue(result["smoke_test"])
        self.assertEqual(result["registrations"], {"codex": True})
        self.assertTrue(result["healthy"])


if __name__ == "__main__":
    unittest.main()
