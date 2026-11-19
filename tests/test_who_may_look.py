"""Who gets the look command, and what it does not buy them.

The capability is one allow-rule on one command, and it is handed out per
item rather than per run: an item that writes a migration has nothing to
look at, and giving it a browser is surface for no gain. The rule, the
budget and the briefing all have to agree - a worker told to look with no
rule spends turns on a command it cannot run, and a worker with the rule
and no briefing never runs it at all.

What it must not buy: a gate. The verifier builds, the inspector reads, the
reviewer reads against the item and the critic looks, and none of them is
told that the engineer looked. That is the line this whole thing is
balanced on, so it is pinned here.
"""

import inspect
import os
from pathlib import Path

import pytest

from drydock import engineer, orchestrate
from drydock.engines import LOOK, _confinement, _shell_rule
from drydock.models import Item
from drydock.policy import of


def flat(text: str) -> str:
    """One line, so an assertion is not a claim about where it wraps."""
    return " ".join(text.split())


def item(**kw) -> Item:
    return Item(
        **{
            "id": 1,
            "title": "t",
            "rationale": "r",
            "files": ["src/server.js"],
            "verify_with": "tests",
            **kw,
        }
    )


class TestTheRule:
    def test_it_is_absent_unless_asked_for(self):
        assert LOOK not in _shell_rule("npm run build")
        assert LOOK not in _shell_rule("")

    def test_asked_for_it_is_two_exact_forms(self):
        """Useful with no argument - that is the home page - and with one
        path. Nothing else."""
        rule = _shell_rule("npm run build", can_look=True)
        assert f"Bash({LOOK})" in rule
        assert f"Bash({LOOK} *)" in rule

    def test_the_build_command_is_still_the_only_other_thing(self):
        rule = _shell_rule("npm run build", can_look=True)
        assert rule.count("Bash(") == 3
        assert "Bash(npm *)" in rule

    def test_it_does_not_widen_a_greenfield_worker(self):
        """Before a project has a build command the worker already has the
        bootstrap list. Looking adds one command to it, not a shell."""
        before = _shell_rule("")
        after = _shell_rule("", can_look=True)
        assert after.count("Bash(") == before.count("Bash(") + 2


class TestTheEnvironment:
    def test_nothing_is_added_when_nobody_may_look(self, tmp_path):
        _settings, env = _confinement(tmp_path)
        assert "DRYDOCK_LOOK_KEY" not in env
        assert "DRYDOCK_LOOK_LIMIT" not in env

    def test_the_budget_travels_in_the_environment(self, tmp_path):
        _settings, env = _confinement(tmp_path, look_key="r-item2", looks=3)
        assert env["DRYDOCK_LOOK_KEY"] == "r-item2"
        assert env["DRYDOCK_LOOK_LIMIT"] == "3"

    def test_the_command_is_put_on_the_path_and_runs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        _settings, env = _confinement(tmp_path, look_key="r-item2", looks=1)
        first = Path(env["PATH"].split(os.pathsep)[0])
        tool = first / LOOK
        assert tool.exists()
        assert os.access(tool, os.X_OK)
        assert tool.read_text().startswith("#!/bin/sh")

    def test_the_confinement_hook_is_untouched_by_it(self, tmp_path):
        """The worker's file tools stay inside the repository whether or
        not it can look. The tally lives outside, which is the point."""
        plain, _ = _confinement(tmp_path)
        looking, _ = _confinement(tmp_path, look_key="r-item2", looks=3)
        assert plain == looking
        assert "drydock.confine" in looking

    def test_the_root_is_still_the_repository(self, tmp_path):
        _settings, env = _confinement(tmp_path, look_key="r-item2", looks=3)
        assert env["DRYDOCK_ROOT"] == str(tmp_path.resolve())


class TestWhoGetsIt:
    def test_an_item_the_planner_called_visual(self):
        assert orchestrate._worth_a_look(item(worth_looking_at=True))

    def test_an_item_the_planner_ruled_out(self):
        assert not orchestrate._worth_a_look(item(worth_looking_at=False))

    @pytest.mark.parametrize(
        "files",
        [
            ["public/styles.css"],
            ["src/views/home.js"],
            ["index.html"],
            ["app/components/Hero.tsx"],
        ],
    )
    def test_the_files_decide_when_the_planner_did_not(self, files):
        assert orchestrate._worth_a_look(item(files=files))

    @pytest.mark.parametrize(
        "files", [["src/lib/hours.js"], ["migrations/004_add_column.sql"], []]
    )
    def test_an_item_with_nothing_to_see_does_not_get_it(self, files):
        assert not orchestrate._worth_a_look(item(files=files))

    def test_it_is_decided_before_the_work_exists(self):
        """`_changes_the_view` reads a diff, and there is no diff yet.
        This is asked when the item is handed out."""
        source = inspect.getsource(orchestrate._worth_a_look)
        assert "item.files" in source
        assert "diff" not in source.replace("the diff", "")

    def test_the_key_names_the_run_and_the_item(self):
        source = inspect.getsource(orchestrate._one_item)
        assert 'look_key=f"{run.id}-item{item.id}"' in source
        assert "can_look=_worth_a_look(item)" in source


class TestTheEngineerSideOfIt:
    def _built(self, monkeypatch, **kw):
        seen = {}

        class Fake:
            def __init__(self, **_):
                pass

            def work(self, repo, system, prompt, build_command, on_event=None, **extra):
                seen["system"] = system
                seen.update(extra)
                return engineer.EngineResult(
                    done=True, summary="", files_changed=[], noticed=[], turns=1
                )

        monkeypatch.setattr(engineer, "ClaudeCodeEngine", Fake)
        monkeypatch.setattr(engineer, "briefing", lambda skills, role: "")
        engineer.work(
            Path("/tmp"),
            "a task",
            item(),
            "npm run build",
            engine="claude",
            model="opus",
            policy=of("balanced"),
            **kw,
        )
        return seen

    def test_a_worker_that_may_not_look_is_not_told_about_looking(self, monkeypatch):
        built = self._built(monkeypatch)
        assert built["looks"] == 0
        assert LOOK not in built["system"]

    def test_a_worker_that_may_look_is_told_how(self, monkeypatch):
        built = self._built(monkeypatch, can_look=True, look_key="r-item1")
        assert built["looks"] == of("balanced").self_looks
        assert LOOK in built["system"]
        assert "Open every picture it names with Read" in flat(built["system"])

    def test_it_is_told_how_many_it_has(self, monkeypatch):
        built = self._built(monkeypatch, can_look=True, look_key="r-item1")
        assert f"You have {of('balanced').self_looks} of these" in flat(built["system"])

    def test_it_is_told_that_this_is_not_the_check(self, monkeypatch):
        built = self._built(monkeypatch, can_look=True, look_key="r-item1")
        assert "not a check that counts" in built["system"]
        assert "somebody who is not you" in built["system"]

    def test_it_is_told_what_not_looked_means(self, monkeypatch):
        """The failure this exists to prevent is a report describing a
        page nobody rendered."""
        built = self._built(monkeypatch, can_look=True, look_key="r-item1")
        assert "NOT LOOKED" in built["system"]
        assert "Describing a page you have not seen" in flat(built["system"])

    def test_no_key_means_no_looking_however_it_was_asked(self, monkeypatch):
        """Without a key the tally has nothing to count against, and an
        uncounted budget is no budget."""
        built = self._built(monkeypatch, can_look=True, look_key="")
        assert built["looks"] == 0
        assert LOOK not in built["system"]

    def test_the_api_engine_is_not_offered_something_it_cannot_run(self):
        """It has no shell at all by design, so there is nothing there to
        run the tool with."""
        source = inspect.getsource(engineer.work)
        assert 'engine == "claude"' in source[: source.index("briefed =")]

    def test_the_scope_rule_is_untouched(self):
        """Looking at the page is not permission to widen the item."""
        assert "The item you are given is the entire scope" in engineer.SYSTEM
        assert "Do not touch the verification" in engineer.SYSTEM


class TestItDoesNotReplaceAnybody:
    def test_the_gates_do_not_know_whether_the_engineer_looked(self):
        """If any of them read it, looking becomes a way to be believed."""
        for name in ("orchestrate", "critic", "reviewer", "inspect", "verify"):
            source = Path(f"src/drydock/{name}.py").read_text()
            assert "DRYDOCK_LOOK" not in source, name
            assert "self_looks" not in source, name

    def test_the_report_has_no_field_for_it(self):
        source = inspect.getsource(engineer._report_tool)
        assert "look" not in source.lower()

    def test_the_critic_still_measures_the_page_itself(self):
        source = inspect.getsource(orchestrate._show_it)
        assert "probe.look(" in source
        assert "why_it_does_not_fit(" in source

    def test_nothing_about_the_attempt_budget_changed(self):
        plain = of("balanced")
        assert (plain.turns, plain.minutes, plain.attempts) == (60, 12.0, 2)
