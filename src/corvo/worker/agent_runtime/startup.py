"""The agent worker's start and stop: the agents profile's two hooks (KTD10,
KTD19).

before_start runs before the Hatchet worker exists. Within PREPARE_TIMEOUT
it checks, in order:

1. settings: the agents' root, the proxy and the engine are set;
2. credential in environment: no Claude credential is in the worker's
   environment, since sessions get only its placeholder (R13);
3. cgroup delegation: the cgroup2 mount delegates by namespace, so a session
   in its own cgroup namespace cannot rewrite its limits, and a run's cgroup
   can be made;
4. bubblewrap: the wrapper's sandbox, run as a session's in a cgroup of its
   own, shows only its own processes, only the variables a session may
   hold, no /sys and none of the worker's files;
5. the SDK's sandbox: inside it, a nested bubblewrap with its own user and
   network namespaces starts, and socat is there;
6. proxy: the credential proxy accepts a connection, retried until the
   bound, since compose may start it later.

The first that fails logs `agents refused: <part>: <detail>` and exits with
status 1, so the worker never registers an agent task, and their runs wait
for an agent worker that can isolate them. Compose restarts it with backoff.
Then it kills and removes every run's cgroup sessions left (KTD21).

The checks are weaker than a real engine's start: U1's gate and U8's probe
prove that on CI.

on_sigterm runs on SIGTERM, before Hatchet's graceful exit. It refuses every
run from then on, then kills the cgroup of every in-flight session. Those
runs fail while the worker still answers, so the engine records a failure
rather than re-queue them once the worker is gone.
"""

import asyncio
import contextlib
import json
import logging
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from corvo.agents.session import sandbox_settings
from corvo.settings import Settings, get_settings
from corvo.worker.agent_runtime import cgroups, sandbox, sessions
from corvo.worker.agent_runtime.cgroups import Cgroup
from corvo.worker.agent_runtime.sessions import CLEANUP_TIMEOUT, POLL_INTERVAL
from corvo.worker.agent_runtime.start_check import check

logger = logging.getLogger(__name__)

PREPARE_TIMEOUT = 45
# Each connection to the proxy, and the pause before the next.
CONNECT_TIMEOUT = 2
RETRY_INTERVAL = 1

# The parts a refusal names (R28).
SETTINGS = "settings"
CREDENTIAL = "credential in environment"
DELEGATION = "cgroup delegation"
BUBBLEWRAP = "bubblewrap"
SDK_SANDBOX = "the SDK's sandbox"
PROXY = "proxy"

# A run's failure on a worker that is stopping.
STOPPING = "worker stopping"

# The variables the engine authenticates with.
CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")

MOUNTINFO = Path("/proc/self/mountinfo")

# Every variable the wrapper may give the engine, and the PWD bubblewrap
# sets for its --chdir.
ALLOWED = {
    *sandbox.sandbox_env(
        {name: sandbox.PLACEHOLDER for name in sandbox.CREDENTIAL_VARIABLES}
        | {name: "" for name in sandbox.PASSED_VARIABLES}
    ),
    "PWD",
}


class Disabled(Exception):
    """Why this worker cannot run agents: the part of its isolation that
    failed, and how."""

    def __init__(self, part: str, detail: str) -> None:
        super().__init__(f"{part}: {detail}")


@dataclass
class Progress:
    """The check that is running, for a refusal at the bound."""

    part: str = SETTINGS
    # The last failure of a check that retries.
    last: str = ""


def check_settings(settings: Settings) -> None:
    for value, name in (
        (settings.agent_root, "CORVO_AGENT_ROOT"),
        (settings.agent_proxy_url, "CORVO_AGENT_PROXY_URL"),
        (settings.agent_engine, "CORVO_AGENT_ENGINE"),
    ):
        if not value:
            raise Disabled(SETTINGS, f"{name} is not set")


def check_credentials(environ: Mapping[str, str]) -> None:
    found = [name for name in CREDENTIALS if name in environ]
    if found:
        raise Disabled(CREDENTIAL, ", ".join(found))


def check_delegation(mountinfo: str, root: Path) -> None:
    options = [
        line.split(" - ", 1)[1].split()[2].split(",")
        for line in mountinfo.splitlines()
        if " - cgroup2 " in line
    ]
    if not options:
        raise Disabled(DELEGATION, "no cgroup2 mount")
    if not all("nsdelegate" in mount for mount in options):
        raise Disabled(DELEGATION, "the cgroup2 mount lacks nsdelegate")
    cgroup = make_cgroup(root)
    try:
        cgroup.remove()
    except OSError as error:
        raise Disabled(DELEGATION, f"cannot remove a run's cgroup: {error}") from None


def make_cgroup(root: Path) -> Cgroup:
    """A cgroup like a run's, named like one, so a start that fails to
    remove it leaves it to the next start's sweep."""
    try:
        return cgroups.create(root, f"start-{uuid.uuid4().hex[:8]}")
    except OSError as error:
        raise Disabled(DELEGATION, f"cannot make a run's cgroup: {error}") from None


async def remove_emptied(cgroup: Cgroup) -> None:
    """Kills the cgroup until it is empty, within CLEANUP_TIMEOUT, then
    removes it."""
    async with asyncio.timeout(CLEANUP_TIMEOUT):
        cgroup.kill()
        while cgroup.populated():
            await asyncio.sleep(POLL_INTERVAL)
            cgroup.kill()
    cgroup.remove()


async def sandbox_report(
    settings: Settings, root: Path, environ: Mapping[str, str]
) -> dict[str, Any]:
    """The start check's report, from check.py run through the wrapper in
    the engine's place, with a session's variables and settings, in a
    cgroup of its own."""
    cgroup = make_cgroup(root)
    env = {
        # The worker's own variables too, as the SDK passes them: the
        # wrapper must keep them out of the sandbox.
        **environ,
        **sessions.session_env(settings, cgroup, None, False),
        "CORVO_SANDBOX_ENGINE": check.__file__,
    }
    absent = [sys.prefix, sessions.__file__, settings.agent_root]
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            sessions.WRAPPER,
            "--setting-sources=",
            "--settings",
            json.dumps({"sandbox": sandbox_settings()}),
            *(arg for path in absent for arg in ("--absent", path)),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
    finally:
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await remove_emptied(cgroup)
    if process.returncode != 0:
        lines = stderr.decode(errors="replace").strip().splitlines() or ["no output"]
        raise Disabled(BUBBLEWRAP, sessions.printable(lines[-1]))
    try:
        report: dict[str, Any] = json.loads(stdout)
    except ValueError:
        raise Disabled(BUBBLEWRAP, "the check printed no report") from None
    if not isinstance(report, dict):
        raise Disabled(BUBBLEWRAP, "the check printed no report")
    return report


def judge_bubblewrap(report: dict[str, Any]) -> None:
    if report["sys"]:
        raise Disabled(BUBBLEWRAP, "the sandbox shows /sys")
    if report["present"]:
        raise Disabled(BUBBLEWRAP, f"the sandbox shows {', '.join(report['present'])}")
    # bubblewrap's own pid 1, and the check.
    for pid, command in report["processes"].items():
        if pid not in ("1", report["self"]):
            raise Disabled(
                BUBBLEWRAP, f"the sandbox shows a process not its own: {command}"
            )
    for pid, names in report["environ"].items():
        if isinstance(names, str):
            raise Disabled(BUBBLEWRAP, f"process {pid}'s environment is {names}")
        extra = sorted(set(names) - ALLOWED)
        if extra:
            raise Disabled(BUBBLEWRAP, f"process {pid} holds {', '.join(extra)}")


def judge_sdk_sandbox(report: dict[str, Any]) -> None:
    nested = report["nested"]
    if nested["returncode"] != 0:
        failed = sessions.printable(str(nested["stderr"]).strip())
        raise Disabled(SDK_SANDBOX, f"a nested bubblewrap failed: {failed}")
    if report["socat"] is None:
        raise Disabled(SDK_SANDBOX, "socat is missing")


async def check_proxy(url: str, progress: Progress) -> None:
    parts = urlsplit(url)
    if parts.hostname is None:
        raise Disabled(PROXY, f"{url!r} names no host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    while True:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                _, writer = await asyncio.open_connection(parts.hostname, port)
            writer.close()
            return
        except (OSError, TimeoutError) as error:
            progress.last = f"{type(error).__name__}: {error}"
        await asyncio.sleep(RETRY_INTERVAL)


async def prepare(settings: Settings, environ: Mapping[str, str]) -> None:
    """Checks the worker's isolation within PREPARE_TIMEOUT, and raises
    Disabled at the first part that fails."""
    progress = Progress()
    try:
        async with asyncio.timeout(PREPARE_TIMEOUT):
            check_settings(settings)
            progress.part = CREDENTIAL
            check_credentials(environ)
            progress.part = DELEGATION
            root = Path(settings.agent_cgroup_root)
            check_delegation(MOUNTINFO.read_text(), root)
            progress.part = BUBBLEWRAP
            report = await sandbox_report(settings, root, environ)
            judge_bubblewrap(report)
            progress.part = SDK_SANDBOX
            judge_sdk_sandbox(report)
            progress.part = PROXY
            await check_proxy(settings.agent_proxy_url, progress)
    except Disabled:
        raise
    except TimeoutError:
        last = f"; last: {progress.last}" if progress.last else ""
        raise Disabled(
            progress.part, f"not done within {PREPARE_TIMEOUT} seconds{last}"
        ) from None
    except Exception as error:
        raise Disabled(progress.part, f"{type(error).__name__}: {error}") from None


async def sweep(root: Path) -> None:
    """Kills and removes every run's cgroup sessions left. One that cannot
    be removed is logged, and stays."""
    swept = []
    for path in sorted(root.glob("run-*")):
        try:
            await remove_emptied(Cgroup(path))
        except Exception as error:
            logger.warning(
                "agents: %s is left: %s: %s", path.name, type(error).__name__, error
            )
            continue
        swept.append(path.name)
    logger.info(
        "agents: swept %d leftover cgroups%s",
        len(swept),
        f": {', '.join(swept)}" if swept else "",
    )


async def start(settings: Settings, environ: Mapping[str, str]) -> None:
    await prepare(settings, environ)
    logger.info("agents: every isolation check passed")
    await sweep(Path(settings.agent_cgroup_root))


def before_start() -> None:
    """The agents profile's before_start: checks the isolation and sweeps,
    or exits the process with status 1."""
    settings = get_settings()
    logger.info("agents: the sessions' engine is %s", settings.agent_engine)
    try:
        asyncio.run(start(settings, os.environ))
    except Disabled as refused:
        logger.error("agents refused: %s", refused)
        sys.exit(1)


def on_sigterm() -> None:
    """The agents profile's on_sigterm: refuses every run from now on, then
    kills the cgroup of every in-flight session (KTD19)."""
    sessions.refusal = STOPPING
    killed = 0
    for path in sorted(sessions.in_flight):
        try:
            Cgroup(path).kill()
        except OSError as error:
            logger.error("agents: cannot kill %s: %s", path.name, error)
            continue
        killed += 1
    logger.info("agents: %s, killed %d in-flight sessions", STOPPING, killed)
