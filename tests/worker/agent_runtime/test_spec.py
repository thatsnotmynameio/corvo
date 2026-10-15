from pathlib import Path

import pytest
from docker.types import Mount
from hatchet_sdk import V1TaskStatus

from corvo.agents.envelope import ProbeReport
from corvo.worker.agent_runtime import spec
from corvo.worker.agent_runtime.spec import (
    Credential,
    InvalidWorkdir,
    Run,
    check_workdir,
    container_spec,
    deployment_label,
    egress_open,
    probe_problems,
    session_budget,
    sweep_decision,
)
from corvo.worker.defaults import (
    AGENT_DEADLINE_MARGIN,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_MEMORY,
    AGENT_NANO_CPUS,
    AGENT_PIDS_LIMIT,
)

RUN = Run(
    deployment="tenant@http://hatchet",
    run_id="run-1",
    task_run_id="task-1",
    attempt=0,
    agent="tone",
)

ISOLATION = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    "HOME": "/home/agent",
    "CLAUDE_CONFIG_DIR": "/home/agent/.claude",
}


def test_the_spec_hardens_and_limits_the_container() -> None:
    built = container_spec(
        image="corvo-agent", run=RUN, command=["run"], run_dir=Path("/r")
    )

    assert built["image"] == "corvo-agent"
    assert built["command"] == ["run"]
    assert built["cap_drop"] == ["ALL"]
    assert built["security_opt"] == ["no-new-privileges"]
    assert built["read_only"] is True
    assert built["init"] is True
    assert built["tmpfs"] == {
        "/tmp": "rw,noexec,nosuid,nodev,size=100m",
        "/home/agent": "rw,noexec,nosuid,nodev,size=500m",
    }
    assert built["mem_limit"] == AGENT_MEMORY
    assert built["memswap_limit"] == AGENT_MEMORY
    assert built["nano_cpus"] == AGENT_NANO_CPUS
    assert built["pids_limit"] == AGENT_PIDS_LIMIT


def test_the_spec_names_and_labels_the_run() -> None:
    built = container_spec(
        image="corvo-agent", run=RUN, command=["run"], run_dir=Path("/r")
    )

    assert built["name"] == "corvo-agent-task-1-0"
    assert built["labels"] == {
        "corvo.managed": "true",
        "corvo.deployment": "tenant@http://hatchet",
        "corvo.run_id": "run-1",
        "corvo.task_run_id": "task-1",
        "corvo.attempt": "0",
        "corvo.agent": "tone",
    }


def test_the_spec_mounts_the_run_directory_and_a_read_only_workdir() -> None:
    built = container_spec(
        image="corvo-agent",
        run=RUN,
        command=["run"],
        run_dir=Path("/root/runs/task-1-0"),
        workdir=Path("/root/workdirs/repo"),
    )

    assert built["mounts"] == [
        Mount("/corvo/run", "/root/runs/task-1-0", type="bind", read_only=False),
        Mount("/workspace", "/root/workdirs/repo", type="bind", read_only=True),
    ]


def test_an_agent_that_writes_gets_a_writable_workdir() -> None:
    built = container_spec(
        image="corvo-agent",
        run=RUN,
        command=["run"],
        run_dir=Path("/r"),
        workdir=Path("/w"),
        writes_workdir=True,
    )

    assert Mount("/workspace", "/w", type="bind", read_only=False) in built["mounts"]


def test_a_run_without_a_workdir_mounts_no_workspace() -> None:
    built = container_spec(
        image="corvo-agent", run=RUN, command=["run"], run_dir=Path("/r")
    )

    assert [mount["Target"] for mount in built["mounts"]] == ["/corvo/run"]


def test_without_a_credential_the_spec_carries_only_the_isolation() -> None:
    built = container_spec(
        image="corvo-agent", run=RUN, command=["probe"], run_dir=Path("/r")
    )

    assert built["environment"] == ISOLATION


@pytest.mark.parametrize(
    ("kind", "variable"),
    [("api_key", "ANTHROPIC_API_KEY"), ("oauth_token", "CLAUDE_CODE_OAUTH_TOKEN")],
)
def test_the_credential_reaches_the_container_under_its_one_name(
    kind: spec.CredentialKind, variable: str
) -> None:
    built = container_spec(
        image="corvo-agent",
        run=RUN,
        command=["run"],
        run_dir=Path("/r"),
        credential=Credential(kind=kind, value="secret"),
    )

    assert built["environment"] == {**ISOLATION, variable: "secret"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "workdirs" / "repo").mkdir(parents=True)
    (tmp_path / "runs").mkdir()
    return tmp_path


def test_a_directory_below_workdirs_is_accepted(root: Path) -> None:
    assert check_workdir(root, root / "workdirs" / "repo") == root / "workdirs" / "repo"


def test_a_link_inside_workdirs_resolves_to_its_target(root: Path) -> None:
    (root / "workdirs" / "link").symlink_to(root / "workdirs" / "repo")

    accepted = check_workdir(root, root / "workdirs" / "link")

    assert accepted == root / "workdirs" / "repo"


@pytest.mark.parametrize(
    "workdir",
    [
        "workdirs",
        "runs",
        "workdirs/../runs",
        "workdirs/missing",
        "workdirs/outside",
        "workdirs/file",
    ],
)
def test_a_directory_not_strictly_below_workdirs_is_refused(
    root: Path, tmp_path_factory: pytest.TempPathFactory, workdir: str
) -> None:
    (root / "workdirs" / "outside").symlink_to(tmp_path_factory.mktemp("outside"))
    (root / "workdirs" / "file").touch()

    with pytest.raises(InvalidWorkdir):
        check_workdir(root, root / workdir)


def test_the_deployment_is_the_tenant_at_the_server() -> None:
    assert (
        deployment_label("t-1", "http://localhost:8080") == "t-1@http://localhost:8080"
    )


@pytest.mark.parametrize(
    "status", [V1TaskStatus.COMPLETED, V1TaskStatus.FAILED, V1TaskStatus.CANCELLED]
)
def test_the_sweep_removes_a_container_whose_run_ended(status: V1TaskStatus) -> None:
    assert sweep_decision(status) == "remove"


@pytest.mark.parametrize("status", [V1TaskStatus.QUEUED, V1TaskStatus.RUNNING])
def test_the_sweep_keeps_a_container_whose_run_goes_on(status: V1TaskStatus) -> None:
    assert sweep_decision(status) == "keep"


@pytest.mark.parametrize("lookup", ["not_found", "timed_out"])
def test_the_sweep_warns_of_a_run_it_could_not_read(lookup: spec.Lookup) -> None:
    assert sweep_decision(lookup) == "warn"


def test_the_budget_ends_the_margin_before_hatchets_timeout() -> None:
    whole = (AGENT_EXECUTION_TIMEOUT - AGENT_DEADLINE_MARGIN).total_seconds()

    assert session_budget(elapsed=0) == whole
    assert session_budget(elapsed=12.5) == whole - 12.5
    assert session_budget(elapsed=0) < AGENT_EXECUTION_TIMEOUT.total_seconds()


def report(**changes: object) -> ProbeReport:
    """What the probe reads in a container built by the spec."""
    fields: dict[str, object] = {
        "fingerprint": "f",
        "memory_max": str(AGENT_MEMORY),
        "cpu_max": "100000 100000",
        "pids_max": str(AGENT_PIDS_LIMIT),
        "cap_eff": "0000000000000000",
        "env_names": sorted([*ISOLATION, "PATH"]),
        "root_read_only": True,
        "mounts": {
            "/tmp": ["rw", "nosuid", "nodev", "noexec", "relatime", "size=102400k"],
            "/home/agent": [
                "rw",
                "nosuid",
                "nodev",
                "noexec",
                "relatime",
                "size=512000k",
            ],
        },
        "gateway": "10.0.2.2",
        "gateway_reachable": False,
        "metadata_reachable": False,
    }
    return ProbeReport.model_validate(fields | changes)


def test_a_report_that_matches_the_spec_has_no_problem() -> None:
    assert probe_problems(report(), fingerprint="f") == []


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"memory_max": "max"}, f"memory.max is 'max', not '{AGENT_MEMORY}'"),
        ({"cpu_max": "max 100000"}, "cpu.max is 'max 100000', not '100000 100000'"),
        ({"pids_max": "max"}, f"pids.max is 'max', not '{AGENT_PIDS_LIMIT}'"),
        (
            {"cap_eff": "00000000a80425fb"},
            "the effective capabilities are 00000000a80425fb, not none",
        ),
        ({"root_read_only": False}, "the root filesystem is writable"),
        (
            {"mounts": {"/tmp": ["rw", "size=102400k"], "/home/agent": []}},
            "/tmp lacks noexec, nosuid, nodev",
        ),
        (
            {"env_names": ["HOME", "PATH"]},
            "the environment lacks CLAUDE_CODE_DISABLE_AUTO_MEMORY",
        ),
        (
            {"env_names": sorted([*ISOLATION, "ANTHROPIC_API_KEY"])},
            "the environment holds ANTHROPIC_API_KEY",
        ),
    ],
)
def test_a_report_that_differs_is_named(
    changes: dict[str, object], problem: str
) -> None:
    assert problem in probe_problems(report(**changes), fingerprint="f")


def test_a_mount_of_another_size_is_named() -> None:
    mounts = report().mounts | {"/home/agent": ["rw", "noexec", "nosuid", "nodev"]}

    found = probe_problems(report(mounts=mounts), fingerprint="f")

    assert found == ["/home/agent is not size=512000k"]


def test_a_stale_image_is_named() -> None:
    found = probe_problems(report(fingerprint="old"), fingerprint="new")

    assert found == ["the image's fingerprint differs from the worker's: rebuild it"]


@pytest.mark.parametrize(
    ("gateway", "metadata", "open"),
    [(False, False, False), (True, False, True), (None, True, True)],
)
def test_egress_is_open_when_the_gateway_or_the_metadata_answers(
    gateway: bool | None, metadata: bool, open: bool
) -> None:
    probed = report(gateway_reachable=gateway, metadata_reachable=metadata)

    assert egress_open(probed) is open
