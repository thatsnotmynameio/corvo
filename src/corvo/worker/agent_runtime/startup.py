"""The worker's preparation of agents, before it serves any task (KTD10).

When agents are configured, prepare checks within 45 seconds that the
agent image is in the agents' Podman, runs corvo-agent probe in a container
built by the same spec as every run, compares the probe's report with that
spec and with the worker's own fingerprint, and sweeps the containers of
this deployment whose run has ended. Any failure disables agents, with the
reason logged, until the worker restarts: every agent run then fails at
once with that reason, and every other task keeps working. The probe is
also the cgroup check: on cgroup v2, a limit whose controller the host
does not delegate keeps the container from starting.

install_sigterm_hook removes the containers of the worker's in-flight agent
runs when it gets SIGTERM, before Hatchet's graceful wait (KTD19). Their
tasks then fail on a missing envelope while the worker still answers, so
the engine records a failure instead of re-queuing them later.
"""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import FrameType
from uuid import uuid4

from docker import DockerClient
from docker.errors import ImageNotFound
from hatchet_sdk import Hatchet, V1TaskStatus
from hatchet_sdk.clients.rest.api.workflow_runs_api import WorkflowRunsApi
from hatchet_sdk.clients.rest.exceptions import NotFoundException
from pydantic import ValidationError

from corvo.agents.envelope import ProbeReport
from corvo.agents.fingerprint import fingerprint
from corvo.settings import Settings
from corvo.worker.agent_runtime import containers
from corvo.worker.agent_runtime.containers import (
    CLEANUP_TIMEOUT,
    NOT_CONFIGURED,
    Calls,
    Runtime,
    UntrustedFile,
    make_run_dir,
    read_untrusted,
    remove,
    remove_in_flight,
    remove_run,
    shielded,
)
from corvo.worker.agent_runtime.spec import (
    MANAGED,
    Credential,
    Lookup,
    container_spec,
    egress_open,
    probe_problems,
    sweep_decision,
)

logger = logging.getLogger(__name__)

PREPARE_TIMEOUT = 45
SWEEP_TIMEOUT = 20
# Each run's status is read once within it: the SDK's own get_status
# retries a 404 five times, some 15 seconds a container.
LOOKUP_TIMEOUT = 5

# A run's status, read from Hatchet. Raises NotFoundException when Hatchet
# has no such run.
type StatusOf = Callable[[str], Awaitable[V1TaskStatus]]


class Disabled(Exception):
    """Why agents cannot run on this worker."""


def hatchet_status(hatchet: Hatchet) -> StatusOf:
    """Reads a workflow run's status through Hatchet's REST client, once."""

    def get(run_id: str) -> V1TaskStatus:
        with hatchet.runs.client() as api:
            return WorkflowRunsApi(api).v1_workflow_run_get_status(
                run_id, _request_timeout=LOOKUP_TIMEOUT + 1
            )

    async def status_of(run_id: str) -> V1TaskStatus:
        return await asyncio.to_thread(get, run_id)

    return status_of


async def lookup(status_of: StatusOf, run_id: str) -> Lookup:
    try:
        async with asyncio.timeout(LOOKUP_TIMEOUT):
            return await status_of(run_id)
    except NotFoundException:
        return "not_found"
    except TimeoutError:
        return "timed_out"


async def sweep(client: DockerClient, deployment: str, status_of: StatusOf) -> None:
    """Removes the containers of this deployment whose run has ended (KTD11).

    The probe's containers carry no run, and are the probe's own to remove.
    """
    found = await asyncio.to_thread(
        client.containers.list,
        all=True,
        filters={"label": [MANAGED, f"corvo.deployment={deployment}"]},
    )
    runs = [container for container in found if "corvo.run_id" in container.labels]
    lookups = await asyncio.gather(
        *(lookup(status_of, container.labels["corvo.run_id"]) for container in runs)
    )
    for container, looked_up in zip(runs, lookups, strict=True):
        run_id = container.labels["corvo.run_id"]
        match sweep_decision(looked_up):
            case "remove":
                await asyncio.to_thread(remove, container)
                logger.info("removed the container of ended run %s", run_id)
            case "warn":
                status = "was not found" if looked_up == "not_found" else "timed out"
                logger.warning(
                    "kept the container %s: the status of its run %s %s",
                    container.name,
                    run_id,
                    status,
                )
            case "keep":
                pass


async def probe(client: DockerClient, settings: Settings, deployment: str) -> None:
    """Runs corvo-agent probe in the spec's container, with no credential and
    no working directory, and raises Disabled when its report differs from
    the spec or from the worker's fingerprint."""
    probe_id = uuid4().hex
    run_dir = Path(settings.agent_root) / "runs" / f"probe-{probe_id}"
    make_run_dir(run_dir)
    label = f"corvo.probe={probe_id}"
    spec = container_spec(
        image=settings.agent_image,
        name=f"corvo-agent-probe-{probe_id}",
        labels={
            "corvo.managed": "true",
            "corvo.deployment": deployment,
            "corvo.probe": probe_id,
        },
        command=["probe"],
        run_dir=run_dir,
    )
    calls = Calls()
    try:
        container = await calls(client.containers.create, **spec)
        await calls(container.start)
        exit_code = (await asyncio.to_thread(container.wait))["StatusCode"]
        if exit_code != 0:
            raise Disabled(f"the probe exited with {exit_code}")
        try:
            raw = read_untrusted(run_dir / "probe.json")
            report = ProbeReport.model_validate_json(raw)
        # Two clauses: see corvo.agents.runner.
        except OSError:
            raise Disabled("the probe's report is invalid") from None
        except UntrustedFile:
            raise Disabled("the probe's report is invalid") from None
        except ValidationError:
            raise Disabled("the probe's report is invalid") from None
    finally:
        await shielded(remove_run(client, label, run_dir, calls))

    problems = probe_problems(report, fingerprint())
    if problems:
        raise Disabled(f"the probe found: {'; '.join(problems)}")
    if egress_open(report):
        open_egress = (
            "the agent container reached the gateway or the metadata address, "
            "which the production nftables rule blocks"
        )
        if settings.agent_require_egress_block:
            raise Disabled(open_egress)
        logger.warning(open_egress)


async def check(
    client: DockerClient, settings: Settings, deployment: str, status_of: StatusOf
) -> None:
    """Checks the image and the probe's report, then sweeps."""
    try:
        await asyncio.to_thread(client.images.get, settings.agent_image)
    except ImageNotFound:
        raise Disabled(
            f"the image {settings.agent_image} is not in the agents' Podman: "
            "build it there with --target agent"
        ) from None
    (Path(settings.agent_root) / "runs").mkdir(exist_ok=True)
    await probe(client, settings, deployment)
    try:
        async with asyncio.timeout(SWEEP_TIMEOUT):
            await sweep(client, deployment, status_of)
    except TimeoutError:
        logger.warning("the sweep took longer than %s seconds", SWEEP_TIMEOUT)


async def checked_runtime(
    settings: Settings, deployment: str, status_of: StatusOf
) -> Runtime:
    if not settings.agent_credential:
        raise Disabled("CORVO_AGENT_CREDENTIAL is empty")
    client = DockerClient(base_url=f"unix://{settings.agent_podman_socket}")
    try:
        await check(client, settings, deployment, status_of)
    except BaseException:
        # Agents stay off, so nothing uses the client again.
        client.close()
        raise
    return Runtime(
        client=client,
        root=Path(settings.agent_root),
        image=settings.agent_image,
        credential=Credential(
            kind=settings.agent_credential_kind, value=settings.agent_credential
        ),
        deployment=deployment,
    )


async def prepare(settings: Settings, deployment: str, status_of: StatusOf) -> None:
    """Enables agents, or disables them with the reason logged."""
    if not settings.agents_configured():
        containers.disable(NOT_CONFIGURED)
        logger.info(NOT_CONFIGURED)
        return
    try:
        async with asyncio.timeout(PREPARE_TIMEOUT):
            runtime = await checked_runtime(settings, deployment, status_of)
    except Exception as error:
        if isinstance(error, Disabled):
            reason = str(error)
        elif isinstance(error, TimeoutError):
            reason = f"preparing agents took longer than {PREPARE_TIMEOUT} seconds"
        else:
            reason = f"preparing agents failed: {type(error).__name__}: {error}"
        containers.disable(f"agents are disabled: {reason}")
        logger.error("agents are disabled: %s", reason)
        return
    containers.enable(runtime)
    logger.info("agents are enabled")


# The hook's task, kept from the garbage collector until it ends.
handovers: set[asyncio.Task[None]] = set()


def install_sigterm_hook() -> None:
    """Has SIGTERM remove the in-flight agent containers, then run the
    handler installed before, Hatchet's own (KTD19)."""
    previous = signal.getsignal(signal.SIGTERM)

    def hand_over(signum: int, frame: FrameType | None) -> None:
        if callable(previous):
            previous(signum, frame)

    async def remove_then_hand_over(
        runtime: Runtime, signum: int, frame: FrameType | None
    ) -> None:
        try:
            async with asyncio.timeout(CLEANUP_TIMEOUT):
                await remove_in_flight(runtime)
        except Exception:
            logger.exception("removing the in-flight agent containers failed")
        finally:
            hand_over(signum, frame)

    def handler(signum: int, frame: FrameType | None) -> None:
        runtime = containers.state
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if not isinstance(runtime, Runtime) or not runtime.in_flight or loop is None:
            hand_over(signum, frame)
            return
        task = loop.create_task(remove_then_hand_over(runtime, signum, frame))
        handovers.add(task)
        task.add_done_callback(handovers.discard)

    signal.signal(signal.SIGTERM, handler)
