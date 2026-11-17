"""The crew, and the three places it is described.

A station exists in code, in the slash menu, and in the README. They were
three hand-written lists, which is the shape of bug this program has been
fixing all day: the one nobody updates is the one everybody reads.
"""

import re
from pathlib import Path

from drydock.crew import CREW, as_rows

README = Path("README.md")


class TestTheCrewItself:
    def test_every_station_says_what_it_does_and_when(self):
        for station in CREW:
            assert station.does, station.name
            assert station.when, station.name
            assert station.reads, station.name

    def test_the_ones_that_are_code_can_all_refuse(self):
        """A check written in code that cannot stop anything is a log line."""
        for station in CREW:
            if station.is_code:
                assert station.can_refuse, station.name

    def test_names_are_not_repeated(self):
        assert len({s.name for s in CREW}) == len(CREW)


class TestWhatTheRowsCarry:
    def test_a_row_exists_for_every_station(self):
        assert len(as_rows()) == len(CREW)

    def test_a_row_can_be_read_without_the_class(self):
        """The menu is built from these in the browser."""
        for row in as_rows():
            assert set(row) >= {"name", "does", "can_refuse"}
            assert isinstance(row["name"], str)


class TestTheReadmeAgrees:
    """It is the first thing anybody reads about this and the last thing
    anybody updates."""

    def test_the_number_of_stations(self):
        assert f"{_in_words(len(CREW))} stations" in _said()

    def test_how_many_can_refuse(self):
        refuse = sum(1 for s in CREW if s.can_refuse)
        assert f"{_in_words(refuse)} of them can refuse" in _said()

    def test_how_many_are_code(self):
        code = sum(1 for s in CREW if s.is_code)
        assert f"{_in_words(code)} of those are code" in _said()

    def test_every_station_is_named_in_it(self):
        said = README.read_text()
        for station in CREW:
            assert f"**{station.name}**" in said, station.name

    def test_the_gate_count_is_the_refusing_count(self):
        refuse = sum(1 for s in CREW if s.can_refuse)
        for claim in re.findall(r"(\w+) gates", _said()):
            assert claim == _in_words(refuse), claim


def _said() -> str:
    """The README, lowercased - a sentence may start with any of these."""
    return README.read_text().lower()


def _in_words(number: int) -> str:
    return {2: "two", 3: "three", 4: "four", 9: "nine"}[number]
