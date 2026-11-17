"""The crew stays in the repository it was pointed at.

This is not a prompt rule and must not become one. A worker that reads
whatever it likes on somebody's machine is wrong even on the runs where it
behaves, and the run that found this bug behaved perfectly: it surveyed the
wrong codebase very competently.
"""

from pathlib import Path

from drydock.confine import offending


def call(tool: str, **args) -> dict:
    return {"tool_name": tool, "tool_input": args}


ROOT = Path("/tmp/a-project").resolve()


def test_a_file_in_the_project_is_allowed():
    assert offending(call("Read", file_path=str(ROOT / "src/main.py")), ROOT) is None


def test_a_file_above_the_project_is_refused():
    assert offending(call("Read", file_path="/tmp/secrets.env"), ROOT)


def test_the_parent_directory_is_refused():
    """The actual bug: an empty project, so it looked upwards."""
    assert offending(call("Grep", pattern="x", path=str(ROOT.parent)), ROOT)


def test_writing_outside_is_refused_too():
    assert offending(call("Edit", file_path="/etc/hosts"), ROOT)
    assert offending(
        call("Write", file_path=str(Path.home() / ".ssh/authorized_keys")), ROOT
    )


def test_an_absolute_pattern_counts_as_a_path():
    assert offending(call("Glob", pattern="/Users/someone/**"), ROOT)


def test_a_relative_pattern_is_not_a_path():
    assert offending(call("Glob", pattern="**/*.py", path=str(ROOT)), ROOT) is None


def test_a_call_with_no_path_is_not_this_guard_s_business():
    assert offending(call("Bash", command="ls"), ROOT) is None
