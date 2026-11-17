"""What the worker is allowed to run.

The bound on the worker is the directory it may touch and the commands it may
run. The second one used to be derived by splitting the build command, which
worked for every repository that already had one and crashed on every
repository that did not - which is to say, on every greenfield job, at the
first item, every time.
"""

from drydock.engines import BOOTSTRAP, _shell_rule


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
