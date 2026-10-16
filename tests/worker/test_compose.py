"""Each worker service in compose.yaml states a profile, and each profile has
a service.

corvo-worker serves main when CORVO_WORKER_PROFILE is unset, so a worker
service that forgets it starts without complaint and serves main with
whatever credentials compose gives it. A profile no service serves leaves its
runs queued until they time out. This test reads compose.yaml and the
Dockerfile stages its services build, and decides which services run
corvo-worker: by their command, or by the CMD of the stage they build. It
names each worker service that states no profile, each service whose
CORVO_WORKER_PROFILE is not a literal name in PROFILES, and each profile with
no service. It also fails on a service whose command it cannot work out.
"""

import json
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from corvo.worker.profiles import PROFILES

ROOT = Path(__file__).parents[2]
VARIABLE = "CORVO_WORKER_PROFILE"
WORKER = "corvo-worker"


@dataclass(frozen=True)
class Stage:
    name: str | None
    # The image or the earlier stage it starts FROM.
    base: str
    # An exec-form CMD as its arguments, a shell-form one as its text, or
    # None when the stage declares none and inherits its base's.
    cmd: tuple[str, ...] | str | None


def stages(dockerfile: str) -> list[Stage]:
    """The Dockerfile's stages, from its FROM and CMD instructions."""
    found: list[Stage] = []
    for line in dockerfile.replace("\\\n", " ").splitlines():
        keyword, _, rest = line.strip().partition(" ")
        if keyword.upper() == "FROM":
            parsed = re.fullmatch(r"(\S+)(?:\s+AS\s+(\S+))?", rest.strip(), re.I)
            assert parsed is not None, f"unreadable FROM: {line}"
            found.append(Stage(parsed[2], parsed[1], None))
        elif keyword.upper() == "CMD":
            rest = rest.strip()
            cmd = tuple(json.loads(rest)) if rest.startswith("[") else rest
            found[-1] = Stage(found[-1].name, found[-1].base, cmd)
    return found


def stage_command(built: Sequence[Stage], index: int) -> tuple[str, ...] | None:
    """The CMD the stage at index runs, inherited through FROM, or None when
    it cannot be told: a shell form, or a base image's own."""
    stage = built[index]
    if isinstance(stage.cmd, tuple):
        return stage.cmd
    if stage.cmd is not None:
        return None
    for earlier in reversed(range(index)):
        if built[earlier].name == stage.base:
            return stage_command(built, earlier)
    return None


class Unknown(Exception):
    """What a service runs cannot be told; its message names the service."""


def command(
    name: str, service: Mapping[str, Any], built: Sequence[Stage]
) -> tuple[str, ...]:
    """The command the service runs, or Unknown when that cannot be told."""
    if "command" in service:
        given = service["command"]
        return tuple(given) if isinstance(given, list) else tuple(shlex.split(given))
    if "build" not in service:
        # An image's own command, which runs no corvo-worker.
        return ()
    build = service["build"]
    target = build.get("target") if isinstance(build, Mapping) else None
    if target is None:
        index = len(built) - 1
    else:
        indexes = [i for i, stage in enumerate(built) if stage.name == target]
        if not indexes:
            raise Unknown(
                f"{name} builds the target {target!r}, which the Dockerfile "
                "lacks, so what it runs is unknown"
            )
        index = indexes[-1]
    found = stage_command(built, index)
    if found is None:
        stage = built[index].name or "the last stage"
        raise Unknown(
            f"{name} builds {stage}, whose CMD is not in exec form in the "
            "Dockerfile, so what it runs is unknown"
        )
    return found


def problems(
    services: Mapping[str, Mapping[str, Any]],
    built: Sequence[Stage],
    profiles: Mapping[str, str],
) -> list[str]:
    """Each worker service checked against the profiles, then each profile
    against the services."""
    unprofiled: list[str] = []
    invalid: list[str] = []
    served: set[str] = set()
    known = ", ".join(sorted(profiles))
    for name, service in services.items():
        environment = service.get("environment") or {}
        if VARIABLE in environment:
            # Only a literal name: an interpolation or a key with no value
            # leaves the profile to the host's environment.
            value = environment[VARIABLE]
            if isinstance(value, str) and value in profiles:
                served.add(value)
            else:
                invalid.append(
                    f"{name} sets {VARIABLE} to {value!r}, which is no profile: "
                    f"the profiles are {known}"
                )
            continue
        try:
            runs = command(name, service, built)
        except Unknown as unknown:
            unprofiled.append(str(unknown))
            continue
        if runs[:1] == (WORKER,):
            unprofiled.append(
                f"{name} runs {WORKER} without {VARIABLE}, so it serves main: "
                "set the profile it serves"
            )
    return [
        *unprofiled,
        *invalid,
        *(
            f"the {profile} profile has no service in compose.yaml: add one "
            f"that sets {VARIABLE}: {profile}"
            for profile in sorted(profiles)
            if profile not in served
        ),
    ]


DOCKERFILE = """\
FROM python:3.14.7-slim AS app
RUN uv sync \\
    --locked
CMD ["uvicorn", "corvo.server.api.server:app", "--port", "8000"]

FROM app AS worker
CMD ["corvo-worker"]

FROM worker AS inherits

FROM app AS shell
CMD corvo-worker

FROM app
"""

STAGES = stages(DOCKERFILE)

# The services that keep both profiles served, so each test shows only its
# own problems.
SERVED = """\
  main-worker:
    command: ["corvo-worker"]
    environment:
      CORVO_WORKER_PROFILE: main
  agents-worker:
    build:
      context: .
      target: worker
    environment:
      CORVO_WORKER_PROFILE: agents
"""


def compose(text: str) -> dict[str, Any]:
    """The services of a compose file whose services: holds SERVED and
    text."""
    loaded = yaml.safe_load(f"services:\n{SERVED}{text}")
    services: dict[str, Any] = loaded["services"]
    return services


def test_compose_states_a_profile_for_every_worker_and_serves_every_profile() -> None:
    services = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]
    built = stages((ROOT / "Dockerfile").read_text())

    assert problems(services, built, PROFILES) == []


def test_the_services_both_profiles_need_pass() -> None:
    assert problems(compose(""), STAGES, PROFILES) == []


def test_a_worker_without_a_profile_is_named() -> None:
    services = compose(
        """\
  db-worker:
    command: ["corvo-worker"]
    environment:
      CORVO_POSTGRES_PASSWORD: secret
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "db-worker runs corvo-worker without CORVO_WORKER_PROFILE, so it serves "
        "main: set the profile it serves"
    ]


def test_a_worker_from_its_stage_s_cmd_is_named() -> None:
    services = compose(
        """\
  quiet:
    build:
      context: .
      target: worker
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "quiet runs corvo-worker without CORVO_WORKER_PROFILE, so it serves "
        "main: set the profile it serves"
    ]


def test_a_stage_without_a_cmd_inherits_its_base_s() -> None:
    services = compose(
        """\
  inherited:
    build:
      context: .
      target: inherits
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "inherited runs corvo-worker without CORVO_WORKER_PROFILE, so it serves "
        "main: set the profile it serves"
    ]


def test_a_build_without_a_target_runs_the_last_stage() -> None:
    # The last stage is the app's, which runs uvicorn.
    services = compose(
        """\
  app:
    build: .
  migrate:
    build:
      context: .
"""
    )

    assert problems(services, STAGES, PROFILES) == []


def test_a_target_the_dockerfile_lacks_is_named() -> None:
    services = compose(
        """\
  lost:
    build:
      context: .
      target: nowhere
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "lost builds the target 'nowhere', which the Dockerfile lacks, so what "
        "it runs is unknown"
    ]


def test_a_stage_with_a_shell_form_cmd_is_named() -> None:
    services = compose(
        """\
  shelled:
    build:
      context: .
      target: shell
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "shelled builds shell, whose CMD is not in exec form in the Dockerfile, "
        "so what it runs is unknown"
    ]


def test_an_unknown_profile_is_named_with_its_value() -> None:
    services = compose(
        """\
  typo:
    command: ["corvo-worker"]
    environment:
      CORVO_WORKER_PROFILE: agent
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "typo sets CORVO_WORKER_PROFILE to 'agent', which is no profile: the "
        "profiles are agents, main"
    ]


@pytest.mark.parametrize(
    ("written", "shown"),
    [('"${PROFILE}"', "'${PROFILE}'"), ('""', "''"), ("", "None")],
)
def test_a_profile_left_to_the_host_is_named(written: str, shown: str) -> None:
    services = compose(
        f"""\
  hosted:
    command: ["corvo-worker"]
    environment:
      CORVO_WORKER_PROFILE: {written}
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        f"hosted sets CORVO_WORKER_PROFILE to {shown}, which is no profile: the "
        "profiles are agents, main"
    ]


def test_an_unknown_profile_is_named_on_any_service() -> None:
    services = compose(
        """\
  proxy:
    image: caddy:2.11.7-alpine
    environment:
      CORVO_WORKER_PROFILE: nope
"""
    )

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "proxy sets CORVO_WORKER_PROFILE to 'nope', which is no profile: the "
        "profiles are agents, main"
    ]


def test_an_environment_merged_from_an_anchor_is_read() -> None:
    loaded = yaml.safe_load(
        f"""\
x-worker: &worker
  command: ["corvo-worker"]
  environment:
    CORVO_WORKER_PROFILE: nope
services:
{SERVED}\
  merged:
    <<: *worker
"""
    )

    found = problems(loaded["services"], STAGES, PROFILES)

    assert found == [
        "merged sets CORVO_WORKER_PROFILE to 'nope', which is no profile: the "
        "profiles are agents, main"
    ]


def test_a_profile_without_a_service_is_named() -> None:
    profiles = {**PROFILES, "db": "corvo.worker.profiles.db"}

    found = problems(compose(""), STAGES, profiles)

    assert found == [
        "the db profile has no service in compose.yaml: add one that sets "
        "CORVO_WORKER_PROFILE: db"
    ]


def test_a_profile_whose_only_service_is_invalid_has_no_service() -> None:
    services = yaml.safe_load(
        """\
services:
  main-worker:
    command: ["corvo-worker"]
    environment:
      CORVO_WORKER_PROFILE: main
  agents-worker:
    command: ["corvo-worker"]
    environment:
      CORVO_WORKER_PROFILE: agent
"""
    )["services"]

    found = problems(services, STAGES, PROFILES)

    assert found == [
        "agents-worker sets CORVO_WORKER_PROFILE to 'agent', which is no "
        "profile: the profiles are agents, main",
        "the agents profile has no service in compose.yaml: add one that sets "
        "CORVO_WORKER_PROFILE: agents",
    ]
