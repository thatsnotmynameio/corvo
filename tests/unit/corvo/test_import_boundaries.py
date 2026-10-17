"""The import boundaries ruff cannot see hold across every module in corvo.

Only corvo.agents imports the Claude Agent SDK, and it imports neither
Hatchet nor the worker; corvo.core imports neither corvo.agents nor the SDK;
the main profile, and the server, reach neither the agent worker's side nor
a module that imports the SDK; the sandbox wrapper imports only the standard
library; the Hatchet adapter, corvo.vendors.hatchet, never imports the worker
that imports it. Ruff cannot check this: corvo.worker, corvo.server.api and
corvo.vendors.hatchet ignore its TID251 bans wholesale, and CI reads no
nested ruff config. This test parses each module's imports and names every
module that crosses a boundary, and the import that does.
"""

import ast
import sys
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

import corvo

SDK = "claude_agent_sdk"

# The main profile's modules, which reach agents only through stubs, and the
# server, which will trigger them through the same stubs. The agents
# profile's modules are imported by name, so nothing here reaches them.
MAIN_PROFILE = (
    "corvo.worker.worker",
    "corvo.worker.profiles",
    "corvo.worker.profiles.main",
)
MAIN_PROFILE_AREAS = (
    "corvo.worker.tasks",
    "corvo.worker.workflows",
    "corvo.worker.event_gateway",
    "corvo.worker.agent_calls",
    "corvo.server",
)
# The agent worker's side, which reaches the SDK through corvo.agents.
AGENT_SIDE = (
    "corvo.worker.agents",
    "corvo.worker.agent_runtime",
    "corvo.worker.profiles.agents",
)

# It runs as the wrapper process before joining its cgroup (KTD20).
SANDBOX = "corvo.worker.agent_runtime.sandbox"

type Imports = dict[str, set[str]]


def within(name: str, package: str) -> bool:
    return name == package or name.startswith(f"{package}.")


def tree_sources(root: Path) -> dict[str, str]:
    """Each module under the corvo package directory, by its dotted name."""
    sources = {}
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root.parent).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        sources[".".join(parts)] = path.read_text()
    return sources


def imported_names(source: str) -> tuple[set[str], bool]:
    """The names a module imports, and whether it imports relatively."""
    names: set[str] = set()
    relative = False
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = True
            elif node.module is not None:
                names.add(node.module)
                # from corvo import worker imports the corvo.worker module.
                names.update(
                    f"{node.module}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
        elif (name := dynamic_import(node)) is not None:
            if name.startswith("."):
                relative = True
            else:
                names.add(name)
    return names, relative


def dynamic_import(node: ast.AST) -> str | None:
    """The module an __import__ or import_module call names in a literal."""
    if not (isinstance(node, ast.Call) and node.args):
        return None
    function = node.func
    if isinstance(function, ast.Name):
        called = function.id
    elif isinstance(function, ast.Attribute):
        called = function.attr
    else:
        return None
    target = node.args[0]
    if called in ("__import__", "import_module") and isinstance(target, ast.Constant):
        return target.value if isinstance(target.value, str) else None
    return None


def internal_edges(names: Iterable[str], modules: Iterable[str]) -> set[str]:
    """The corvo modules importing names runs: each name's own module and
    every package above it, whose __init__ runs first."""
    known = set(modules)
    return {
        prefix
        for name in names
        for prefix in (
            ".".join(name.split(".")[:end]) for end in range(1, name.count(".") + 2)
        )
        if prefix in known
    }


def on_main_profile(module: str) -> bool:
    return module in MAIN_PROFILE or any(
        within(module, area) for area in MAIN_PROFILE_AREAS
    )


def chain_to_agents(start: str, edges: Imports, direct: Imports) -> list[str] | None:
    """The shortest import chain from start to a module on the agent worker's
    side or another corvo module that imports the SDK, or None when there is
    none."""
    previous: dict[str, str] = {}
    queue = deque([start])
    seen = {start}
    while queue:
        current = queue.popleft()
        for target in sorted(edges[current]):
            if target in seen:
                continue
            seen.add(target)
            previous[target] = current
            if any(within(target, side) for side in AGENT_SIDE) or any(
                within(name, SDK) for name in direct[target]
            ):
                chain = [target]
                while chain[-1] != start:
                    chain.append(previous[chain[-1]])
                return chain[::-1]
            queue.append(target)
    return None


def crossing(module: str, names: Iterable[str], banned: str, rule: str) -> list[str]:
    matches = sorted(name for name in names if within(name, banned))
    return [f"{module} imports {matches[0]}: {rule}"] if matches else []


def problems(sources: Mapping[str, str]) -> list[str]:
    direct: Imports = {}
    found: list[str] = []
    for module, source in sources.items():
        direct[module], relative = imported_names(source)
        if relative:
            found.append(
                f"{module} imports relatively, which this check cannot follow: "
                "import absolutely"
            )
    edges = {
        module: internal_edges(names, sources) - {module}
        for module, names in direct.items()
    }

    for module, names in direct.items():
        if within(module, "corvo.agents"):
            for banned in ("hatchet_sdk", "corvo.worker"):
                found += crossing(
                    module,
                    names,
                    banned,
                    "corvo.agents imports neither Hatchet nor corvo.worker",
                )
        else:
            found += crossing(
                module, names, SDK, "only corvo.agents imports the Claude Agent SDK"
            )
        if within(module, "corvo.vendors.hatchet"):
            found += crossing(
                module,
                names,
                "corvo.worker",
                "corvo.vendors.hatchet never imports corvo.worker, which imports it",
            )
        if within(module, "corvo.core"):
            for banned in ("corvo.agents", SDK):
                found += crossing(
                    module,
                    names,
                    banned,
                    "corvo.core imports neither corvo.agents nor the SDK",
                )
        if on_main_profile(module):
            chain = chain_to_agents(module, edges, direct)
            if chain is not None:
                found.append(
                    f"{module} reaches the agents through {' -> '.join(chain)}: "
                    "the main profile reaches agents only through "
                    "corvo.worker.agent_calls' stubs, and imports only corvo.agents "
                    "modules that do not import the SDK, such as its models"
                )
        # The sandbox, and each package above it, whose __init__ runs first.
        if within(SANDBOX, module):
            outside = sorted(
                name
                for name in names
                if name.split(".")[0] not in sys.stdlib_module_names
            )
            if outside:
                found.append(
                    f"{module} imports {outside[0]}: {SANDBOX} runs before it "
                    "joins its cgroup, so it and the packages above it import only "
                    "the standard library"
                )
    return found


def test_the_tree_keeps_the_agents_boundaries() -> None:
    root = Path(corvo.__file__).parent

    assert problems(tree_sources(root)) == []


def test_the_worker_importing_the_sdk_is_named() -> None:
    found = problems({"corvo.worker.agents.x": "import claude_agent_sdk\n"})

    assert found == [
        "corvo.worker.agents.x imports claude_agent_sdk: "
        "only corvo.agents imports the Claude Agent SDK"
    ]


def test_a_name_imported_from_the_sdk_is_named() -> None:
    found = problems({"corvo.server.api.x": "from claude_agent_sdk import query\n"})

    assert found == [
        "corvo.server.api.x imports claude_agent_sdk: "
        "only corvo.agents imports the Claude Agent SDK"
    ]


def test_an_agent_importing_hatchet_is_named() -> None:
    found = problems({"corvo.agents.x.agent": "from hatchet_sdk import Context\n"})

    assert found == [
        "corvo.agents.x.agent imports hatchet_sdk: "
        "corvo.agents imports neither Hatchet nor corvo.worker"
    ]


def test_an_agent_importing_the_worker_is_named() -> None:
    found = problems({"corvo.agents.x.agent": "import corvo.worker.defaults\n"})

    assert found == [
        "corvo.agents.x.agent imports corvo.worker.defaults: "
        "corvo.agents imports neither Hatchet nor corvo.worker"
    ]


def test_an_agent_importing_the_worker_package_by_name_is_named() -> None:
    found = problems({"corvo.agents.x.agent": "from corvo import worker\n"})

    assert found == [
        "corvo.agents.x.agent imports corvo.worker: "
        "corvo.agents imports neither Hatchet nor corvo.worker"
    ]


ADAPTER_RULE = "corvo.vendors.hatchet never imports corvo.worker, which imports it"


@pytest.mark.parametrize(
    ("source", "imported"),
    [
        ("from corvo.worker.defaults import RETRIES\n", "corvo.worker.defaults"),
        ("from corvo import worker\n", "corvo.worker"),
    ],
    ids=["a module", "the package by name"],
)
def test_the_hatchet_adapter_importing_the_worker_is_named(
    source: str, imported: str
) -> None:
    found = problems({"corvo.vendors.hatchet.x": source})

    assert found == [f"corvo.vendors.hatchet.x imports {imported}: {ADAPTER_RULE}"]


def test_the_hatchet_adapter_importing_hatchet_and_itself_is_allowed() -> None:
    source = "import hatchet_sdk\nfrom corvo.vendors.hatchet.client import hatchet\n"

    assert problems({"corvo.vendors.hatchet.x": source}) == []


def test_the_stubs_importing_sdk_free_models_is_allowed() -> None:
    found = problems(
        {
            "corvo.worker.agent_calls": "from corvo.agents.x.models import Out\n",
            "corvo.agents.x.models": "from pydantic import BaseModel\n",
        }
    )

    assert found == []


REACHES_THE_AGENTS = (
    "the main profile reaches agents only through corvo.worker.agent_calls' "
    "stubs, and imports only corvo.agents modules that do not import the SDK, "
    "such as its models"
)


def test_the_main_profile_reaching_the_sdk_through_models_names_the_chain() -> None:
    found = problems(
        {
            "corvo.worker.agent_calls": "from corvo.agents.x.models import Out\n",
            "corvo.agents.x.models": "import corvo.agents.x.agent\n",
            "corvo.agents.x.agent": "from claude_agent_sdk import query\n",
        }
    )

    assert found == [
        "corvo.worker.agent_calls reaches the agents through "
        "corvo.worker.agent_calls -> corvo.agents.x.models -> corvo.agents.x.agent: "
        f"{REACHES_THE_AGENTS}"
    ]


def test_a_package_init_on_the_way_counts() -> None:
    found = problems(
        {
            "corvo.worker.agent_calls": "import corvo.agents.x.models\n",
            "corvo.agents.x": "from claude_agent_sdk import query\n",
            "corvo.agents.x.models": "",
        }
    )

    assert found == [
        "corvo.worker.agent_calls reaches the agents through "
        f"corvo.worker.agent_calls -> corvo.agents.x: {REACHES_THE_AGENTS}"
    ]


AGENT_TASK = {
    "corvo.worker.agents.y": "import corvo.agents.y.agent\n",
    "corvo.agents.y.agent": "from claude_agent_sdk import query\n",
}


@pytest.mark.parametrize("module", ["corvo.worker.workflows.x", "corvo.server.api.x"])
def test_the_main_profile_importing_an_agent_task_is_named(module: str) -> None:
    found = problems({module: "import corvo.worker.agents.y\n", **AGENT_TASK})

    assert found == [
        f"{module} reaches the agents through {module} -> corvo.worker.agents.y: "
        f"{REACHES_THE_AGENTS}"
    ]


def test_an_agent_task_reaching_the_sdk_is_allowed() -> None:
    assert problems(AGENT_TASK) == []


def test_the_worker_importing_the_agents_profile_is_named() -> None:
    found = problems(
        {
            "corvo.worker.worker": "import corvo.worker.profiles.agents\n",
            "corvo.worker.profiles": "",
            "corvo.worker.profiles.agents": "",
        }
    )

    assert found == [
        "corvo.worker.worker reaches the agents through "
        f"corvo.worker.worker -> corvo.worker.profiles.agents: {REACHES_THE_AGENTS}"
    ]


SANDBOX_RULE = (
    "corvo.worker.agent_runtime.sandbox runs before it joins its cgroup, so it "
    "and the packages above it import only the standard library"
)


@pytest.mark.parametrize("imported", ["corvo.worker.defaults", "pydantic"])
def test_the_sandbox_importing_beyond_the_standard_library_is_named(
    imported: str,
) -> None:
    found = problems({"corvo.worker.agent_runtime.sandbox": f"import {imported}\n"})

    assert found == [
        f"corvo.worker.agent_runtime.sandbox imports {imported}: {SANDBOX_RULE}"
    ]


def test_a_package_above_the_sandbox_importing_beyond_it_is_named() -> None:
    found = problems(
        {
            "corvo.worker": "import hatchet_sdk\n",
            "corvo.worker.agent_runtime.sandbox": "import json\nimport os.path\n",
        }
    )

    assert found == [f"corvo.worker imports hatchet_sdk: {SANDBOX_RULE}"]


def test_core_importing_the_agents_is_named() -> None:
    found = problems({"corvo.core.agents.x": "import corvo.agents\n"})

    assert found == [
        "corvo.core.agents.x imports corvo.agents: "
        "corvo.core imports neither corvo.agents nor the SDK"
    ]


def test_an_import_inside_a_function_counts() -> None:
    source = "def run():\n    import claude_agent_sdk\n"

    found = problems({"corvo.worker.agents.x": source})

    assert found == [
        "corvo.worker.agents.x imports claude_agent_sdk: "
        "only corvo.agents imports the Claude Agent SDK"
    ]


def test_a_relative_import_is_named() -> None:
    found = problems({"corvo.worker.agents.x": "from . import y\n"})

    assert found == [
        "corvo.worker.agents.x imports relatively, which this check cannot "
        "follow: import absolutely"
    ]


def test_the_tree_is_read_by_dotted_name(tmp_path: Path) -> None:
    root = tmp_path / "corvo"
    (root / "agents").mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "agents" / "__init__.py").write_text("import a\n")
    (root / "agents" / "tone.py").write_text("import b\n")

    assert tree_sources(root) == {
        "corvo": "",
        "corvo.agents": "import a\n",
        "corvo.agents.tone": "import b\n",
    }


def test_a_dynamic_import_by_name_counts() -> None:
    source = (
        "import importlib\n"
        'importlib.import_module("claude_agent_sdk")\n'
        '__import__("claude_agent_sdk.types")\n'
    )

    found = problems({"corvo.worker.agents.x": source})

    assert found == [
        "corvo.worker.agents.x imports claude_agent_sdk: "
        "only corvo.agents imports the Claude Agent SDK"
    ]
