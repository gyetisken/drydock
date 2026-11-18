"""Not reading a repository that was already read.

The Analyst took two minutes and thirty tool calls on a repository this
program had worked thirteen times, to establish a toolchain, a build
command and a test command that were already written down. Three quarters
of that run went by before any code was written.

What is pinned here is that the survey is skipped only when skipping it
buys something and costs nothing - and that a repository nobody has seen
is still read, which is the case that must not break.
"""

from pathlib import Path

import pytest

from drydock.memory import Memory, Note
from drydock.policy import BALANCED, DEEP, FAST, of
from drydock.session import Session


@pytest.fixture
def shop(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
    repo = tmp_path / "shop"
    repo.mkdir()
    (repo / "package.json").write_text("{}\n")
    return repo


def a_session(repo: Path, profile: str = BALANCED, memory: Memory | None = None):
    session = Session(repo, "add a thing", [], policy=of(profile))
    if memory is not None:
        session.memory = memory
    from drydock.run import Run

    session.run = Run.start(repo, "add a thing")
    return session


def knowing(repo: Path, commit: str = "", **kw) -> Memory:
    """A memory of a repository that has been worked on here before."""
    memory = Memory(repo=str(repo))
    memory.toolchain = kw.get("toolchain", "npm / TypeScript")
    memory.build_command = "npm run build"
    memory.test_command = "npm test"
    if commit:
        memory.notes = [
            Note(text="the suite lives in src/", commit=commit, learned="2026-11-18")
        ]
    return memory


class TestWhenReadingAgainBuysNothing:
    """The same commit was surveyed before. Nothing has changed since, so
    the reading still holds."""

    def test_the_same_commit_is_not_read_twice(self, shop):
        session = a_session(shop, BALANCED, knowing(shop, commit="abc123"))
        assert session._already_read("abc123") is True

    def test_what_was_read_before_is_what_is_used(self, shop):
        session = a_session(shop, BALANCED, knowing(shop, commit="abc123"))
        session._already_read("abc123")
        assert "the suite lives in src/" in session.run.inventory.findings

    def test_it_holds_for_every_profile(self, shop):
        """Nothing about the code changed, so there is nothing for a
        careful profile to find that a quick one would not."""
        for profile in (FAST, BALANCED, DEEP):
            session = a_session(shop, profile, knowing(shop, commit="abc123"))
            assert session._already_read("abc123") is True, profile


class TestWhenTheCommitHasMoved:
    """The toolchain and the commands do not go stale the way a reading of
    the code does - but the reading does."""

    def test_a_fast_job_starts_from_what_is_known(self, shop):
        session = a_session(shop, FAST, knowing(shop, commit="old"))
        assert session._already_read("new") is True

    def test_a_balanced_job_reads_it_again(self, shop):
        session = a_session(shop, BALANCED, knowing(shop, commit="old"))
        assert session._already_read("new") is False

    def test_a_deep_job_reads_it_again(self, shop):
        session = a_session(shop, DEEP, knowing(shop, commit="old"))
        assert session._already_read("new") is False

    def test_what_it_says_is_true_of_itself(self, shop):
        """It must not pass off remembered facts as a fresh reading."""
        session = a_session(shop, FAST, knowing(shop, commit="old"))
        session._already_read("new")
        said = " ".join(session.run.inventory.findings)
        assert "not read again" in said


class TestARepositoryNobodyHasSeen:
    """The case that must not break."""

    def test_a_repository_with_no_memory_is_read(self, shop):
        session = a_session(shop, FAST, Memory(repo=str(shop)))
        assert session._already_read("abc123") is False

    def test_a_half_remembered_repository_is_read(self, shop):
        """A toolchain with no test command is not a repository anybody
        has established anything about."""
        memory = Memory(repo=str(shop))
        memory.toolchain = "npm / TypeScript"
        session = a_session(shop, FAST, memory)
        assert session._already_read("abc123") is False

    def test_the_commands_still_come_from_the_repository(self, shop):
        """Read from disk, not from memory: the memory is for what was
        learned, and the commands are something that can be looked up."""
        session = a_session(shop, FAST, knowing(shop))
        session._already_read("new")
        assert session.run.inventory.build_command is not None


class TestItSaysWhatItDid:
    def test_the_skip_is_announced_with_its_reason(self, shop):
        session = a_session(shop, BALANCED, knowing(shop, commit="abc123"))
        seen = []
        session.feed.emit = lambda kind, **data: seen.append((kind, data))
        session._already_read("abc123")

        skipped = [d for k, d in seen if k == "agent.state"]
        assert skipped and skipped[0]["state"] == "skipped"
        assert "read before" in skipped[0]["note"]

    def test_the_findings_still_reach_whoever_reads_them(self, shop):
        """The planner is handed the survey either way."""
        session = a_session(shop, FAST, knowing(shop, commit="old"))
        seen = []
        session.feed.emit = lambda kind, **data: seen.append((kind, data))
        session._already_read("new")

        assert any(k == "survey" for k, _ in seen)
