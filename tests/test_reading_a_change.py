"""`/review`: read what has changed and say what is wrong with it.

The Reviewer station already existed and does something narrower - it
holds one item against the one sentence it was given, during a run, and
can send it back. What was missing is the thing a person actually does:
open everything that has changed, read it at once, and say what they
would say in a pull request.

It changes nothing, which is what makes it safe to point at anything: a
branch somebody else wrote, a working tree halfway through an afternoon,
the last commit.
"""

import subprocess
from pathlib import Path

import pytest

from drydock.commands import BUILT_IN
from drydock.intent import read
from drydock.repo import Repo
from drydock.review import Reading, _said, _tool


def a_repo(tmp_path: Path) -> Repo:
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "first"], check=True
    )
    return Repo(tmp_path)


class TestWhichChangeItReads:
    def test_a_dirty_tree_is_what_somebody_is_working_on(self, tmp_path):
        repo = a_repo(tmp_path)
        (tmp_path / "a.py").write_text("x = 2\n")

        diff, about = repo.what_changed()

        assert "x = 2" in diff
        assert "not yet committed" in about

    def test_a_branch_is_read_against_the_trunk(self, tmp_path):
        repo = a_repo(tmp_path)
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-q", "-b", "work"], check=True
        )
        (tmp_path / "b.py").write_text("y = 1\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-q", "-m", "second"], check=True
        )

        diff, about = repo.what_changed()

        assert "y = 1" in diff
        assert "`work`" in about and "`main`" in about

    def test_otherwise_the_last_commit(self, tmp_path):
        repo = a_repo(tmp_path)
        (tmp_path / "c.py").write_text("z = 1\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-q", "-m", "third"], check=True
        )

        diff, about = repo.what_changed()

        assert "z = 1" in diff
        assert about == "The last commit."

    def test_nothing_changed_is_said_rather_than_reported_on(self, tmp_path):
        """A clean trunk with one commit has nothing to read. Reporting on
        a diff of nothing is worse than saying there is nothing."""
        repo = a_repo(tmp_path)

        diff, about = repo.what_changed()

        assert diff == "", (
            "a repository with one commit has no HEAD~1, and git's refusal "
            "read as a diff whose contents were 'fatal: ambiguous argument'"
        )
        assert "nothing changed" in about

    @pytest.mark.parametrize("trunk", ["main", "master", "trunk"])
    def test_whichever_name_the_trunk_has(self, tmp_path, trunk):
        for args in (
            ["init", "-q", "-b", trunk],
            ["config", "user.email", "t@t"],
            ["config", "user.name", "t"],
            ["commit", "-q", "--allow-empty", "-m", "first"],
        ):
            subprocess.run(["git", "-C", str(tmp_path), *args], check=True)

        assert Repo(tmp_path)._trunk() == trunk


class TestWhatItReportsBack:
    def test_a_finding_names_a_place_and_a_thing(self):
        said = _said(
            {
                "verdict": "v",
                "findings": [
                    {"where": "a.py:12", "what": "returns None", "sure": True}
                ],
                "good": [],
            },
            [],
        )
        assert said.findings[0].where == "a.py:12"
        assert said.findings[0].sure is True

    def test_a_suspicion_is_marked_as_one(self):
        """Something checked and something suspected are different claims,
        and the difference matters more than the count."""
        said = _said(
            {
                "verdict": "v",
                "findings": [{"where": "a", "what": "b", "sure": False}],
                "good": [],
            },
            [],
        )
        assert said.findings[0].sure is False
        assert "sure" in _tool().schema["properties"]["findings"]["items"]["required"]

    def test_counted_findings_come_through_untouched(self):
        """The deterministic half runs first and costs nothing. The model
        is told not to repeat it."""
        said = _said({"verdict": "v", "findings": [], "good": []}, ["one test removed"])
        assert said.counted == ["one test removed"]
        assert not said.clean

    def test_nothing_found_is_a_clean_reading(self):
        assert Reading(verdict="fine").clean


class TestHowItIsReached:
    def test_there_is_a_command(self):
        review = next(c for c in BUILT_IN if c.name == "/review")
        assert review.stop_after == "review"
        assert "Nothing is changed" in review.summary

    @pytest.mark.parametrize(
        "said",
        [
            "review my changes",
            "what is wrong with my diff",
            "look over the branch",
            "review it",
            "go over these edits",
        ],
    )
    def test_it_is_routed_to(self, said):
        assert read(said).command == "/review"

    @pytest.mark.parametrize("said", ["audit this project", "what is fragile here"])
    def test_an_audit_is_still_an_audit(self, said):
        """`review` used to sit in the audit pattern, which surveys the
        whole repository - a different and much longer question than what
        is wrong with what I just wrote."""
        assert read(said).command == "/audit"

    def test_it_changes_nothing(self):
        import inspect

        from drydock import review, session

        assert "Edit" in inspect.getsource(review.read_it).split("without=")[1]
        reviewing = inspect.getsource(session.Session._review)
        for forbidden in (
            "repo.commit(",
            "repo.branch(",
            "Run.start(self.repo, self.task, [s",
        ):
            assert forbidden not in reviewing

    def test_it_is_its_own_stage(self):
        """And the two places that have to agree about that ask the same
        tuple, rather than each keeping a list. They did not: `/review`
        was taught to `Session._stages` and not to `Command.stages`, so
        `STAGES.index("review")` raised ValueError on every call to
        `GET /api/state` - the window would not load at all."""
        import inspect

        from drydock import session
        from drydock.commands import ALONE

        assert "review" in ALONE
        assert "ALONE" in inspect.getsource(session.Session._stages)
        assert next(c for c in BUILT_IN if c.name == "/review").stages == ["review"]


class TestItHasRoomToAnswer:
    """Six turns, thirteen tool calls, then the limit, then nothing
    written: `EngineUnavailable: the worker stopped without writing an
    answer (exit 1)`. A station given tools needs the turns those tools
    cost plus the one that answers.
    """

    def test_a_station_that_reads_gets_turns_to_read_with(self):
        import inspect
        import re

        from drydock import review

        # The largest, not the only one: the API path next to it runs with
        # no tools at all and two turns is right there.
        source = inspect.getsource(review.read_it)
        turns = [int(n) for n in re.findall(r"max_turns=(\d+)", source)]
        assert max(turns) >= 20, "it reads; six was not enough to read and answer"

    def test_it_is_told_that_running_out_leaves_nothing(self):
        from drydock import review

        assert "run out of turns" in review.SYSTEM
        assert "Read what you need and then answer" in review.SYSTEM

    def test_every_station_with_read_tools_has_room(self):
        """The same arithmetic everywhere, not only where it was noticed."""
        import inspect
        import re

        from drydock import analyst, answer, review, start

        for module in (review.read_it, start.begin, answer.ask, analyst.survey):
            source = inspect.getsource(module)
            # Case-insensitive, and `read_only(repo)` counts. The first
            # version of this looked for a capital `Read` in the sixty
            # characters after `tools=`, which skipped every station that
            # passes `tools=read_only(repo)` - that is, most of them - and
            # passed by checking almost nothing.
            handed = source.split("tools=")[1][:60].lower()
            if "read" not in handed:
                continue
            # Every number this station could run with, from wherever it
            # is written. Two things defeated reading the source alone:
            # `max_turns=2 if chatting else 30`, where stopping at the
            # first digit reports 2, and `max_turns=max_turns`, where the
            # number is a parameter default and is not in the body at all.
            turns = [
                int(n)
                for expression in re.findall(r"max_turns=([^,\n)]+)", source)
                for n in re.findall(r"\d+", expression)
            ]
            given = inspect.signature(module).parameters.get("max_turns")
            if given is not None and isinstance(given.default, int):
                turns.append(given.default)

            assert turns and max(turns) >= 20, f"{module.__name__}: {turns}"


class TestItReallyChangesNothing:
    def test_the_index_is_left_exactly_as_it_was(self, tmp_path):
        """`pending_for_review` runs `git add -A -N` so untracked files
        appear in the diff. Right during a run - this program owns that
        tree - and wrong here, where the whole promise is that reading a
        change does not change it. An untracked file went from `??` to
        ` A` because somebody asked what was wrong with their work."""
        repo = a_repo(tmp_path)
        (tmp_path / "a.py").write_text("x = 2\n")
        (tmp_path / "new.py").write_text("brand = 'new'\n")
        (tmp_path / "staged.py").write_text("on = 'purpose'\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "staged.py"], check=True)
        before = subprocess.run(
            ["git", "-C", str(tmp_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        repo.what_changed()

        after = subprocess.run(
            ["git", "-C", str(tmp_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert after == before
        assert "?? new.py" in after, "an untracked file stayed untracked"
        assert "A  staged.py" in after, "something staged on purpose stayed staged"

    def test_a_file_nobody_has_tracked_is_still_read(self, tmp_path):
        """Putting the index back must not cost the thing it was moved
        for: brand new work is most of what a review is asked about."""
        repo = a_repo(tmp_path)
        (tmp_path / "new.py").write_text("brand = 'new'\n")

        diff, _ = repo.what_changed()

        assert "brand = 'new'" in diff


class TestFindingTheTrunk:
    def test_the_remote_is_asked_first(self, tmp_path):
        """`origin/HEAD` is what the clone was told the default branch is,
        including `develop` and whatever else somebody chose. Guessing
        from a list of three names misses those silently and reviews the
        last commit instead of the branch."""
        a_repo(tmp_path)
        subprocess.run(
            ["git", "-C", str(tmp_path), "checkout", "-q", "-b", "develop"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "update-ref",
                "refs/remotes/origin/develop",
                "HEAD",
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/develop",
            ],
            check=True,
        )

        assert Repo(tmp_path)._trunk() == "develop"

    def test_a_remote_only_trunk_is_found(self, tmp_path):
        """A feature-only clone has no local `main`."""
        a_repo(tmp_path)
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "update-ref",
                "refs/remotes/origin/master",
                "HEAD",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "branch", "-m", "main", "feature"],
            check=True,
        )

        assert Repo(tmp_path)._trunk() == "master"


class TestWhatWasTypedIsNotThrownAway:
    def test_the_task_reaches_the_reading(self):
        """ "review my changes, the error handling especially" became
        "review what has changed" and the second half went nowhere."""
        import inspect

        from drydock import session

        reviewing = inspect.getsource(session.Session._review)
        assert "self.task" in reviewing.split("read_it(")[1][:400]
