"""The picker said Opus and Sonnet did the work.

`WORK_MODEL` mapped "opus" to "sonnet", and `engineer.work` applied it to
every attempt that was not a retry. So a run whose record said
`model: opus` had its code - the only station that writes any - typed by
Sonnet, and Opus appeared only after an item had already been refused
once.

The reasoning behind it was sound and it is kept: the engineer is three
quarters of a run's wall clock and the most heavily checked station, so a
faster model there costs least. What was wrong was that it happened in a
dict, with nothing anywhere saying it had happened, under a picker whose
whole job is to let somebody choose the model. A saving nobody can see is
indistinguishable from a bug, and for weeks it was read as one.

Now the chosen model does the typing, and the saving is a flag somebody
sets on purpose.
"""

import ast
import inspect
from pathlib import Path

import pytest

from drydock import engineer
from drydock.agent import CHEAP_ENGINEER, CHEAPER, cheap_engineer, for_work

SOURCE = inspect.getsource(engineer.work)


@pytest.fixture(autouse=True)
def _unset(monkeypatch):
    """Every test here says for itself whether the flag is set."""
    monkeypatch.delenv(CHEAP_ENGINEER, raising=False)


class TestWhatYouChoseIsWhatRuns:
    @pytest.mark.parametrize("chosen", ["opus", "sonnet", "haiku"])
    def test_the_chosen_model_does_the_typing(self, chosen):
        assert for_work(chosen) == chosen

    def test_opus_is_not_quietly_sonnet(self):
        """The one that was actually happening."""
        assert for_work("opus") == "opus"

    def test_a_model_nobody_mapped_is_passed_through(self):
        assert for_work("claude-opus-5") == "claude-opus-5"


class TestTheSavingIsStillAvailable:
    def test_it_is_off_unless_it_is_asked_for(self, monkeypatch):
        assert cheap_engineer() is False
        monkeypatch.setenv(CHEAP_ENGINEER, "1")
        assert cheap_engineer() is True

    def test_asked_for_by_name_it_routes_opus_to_sonnet(self, monkeypatch):
        monkeypatch.setenv(CHEAP_ENGINEER, "1")
        assert for_work("opus") == "sonnet"

    def test_only_a_1_turns_it_on(self, monkeypatch):
        """An env var left lying around as "0" or "false" is not consent."""
        for value in ("0", "", "false", "no"):
            monkeypatch.setenv(CHEAP_ENGINEER, value)
            assert for_work("opus") == "opus", value

    def test_the_cheapest_choice_is_never_overridden(self, monkeypatch):
        monkeypatch.setenv(CHEAP_ENGINEER, "1")
        assert for_work("haiku") == "haiku"
        assert CHEAPER["haiku"] == "haiku"


class TestTheEngineerUsesIt:
    def test_both_engines_type_with_the_same_model(self):
        """The API path used to call `for_work` a second time of its own.
        Two copies of a routing decision drift apart, and one of them is
        the one nobody reads."""
        assert SOURCE.count("for_work(") == 1
        assert "model=typing," in SOURCE
        assert "model=API_MODEL.get(typing, JUDGEMENT)" in SOURCE

    def test_a_retry_runs_on_the_model_that_was_chosen(self):
        assert "typing = model if retry_of else for_work(model)" in SOURCE

    def test_routing_is_announced_when_it_happens(self):
        assert "if typing != model and on_event:" in SOURCE
        said = SOURCE[SOURCE.index("if typing != model") :]
        assert 'on_event(\n            "model",' in said
        assert CHEAP_ENGINEER in said or "{CHEAP_ENGINEER}" in said

    def test_nothing_else_routes_a_model_behind_anybody(self):
        """Any other station that quietly downgrades is the same bug
        again, so the only call to `for_work` in the package is the
        engineer's."""
        calls = []
        for path in Path("src/drydock").glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "for_work"
                ):
                    calls.append(f"{path.name}:{node.lineno}")
        assert [c.split(":")[0] for c in calls] == ["engineer.py"], calls
