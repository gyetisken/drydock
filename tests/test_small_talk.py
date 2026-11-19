"""Saying hello to a thing that reads repositories for a living.

Typed into the application: `hello, how are you today ?`. It routed to
the question path, which read the repository, and came back with a
paragraph on which files were tracked, what the one commit contained, and
an offer to build the site - none of which was asked for. It also took
its time about it, because reading a project is what that path does.

Two different mistakes. Routing a hello to the question path is right:
nothing is being changed. Reading a repository to answer it is not.
"""

import inspect

import pytest

from drydock import answer
from drydock.intent import is_small_talk, read


class TestWhatCountsAsSmallTalk:
    @pytest.mark.parametrize(
        "said",
        [
            "hello, how are you today ?",
            "hi",
            "hey there",
            "good morning",
            "thanks!",
            "how are you?",
            "how's it going",
            "whats up",
            "are you ready?",
            "ok",
            "bye",
        ],
    )
    def test_it_is_recognised(self, said):
        assert is_small_talk(said)

    @pytest.mark.parametrize(
        "said",
        [
            "what does this project do?",
            "how does the planner work?",
            "how is the build set up?",
            "how are the tests run here?",
            "hi, add a logout button to the navbar",
            "where is the config?",
        ],
    )
    def test_a_real_question_is_not(self, said):
        """`how are the tests run here` opens the same way as `how are
        you` and is nothing like it."""
        assert not is_small_talk(said)

    def test_the_router_sends_it_nowhere_that_changes_anything(self):
        assert read("hello, how are you today ?").command == "/ask"


class TestItDoesNotReadTheRepository:
    def test_there_is_a_system_prompt_that_says_so(self):
        assert "Do not read the" in answer.SMALL_TALK
        assert "do not report on what is or is not in" in answer.SMALL_TALK

    def test_the_tools_are_taken_away(self):
        """Not only told not to read - unable to. The instruction on its
        own is the kind of thing that holds until it does not."""
        source = inspect.getsource(answer.ask)

        assert '"tools": ""' in source
        assert "Bash Read Glob Grep Edit" in source
        assert "tools=[] if chatting else read_only(repo)" in source
        # Not Write. The answer comes back through a file, and refusing
        # that is how `hey, how are you today ?` came back as
        # "the worker stopped without writing an answer (exit 1)".
        assert '"without": "Bash Read Glob Grep Edit "\n' in source or (
            "Write" not in source.split('"without"')[1].split("}")[0]
        )

    def test_it_gets_two_turns_rather_than_thirty(self):
        source = inspect.getsource(answer.ask)
        assert "max_turns=2 if chatting else 30" in source

    def test_the_memory_briefing_is_not_attached_either(self):
        """What this repository taught the last job is not an answer to
        good morning."""
        source = inspect.getsource(answer.ask)
        assert 'known = "" if chatting else' in source


class TestTheOfficeSaysWhatIsHappening:
    def test_the_desk_does_not_claim_to_be_reading(self):
        from pathlib import Path

        session = (Path(answer.__file__).parent / "session.py").read_text()
        assert 'note="answering" if chatting else "reading the repository"' in session


class TestAQuestionTheCodeCannotAnswer:
    """`how's the weather today in sarasota ?` read the repository, grepped
    it for `weather`, `forecast`, `temperature` and `sarasota`, and
    reported that there is no weather API client and no cached forecast
    data. Six steps to arrive somewhere visible from the start.

    It is not small talk and it is not about the code, and the second one
    is the part that matters: the instruction said read before answering
    and gave no way out of it.
    """

    def test_it_is_not_small_talk(self):
        """Nothing about it is a greeting, and pattern-matching it as one
        would catch `how's the build` with it."""
        assert not is_small_talk("how's the weather today in sarasota ?")

    def test_the_instruction_has_a_way_out_of_reading(self):
        assert "not about this repository at all" in answer.SYSTEM
        assert "do\nnot search it" in answer.SYSTEM

    def test_it_says_which_way_to_be_wrong(self):
        """Told to stop at one or two lines, because the failure here was
        length as much as it was searching."""
        assert "one or two lines" in answer.SYSTEM

    def test_it_is_about_the_subject_and_not_the_opening_words(self):
        assert "how is the weather" in answer.SYSTEM
        assert "How are the tests run here" in answer.SYSTEM or (
            "how are the tests run here" in answer.SYSTEM.lower()
        )


class TestTheMachineryDoesNotShowThrough:
    """Under a hello the window printed "Looking at drydock-demo ·" and a
    drawer of three steps - a file write, the answer, and "worker
    finished". All true, all internal, and none of it part of saying good
    morning.

    The same two are worth having when a question is answered out of a
    codebase, so what changes is not the window but whether this job is
    one of those.
    """

    def test_the_run_says_whether_it_is_chatting(self):
        from pathlib import Path

        session = (Path(answer.__file__).parent / "session.py").read_text()
        started = session[
            session.index('"run.started",', session.index("def _answer(")) :
        ]
        started = started[: started.index(")")]

        assert "chatting=chatting" in started

    def test_it_is_worked_out_before_it_is_sent(self):
        """It was computed after the event that carries it, which reads
        fine and sends nothing."""
        from pathlib import Path

        session = (Path(answer.__file__).parent / "session.py").read_text()
        answering = session[session.index("def _answer(") :]
        answering = answering[: answering.index("\n    def ")]

        assert answering.index("chatting = is_small_talk") < answering.index(
            '"run.started"'
        )

    def test_the_window_shows_neither(self):
        from pathlib import Path

        chat = (Path(answer.__file__).parent / "static" / "chat.js").read_text()
        started = chat[chat.index('"run.started": (e) =>') :]
        started = started[: started.index("\n  },")]

        assert "if (e.chatting) return;" in started
        assert started.index("if (e.chatting) return;") < started.index("Looking at")
        assert started.index("if (e.chatting) return;") < started.index("live.el.tools")
