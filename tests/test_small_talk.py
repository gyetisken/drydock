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
        assert "Bash Read Glob Grep Edit Write" in source
        assert "tools=[] if chatting else read_only(repo)" in source

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
