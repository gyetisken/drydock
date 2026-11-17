"""Which jobs get a designer.

A parser, a migration or a command-line tool does not need a palette, and
asking for one costs a minute and produces an answer nobody reads. A website
does, and not having one is why everything this built looked the same.
"""

from pathlib import Path

from drydock.session import Session


def asking(task: str, repo: Path) -> bool:
    session = Session.__new__(Session)
    session.task = task
    session.repo = repo
    return session._has_a_face()


def test_anything_somebody_looks_at(tmp_path):
    for task in (
        "a website for an italian restaurant",
        "build a landing page for the launch",
        "a dashboard showing yesterday's orders",
        "an online shop for the bakery",
    ):
        assert asking(task, tmp_path), task


def test_work_nobody_looks_at(tmp_path):
    for task in (
        "migrate the test suite from JUnit 4 to JUnit 5",
        "upgrade express from 4 to 5",
        "a command line tool that converts CSV to JSON",
        "add retries to the payment client",
    ):
        assert not asking(task, tmp_path), task


def test_a_repository_that_already_serves_pages_has_a_face(tmp_path):
    """The request need not mention it. A repository with views in it is
    looked at by somebody whatever the item says."""
    assert not asking("add retries to the payment client", tmp_path)
    (tmp_path / "views").mkdir()
    assert asking("add retries to the payment client", tmp_path)


class TestWhichStationsAJobReaches:
    """Not every job walks the line. Indexing the stage list by the stopping
    point assumed it always did, and raised on the first /fix."""

    def reaching(self, stop_after: str) -> list:
        session = Session.__new__(Session)
        session.stop_after = stop_after
        return session._stages()

    def test_a_question_reaches_nothing(self):
        assert self.reaching("ask") == ["ask"]

    def test_one_change_skips_the_planning(self):
        assert self.reaching("straight") == ["baseline", "engineer"]

    def test_the_ordinary_path_is_unchanged(self):
        assert self.reaching("planner") == ["baseline", "analyst", "planner"]
        assert self.reaching("baseline") == ["baseline"]
