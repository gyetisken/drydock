"""What the worker is allowed to run.

The bound on the worker is the directory it may touch and the commands it may
run. The second one used to be derived by splitting the build command, which
worked for every repository that already had one and crashed on every
repository that did not - which is to say, on every greenfield job, at the
first item, every time.
"""

import pytest

from drydock.engines import BOOTSTRAP, ClaudeCodeEngine, EngineUnavailable, _shell_rule


def test_worker_configuration_does_not_require_claude_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    engine = ClaudeCodeEngine(model="sonnet", max_turns=7, minutes=1.5)
    assert (engine.model, engine.max_turns, engine.seconds) == ("sonnet", 7, 90)


@pytest.mark.parametrize(
    "method,argument,filename",
    [
        ("work", "npm run build", ".drydock-report.json"),
        ("structured", "{}", ".drydock-out.json"),
    ],
)
def test_launch_requires_claude_before_touching_the_repository(
    tmp_path, monkeypatch, method, argument, filename
):
    monkeypatch.setenv("PATH", str(tmp_path))
    scratch_file = tmp_path / filename
    scratch_file.write_text("existing file")
    engine = ClaudeCodeEngine()
    with pytest.raises(EngineUnavailable, match="claude.*not on PATH"):
        getattr(engine, method)(tmp_path, "system", "task", argument)
    assert scratch_file.read_text() == "existing file"


def test_a_project_with_a_build_command_is_held_to_it():
    assert _shell_rule("mvn -B -q compile") == "Bash(mvn *)"
    assert _shell_rule("npm run build") == "Bash(npm *)"


def test_a_project_with_no_build_command_still_gets_a_rule():
    rule = _shell_rule("")
    assert rule
    assert "Bash(npm *)" in rule
    assert "Bash(uv *)" in rule


def test_whitespace_is_not_a_build_command():
    assert _shell_rule("   ") == _shell_rule("")


def test_the_bootstrap_list_has_nothing_that_deletes_or_fetches():
    for name in BOOTSTRAP:
        assert name not in {"rm", "curl", "wget", "sudo", "ssh", "bash", "sh", "eval"}
