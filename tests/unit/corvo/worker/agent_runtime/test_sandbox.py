"""corvo-agent-sandbox starts the engine in bubblewrap only for a run that
asked for the SDK's sandbox, and hands it nothing of the worker (KTD20)."""

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from corvo.worker.agent_runtime import sandbox

ENGINE = "/opt/corvo/engine/claude"
SANDBOX = {
    "enabled": True,
    "autoAllowBashIfSandboxed": True,
    "allowUnsandboxedCommands": False,
    "failIfUnavailable": True,
}


def settings_argv(**overrides: Any) -> list[str]:
    """The engine's arguments as the SDK passes them for setting_sources=[]
    and the session's sandbox, with overrides to the sandbox."""
    settings = {"sandbox": {**SANDBOX, **overrides}}
    return [
        "--output-format",
        "stream-json",
        "--setting-sources=",
        "--settings",
        json.dumps(settings),
    ]


def run_env(cgroup: Path, workdir: str = "", writes: str = "0") -> dict[str, str]:
    """What the session piece puts in options.env, over the worker's own."""
    return {
        "CORVO_SANDBOX_CGROUP": str(cgroup),
        "CORVO_SANDBOX_WORKDIR": workdir,
        "CORVO_SANDBOX_WRITES": writes,
        "CORVO_SANDBOX_ENGINE": ENGINE,
        "CORVO_SANDBOX_TMPFS": "104857600",
        "ANTHROPIC_BASE_URL": "http://claude-proxy:8080",
        "CLAUDE_CODE_OAUTH_TOKEN": sandbox.PLACEHOLDER,
        "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
        "CLAUDE_AGENT_SDK_VERSION": "0.2.167",
        "CLAUDE_CODE_SDK_READS_SESSION_STATE": "1",
    }


class Exec(Exception):
    def __init__(self, path: str, args: Sequence[str], env: dict[str, str]) -> None:
        self.path, self.argv, self.env = path, list(args), env


@pytest.fixture
def cgroup(tmp_path: Path) -> Path:
    """A run's cgroup, as far as the wrapper sees one: a cgroup.procs to join."""
    path = tmp_path / "cgroup" / "run-1"
    path.mkdir(parents=True)
    (path / "cgroup.procs").touch()
    return path


def launch(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], argv: Sequence[str]
) -> None:
    """Runs main over the worker's environment plus env, with an exec that
    raises Exec."""

    def execve(path: str, args: Sequence[str], exec_env: dict[str, str]) -> None:
        raise Exec(path, args, exec_env)

    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "argv", ["corvo-agent-sandbox", *argv])
    monkeypatch.setattr(os, "execve", execve)
    sandbox.main()


def start(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], argv: Sequence[str]
) -> Exec:
    """The exec main ends in."""
    with pytest.raises(Exec) as started:
        launch(monkeypatch, env, argv)
    return started.value


def refused(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], argv: Sequence[str]
) -> None:
    """Checks main exits non-zero; an exec raises Exec, which fails the test."""
    with pytest.raises(SystemExit) as exited:
        launch(monkeypatch, env, argv)
    assert exited.value.code != 0


def setenv(args: Sequence[str]) -> dict[str, str]:
    return {
        args[at + 1]: args[at + 2] for at, arg in enumerate(args) if arg == "--setenv"
    }


def writable_binds(args: Sequence[str]) -> list[str]:
    """The destination of each host path bound writable."""
    binds = {"--bind": 2, "--bind-try": 2, "--dev-bind": 2, "--bind-fd": 2}
    return [args[at + binds[arg]] for at, arg in enumerate(args) if arg in binds]


def test_the_engine_runs_in_a_fresh_sandbox(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    started = start(monkeypatch, run_env(cgroup), settings_argv())

    assert started.path == "/usr/bin/bwrap"
    flags = [
        "--unshare-all",
        "--unshare-cgroup",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ]
    assert started.argv[1:7] == flags
    assert not any(arg.startswith("/sys") for arg in started.argv)
    assert started.argv[-6:] == [ENGINE, *settings_argv()]


def test_bubblewrap_starts_with_an_empty_environment(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    started = start(monkeypatch, run_env(cgroup), settings_argv())

    assert started.env == {}


def test_only_the_allowed_variables_enter(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    env = run_env(cgroup) | {
        "ANTHROPIC_API_KEY": "sk-ant-a-real-key",
        "CLAUDE_CODE_SYNC_PLUGIN_INSTALL": "1",
        "CORVO_HATCHET_TOKEN": "the-workers-token",
    }

    started = start(monkeypatch, env, settings_argv())

    assert setenv(started.argv) == {
        "CLAUDE_CODE_OAUTH_TOKEN": "corvo-placeholder",
        "ANTHROPIC_BASE_URL": "http://claude-proxy:8080",
        "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
        "CLAUDE_AGENT_SDK_VERSION": "0.2.167",
        "CLAUDE_CODE_SDK_READS_SESSION_STATE": "1",
        "HOME": "/home/agent",
        "CLAUDE_CONFIG_DIR": "/home/agent/.claude",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
    }


def test_the_isolation_flags_override_the_session(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    env = run_env(cgroup) | {
        "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "0",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "true",
        "HOME": "/home/matheus",
    }

    variables = setenv(start(monkeypatch, env, settings_argv()).argv)

    assert variables["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    assert variables["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert variables["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert variables["HOME"] == "/home/agent"


def test_the_wrapper_joins_its_runs_cgroup(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    start(monkeypatch, run_env(cgroup), settings_argv())

    assert (cgroup / "cgroup.procs").read_text() == str(os.getpid())


def test_the_working_directory_is_bound_read_only_by_descriptor(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "workdirs" / "run-1"
    workdir.mkdir(parents=True)

    args = start(monkeypatch, run_env(cgroup, str(workdir)), settings_argv()).argv

    at = args.index("--ro-bind-fd")
    fd = int(args[at + 1])
    assert args[at + 2] == str(workdir)
    assert os.path.samestat(os.fstat(fd), os.stat(workdir))
    assert os.get_inheritable(fd)
    assert args[args.index("--chdir") + 1] == str(workdir)
    assert writable_binds(args) == []


def test_a_writing_agent_gets_its_working_directory_writable(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "run-1"
    workdir.mkdir()

    args = start(monkeypatch, run_env(cgroup, str(workdir), "1"), settings_argv()).argv

    assert writable_binds(args) == [str(workdir)]
    assert "--ro-bind-fd" not in args


def test_without_a_working_directory_the_engine_starts_at_home(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    args = start(monkeypatch, run_env(cgroup), settings_argv()).argv

    assert args[args.index("--chdir") + 1] == "/home/agent"
    assert writable_binds(args) == []
    assert "--ro-bind-fd" not in args


def test_a_working_directory_swapped_for_a_symlink_is_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, tmp_path: Path
) -> None:
    workdir = tmp_path / "run-1"
    workdir.symlink_to("/proc")

    refused(monkeypatch, run_env(cgroup, str(workdir)), settings_argv())


def test_a_symlink_above_the_working_directory_is_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, tmp_path: Path
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "run-1").mkdir()
    (tmp_path / "workdirs").symlink_to(tmp_path / "real")

    workdir = tmp_path / "workdirs" / "run-1"
    refused(monkeypatch, run_env(cgroup, str(workdir)), settings_argv())


@pytest.mark.parametrize(
    "missing",
    [
        "CORVO_SANDBOX_CGROUP",
        "CORVO_SANDBOX_WORKDIR",
        "CORVO_SANDBOX_WRITES",
        "CORVO_SANDBOX_ENGINE",
        "CORVO_SANDBOX_TMPFS",
    ],
)
def test_a_call_without_its_runs_values_is_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, missing: str
) -> None:
    env = run_env(cgroup)
    del env[missing]
    monkeypatch.delenv(missing, raising=False)

    refused(monkeypatch, env, settings_argv())


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CORVO_SANDBOX_WRITES", "2"),
        ("CORVO_SANDBOX_CGROUP", "cgroups/run-1"),
        ("CORVO_SANDBOX_CGROUP", ""),
        ("CORVO_SANDBOX_ENGINE", "engine/claude"),
        ("CORVO_SANDBOX_ENGINE", ""),
        ("CORVO_SANDBOX_WORKDIR", "workdirs/run-1"),
        ("CORVO_SANDBOX_TMPFS", "0"),
        ("CORVO_SANDBOX_TMPFS", "-1"),
        ("CORVO_SANDBOX_TMPFS", "100M"),
    ],
)
def test_a_call_with_an_invalid_value_is_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, name: str, value: str
) -> None:
    refused(monkeypatch, run_env(cgroup) | {name: value}, settings_argv())


def test_writes_without_a_working_directory_are_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path
) -> None:
    refused(monkeypatch, run_env(cgroup, "", "1"), settings_argv())


@pytest.mark.parametrize(
    "workdir",
    [
        "/",
        "/proc",
        "/proc/1",
        "/dev/shm",
        "/usr/share",
        "/etc",
        "/lib/x86_64-linux-gnu",
        "/opt",
        "/opt/corvo/engine",
        "//proc",
        "/./proc",
    ],
)
def test_a_working_directory_over_the_sandboxs_own_mounts_is_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, workdir: str
) -> None:
    # Bound over /proc it would show the worker's processes and environment,
    # and bound over / or /opt every host path.
    refused(monkeypatch, run_env(cgroup, workdir), settings_argv())


@pytest.mark.parametrize(
    "sources",
    [
        [],
        ["--setting-sources=project"],
        ["--setting-sources=user,project,local"],
        ["--setting-sources", ""],
        ["--setting-sources=", "--setting-sources=project"],
    ],
    ids=["absent", "project", "every source", "separate value", "two"],
)
def test_a_session_that_loads_settings_from_disk_is_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, sources: list[str]
) -> None:
    # The working directory's .claude settings could add hooks or exclude
    # commands from the sandbox.
    argv = [arg for arg in settings_argv() if arg != "--setting-sources="]

    refused(monkeypatch, run_env(cgroup), [*sources, *argv])


def test_a_cgroup_it_cannot_join_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    refused(monkeypatch, run_env(tmp_path / "gone"), settings_argv())


@pytest.mark.parametrize(
    "argv",
    [
        settings_argv(failIfUnavailable=False),
        settings_argv(allowUnsandboxedCommands=True),
        settings_argv(enabled=False),
        settings_argv(excludedCommands=["git"]),
        settings_argv(enableWeakerNestedSandbox=True),
        [
            "--setting-sources=",
            "--settings",
            json.dumps({"sandbox": {"enabled": True}}),
        ],
        ["--setting-sources=", "--settings", json.dumps({"permissions": {}})],
        ["--setting-sources=", "--settings", "/home/agent/settings.json"],
        ["--setting-sources=", "--output-format", "stream-json"],
        [*settings_argv(), "--settings", settings_argv()[-1]],
        [*settings_argv(), '--settings={"sandbox": {"enabled": false}}'],
    ],
    ids=[
        "fail-if-unavailable off",
        "unsandboxed commands allowed",
        "sandbox off",
        "commands excluded",
        "weaker nested sandbox",
        "neither key",
        "no sandbox",
        "a settings file",
        "no settings",
        "two settings",
        "inline settings",
    ],
)
def test_a_session_without_the_sdks_sandbox_is_refused(
    monkeypatch: pytest.MonkeyPatch, cgroup: Path, argv: list[str]
) -> None:
    refused(monkeypatch, run_env(cgroup), argv)

    assert (cgroup / "cgroup.procs").read_text() == ""
