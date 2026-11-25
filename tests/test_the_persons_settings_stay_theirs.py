"""What a worker inherits from the person running it: nothing.

Measured, which is why this file exists. The same probe, run twice,
differing in one flag and nothing else:

    --setting-sources user   "do your instructions mention a /marketing
                             or /sales agent?"   MENTIONED
    --setting-sources ""                         NOT-MENTIONED

So `~/.claude/CLAUDE.md` was arriving in every worker. On this machine
that is a page about marketing and sales agents, and the run it arrived
in was about a hotel website. With it came the person's `model`, their
`permissions.defaultMode`, an enabled third-party plugin and a block of
organisation text naming an unrelated repository as trusted.

The same pair also measured what must not change: asked to `cat
/etc/hosts`, a worker with `--setting-sources ""` was still refused.
The confinement does not travel with the settings - it arrives by
`--settings`, as inline JSON, which is a different flag.

None of that can be asserted here, because it needs the CLI and a
model. What is asserted is the mechanism it rests on, which is the part
that could be undone by an edit.
"""

import inspect
import json
from pathlib import Path

from drydock import engines

ENGINES = Path("src/drydock/engines.py").read_text()


class TestNoSettingsFileIsLoaded:
    def test_the_flag_is_empty_and_names_no_source(self):
        """The value is "", and no source is named. `--strict-mcp-config`
        sits beside it because MCP configuration is read from places
        `--setting-sources` does not cover."""
        said = engines.SETTING_SOURCES
        assert said[0] == "--setting-sources"
        assert said[1] == ""
        for source in ("user", "project", "local"):
            assert source not in said

    def test_both_ways_of_running_a_worker_pass_it(self):
        """Structured answers and ordinary runs are two command builders.
        A flag in one of them is a flag in half the program."""
        assert ENGINES.count("*SETTING_SOURCES,") == 2

    def test_it_is_one_constant_rather_than_two_literals(self):
        """So the next person to change it changes it everywhere."""
        assert ENGINES.count('"--setting-sources"') == 1


class TestTheWaysOfStoppingItThatWouldCostTooMuch:
    """`--bare` and `--safe-mode` also stop the inheritance. Both also
    turn hooks off, and the hook is the filesystem confinement."""

    def test_neither_is_used(self):
        """As an argument. They are named in the comment explaining why
        they are not passed, which is the opposite of passing them."""
        for flag in ("--bare", "--safe-mode"):
            assert f'"{flag}"' not in ENGINES

    def test_because_the_confinement_is_a_hook(self):
        settings, _env = engines._confinement(Path.cwd())
        assert json.loads(settings)["hooks"]["PreToolUse"]


class TestWhatDrydockStatesItselfIsUnaffected:
    """Everything the run depends on is named on the command line or in
    `--settings`, so dropping the settings files drops none of it."""

    def test_the_model_is_a_flag(self):
        assert '"--model"' in ENGINES

    def test_the_tools_are_a_flag(self):
        assert '"--allowedTools"' in ENGINES
        assert "Read Edit Write Glob Grep " in ENGINES

    def test_the_permission_mode_is_a_flag(self):
        assert '"acceptEdits"' in ENGINES

    def test_the_hook_arrives_by_its_own_flag(self):
        source = inspect.getsource(engines)
        assert '["--settings", settings]' in source
        assert source.count('["--settings", settings]') == 2

    def test_the_matcher_still_names_every_tool_that_touches_a_path(self):
        settings, _env = engines._confinement(Path.cwd())
        matcher = json.loads(settings)["hooks"]["PreToolUse"][0]["matcher"]
        for tool in ("Bash", "Read", "Edit", "Write", "Glob", "Grep"):
            assert tool in matcher

    def test_the_credentials_are_still_taken_out(self):
        _settings, env = engines._confinement(Path.cwd())
        for name in engines.AUTH_THAT_IS_NOT_OURS:
            assert name not in env
