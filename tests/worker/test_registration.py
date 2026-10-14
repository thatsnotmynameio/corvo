"""The worker registers every task and workflow the two areas define.

Hatchet starts a worker without complaint when a definition is missing from
its list, so this test checks WORKFLOWS against every module-level definition
in corvo.worker.tasks and corvo.worker.workflows.
"""

import importlib
import pkgutil
from collections.abc import Iterable
from types import ModuleType
from typing import Any

from hatchet_sdk import Context, EmptyModel
from hatchet_sdk.runnables.workflow import BaseWorkflow

import corvo.worker.tasks
import corvo.worker.workflows
from corvo.worker.hatchet_client import hatchet
from corvo.worker.worker import WORKFLOWS

AREAS = [corvo.worker.tasks, corvo.worker.workflows]

type Definition = tuple[str, BaseWorkflow[Any]]


def area_modules(areas: Iterable[ModuleType]) -> list[ModuleType]:
    return [
        importlib.import_module(info.name)
        for area in areas
        for info in pkgutil.walk_packages(area.__path__, f"{area.__name__}.")
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
    defined: Iterable[Definition], registered: list[BaseWorkflow[Any]]
) -> list[str]:
    registered_ids = {id(workflow) for workflow in registered}
    return [
        f"{label} ({workflow.name}) is on no worker: add it to WORKFLOWS"
        for label, workflow in defined
        if id(workflow) not in registered_ids
    ]


def module(name: str, **attributes: object) -> ModuleType:
    built = ModuleType(name)
    vars(built).update(attributes)
    return built


@hatchet.task(name="registration-example")
async def example(input: EmptyModel, ctx: Context) -> None: ...


def test_every_definition_in_the_areas_is_registered() -> None:
    found = problems(definitions(area_modules(AREAS)), WORKFLOWS)

    assert found == []


def test_a_definition_missing_from_the_list_is_named() -> None:
    defined = definitions([module("area.example", example=example)])

    found = problems(defined, [])

    assert found == [
        "area.example.example (registration-example) is on no worker: "
        "add it to WORKFLOWS"
    ]
