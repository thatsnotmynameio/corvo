"""The worker registers every task and workflow the two areas define.

Hatchet starts a worker without complaint when a definition is missing from
its list, and lets a duplicate name win silently. This test checks WORKFLOWS
against every module-level definition in corvo.worker.tasks and
corvo.worker.workflows, and names each one that is unregistered, listed twice
or sharing a name. It also fails on what would hide a definition from it: a
directory without __init__.py, or a module that fails to import.
"""

import importlib
import pkgutil
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from hatchet_sdk import ClientConfig, Context, EmptyModel, Hatchet
from hatchet_sdk.runnables.workflow import BaseWorkflow

import corvo.worker.tasks
import corvo.worker.workflows
from corvo.settings import get_settings
from corvo.worker.hatchet_client import hatchet
from corvo.worker.worker import WORKFLOWS

AREAS = [corvo.worker.tasks, corvo.worker.workflows]

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
    defined: Sequence[Definition], registered: list[BaseWorkflow[Any]]
) -> list[str]:
    labels = {id(workflow): label for label, workflow in defined}
    every = {id(workflow): workflow for _, workflow in defined}
    every |= {id(workflow): workflow for workflow in registered}

    def label(workflow: BaseWorkflow[Any]) -> str:
        return labels.get(id(workflow), workflow.name)

    listed = Counter(id(workflow) for workflow in registered)
    # Hatchet keys a worker's actions on service_name, the name lowercased
    # with the namespace applied, and the last one registered wins.
    sharing: defaultdict[str, list[str]] = defaultdict(list)
    for workflow in every.values():
        sharing[workflow.service_name].append(label(workflow))

    return [
        *(
            f"{label(workflow)} ({workflow.name}) is on no worker: add it to WORKFLOWS"
            for workflow in every.values()
            if not listed[id(workflow)]
        ),
        *(
            f"{label(workflow)} ({workflow.name}) is listed {listed[id(workflow)]} "
            "times in WORKFLOWS"
            for workflow in every.values()
            if listed[id(workflow)] > 1
        ),
        *(
            f"{' and '.join(names)} share the name {name!r}"
            for name, names in sharing.items()
            if len(names) > 1
        ),
    ]


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


def test_every_definition_in_the_areas_is_registered() -> None:
    roots = [Path(path) for area in AREAS for path in area.__path__]

    found = unpackaged(roots) + problems(definitions(area_modules(AREAS)), WORKFLOWS)

    assert found == []


def test_a_definition_missing_from_the_list_is_named() -> None:
    defined = definitions([module("area.example", example=example)])

    found = problems(defined, [])

    assert found == [
        "area.example.example (registration-example) is on no worker: "
        "add it to WORKFLOWS"
    ]


def test_two_definitions_sharing_a_name_are_both_named() -> None:
    defined = definitions(
        [module("area.first", dup=first_dup), module("area.second", dup=second_dup)]
    )

    found = problems(defined, [first_dup, second_dup])

    assert found == ["area.first.dup and area.second.dup share the name 'dup'"]


def test_names_differing_only_in_case_are_shared() -> None:
    defined = definitions(
        [module("area.first", dup=first_dup), module("area.second", dup=capital_dup)]
    )

    found = problems(defined, [first_dup, capital_dup])

    assert found == ["area.first.dup and area.second.dup share the name 'dup'"]


def test_names_sharing_a_namespaced_name_are_shared() -> None:
    # The namespace is prefixed only to a name that does not start with it.
    defined = definitions(
        [
            module("area.first", job=namespaced_job),
            module("area.second", job=prefixed_job),
        ]
    )

    found = problems(defined, [namespaced_job, prefixed_job])

    assert found == ["area.first.job and area.second.job share the name 'foo_job'"]


def test_a_definition_listed_twice_is_named() -> None:
    defined = definitions([module("area.example", example=example)])

    found = problems(defined, [example, example])

    assert found == [
        "area.example.example (registration-example) is listed 2 times in WORKFLOWS"
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
