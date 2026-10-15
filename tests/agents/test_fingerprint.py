from pathlib import Path

from corvo.agents.fingerprint import fingerprint


def tree(root: Path) -> Path:
    """A corvo package directory with one agent and its core twin."""
    corvo = root / "corvo"
    (corvo / "agents" / "tone" / "prompts").mkdir(parents=True)
    (corvo / "core" / "agents").mkdir(parents=True)
    (corvo / "agents" / "tone" / "agent.py").write_text("MODEL = 'haiku'\n")
    (corvo / "agents" / "tone" / "prompts" / "system.md").write_text("Classify.\n")
    (corvo / "core" / "agents" / "tone.py").write_text("def is_friendly(): ...\n")
    return corvo


def test_the_same_files_give_the_same_fingerprint(tmp_path: Path) -> None:
    assert fingerprint(tree(tmp_path / "a")) == fingerprint(tree(tmp_path / "b"))


def test_one_byte_of_a_prompt_changes_it(tmp_path: Path) -> None:
    corvo = tree(tmp_path)
    before = fingerprint(corvo)

    (corvo / "agents" / "tone" / "prompts" / "system.md").write_text("Classify!\n")

    assert fingerprint(corvo) != before


def test_a_change_to_the_core_twin_changes_it(tmp_path: Path) -> None:
    corvo = tree(tmp_path)
    before = fingerprint(corvo)

    (corvo / "core" / "agents" / "tone.py").write_text("def is_friendly(): 1\n")

    assert fingerprint(corvo) != before


def test_a_stray_bytecode_file_leaves_it_unchanged(tmp_path: Path) -> None:
    corvo = tree(tmp_path)
    before = fingerprint(corvo)

    (corvo / "agents" / "__pycache__").mkdir()
    (corvo / "agents" / "__pycache__" / "x.cpython-314.pyc").write_bytes(b"\0")

    assert fingerprint(corvo) == before


def test_the_installed_tree_has_a_fingerprint() -> None:
    assert len(fingerprint()) == 64
