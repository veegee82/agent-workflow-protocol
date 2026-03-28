"""Tests for the terminal.execute built-in tool (sudo-free shell access)."""

import pytest

from awp.runtime.tools import ToolRegistry


@pytest.fixture()
def registry() -> ToolRegistry:
    return ToolRegistry()


class TestTerminalExecuteRegistration:
    """Verify terminal.execute is registered as a built-in tool."""

    def test_registered(self, registry: ToolRegistry):
        assert "terminal.execute" in registry.tool_names

    def test_definition_exists(self, registry: ToolRegistry):
        defs = registry.get_definitions(["terminal.execute"])
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "terminal.execute"

    def test_definition_has_command_param(self, registry: ToolRegistry):
        defs = registry.get_definitions(["terminal.execute"])
        params = defs[0]["function"]["parameters"]
        assert "command" in params["properties"]
        assert "command" in params["required"]

    def test_glob_pattern_match(self, registry: ToolRegistry):
        defs = registry.get_definitions(["terminal.*"])
        names = [d["function"]["name"] for d in defs]
        assert "terminal.execute" in names


class TestTerminalExecuteHappyPath:
    """Normal commands should work identically to shell.execute."""

    def test_echo(self, registry: ToolRegistry):
        result = registry.call("terminal.execute", {"command": "echo hello"})
        assert result["ok"] is True
        assert "hello" in result["data"]["stdout"]
        assert result["data"]["returncode"] == 0

    def test_ls(self, registry: ToolRegistry):
        result = registry.call("terminal.execute", {"command": "ls /"})
        assert result["ok"] is True
        assert result["data"]["returncode"] == 0

    def test_pipe(self, registry: ToolRegistry):
        result = registry.call(
            "terminal.execute", {"command": "echo 'foo bar baz' | wc -w"}
        )
        assert result["ok"] is True
        assert "3" in result["data"]["stdout"]

    def test_env_variable(self, registry: ToolRegistry):
        result = registry.call(
            "terminal.execute", {"command": "MY_VAR=hello && echo $MY_VAR"}
        )
        assert result["ok"] is True

    def test_cwd(self, registry: ToolRegistry, tmp_path):
        result = registry.call(
            "terminal.execute", {"command": "pwd", "cwd": str(tmp_path)}
        )
        assert result["ok"] is True
        assert str(tmp_path) in result["data"]["stdout"]

    def test_timeout_cap(self, registry: ToolRegistry):
        """Timeout should be capped at 120s."""
        result = registry.call(
            "terminal.execute", {"command": "echo fast", "timeout": 999}
        )
        assert result["ok"] is True

    def test_timeout_triggers(self, registry: ToolRegistry):
        result = registry.call(
            "terminal.execute", {"command": "sleep 10", "timeout": 1}
        )
        assert result["ok"] is False
        assert result["status"] == 408

    def test_nonzero_exit(self, registry: ToolRegistry):
        result = registry.call("terminal.execute", {"command": "exit 42"})
        assert result["ok"] is True
        assert result["data"]["returncode"] == 42

    def test_stderr_captured(self, registry: ToolRegistry):
        result = registry.call(
            "terminal.execute", {"command": "echo err >&2"}
        )
        assert result["ok"] is True
        assert "err" in result["data"]["stderr"]


class TestTerminalExecuteSudoBlocking:
    """sudo and privilege-escalation commands must be rejected with 403."""

    @pytest.mark.parametrize(
        "command",
        [
            "sudo ls",
            "sudo -u root ls",
            "sudo rm -rf /",
            "/usr/bin/sudo ls",
            "/bin/sudo ls",
            "env sudo ls",
            "command sudo ls",
            "pkexec ls",
            "doas ls",
            # Chained commands with sudo
            "echo hi && sudo rm -rf /",
            "echo hi; sudo ls",
            "echo hi | sudo tee /etc/passwd",
            "ls || sudo reboot",
            # Backtick subshell
            "echo `sudo whoami`",
            # Multi-line
            "echo hi\nsudo ls",
        ],
    )
    def test_sudo_blocked(self, registry: ToolRegistry, command: str):
        result = registry.call("terminal.execute", {"command": command})
        assert result["ok"] is False
        assert result["status"] == 403
        assert "sudo" in result["error"].lower() or "privilege" in result["error"].lower()

    @pytest.mark.parametrize(
        "command",
        [
            # The word "sudo" inside strings or variable names should NOT trigger
            "echo 'this is not sudo'",
            "echo sudo_config_file",
            "cat /etc/sudoers",  # reading about sudo, not invoking it
            "grep sudo /var/log/auth.log",
            "echo pseudonym",
        ],
    )
    def test_sudo_false_positive_avoided(self, registry: ToolRegistry, command: str):
        """Commands that mention 'sudo' but don't invoke it should be allowed."""
        result = registry.call("terminal.execute", {"command": command})
        assert result["ok"] is True


class TestTerminalVsShellCoexistence:
    """Both tools exist and work independently."""

    def test_both_registered(self, registry: ToolRegistry):
        assert "shell.execute" in registry.tool_names
        assert "terminal.execute" in registry.tool_names

    def test_shell_allows_sudo_syntax(self, registry: ToolRegistry):
        """shell.execute has no sudo blocking (command will fail without sudo, but won't 403)."""
        result = registry.call("shell.execute", {"command": "sudo echo test"})
        # It might fail (no sudo available in test env), but should NOT be 403
        assert result["status"] != 403

    def test_terminal_blocks_sudo(self, registry: ToolRegistry):
        result = registry.call("terminal.execute", {"command": "sudo echo test"})
        assert result["ok"] is False
        assert result["status"] == 403


class TestTerminalSecurityIntegration:
    """Verify terminal.execute respects the existing security system."""

    def test_access_control_denies(self, registry: ToolRegistry):
        """If access control denies terminal.execute, it should return 403."""
        from awp.runtime.security import AccessController, SecurityContext

        ac = AccessController(
            default_policy="allow",
            rules=[{"agent": "test_agent", "deny_tools": ["terminal.execute"]}],
        )
        ctx = SecurityContext(access_controller=ac)
        registry.set_security_context(ctx)
        registry._current_agent_id = "test_agent"

        result = registry.call("terminal.execute", {"command": "echo hello"})
        assert result["ok"] is False
        assert result["status"] == 403
        assert "Access denied" in result["error"]

    def test_access_control_allows(self, registry: ToolRegistry):
        """If access control allows terminal.execute, it should work."""
        from awp.runtime.security import AccessController, SecurityContext

        ac = AccessController(default_policy="allow")
        ctx = SecurityContext(access_controller=ac)
        registry.set_security_context(ctx)
        registry._current_agent_id = "test_agent"

        result = registry.call("terminal.execute", {"command": "echo hello"})
        assert result["ok"] is True

    def test_deny_shell_allow_terminal(self, registry: ToolRegistry):
        """An agent denied shell.execute can still use terminal.execute."""
        from awp.runtime.security import AccessController, SecurityContext

        ac = AccessController(
            default_policy="allow",
            rules=[{"agent": "safe_agent", "deny_tools": ["shell.execute"]}],
        )
        ctx = SecurityContext(access_controller=ac)
        registry.set_security_context(ctx)
        registry._current_agent_id = "safe_agent"

        shell_result = registry.call("shell.execute", {"command": "echo hi"})
        assert shell_result["ok"] is False
        assert shell_result["status"] == 403

        term_result = registry.call("terminal.execute", {"command": "echo hi"})
        assert term_result["ok"] is True


class TestContainsSudoHelper:
    """Unit tests for the static _contains_sudo method."""

    def test_plain_sudo(self):
        assert ToolRegistry._contains_sudo("sudo ls") is True

    def test_no_sudo(self):
        assert ToolRegistry._contains_sudo("ls -la") is False

    def test_sudo_in_middle(self):
        assert ToolRegistry._contains_sudo("echo hi && sudo rm") is True

    def test_absolute_path_sudo(self):
        assert ToolRegistry._contains_sudo("/usr/bin/sudo cat /etc/shadow") is True

    def test_env_sudo(self):
        assert ToolRegistry._contains_sudo("env sudo ls") is True

    def test_pkexec(self):
        assert ToolRegistry._contains_sudo("pkexec ls") is True

    def test_doas(self):
        assert ToolRegistry._contains_sudo("doas ls") is True

    def test_sudo_as_substring(self):
        """'pseudocode' contains 'sudo' but should not match."""
        assert ToolRegistry._contains_sudo("echo pseudocode") is False

    def test_sudoers_file(self):
        assert ToolRegistry._contains_sudo("cat /etc/sudoers") is False

    def test_empty_string(self):
        assert ToolRegistry._contains_sudo("") is False
