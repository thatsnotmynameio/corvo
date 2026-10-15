"""corvo-agent-sandbox: the SDK's cli_path in the agent worker (KTD20).

The SDK runs it in place of the engine, with the engine's arguments and the
worker's environment merged with the session's. It checks that the session
asked for the SDK's own sandbox, joins its run's cgroup, then replaces itself
with bubblewrap, started with an empty environment, which runs the engine in a
sandbox of its own: its own namespaces but the network's, read-only system
files, a temporary home, and the run's working directory alone.

It runs before it has joined its cgroup, so it imports only the standard
library (KTD2).
"""

import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

BWRAP = "/usr/bin/bwrap"

# The fixed credential each session sends, which the credential proxy
# replaces. Only a credential variable that holds it enters the sandbox.
PLACEHOLDER = "corvo-placeholder"
CREDENTIAL_VARIABLES = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

# The session's values that enter the sandbox as they are: the proxy's
# address, and what the SDK itself sets for the engine.
PASSED_VARIABLES = (
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_SDK_READS_SESSION_STATE",
)

HOME = "/home/agent"
PATH = "/usr/local/bin:/usr/bin:/bin"

# Set whatever the session's environment held: credentials scrubbed from every
# command, no memory or CLAUDE.md read from disk, no traffic beyond the API,
# no prompt history, and no claude.ai MCP servers.
ISOLATION_FLAGS = {
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
}

# Debian's merged /usr, as the agent worker's image has it.
ROOT_SYMLINKS = (
    ("usr/bin", "/bin"),
    ("usr/sbin", "/sbin"),
    ("usr/lib", "/lib"),
    ("usr/lib64", "/lib64"),
)


class Refused(Exception):
    """The wrapper will not start the engine."""


@dataclass(frozen=True)
class Run:
    """The run's values, from the variables the session piece sets."""

    cgroup: str
    workdir: str
    writes: bool
    engine: str
    tmpfs_bytes: int


def read_run(env: Mapping[str, str]) -> Run:
    names = (
        "CORVO_SANDBOX_CGROUP",
        "CORVO_SANDBOX_WORKDIR",
        "CORVO_SANDBOX_WRITES",
        "CORVO_SANDBOX_ENGINE",
        "CORVO_SANDBOX_TMPFS",
    )
    missing = [name for name in names if name not in env]
    if missing:
        raise Refused(f"missing {', '.join(missing)}")
    cgroup, workdir, writes, engine, tmpfs = (env[name] for name in names)
    if writes not in ("0", "1"):
        raise Refused("CORVO_SANDBOX_WRITES is neither 0 nor 1")
    if writes == "1" and not workdir:
        raise Refused("writes without a working directory")
    for name, path in (("cgroup", cgroup), ("engine", engine), ("workdir", workdir)):
        if path and not os.path.isabs(path):
            raise Refused(f"the {name} path is not absolute")
    if not cgroup or not engine:
        raise Refused("an empty cgroup or engine")
    if not tmpfs.isdigit() or int(tmpfs) == 0:
        raise Refused("CORVO_SANDBOX_TMPFS is not a size in bytes")
    return Run(cgroup, workdir, writes == "1", engine, int(tmpfs))


def check_settings(argv: Sequence[str]) -> None:
    """Refuses unless the one --settings the SDK passes runs every command in
    the SDK's sandbox, and none outside it."""
    if any(arg.startswith("--settings=") for arg in argv):
        raise Refused("--settings given inline")
    at = [index for index, arg in enumerate(argv) if arg == "--settings"]
    if len(at) != 1 or at[0] + 1 >= len(argv):
        raise Refused("no single --settings")
    try:
        settings: Any = json.loads(argv[at[0] + 1])
    except ValueError:
        raise Refused("--settings is not JSON") from None
    sandbox = settings.get("sandbox") if isinstance(settings, dict) else None
    if not isinstance(sandbox, dict):
        raise Refused("--settings has no sandbox")
    if sandbox.get("enabled") is not True:
        raise Refused("the sandbox is not enabled")
    if sandbox.get("failIfUnavailable") is not True:
        raise Refused("the sandbox does not fail when unavailable")
    if sandbox.get("allowUnsandboxedCommands") is not False:
        raise Refused("the sandbox allows unsandboxed commands")
    if sandbox.get("excludedCommands"):
        raise Refused("the sandbox excludes commands")
    if sandbox.get("enableWeakerNestedSandbox"):
        raise Refused("the sandbox is the weaker nested one")


def sandbox_env(env: Mapping[str, str]) -> dict[str, str]:
    """The engine's whole environment."""
    kept = {
        name: env[name] for name in CREDENTIAL_VARIABLES if env.get(name) == PLACEHOLDER
    }
    kept |= {name: env[name] for name in PASSED_VARIABLES if name in env}
    return kept | {
        "HOME": HOME,
        "CLAUDE_CONFIG_DIR": f"{HOME}/.claude",
        "PATH": PATH,
        **ISOLATION_FLAGS,
    }


def bwrap_args(
    run: Run, env: Mapping[str, str], argv: Sequence[str], workdir_fd: int | None
) -> list[str]:
    """bubblewrap's command line: the engine, with argv, in a sandbox whose
    only writable host path is the working directory when the run writes."""
    args = [
        BWRAP,
        "--unshare-all",
        "--unshare-cgroup",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ]
    for name, value in sandbox_env(env).items():
        args += ["--setenv", name, value]
    args += ["--ro-bind", "/usr", "/usr"]
    for target, link in ROOT_SYMLINKS:
        args += ["--symlink", target, link]
    args += ["--ro-bind", "/etc", "/etc", "--proc", "/proc", "--dev", "/dev"]
    for tmpfs in ("/tmp", HOME):
        args += ["--size", str(run.tmpfs_bytes), "--tmpfs", tmpfs]
    engine_dir = os.path.dirname(run.engine)
    args += ["--ro-bind", engine_dir, engine_dir]
    if run.workdir:
        if workdir_fd is None:
            raise Refused("a working directory with no descriptor")
        bind = "--bind-fd" if run.writes else "--ro-bind-fd"
        args += [bind, str(workdir_fd), run.workdir, "--chdir", run.workdir]
    else:
        args += ["--chdir", HOME]
    return [*args, run.engine, *argv]


def open_workdir(path: str) -> int:
    """The working directory, opened one component at a time without
    following a symlink, so a path replaced after the task checked it never
    binds somewhere else."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for component in path.split("/"):
            if component in ("", "."):
                continue
            if component == "..":
                raise Refused("the working directory holds ..")
            try:
                child = os.open(component, flags, dir_fd=fd)
            except OSError as error:
                raise Refused(f"the working directory: {error.strerror}") from None
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def join_cgroup(cgroup: str) -> None:
    try:
        with open(os.path.join(cgroup, "cgroup.procs"), "w") as procs:
            procs.write(str(os.getpid()))
    except OSError as error:
        raise Refused(f"cannot join {cgroup}: {error.strerror}") from None


def main() -> NoReturn:
    argv, env = sys.argv[1:], dict(os.environ)
    try:
        run = read_run(env)
        check_settings(argv)
        join_cgroup(run.cgroup)
        workdir_fd = open_workdir(run.workdir) if run.workdir else None
        args = bwrap_args(run, env, argv, workdir_fd)
    except Refused as refused:
        print(f"corvo-agent-sandbox: refused: {refused}", file=sys.stderr)
        sys.exit(1)
    if workdir_fd is not None:
        os.set_inheritable(workdir_fd, True)
    # An empty environment: bubblewrap's own pid 1 in the sandbox never execs,
    # so whatever bubblewrap starts with stays readable at /proc/1/environ.
    os.execve(BWRAP, args, {})
