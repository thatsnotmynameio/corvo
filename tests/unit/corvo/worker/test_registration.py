"""Each profile registers every task and workflow its areas define.

Hatchet starts a worker without complaint when a definition is missing from
its list, and lets a duplicate name win silently. This test maps each area
to its profile, corvo.worker.tasks, corvo.worker.workflows and
corvo.worker.event_gateway to main and corvo.worker.agents to agents, and
checks each profile's list against every module-level definition in its
areas. It names each one that is on no worker, on a profile other than its
area's, listed twice or sharing a name with another on any profile. It also
fails on what would hide a definition from it: a directory without
__init__.py, or a module that fails to import.
"""

import importlib
import pkgutil
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hatchet_sdk import ClientConfig, Context, EmptyModel, Hatchet
from hatchet_sdk.runnables.workflow import BaseWorkflow, Standalone
from pydantic import BaseModel

import corvo.worker.agent_calls
import corvo.worker.agents
import corvo.worker.event_gateway
import corvo.worker.tasks
import corvo.worker.workflows
from corvo.settings import get_settings
from corvo.vendors.hatchet.client import hatchet
from corvo.worker.profiles import PROFILES

# Each profile's areas: an agent task belongs on the agent worker alone.
AREAS = {
    "main": [corvo.worker.tasks, corvo.worker.workflows, corvo.worker.event_gateway],
    "agents": [corvo.worker.agents],
}

type Definition = tuple[str, BaseWorkflow[Any]]


def area_modules(areas: Iterable[ModuleType]) -> list[ModuleType]:
    # Importing each module here raises its import error, which walk_packages
    # would swallow for a package.
    return [
        importlib.import_module(info.name)
        for area in areas
        for info in pkgutil.walk_packages(area.__path__, f"{area.__name__}.")
    ]


def unpackaged(roots: Iterable[Path]) -> list[str]:
    """Each directory pkgutil skips: it holds Python files but no __init__.py."""
    directories = {
        root / relative
        for root in roots
        for source in root.rglob("*.py")
        for relative in source.relative_to(root).parents[:-1]
    }
    return [
        f"{directory} has no __init__.py, so its modules go unchecked"
        for directory in sorted(directories)
        if not (directory / "__init__.py").exists()
    ]


def definitions(modules: Iterable[ModuleType]) -> list[Definition]:
    """Each module-level definition once, labelled module.attribute."""
    found: dict[int, Definition] = {}
    for module in modules:
        for attribute, value in vars(module).items():
            if isinstance(value, BaseWorkflow):
                found.setdefault(id(value), (f"{module.__name__}.{attribute}", value))
    return list(found.values())


def problems(
    defined: Mapping[str, Sequence[Definition]],
    registered: Mapping[str, list[BaseWorkflow[Any]]],
    stubs: Sequence[Definition] = (),
) -> list[str]:
    """Each profile's definitions checked against each profile's list.

    A stub, which a workflow imports to spawn its task, is no definition of
    an area, and it shares its task's name by design. A stub on a list would
    take its task's runs and raise.
    """
    stub_labels = {id(workflow): label for label, workflow in stubs}
    on_lists = [
        f"{stub_labels[id(workflow)]} ({workflow.name}) is a stub, on the "
        f"{profile} profile: a worker serving it would take its task's runs "
        "and raise"
        for profile, workflows in sorted(registered.items())
        for workflow in workflows
        if id(workflow) in stub_labels
    ]
    defined = {
        profile: [found for found in each if id(found[1]) not in stub_labels]
        for profile, each in defined.items()
    }
    registered = {
        profile: [workflow for workflow in workflows if id(workflow) not in stub_labels]
        for profile, workflows in registered.items()
    }

    labels = {
        id(workflow): label for found in defined.values() for label, workflow in found
    }
    home = {
        id(workflow): profile
        for profile, found in defined.items()
        for _, workflow in found
    }
    every = {
        id(workflow): workflow for found in defined.values() for _, workflow in found
    }
    every |= {
        id(workflow): workflow
        for workflows in registered.values()
        for workflow in workflows
    }

    def label(key: int) -> str:
        workflow = every[key]
        return f"{labels.get(key, workflow.name)} ({workflow.name})"

    listed = {
        profile: Counter(id(workflow) for workflow in workflows)
        for profile, workflows in sorted(registered.items())
    }
    # Hatchet keys a worker's actions on service_name, the name lowercased
    # with the namespace applied, and the last one registered wins. Two
    # profiles' tasks sharing one would share their runs too.
    sharing: defaultdict[str, list[str]] = defaultdict(list)
    for key, workflow in every.items():
        sharing[workflow.service_name].append(labels.get(key, workflow.name))

    return [
        *(
            f"{label(key)} is on no worker: add it to the {profile} profile"
            for key, profile in home.items()
            if not listed.get(profile, Counter())[key]
        ),
        *(
            f"{label(key)} is on the {profile} profile, but its area's profile "
            f"is {home[key]}"
            for profile, counts in listed.items()
            for key in counts
            if key in home and home[key] != profile
        ),
        *(
            f"{label(key)} is listed {count} times on the {profile} profile"
            for profile, counts in listed.items()
            for key, count in counts.items()
            if count > 1
        ),
        *(
            f"{' and '.join(names)} share the name {name!r}"
            for name, names in sharing.items()
            if len(names) > 1
        ),
        *on_lists,
    ]


def stub_problems(
    stubs: Sequence[Definition], tasks: Sequence[Definition]
) -> list[str]:
    """Each stub checked against the agent task of its name: a stub's input
    and output classes are its task's, so caller and task validate alike."""
    by_name = {
        workflow.name: workflow
        for _, workflow in tasks
        if isinstance(workflow, Standalone)
    }
    found = []
    for label, stub in stubs:
        assert isinstance(stub, Standalone)
        named = f"{label} ({stub.name})"
        task = by_name.get(stub.name)
        if task is None:
            found.append(f"{named} is a stub of no agent task")
            continue
        if stub.input_validator_type is not task.input_validator_type:
            found.append(
                f"{named} takes {stub.input_validator_type.__name__}, but its "
                f"task takes {task.input_validator_type.__name__}"
            )
        if stub.output_validator_type is not task.output_validator_type:
            found.append(
                f"{named} returns {stub.output_validator_type.__name__}, but its "
                f"task returns {task.output_validator_type.__name__}"
            )
    return found


def profile_lists() -> dict[str, list[BaseWorkflow[Any]]]:
    return {
        name: importlib.import_module(path).PROFILE.workflows
        for name, path in PROFILES.items()
    }


def module(name: str, **attributes: object) -> ModuleType:
    built = ModuleType(name)
    vars(built).update(attributes)
    return built


@hatchet.task(name="registration-example")
async def example(input: EmptyModel, ctx: Context) -> None: ...


@hatchet.task(name="dup")
async def first_dup(input: EmptyModel, ctx: Context) -> None: ...


@hatchet.task(name="dup")
async def second_dup(input: EmptyModel, ctx: Context) -> None: ...


@hatchet.task(name="Dup")
async def capital_dup(input: EmptyModel, ctx: Context) -> None: ...


dag = hatchet.workflow(name="registration-dag")


@dag.task()
async def step(input: EmptyModel, ctx: Context) -> None: ...


namespaced = Hatchet(
    config=ClientConfig(token=get_settings().hatchet_token, namespace="foo")
)


@namespaced.task(name="job")
async def namespaced_job(input: EmptyModel, ctx: Context) -> None: ...


@namespaced.task(name="foo_job")
async def prefixed_job(input: EmptyModel, ctx: Context) -> None: ...


class AgentInput(BaseModel):
    text: str


class OtherInput(BaseModel):
    words: int


class AgentOutput(BaseModel):
    text: str


class OtherOutput(BaseModel):
    words: int


@hatchet.task(name="registration-agent", input_validator=AgentInput)
async def agent_task(input: AgentInput, ctx: Context) -> AgentOutput:
    return AgentOutput(text=input.text)


stub = hatchet.stubs.task(
    name="registration-agent", input_validator=AgentInput, output_validator=AgentOutput
)
other_input_stub = hatchet.stubs.task(
    name="registration-agent", input_validator=OtherInput, output_validator=AgentOutput
)
other_output_stub = hatchet.stubs.task(
    name="registration-agent", input_validator=AgentInput, output_validator=OtherOutput
)
STUB = ("calls.agent", stub)


def test_every_definition_in_the_areas_is_on_its_profile() -> None:
    roots = [
        Path(path)
        for areas in AREAS.values()
        for area in areas
        for path in area.__path__
    ]
    defined = {
        profile: definitions(area_modules(areas)) for profile, areas in AREAS.items()
    }
    stubs = definitions([corvo.worker.agent_calls])

    found = (
        unpackaged(roots)
        + problems(defined, profile_lists(), stubs)
        + stub_problems(stubs, defined["agents"])
    )

    assert found == []


def test_every_profile_has_its_areas() -> None:
    assert sorted(AREAS) == sorted(PROFILES)


def test_a_definition_missing_from_its_profile_is_named() -> None:
    defined = definitions([module("area.example", example=example)])

    found = problems({"agents": defined}, {"agents": [], "main": []})

    assert found == [
        "area.example.example (registration-example) is on no worker: "
        "add it to the agents profile"
    ]


def test_a_definition_on_both_profiles_is_named() -> None:
    defined = definitions([module("area.example", example=example)])

    found = problems({"agents": defined}, {"agents": [example], "main": [example]})

    assert found == [
        "area.example.example (registration-example) is on the main profile, "
        "but its area's profile is agents"
    ]


def test_a_definition_on_the_other_profile_alone_is_named() -> None:
    defined = definitions([module("area.example", example=example)])

    found = problems({"agents": defined}, {"agents": [], "main": [example]})

    assert found == [
        "area.example.example (registration-example) is on no worker: "
        "add it to the agents profile",
        "area.example.example (registration-example) is on the main profile, "
        "but its area's profile is agents",
    ]


def test_two_definitions_sharing_a_name_across_profiles_are_both_named() -> None:
    found = problems(
        {
            "main": definitions([module("area.first", dup=first_dup)]),
            "agents": definitions([module("area.second", dup=second_dup)]),
        },
        {"main": [first_dup], "agents": [second_dup]},
    )

    assert found == ["area.first.dup and area.second.dup share the name 'dup'"]


def test_names_differing_only_in_case_are_shared() -> None:
    defined = definitions(
        [module("area.first", dup=first_dup), module("area.second", dup=capital_dup)]
    )

    found = problems({"main": defined}, {"main": [first_dup, capital_dup]})

    assert found == ["area.first.dup and area.second.dup share the name 'dup'"]


def test_names_sharing_a_namespaced_name_are_shared() -> None:
    # The namespace is prefixed only to a name that does not start with it.
    defined = definitions(
        [
            module("area.first", job=namespaced_job),
            module("area.second", job=prefixed_job),
        ]
    )

    found = problems({"main": defined}, {"main": [namespaced_job, prefixed_job]})

    assert found == ["area.first.job and area.second.job share the name 'foo_job'"]


def test_a_definition_listed_twice_is_named() -> None:
    defined = definitions([module("area.example", example=example)])

    found = problems({"main": defined}, {"main": [example, example]})

    assert found == [
        "area.example.example (registration-example) is listed 2 times on the "
        "main profile"
    ]


def test_a_definition_imported_elsewhere_counts_once() -> None:
    modules = [
        module("area.example", example=example),
        module("area.parent", example=example),
    ]

    defined = definitions(modules)

    assert defined == [("area.example.example", example)]


def test_a_workflow_step_is_not_a_definition_of_its_own() -> None:
    defined = definitions([module("area.dag", dag=dag, step=step)])

    assert defined == [("area.dag.dag", dag)]


def test_a_directory_without_init_is_named(tmp_path: Path) -> None:
    area = tmp_path / "area"
    (area / "loose").mkdir(parents=True)
    (area / "__init__.py").touch()
    (area / "loose" / "step.py").touch()
    (area / "outer" / "inner").mkdir(parents=True)
    (area / "outer" / "inner" / "__init__.py").touch()
    (area / "outer" / "inner" / "step.py").touch()

    found = unpackaged([area])

    assert found == [
        f"{area / 'loose'} has no __init__.py, so its modules go unchecked",
        f"{area / 'outer'} has no __init__.py, so its modules go unchecked",
    ]


def test_a_package_that_fails_to_import_fails_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    area = tmp_path / "registration_area"
    (area / "broken").mkdir(parents=True)
    (area / "__init__.py").touch()
    (area / "broken" / "__init__.py").write_text("import nowhere_to_be_found\n")
    monkeypatch.syspath_prepend(tmp_path)

    with pytest.raises(ModuleNotFoundError, match="nowhere_to_be_found"):
        area_modules([importlib.import_module("registration_area")])


def test_a_stub_imported_into_an_area_is_not_a_definition_of_its_own() -> None:
    defined = definitions(
        [module("area.agent", agent=agent_task), module("area.flow", agent=stub)]
    )

    found = problems(
        {"agents": defined}, {"agents": [agent_task], "main": []}, stubs=[STUB]
    )

    assert found == []


def test_a_stub_on_a_profile_is_named() -> None:
    for profile in ("agents", "main"):
        found = problems({}, {profile: [stub]}, stubs=[STUB])

        assert found == [
            f"calls.agent (registration-agent) is a stub, on the {profile} "
            "profile: a worker serving it would take its task's runs and raise"
        ]


def test_a_stub_matching_its_task_passes() -> None:
    assert stub_problems([STUB], [("area.agent.agent", agent_task)]) == []


def test_a_stub_of_no_agent_task_is_named() -> None:
    found = stub_problems([STUB], [("area.example.example", example)])

    assert found == ["calls.agent (registration-agent) is a stub of no agent task"]


def test_a_stub_whose_input_differs_from_its_task_s_is_named() -> None:
    found = stub_problems(
        [("calls.agent", other_input_stub)], [("area.agent.agent", agent_task)]
    )

    assert found == [
        "calls.agent (registration-agent) takes OtherInput, but its task takes "
        "AgentInput"
    ]


def test_a_stub_whose_output_differs_from_its_task_s_is_named() -> None:
    found = stub_problems(
        [("calls.agent", other_output_stub)], [("area.agent.agent", agent_task)]
    )

    assert found == [
        "calls.agent (registration-agent) returns OtherOutput, but its task "
        "returns AgentOutput"
    ]
