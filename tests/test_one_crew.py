"""One repository, one crew.

Two of them work the same item, commit into the same tree, and the first
to finish cleans up the other's worker. It is the worst thing this program
can do to somebody's code and it was one click away - resuming a run that
was still going, or starting a second job in the same project.

The only clue it left in the record was two heartbeats in the same second
reporting different amounts of elapsed time.
"""

from pathlib import Path

from drydock.workspace import Workspace


class Crew:
    """A session, as far as the workspace is concerned."""

    def __init__(self, repo: Path, running: bool = True):
        self.repo = repo
        self.running = running


class TestWhoIsWorkingWhere:
    def test_a_running_crew_is_found_by_its_repository(self):
        space = Workspace()
        space.sessions = {"20261117-120000": Crew(Path("/tmp/nero"))}

        assert space.busy_with(Path("/tmp/nero")) == "20261117-120000"

    def test_a_crew_that_has_finished_is_not_in_the_way(self):
        space = Workspace()
        space.sessions = {"old": Crew(Path("/tmp/nero"), running=False)}

        assert space.busy_with(Path("/tmp/nero")) == ""

    def test_another_project_is_not_in_the_way(self):
        """Two repositories at once is the point of having projects."""
        space = Workspace()
        space.sessions = {"a": Crew(Path("/tmp/nero"))}

        assert space.busy_with(Path("/tmp/trattoria")) == ""

    def test_a_resumed_run_counts_as_the_same_repository(self):
        """It is keyed differently - `<id>-resumed` - which is exactly how
        a second crew got into the same tree."""
        space = Workspace()
        space.sessions = {"20261117-120000-resumed": Crew(Path("/tmp/nero"))}

        assert space.busy_with(Path("/tmp/nero")) == "20261117-120000-resumed"

    def test_nothing_running_at_all(self):
        assert Workspace().busy_with(Path("/tmp/nero")) == ""
