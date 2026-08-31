"""Tests for explicit agent browser automation provisioning."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from common import browser_automation_steps
from lib import agent_cli
from lib.arg_parser import add_setup_arguments
from lib.config import SetupConfig
from lib.validation import validate_browser_automation_settings
from plugins.common import extend_agent_steps
from plugins.common import get_custom_step_functions


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
        config.install_git_lfs = True
        steps: list[tuple[str, object]] = []

        extend_agent_steps(config, steps)  # type: ignore[arg-type]

        names = [name for name, _function in steps]
        self.assertLess(
            names.index("Copying agent tool configuration"),
            names.index("Installing agent browser automation"),
        )
        self.assertLess(
            names.index("Installing agent browser automation"),
            names.index("Installing Git LFS for agent repositories"),
        )
        self.assertLess(
            names.index("Installing Git LFS for agent repositories"),
            names.index("Cloning agent repositories on target"),
        )

    def test_browser_automation_is_available_to_explicit_custom_steps(self) -> None:
        self.assertIs(
            get_custom_step_functions()["install_browser_automation"],
            browser_automation_steps.install_browser_automation,
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
                value["mcp"][browser_automation_steps.PLAYWRIGHT_MCP_SERVER_NAME],
                {
                    "type": "local",
                    "command": [browser_automation_steps.PLAYWRIGHT_MCP_WRAPPER],
                    "enabled": True,
                    "timeout": 30000,
                },
            )
            self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)

    def test_codex_registration_reconciles_managed_server(self) -> None:
        config = _config("codex")
        successful = SimpleNamespace(returncode=0, stdout="", stderr="")
        with (
            patch.object(browser_automation_steps, "_tool_available", return_value=True),
            patch.object(browser_automation_steps, "_user_home", return_value="/home/agent"),
            patch.object(
                browser_automation_steps,
                "_run_as_login_user",
                return_value=successful,
            ) as run_as_user,
        ):
            browser_automation_steps._configure_codex(config)

        self.assertEqual(run_as_user.call_count, 2)
        remove_command = run_as_user.call_args_list[0].args[2]
        add_command = run_as_user.call_args_list[1].args[2]
        self.assertIn("codex mcp remove infra-tools-playwright", remove_command)
        self.assertIn("codex mcp add infra-tools-playwright", add_command)

    def test_codex_registration_reports_add_failure(self) -> None:
        config = _config("codex")
        successful = SimpleNamespace(returncode=0, stdout="", stderr="")
        failed = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="codex could not update MCP configuration",
        )
        with (
            patch.object(browser_automation_steps, "_tool_available", return_value=True),
            patch.object(browser_automation_steps, "_user_home", return_value="/home/agent"),
            patch.object(
                browser_automation_steps,
                "_run_as_login_user",
                side_effect=[successful, failed],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "could not update MCP"):
                browser_automation_steps._configure_codex(config)

    def test_opencode_jsonc_registration_accepts_comments_and_preserves_values(self) -> None:
        config = _config("opencode")
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            config_dir = home / ".config" / "opencode"
            config_dir.mkdir(parents=True)
            config_path = config_dir / "opencode.jsonc"
            config_path.write_text(
                "{\n"
                "  // Keep this JSONC file supported.\n"
                "  \"theme\": \"https://example.test//path\",\n"
                "  \"mcp\": {\n"
                "    \"existing\": {\"enabled\": true,},\n"
                "  },\n"
                "}\n",
                encoding="utf-8",
            )
            with (
                patch.object(browser_automation_steps, "_tool_available", return_value=True),
                patch.object(browser_automation_steps, "_user_home", return_value=str(home)),
                patch.object(browser_automation_steps, "_chown_path"),
            ):
                browser_automation_steps._configure_opencode(config)

            value = browser_automation_steps._load_opencode_config(str(config_path))
            self.assertEqual(value["theme"], "https://example.test//path")
            self.assertTrue(value["mcp"]["existing"]["enabled"])
            self.assertEqual(
                value["mcp"][browser_automation_steps.PLAYWRIGHT_MCP_SERVER_NAME]["timeout"],
                30000,
            )

    def test_codex_registration_does_not_match_command_in_another_section(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            (codex_dir / "config.toml").write_text(
                f"[mcp_servers.{agent_cli._BROWSER_MCP_SERVER_NAME}]\n"
                "enabled = true\n"
                "[mcp_servers.other]\n"
                f'command = "{agent_cli._BROWSER_MCP_WRAPPER}"\n',
                encoding="utf-8",
            )

            self.assertFalse(agent_cli._codex_browser_registration(str(home)))

    def test_managed_mcp_launcher_is_headless_and_isolated(self) -> None:
        content = browser_automation_steps._MCP_WRAPPER_CONTENT

        self.assertIn("--headless", content)
        self.assertIn("--isolated", content)
        self.assertIn("--caps vision", content)
        self.assertIn('umask 077', content)
        self.assertIn(
            'output_dir="$HOME/.local/state/infra_tools/playwright-mcp"',
            content,
        )
        self.assertIn('--output-dir "$output_dir"', content)
        self.assertIn(
            f"--output-max-size {browser_automation_steps.PLAYWRIGHT_MCP_OUTPUT_MAX_BYTES}",
            content,
        )
        self.assertIn(
            f"--timeout-settle {browser_automation_steps.PLAYWRIGHT_MCP_SETTLE_TIMEOUT_MS}",
            content,
        )
        self.assertNotIn("--no-sandbox", content)
        self.assertIn('PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"', content)

    def test_smoke_test_has_slow_target_budget_and_hard_process_limit(self) -> None:
        self.assertIn(
            f"timeout: {browser_automation_steps.PLAYWRIGHT_SMOKE_ACTION_TIMEOUT_MS}",
            browser_automation_steps._SMOKE_SCRIPT_CONTENT,
        )
        self.assertIn(
            "setDefaultNavigationTimeout",
            browser_automation_steps._SMOKE_SCRIPT_CONTENT,
        )
        self.assertIn(
            "viewport: { width: 640, height: 480 }",
            browser_automation_steps._SMOKE_SCRIPT_CONTENT,
        )
        self.assertIn(
            f"{browser_automation_steps.PLAYWRIGHT_SMOKE_PROCESS_TIMEOUT_SECONDS}s",
            browser_automation_steps._DOCTOR_WRAPPER_CONTENT,
        )

    def test_smoke_test_reports_resource_pressure_on_process_timeout(self) -> None:
        config = _config("opencode")
        timed_out = SimpleNamespace(returncode=124, stdout="", stderr="")
        with (
            patch.object(browser_automation_steps, "_user_home", return_value="/home/agent"),
            patch.object(
                browser_automation_steps,
                "_run_as_login_user",
                return_value=timed_out,
            ) as run_as_user,
        ):
            with self.assertRaisesRegex(RuntimeError, "memory, swap, or storage pressure"):
                browser_automation_steps._run_smoke_test(config)

        self.assertFalse(run_as_user.call_args.kwargs["check"])


class BrowserAutomationDoctorTests(unittest.TestCase):
    def test_agent_doctor_allows_managed_smoke_process_to_finish(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="browser-ready\n", stderr="")
        with (
            patch.object(agent_cli.os.path, "isfile", return_value=True),
            patch.object(agent_cli.os, "access", return_value=True),
            patch.object(
                agent_cli,
                "_browser_launcher_features",
                return_value={
                    "private_evidence": True,
                    "coordinate_input": True,
                    "webgl_settle_delay": True,
                },
            ),
            patch.object(
                agent_cli,
                "_tool_path",
                side_effect=lambda tool, _home: "/tmp/codex" if tool == "codex" else None,
            ),
            patch.object(agent_cli, "_codex_browser_registration", return_value=True),
            patch.object(agent_cli.subprocess, "run", return_value=completed) as run,
        ):
            result = agent_cli.inspect_browser_automation("/home/agent")

        self.assertTrue(result["healthy"])
        self.assertGreater(
            run.call_args.kwargs["timeout"],
            browser_automation_steps.PLAYWRIGHT_SMOKE_PROCESS_TIMEOUT_SECONDS,
        )

    def test_doctor_checks_registration_and_local_browser_smoke_test(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "home"
            home.mkdir()
            mcp_wrapper = root / "playwright-mcp"
            doctor_wrapper = root / "playwright-doctor"
            mcp_wrapper.write_text(
                "#!/bin/sh\n"
                "umask 077\n"
                'output_dir="$HOME/.local/state/infra_tools/playwright-mcp"\n'
                "exec playwright-mcp --caps vision "
                '--output-dir "$output_dir" --timeout-settle 1000\n',
                encoding="utf-8",
            )
            doctor_wrapper.write_text("#!/bin/sh\necho browser-ready\n", encoding="utf-8")
            os.chmod(mcp_wrapper, 0o755)
            os.chmod(doctor_wrapper, 0o755)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            (codex_dir / "config.toml").write_text(
                f"[mcp_servers.{agent_cli._BROWSER_MCP_SERVER_NAME}]\n"
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
        self.assertTrue(result["managed_defaults"])
        self.assertEqual(result["registrations"], {"codex": True})
        self.assertTrue(result["healthy"])

    def test_doctor_rejects_stale_launcher_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            wrapper = Path(temporary_directory) / "playwright-mcp"
            wrapper.write_text(
                "#!/bin/sh\nexec playwright-mcp --headless\n",
                encoding="utf-8",
            )

            features = agent_cli._browser_launcher_features(str(wrapper))

        self.assertEqual(
            features,
            {
                "private_evidence": False,
                "coordinate_input": False,
                "webgl_settle_delay": False,
            },
        )

    def test_doctor_accepts_opencode_jsonc_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory)
            config_dir = home / ".config" / "opencode"
            config_dir.mkdir(parents=True)
            (config_dir / "opencode.jsonc").write_text(
                f'{{"mcp": {{"{agent_cli._BROWSER_MCP_SERVER_NAME}": {{'
                "\"type\": \"local\", "
                f"\"command\": [\"{agent_cli._BROWSER_MCP_WRAPPER}\"], "
                "\"enabled\": true, \"timeout\": 30000,"
                "}}}\n",
                encoding="utf-8",
            )
            with patch.object(agent_cli, "_tool_path", return_value="/tmp/opencode"):
                self.assertTrue(agent_cli._opencode_browser_registration(str(home)))

    def test_capability_only_doctor_does_not_require_default_tools(self) -> None:
        args = argparse.Namespace(
            agent_command="doctor",
            agent_doctor_capabilities=["browser"],
            agent_doctor_tools=None,
            json=True,
        )
        with (
            patch.object(agent_cli, "inspect_agent_tools", return_value=[]) as tools,
            patch.object(
                agent_cli,
                "inspect_browser_automation",
                return_value={"capability": "browser", "healthy": True},
            ),
        ):
            self.assertEqual(agent_cli.run_agent_command(args), 0)
        tools.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
