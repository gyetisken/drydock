"""Whatever a station refuses, it cannot refuse the file it answers in.

Every structured call comes back through one file: the engine appends
`Write(.drydock-out.json)` to what the worker is allowed. A station that
also lists `Write` among the tools it does not want leaves a worker that
can read the repository, run commands, and has nowhere to put what it
found.

Written twice. The first time was the start call, which span for three
minutes with nothing to show. The second was the answering path, where
`hey, how are you today ?` came back as

    EngineUnavailable: the worker stopped without writing an answer (exit 1)

Twice is what made it the engine's business rather than each caller's.
"""

import inspect
import re

import pytest

from drydock import answer, engines, start


class TestTheEngineKeepsIt:
    @pytest.mark.parametrize(
        "asked,left",
        [
            ("Bash Read Write Edit", "Bash Read Edit"),
            ("Write", ""),
            ("Bash Edit NotebookEdit", "Bash Edit NotebookEdit"),
            ("", ""),
        ],
    )
    def test_write_is_taken_back_out_of_what_was_refused(self, asked, left):
        assert engines._but_not_the_answer(asked) == left

    def test_everything_else_is_refused_as_asked(self):
        asked = "Bash Read Glob Grep Edit NotebookEdit WebFetch WebSearch Task"
        assert engines._but_not_the_answer(asked) == asked

    def test_the_flag_goes_through_it(self):
        source = inspect.getsource(engines.ClaudeCodeEngine.structured)
        assert "_but_not_the_answer(without)" in source
        assert '"--disallowedTools", without' not in source


class TestNoStationAsksForIt:
    """The engine strips it, and the callers still do not ask - so the
    reason is written where somebody changing one of them will read it."""

    @pytest.mark.parametrize("where", [answer.ask, start.begin])
    def test_write_is_not_in_the_refused_list(self, where):
        source = inspect.getsource(where)
        for refused in re.findall(r'"without": "([^"]*(?:"\s*"[^"]*)*)"', source):
            assert "Write" not in refused, source
        for refused in re.findall(r'without="([^"]*(?:"\s*"[^"]*)*)"', source):
            assert "Write" not in refused, source

    def test_the_whole_module_set_is_checked(self):
        """Every station that asks for a structured answer, not only the
        two that got it wrong."""
        import pkgutil

        import drydock

        asked_anywhere = []
        for info in pkgutil.iter_modules(drydock.__path__):
            module = __import__(f"drydock.{info.name}", fromlist=["x"])
            source = inspect.getsource(module)
            for refused in re.findall(r'without="([^"]*(?:"\s*"[^"]*)*)"', source):
                if "Write" in refused:
                    asked_anywhere.append(info.name)
        assert asked_anywhere == [], (
            f"these refuse the file they answer in: {asked_anywhere}"
        )
