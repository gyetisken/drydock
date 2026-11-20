"""A worker decided the shell was shut because one command was refused.

The paytest engineer, read out of its own session:

    Bash  find ... -not -path "*/node_modules/*"      -> succeeded
    Bash  node --check a && node --check b            -> requires approval
    Bash  for f in ...; do node --check "$f"; done    -> contains simple_expansion
    Bash  node --check a; node --check b              -> requires approval
    Bash  node --check src/payments.js                -> requires approval
    text  "Bash isn't permitted here, so I'll verify by reading the files
           I changed."

The rule it was given was `Bash(npm *)`. `node` is not `npm`, so those
four were refused correctly. What went wrong is the conclusion: it never
tried `npm test`, which it was allowed to run the whole time, and
delivered the item without running the suite once. The verifier ran it
afterwards and it passed, so nothing broke - but the engineer shipped
work it had never executed.

The refusal does not say what is allowed, so a worker can only learn the
fence by walking into it, and four turns of walking into it reads as a
wall. So it is told, in words, derived from the same build command the
rule is derived from - the two drifting apart is how this class of bug
starts.
"""

import inspect

from drydock import engineer
from drydock.engines import BOOTSTRAP, _shell_rule, shell_allowance


def flat(text: str) -> str:
    return " ".join(text.split())


class TestWhatItSaysWhenThereIsABuildCommand:
    def test_it_names_the_command_that_works(self):
        said = shell_allowance("npm test")
        assert "`npm`" in said
        assert "`npm test`" in said

    def test_it_says_the_rest_are_refused(self):
        assert "Anything else is refused" in shell_allowance("npm test")

    def test_it_says_a_refusal_is_not_a_closed_shell(self):
        """The exact wrong conclusion the engineer drew."""
        said = shell_allowance("npm test")
        assert "not a sign that the shell is unavailable" in said
        assert "if one command is turned down, `npm` still works" in said

    def test_it_follows_the_rule_rather_than_restating_it(self):
        """Derived from the same build command, so the sentence and the
        permission cannot drift apart."""
        for command in ("npm test", "mvn -B test", "cargo test", "go test ./..."):
            tool = command.split()[0]
            assert f"Bash({tool} *)" == _shell_rule(command)
            assert f"`{tool}`" in shell_allowance(command)

    def test_the_source_says_where_it_comes_from(self):
        source = inspect.getsource(shell_allowance)
        assert "_shell_rule" in source


class TestWhatItSaysOnAGreenfieldJob:
    def test_it_describes_the_bootstrap_list_instead(self):
        said = shell_allowance("")
        assert "no build command yet" in said
        for name in ("npm", "node", "python"):
            assert f"`{name}`" in said

    def test_it_still_says_the_rest_are_refused(self):
        said = shell_allowance("")
        assert "Anything else is refused" in said
        assert "not a sign that the shell is unavailable" in said

    def test_the_bootstrap_list_is_the_one_the_rule_uses(self):
        rule = _shell_rule("")
        for name in BOOTSTRAP[:8]:
            assert f"Bash({name} *)" in rule


class TestTheEngineerIsToldAtAll:
    def test_the_prompt_has_a_place_for_it(self):
        assert "{shell}" in engineer.PROMPT

    def test_it_is_built_from_the_build_command(self):
        source = inspect.getsource(engineer.work)
        assert "shell=shell_allowance(build_command)" in source

    def test_it_sits_with_the_build_line(self):
        said = flat(engineer.PROMPT)
        assert said.index("{build_command}") < said.index("{shell}")
        assert said.index("{shell}") < said.index("{task}")


class TestNoPermissionWasBroadened:
    def test_the_rule_itself_is_untouched(self):
        assert _shell_rule("npm test") == "Bash(npm *)"
        assert _shell_rule("npm test", can_look=True) == (
            "Bash(npm *) Bash(drydock-look) Bash(drydock-look *)"
        )

    def test_nothing_new_is_allowed_on_a_greenfield_job(self):
        rule = _shell_rule("")
        assert rule.count("Bash(") == len(BOOTSTRAP)

    def test_the_allowance_is_prose_and_not_a_rule(self):
        """It must not look like something that grants anything."""
        said = shell_allowance("npm test")
        assert "Bash(" not in said
        assert "--allowedTools" not in said

    def test_the_engineers_other_tools_are_unchanged(self):
        from pathlib import Path

        text = Path("src/drydock/engines.py").read_text()
        assert '"Read Edit Write Glob Grep "' in text
