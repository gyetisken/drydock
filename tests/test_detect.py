"""Working out how a repository builds itself.

A package.json means npm. It does not mean `npm run build` exists, and
assuming it does rolled back a finished item for 'does not compile' when
nothing had failed to compile and there was nothing to compile.
"""

import json
from pathlib import Path

from drydock.detect import detect


def node(tmp_path: Path, scripts: dict) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": scripts}))


def test_a_project_with_a_build_script_uses_it(tmp_path):
    node(tmp_path, {"build": "tsc", "test": "vitest run"})
    chain = detect(tmp_path)
    assert chain.build_command == "npm run build"
    assert chain.test_command == "npm test"


def test_a_project_with_no_build_step_is_checked_by_its_tests(tmp_path):
    """The actual bug: no build script, so the build check could never pass."""
    node(tmp_path, {"start": "node server.js", "test": "node --test"})
    chain = detect(tmp_path)
    assert chain.build_command == "npm test"
    assert chain.test_command == "npm test"


def test_compile_counts_as_a_build(tmp_path):
    node(tmp_path, {"compile": "tsc -b", "test": "jest"})
    assert detect(tmp_path).build_command == "npm run compile"


def test_a_project_with_neither_claims_neither(tmp_path):
    node(tmp_path, {"start": "node ."})
    chain = detect(tmp_path)
    assert chain.build_command == ""
    assert chain.test_command == ""


def test_an_unreadable_manifest_does_not_take_the_run_down(tmp_path):
    (tmp_path / "package.json").write_text("{ not json")
    assert detect(tmp_path).build_tool == "npm"


def test_maven_is_left_alone(tmp_path):
    (tmp_path / "pom.xml").write_text("<project/>")
    chain = detect(tmp_path)
    assert chain.build_tool == "Maven"
    assert chain.build_command.startswith("mvn")
