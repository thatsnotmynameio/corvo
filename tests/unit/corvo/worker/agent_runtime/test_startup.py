"""The agent worker's start checks its isolation and sweeps what earlier
sessions left, and its SIGTERM hook ends the in-flight sessions (KTD10,
KTD19), with the wrapper, the cgroup tree and the mounts replaced."""

import asyncio
import json
import logging
import shutil
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from corvo.agents.session import sandbox_settings
from corvo.settings import Settings
from corvo.worker.agent_runtime import sessions, startup
from corvo.worker.agent_runtime.cgroups import Cgroup
from corvo.worker.agent_runtime.sandbox import PLACEHOLDER
from corvo.worker.agent_runtime.start_check import check

from .fake_cgroups import Tree

DELEGATING = (
    "35 24 0:30 / /sys/fs/cgroup rw,nosuid,nodev,noexec,relatime shared:9 - "
    "cgroup2 cgroup2 rw,nsdelegate,memory_recursiveprot\n"
)
NOT_DELEGATING = DELEGATING.replace("nsdelegate,", "")

# What check.py prints in a sandbox that isolates as it should.
ISOLATED: dict[str, Any] = {
    "self": "2",
    "processes": {"1": "/usr/bin/bwrap", "2": "/usr/local/bin/python3"},
    "environ": {
        "1": ["ANTHROPIC_API_KEY", "HOME", "PATH"],
        "2": ["ANTHROPIC_API_KEY", "HOME", "PATH", "PWD"],
    },
    "sys": False,
    "present": [],
    "nested": {"returncode": 0, "stderr": ""},
    "socat": "/usr/bin/socat",
}


class Wrapper:
    """corvo-agent-sandbox in place: it records how it was called, and
    replies as it is told, by default with ISOLATED."""

    def __init__(self, directory: Path) -> None:
        self.path = directory / "corvo-agent-sandbox"
        self.path.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys, time\n"
            "from pathlib import Path\n"
            "here = Path(__file__).parent\n"
            "call = {'argv': sys.argv[1:], 'env': dict(os.environ),\n"
            "        'pid': os.getpid()}\n"
            "(here / 'call.json').write_text(json.dumps(call))\n"
            "reply = json.loads((here / 'reply.json').read_text())\n"
            "time.sleep(reply['sleep'])\n"
            "sys.stdout.write(reply['stdout'])\n"
            "sys.stderr.write(reply['stderr'])\n"
            "sys.exit(reply['code'])\n"
        )
        self.path.chmod(0o755)
        self.reply(ISOLATED)

    def reply(
        self, report: object, code: int = 0, stderr: str = "", sleep: float = 0
    ) -> None:
        stdout = report if isinstance(report, str) else json.dumps(report)
        reply = {"stdout": stdout, "stderr": stderr, "code": code, "sleep": sleep}
        (self.path.parent / "reply.json").write_text(json.dumps(reply))

    @property
    def call(self) -> dict[str, Any]:
        called: dict[str, Any] = json.loads(
            (self.path.parent / "call.json").read_text()
        )
        return called


@pytest.fixture
async def proxy() -> AsyncIterator[str]:
    """A listening stand-in for the credential proxy."""

    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):  # type: ignore[no-untyped-def]
        writer.close()

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
def mountinfo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mountinfo"
    path.write_text(DELEGATING)
    monkeypatch.setattr(startup, "MOUNTINFO", path)
    return path


@pytest.fixture
def wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Wrapper:
    (tmp_path / "wrapper").mkdir()
    replaced = Wrapper(tmp_path / "wrapper")
    monkeypatch.setattr(sessions, "WRAPPER", replaced.path)
    return replaced


@pytest.fixture
def settings(
    tree: Tree, proxy: str, mountinfo: Path, wrapper: Wrapper, tmp_path: Path
) -> Settings:
    return Settings(
        agent_root=str(tmp_path / "root"),
        agent_proxy_url=proxy,
        agent_cgroup_root=str(tree.root),
        agent_engine="/opt/corvo/engine/claude",
    )


async def refusal(settings: Settings, environ: dict[str, str] | None = None) -> str:
    with pytest.raises(startup.Disabled) as refused:
        await startup.prepare(settings, {} if environ is None else environ)
    return str(refused.value)


async def test_a_worker_that_isolates_passes_every_check(
    settings: Settings, tree: Tree
) -> None:
    await startup.prepare(settings, {})

    # The delegation's probe cgroup and the sandbox check's, each removed.
    assert tree.events == ["create", "remove", "create", "kill", "remove"]


async def test_the_sandbox_check_runs_as_a_session_in_its_own_cgroup(
    settings: Settings, wrapper: Wrapper, tree: Tree
) -> None:
    await startup.prepare(settings, {"CORVO_HATCHET_TOKEN": "secret"})

    call = wrapper.call
    assert call["argv"][:3] == [
        "--setting-sources=",
        "--settings",
        json.dumps({"sandbox": sandbox_settings()}),
    ]
    argv = call["argv"]
    absent = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--absent"]
    assert absent == [sys.prefix, sessions.__file__, settings.agent_root]
    env = call["env"]
    assert env["CORVO_SANDBOX_ENGINE"] == check.__file__
    assert env["CORVO_SANDBOX_CGROUP"] == str(tree.path)
    assert env["CORVO_SANDBOX_WORKDIR"] == ""
    assert env["ANTHROPIC_API_KEY"] == PLACEHOLDER
    # The worker's own environment too, as the SDK passes it, which the
    # wrapper must keep out of the sandbox.
    assert env["CORVO_HATCHET_TOKEN"] == "secret"


@pytest.mark.parametrize(
    ("unset", "named"),
    [
        ("agent_root", "CORVO_AGENT_ROOT"),
        ("agent_proxy_url", "CORVO_AGENT_PROXY_URL"),
        ("agent_engine", "CORVO_AGENT_ENGINE"),
    ],
)
async def test_an_unset_setting_is_refused(
    settings: Settings, tree: Tree, unset: str, named: str
) -> None:
    refused = await refusal(settings.model_copy(update={unset: ""}))

    assert refused == f"settings: {named} is not set"
    assert tree.events == []


@pytest.mark.parametrize(
    "name", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"]
)
async def test_a_credential_in_the_environment_is_refused(
    settings: Settings, tree: Tree, name: str
) -> None:
    refused = await refusal(settings, {name: "sk-ant-secret"})

    assert refused == f"credential in environment: {name}"
    assert "sk-ant-secret" not in refused
    assert tree.events == []


@pytest.mark.parametrize(
    ("mounts", "reason"),
    [
        (NOT_DELEGATING, "the cgroup2 mount lacks nsdelegate"),
        ("", "no cgroup2 mount"),
    ],
)
async def test_a_cgroup_mount_that_does_not_delegate_is_refused(
    settings: Settings, mountinfo: Path, tree: Tree, mounts: str, reason: str
) -> None:
    mountinfo.write_text(mounts)

    refused = await refusal(settings)

    assert refused == f"cgroup delegation: {reason}"
    assert tree.events == []


async def test_a_cgroup_that_cannot_be_made_is_refused(
    settings: Settings, tmp_path: Path
) -> None:
    refused = await refusal(
        settings.model_copy(update={"agent_cgroup_root": str(tmp_path / "none")})
    )

    assert refused.startswith("cgroup delegation: cannot make a run's cgroup: ")


async def test_bubblewrap_that_cannot_start_is_refused(
    settings: Settings, wrapper: Wrapper, tree: Tree
) -> None:
    wrapper.reply(
        "",
        code=1,
        stderr="bwrap: No permissions to create a new namespace\n",
    )

    refused = await refusal(settings)

    assert refused == "bubblewrap: bwrap: No permissions to create a new namespace"
    assert tree.events[-2:] == ["kill", "remove"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"sys": True}, "the sandbox shows /sys"),
        ({"present": ["/app/.venv"]}, "the sandbox shows /app/.venv"),
        (
            {"processes": {**ISOLATED["processes"], "7": "/app/.venv/bin/python"}},
            "the sandbox shows a process not its own: /app/.venv/bin/python",
        ),
        (
            {"environ": {"1": ["HOME", "CORVO_HATCHET_TOKEN"]}},
            "process 1 holds CORVO_HATCHET_TOKEN",
        ),
        (
            {"environ": {"1": "unreadable: Permission denied"}},
            "process 1's environment is unreadable: Permission denied",
        ),
        ("not a report", "the check printed no report"),
    ],
)
async def test_a_sandbox_that_does_not_isolate_is_refused(
    settings: Settings, wrapper: Wrapper, change: object, reason: str
) -> None:
    wrapper.reply(ISOLATED | change if isinstance(change, dict) else change)

    assert await refusal(settings) == f"bubblewrap: {reason}"


async def test_a_check_past_the_bound_is_killed_and_refused(
    settings: Settings,
    wrapper: Wrapper,
    tree: Tree,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup, "PREPARE_TIMEOUT", 1)
    wrapper.reply(ISOLATED, sleep=60)

    refused = await refusal(settings)

    assert refused == "bubblewrap: not done within 1 seconds"
    assert tree.events[-2:] == ["kill", "remove"]
    stat = Path(f"/proc/{wrapper.call['pid']}/stat")
    async with asyncio.timeout(5):
        while stat.exists() and stat.read_text().split()[2] != "Z":
            await asyncio.sleep(0.1)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            {"nested": {"returncode": 1, "stderr": "bwrap: Creating new namespace"}},
            "a nested bubblewrap failed: bwrap: Creating new namespace",
        ),
        ({"socat": None}, "socat is missing"),
    ],
)
async def test_a_sandbox_the_sdk_cannot_nest_in_is_refused(
    settings: Settings, wrapper: Wrapper, change: dict[str, Any], reason: str
) -> None:
    wrapper.reply(ISOLATED | change)

    assert await refusal(settings) == f"the SDK's sandbox: {reason}"


async def test_a_proxy_address_without_a_host_is_refused(settings: Settings) -> None:
    refused = await refusal(
        settings.model_copy(update={"agent_proxy_url": "claude-proxy:8080"})
    )

    assert refused == "proxy: 'claude-proxy:8080' names no host"


async def test_a_proxy_that_starts_later_is_retried(
    settings: Settings, unused_tcp_port: int
) -> None:
    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):  # type: ignore[no-untyped-def]
        writer.close()

    async def start_later() -> asyncio.Server:
        await asyncio.sleep(1.5)
        return await asyncio.start_server(accept, "127.0.0.1", unused_tcp_port)

    later = asyncio.create_task(start_later())
    url = f"http://127.0.0.1:{unused_tcp_port}"

    await startup.prepare(settings.model_copy(update={"agent_proxy_url": url}), {})

    server = await later
    server.close()
    await server.wait_closed()


async def test_a_proxy_unreachable_within_the_bound_is_refused(
    settings: Settings, unused_tcp_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(startup, "PREPARE_TIMEOUT", 1.5)
    url = f"http://127.0.0.1:{unused_tcp_port}"

    refused = await refusal(settings.model_copy(update={"agent_proxy_url": url}))

    assert refused.startswith("proxy: not done within 1.5 seconds; last: ")
    assert "ConnectionRefusedError" in refused


@pytest.fixture
def no_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in startup.CREDENTIALS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def leftovers(tree: Tree, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Two runs' cgroups a session left, and the worker's own cgroup."""
    # cgroupfs drops its control files on rmdir; a directory keeps them.
    monkeypatch.setattr(Cgroup, "remove", lambda self: shutil.rmtree(self.path))
    paths = [tree.root / "run-left-1", tree.root / "run-left-2", tree.root / "worker"]
    for path in paths:
        path.mkdir()
        (path / "cgroup.events").write_text("populated 0\nfrozen 0\n")
    return paths


@pytest.mark.usefixtures("no_credential")
def test_the_start_sweeps_the_cgroups_sessions_left(
    settings: Settings,
    leftovers: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(startup, "get_settings", lambda: settings)

    startup.before_start()

    first, second, worker = leftovers
    assert not first.exists()
    assert not second.exists()
    assert worker.exists()
    assert "agents: swept 2 leftover cgroups: run-left-1, run-left-2" in (
        caplog.messages
    )


@pytest.mark.usefixtures("no_credential")
def test_a_leftover_the_sweep_cannot_remove_stays(
    settings: Settings,
    leftovers: list[Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    # Without its cgroup.events, as no cgroup is.
    broken = leftovers[0].parent / "run-broken"
    broken.mkdir()
    monkeypatch.setattr(startup, "get_settings", lambda: settings)

    startup.before_start()

    assert broken.exists()
    assert caplog.messages[-2].startswith(
        "agents: run-broken is left: FileNotFoundError"
    )
    assert caplog.messages[-1] == (
        "agents: swept 2 leftover cgroups: run-left-1, run-left-2"
    )


@pytest.mark.usefixtures("no_credential")
def test_a_refused_start_logs_the_part_and_exits(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(startup, "get_settings", lambda: settings)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")

    with pytest.raises(SystemExit) as exited:
        startup.before_start()

    assert exited.value.code == 1
    assert caplog.messages[-1] == (
        "agents refused: credential in environment: ANTHROPIC_API_KEY"
    )


@pytest.fixture
def in_flight(tree: Tree) -> Iterator[list[Path]]:
    """Two sessions' cgroups in flight, one that is not, and one in flight
    that is gone."""
    paths = [tree.root / name for name in ("run-a", "run-b", "run-done")]
    for path in paths:
        path.mkdir()
    sessions.in_flight.update([*paths[:2], tree.root / "run-gone"])
    yield paths
    sessions.in_flight.clear()


def test_the_sigterm_hook_refuses_runs_then_kills_the_in_flight_sessions(
    in_flight: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    kills: list[tuple[str, str | None]] = []
    kill = Cgroup.kill

    def record(self: Cgroup) -> None:
        kills.append((self.path.name, sessions.refusal))
        kill(self)

    monkeypatch.setattr(Cgroup, "kill", record)

    startup.on_sigterm()

    assert sorted(kills) == [
        ("run-a", "worker stopping"),
        ("run-b", "worker stopping"),
        ("run-gone", "worker stopping"),
    ]
    assert sessions.refusal == "worker stopping"
    first, second, done = in_flight
    assert (first / "cgroup.kill").read_text() == "1"
    assert (second / "cgroup.kill").read_text() == "1"
    assert not (done / "cgroup.kill").exists()


def test_the_check_reports_what_the_start_judges(tmp_path: Path) -> None:
    present = tmp_path / "present"
    present.mkdir()

    reported = check.report(["--absent", str(present), "--absent", str(tmp_path / "x")])

    assert set(reported) == set(ISOLATED)
    assert reported["self"] in reported["processes"]
    assert reported["present"] == [str(present)]
    assert isinstance(reported["environ"][reported["self"]], list)
    assert set(reported["nested"]) == {"returncode", "stderr"}


def test_the_check_runs_from_a_directory_of_its_own() -> None:
    # The wrapper binds the engine's directory into the sandbox.
    directory = Path(check.__file__).parent

    assert sorted(path.name for path in directory.glob("*.py")) == [
        "__init__.py",
        "check.py",
    ]
