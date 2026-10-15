"""The agents' import boundaries hold across every module in corvo.

Only corvo.agents imports the Claude Agent SDK, and it imports neither
Hatchet nor the worker; the worker reaches no corvo module that imports the
SDK; corvo.core imports neither corvo.agents nor the SDK. Ruff cannot check
this: corvo.worker and corvo.server.api ignore its TID251 bans wholesale, and
CI reads no nested ruff config. This test parses each module's imports and
names every module that crosses a boundary, and the import that does.
"""

import ast
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path

import corvo

SDK = "claude_agent_sdk"

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
    return names, relative


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


def chain_to_sdk(start: str, edges: Imports, direct: Imports) -> list[str] | None:
    """The shortest import chain from start to another corvo module that
    imports the SDK, or None when there is none."""
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
            if any(within(name, SDK) for name in direct[target]):
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
        if within(module, "corvo.core"):
            for banned in ("corvo.agents", SDK):
                found += crossing(
                    module,
                    names,
                    banned,
                    "corvo.core imports neither corvo.agents nor the SDK",
                )
        if within(module, "corvo.worker"):
            chain = chain_to_sdk(module, edges, direct)
            if chain is not None:
                found.append(
                    f"{module} reaches the Claude Agent SDK through "
                    f"{' -> '.join(chain)}: the worker imports only corvo.agents "
                    "modules that do not import the SDK, such as its models"
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


def test_the_worker_importing_sdk_free_models_is_allowed() -> None:
    found = problems(
        {
            "corvo.worker.agents.x": "from corvo.agents.x.models import Out\n",
            "corvo.agents.x.models": "from pydantic import BaseModel\n",
        }
    )

    assert found == []


def test_the_worker_reaching_the_sdk_through_models_names_the_chain() -> None:
    found = problems(
        {
            "corvo.worker.agents.x": "from corvo.agents.x.models import Out\n",
            "corvo.agents.x.models": "import corvo.agents.x.agent\n",
            "corvo.agents.x.agent": "from claude_agent_sdk import query\n",
        }
    )

    assert found == [
        "corvo.worker.agents.x reaches the Claude Agent SDK through "
        "corvo.worker.agents.x -> corvo.agents.x.models -> corvo.agents.x.agent: "
        "the worker imports only corvo.agents modules that do not import the SDK, "
        "such as its models"
    ]


def test_a_package_init_on_the_way_counts() -> None:
    found = problems(
        {
            "corvo.worker.agents.x": "import corvo.agents.x.models\n",
            "corvo.agents.x": "from claude_agent_sdk import query\n",
            "corvo.agents.x.models": "",
        }
    )

    assert found == [
        "corvo.worker.agents.x reaches the Claude Agent SDK through "
        "corvo.worker.agents.x -> corvo.agents.x: "
        "the worker imports only corvo.agents modules that do not import the SDK, "
        "such as its models"
    ]


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
