"""A direction that was decided once, and then written over by a sentence
saying there was none.

A restaurant's first job produced seven and a half thousand characters of
art direction - who walks in, the plaster walls and the linen, the 5:30
seating that is the market in that town, the Gulf a few minutes west. It
went into memory, which is where a project's look is supposed to live so
that the next job builds the same thing.

The next job replaced all of it with:

    "No look is being directed. The visual direction is already settled
     in the repository..."

That is not a direction. It is a worker explaining why it is not writing
one - and it had to write something, because the field is required. It
was then used as the direction for the whole run and saved over the real
one, permanently. The pages built after it are correct, tested and
visually dead, because nothing told the engineers what the thing was
supposed to look like.
"""

import inspect

from drydock.session import Session
from drydock.start import _tool

SOURCE = inspect.getsource(Session._begin_it)


class TestWhyItHappened:
    def test_the_field_is_required_so_something_is_always_written(self):
        """This is not a thing to fix in the schema: strict mode wants
        every field, and a worker with nothing to say in one will say
        why. What has to change is whether anybody believes it."""
        assert "direction" in _tool().schema["required"]

    def test_a_look_nobody_asked_for_is_not_a_direction(self):
        assert 'directed = started.direction if wanted_a_look else ""' in SOURCE

    def test_the_remembered_one_wins_when_none_was_asked_for(self):
        assert "self.run.direction = directed or remembered" in SOURCE


class TestWhatIsSaved:
    def test_memory_is_only_written_when_a_look_was_directed(self):
        saving = SOURCE[SOURCE.index("directed = started.direction") :]
        assert "if directed:" in saving
        assert "self.memory.direct(directed)" in saving

    def test_the_old_unconditional_save_is_gone(self):
        """`if started.direction:` was the whole bug: the field is never
        empty, so the condition was always true."""
        assert "if started.direction:" not in SOURCE
        assert "self.memory.direct(started.direction)" not in SOURCE

    def test_the_question_is_asked_once_and_used_twice(self):
        """Told to the worker, and used again to judge what came back.
        Two copies of that condition would drift apart."""
        assert SOURCE.count("wanted_a_look") == 3
