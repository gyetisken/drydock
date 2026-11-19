"""The pictures of what the last attempt looked like.

Twice in one run an item was sent back by the critic, and twice the
engineer read a sentence describing a photograph it could not see, made a
different change, and was told the same thing again. Item 4: "most of
what this item owns is not on the page". Item 13: "the footer is not on
the page at either width". Both times the photographs existed; both times
they were in a temporary directory that was deleted before the retry
started.

`fits.py` says it plainly about a different check: being told is the only
thing the engineer has. It does not have to be.
"""

import subprocess
from pathlib import Path

from drydock.repo import OUR_LOOK, Repo


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


def shots(repo: Repo) -> Path:
    look = repo.path / OUR_LOOK
    look.mkdir(exist_ok=True)
    (look / "desktop.png").write_bytes(b"\x89PNG not really")
    (look / "phone.png").write_bytes(b"\x89PNG not really")
    return look


class TestTheySurviveTheUndo:
    def test_throwing_the_attempt_away_leaves_them(self, tmp_path):
        """`discard` is the undo button, and it used to take these with
        it - so the retry started with the same sentence and no pictures,
        which is where it was before."""
        repo = a_repo(tmp_path)
        look = shots(repo)
        (tmp_path / "half-written.py").write_text("broken = \n")

        repo.discard()

        assert not (tmp_path / "half-written.py").exists(), "the work went"
        assert (look / "desktop.png").exists(), "the pictures stayed"
        assert (look / "phone.png").exists()

    def test_everything_else_still_goes(self, tmp_path):
        repo = a_repo(tmp_path)
        shots(repo)
        (tmp_path / "rubbish.txt").write_text("left behind")
        (tmp_path / "a.py").write_text("x = 999\n")

        repo.discard()

        assert not (tmp_path / "rubbish.txt").exists()
        assert (tmp_path / "a.py").read_text() == "x = 1\n"


class TestTheyNeverReachACommit:
    def test_sweeping_takes_them(self, tmp_path):
        repo = a_repo(tmp_path)
        look = shots(repo)

        gone = repo.sweep()

        assert OUR_LOOK in gone
        assert not look.exists()

    def test_sweeping_an_absent_one_is_not_an_error(self, tmp_path):
        repo = a_repo(tmp_path)
        assert OUR_LOOK not in repo.sweep()

    def test_the_item_loop_sweeps_before_it_commits(self):
        """`commit` runs `add -A`. A directory of screenshots sitting
        untracked in the tree goes into the commit unless it is taken out
        first, and "before" is the only order that works."""
        import inspect

        from drydock import orchestrate

        source = inspect.getsource(orchestrate._one_item)
        at = source.index("here.commit(")
        assert "here.sweep()" in source[:at]
        assert source.rindex("here.sweep()", 0, at) > at - 400


class TestTheEngineerIsTold:
    def test_the_retry_is_pointed_at_them(self):
        import inspect

        from drydock import orchestrate

        source = inspect.getsource(orchestrate._one_item)
        assert "desktop.png and phone.png" in source
        assert "Open them before" in source

    def test_nothing_is_promised_when_there_are_no_pictures(self):
        """A path that is not there is worse than no path at all."""
        import inspect

        from drydock import orchestrate

        source = inspect.getsource(orchestrate._one_item)
        assert 'any(looked.glob("*.png"))' in source
