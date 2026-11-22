"""Twelve items planned against "could you please continue what you do ?"

The first job in a folder said what was being built: an elegant italian
restaurant in Sarasota, who walks in, what the room is like - a paragraph.
The second job in that folder was typed as a follow-up, because by then
there was something on screen to carry on with, and the run record for it
reads:

    "task": "could you please continue what you do ?"

That sentence was then handed to the single start call as the whole of
what was being asked for, and to the engineer on all twelve items as
"Overall task, for context only". The restaurant was never mentioned to
anybody. The paragraph still existed - it was sitting in the repository's
memory under `jobs` - and nothing read it back.

So: the objective is kept once, per repository, and carried on the run
record, where planning, every retry and a resume days later all read the
same one. A follow-up adds to it or revises it. It does not replace it.
"""

import inspect
import json
from pathlib import Path

from drydock import engineer, orchestrate
from drydock.memory import Memory
from drydock.models import Item
from drydock.run import Run
from drydock.session import Session

BRIEF = (
    "I am planning to open a new italian restaurant in Sarasota. It should "
    "be elegant, with a short menu and a room that feels like somewhere you "
    "would propose."
)
FOLLOW_UP = "could you please continue what you do ?"


class TestTheObjectiveIsKeptOnce:
    def test_the_first_job_sets_it(self, tmp_path):
        m = Memory(repo=str(tmp_path))
        assert m.aim(BRIEF) == BRIEF
        assert m.objective_at

    def test_a_follow_up_does_not_replace_it(self, tmp_path):
        m = Memory(repo=str(tmp_path))
        m.aim(BRIEF)
        assert m.aim(FOLLOW_UP) == BRIEF
        assert m.objective == BRIEF

    def test_a_blank_task_does_not_claim_the_objective(self, tmp_path):
        m = Memory(repo=str(tmp_path))
        assert m.aim("   \n ") == ""
        assert m.aim(BRIEF) == BRIEF

    def test_it_survives_being_written_and_read_back(self, tmp_path):
        m = Memory(repo=str(tmp_path))
        m.aim(BRIEF)
        m.save()
        again = Memory.about(tmp_path)
        assert again.objective == BRIEF
        assert again.objective_at == m.objective_at

    def test_a_memory_saved_before_this_existed_still_loads(self, tmp_path):
        """Older files have no objective field at all, and a repository
        that cannot read its own memory is a repository with none."""
        m = Memory(repo=str(tmp_path))
        m.save()
        raw = json.loads(m.path.read_text())
        del raw["objective"]
        del raw["objective_at"]
        m.path.write_text(json.dumps(raw))
        again = Memory.about(tmp_path)
        assert again.objective == ""
        assert again.aim(BRIEF) == BRIEF


class TestTheBriefEveryStationReads:
    def test_both_the_objective_and_this_instruction_are_in_it(self):
        run = Run.start(Path("/x"), FOLLOW_UP)
        run.objective = BRIEF
        assert BRIEF in run.brief
        assert FOLLOW_UP in run.brief

    def test_the_objective_comes_first(self):
        run = Run.start(Path("/x"), FOLLOW_UP)
        run.objective = BRIEF
        assert run.brief.index(BRIEF) < run.brief.index(FOLLOW_UP)

    def test_the_follow_up_is_said_to_revise_rather_than_replace(self):
        run = Run.start(Path("/x"), FOLLOW_UP)
        run.objective = BRIEF
        assert "does not replace it" in run.brief

    def test_nothing_is_said_twice_on_the_first_job(self):
        """The job that set the objective typed it. Handing it to the
        planner twice is noise, and on a long brief it is expensive
        noise."""
        run = Run.start(Path("/x"), BRIEF)
        run.objective = BRIEF
        assert run.brief == BRIEF

    def test_a_run_with_no_objective_is_unchanged(self):
        run = Run.start(Path("/x"), FOLLOW_UP)
        assert run.brief == FOLLOW_UP

    def test_it_survives_a_resume(self, tmp_path, monkeypatch):
        """A resume reads the run back off disk days later. The objective
        has to be on the record for that, not looked up from anywhere."""
        monkeypatch.chdir(tmp_path)
        run = Run.start(Path("/x"), FOLLOW_UP)
        run.objective = BRIEF
        run.save()
        again = Run.model_validate_json(run.path.read_text())
        assert again.objective == BRIEF
        assert BRIEF in again.brief

    def test_a_record_saved_before_this_existed_reads_back(self):
        old = json.dumps(
            {
                "id": "20261119-120000",
                "repo": "/x",
                "task": FOLLOW_UP,
                "started": "2026-11-19T12:00:00+00:00",
            }
        )
        assert Run.model_validate_json(old).brief == FOLLOW_UP


class TestWhoIsHandedIt:
    def test_the_single_start_call_plans_against_the_brief(self):
        source = inspect.getsource(Session._begin_it)
        assert "self.run.brief," in source
        assert "self.task," not in source

    def test_the_objective_is_taken_before_the_standing_instructions(self):
        """They hold for every job here, so they are not part of what this
        one is for, and an objective carrying them would repeat them in
        every brief for the life of the repository."""
        source = inspect.getsource(Session._work)
        assert source.index("self.memory.aim(self.task)") < source.index(
            "Standing instructions for this repository"
        )

    def test_the_engineer_is_handed_the_brief_on_every_attempt(self):
        source = inspect.getsource(orchestrate._one_item)
        # `as_briefed` is the brief and then, below it, what the brief was
        # taken to mean. The request is still the first thing the engineer
        # reads and still outranks the rest - see
        # test_a_sentence_is_not_a_brief.
        assert "run.as_briefed," in source
        assert "run.task," not in source

    def test_the_engineer_prompt_carries_it(self):
        prompt = engineer.PROMPT.format(
            repo="ca-serena",
            build_command="npm run build",
            shell="you may run npm",
            task=f"{BRIEF}\n\n{FOLLOW_UP}",
            id=7,
            title="Add src/views/home.js",
            rationale="r",
            files="src/views/home.js",
            verify_with="tests",
            criteria="the page carries the six things",
        )
        assert BRIEF in prompt
        assert "the item below is still the whole of what you touch" in prompt

    def test_the_prompt_no_longer_says_the_brief_is_only_context(self):
        """ "For context only" is an instruction to ignore it, and it was
        read as one."""
        assert "for context only" not in engineer.PROMPT


def _prompt_given(monkeypatch, retry_of: str) -> str:
    """What the engineer is actually handed, without running a worker."""
    seen = {}

    class Fake:
        def __init__(self, **_):
            pass

        def work(self, repo, system, prompt, build_command, on_event=None, **_):
            seen["prompt"] = prompt
            return engineer.EngineResult(
                done=True, summary="", files_changed=[], noticed=[], turns=1
            )

    monkeypatch.setattr(engineer, "ClaudeCodeEngine", Fake)
    monkeypatch.setattr(engineer, "briefing", lambda skills, role: "")
    engineer.work(
        Path("/tmp"),
        f"{BRIEF}\n\nAnd now: {FOLLOW_UP}",
        Item(id=1, title="t", rationale="r", files=[], verify_with="tests"),
        "npm run build",
        retry_of=retry_of,
        engine="claude",
        model="opus",
    )
    return seen["prompt"]


class TestARetryKnowsItToo:
    """The run that lost the brief lost it on all twelve items and on
    every retry of them. A retry is the attempt that must not fail."""

    def test_a_first_attempt_is_told_what_is_being_built(self, monkeypatch):
        assert BRIEF in _prompt_given(monkeypatch, retry_of="")

    def test_a_retry_is_told_the_same_thing(self, monkeypatch):
        prompt = _prompt_given(monkeypatch, retry_of="the critic sent it back")
        assert BRIEF in prompt
        assert "the critic sent it back" in prompt
