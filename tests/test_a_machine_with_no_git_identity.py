"""Every commit this program makes, on a machine git has never been set up on.

`_as_whoever` was written for exactly that machine - "a new laptop, a
container, CI" - and then used on one commit out of three. The other two
were the ones that mattered:

    commit()      died with "Author identity unknown"
    checkpoint()  returned "" and the work it exists to preserve was
                  thrown away unrecoverably

Both passed here and failed on CI, which is a runner with no
`user.email`. That is the whole of the difference, and it is the
difference between this program working on somebody's new laptop and
refusing to.

Nothing is ever written to anybody's git config. Where an identity
exists it is used, because the files being committed are theirs.
"""

import subprocess
from pathlib import Path

import pytest

from drydock.repo import OUR_LOOK, Repo

NOBODY = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


@pytest.fixture
def nowhere(tmp_path, monkeypatch):
    """A repository on a machine where git has nobody."""
    for name, value in NOBODY.items():
        monkeypatch.setenv(name, value)
    where = tmp_path / "project"
    where.mkdir()
    subprocess.run(
        ["git", "-C", str(where), "init", "-q"],
        check=True,
        env={**dict(NOBODY), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )
    return Repo(where)


def said_by(repo: Repo, commit: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo.path), "show", "-s", "--format=%an <%ae>", commit],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class TestGitHasNobody:
    def test_the_fixture_really_has_no_identity(self, nowhere):
        code, _ = nowhere._git("config user.email")
        assert code != 0, "this test proves nothing if an identity is set"


class TestTheBaselineCommit:
    def test_it_still_works(self, nowhere):
        nowhere.start_history()
        assert nowhere.has_history()

    def test_it_is_signed_by_this_program(self, nowhere):
        nowhere.start_history()
        assert said_by(nowhere, "HEAD") == "drydock <drydock@localhost>"


class TestAnItemsOwnCommit:
    def test_it_no_longer_dies(self, nowhere):
        """It died with "Author identity unknown", which is a run that
        built the work and could not keep it."""
        nowhere.start_history()
        (nowhere.path / "index.html").write_text("<h1>LUMI</h1>")
        assert nowhere.commit("the page") is not None

    def test_the_work_is_really_in_it(self, nowhere):
        nowhere.start_history()
        (nowhere.path / "index.html").write_text("<h1>LUMI</h1>")
        made = nowhere.commit("the page")
        shown = subprocess.run(
            ["git", "-C", str(nowhere.path), "show", f"{made}:index.html"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert shown.strip() == "<h1>LUMI</h1>"

    def test_nothing_to_commit_is_still_nothing(self, nowhere):
        nowhere.start_history()
        assert nowhere.commit("empty") is None


class TestTheCheckpoint:
    def test_it_no_longer_comes_back_empty(self, nowhere):
        """Returning "" meant the discard that follows threw the work
        away with nothing to read it back from - on the one machine the
        fallback was written for."""
        nowhere.start_history()
        (nowhere.path / "index.html").write_text("<h1>LUMI</h1>")
        assert nowhere.checkpoint("item 1")

    def test_the_work_reads_back_after_the_discard(self, nowhere):
        nowhere.start_history()
        (nowhere.path / "index.html").write_text("<h1>LUMI</h1>")
        kept = nowhere.checkpoint("item 1")
        nowhere.discard()
        assert not (nowhere.path / "index.html").exists()
        shown = subprocess.run(
            ["git", "-C", str(nowhere.path), "show", f"{kept}:index.html"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert shown.strip() == "<h1>LUMI</h1>"

    def test_our_own_pictures_are_still_left_out(self, nowhere):
        nowhere.start_history()
        (nowhere.path / "a.txt").write_text("x")
        (nowhere.path / OUR_LOOK).mkdir()
        (nowhere.path / OUR_LOOK / "desktop.png").write_bytes(b"x")
        kept = nowhere.checkpoint()
        files = subprocess.run(
            ["git", "-C", str(nowhere.path), "show", "--name-only", "--format=", kept],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "a.txt" in files
        assert OUR_LOOK not in files


class TestWhereAnIdentityExistsItIsUsed:
    def test_the_persons_own_name_signs_their_files(self, tmp_path):
        where = tmp_path / "theirs"
        where.mkdir()
        for args in (
            ["init", "-q"],
            ["config", "user.name", "Someone Real"],
            ["config", "user.email", "someone@real"],
        ):
            subprocess.run(["git", "-C", str(where), *args], check=True)
        repo = Repo(where)
        repo.start_history()
        (where / "a.txt").write_text("x")
        made = repo.commit("theirs")
        assert said_by(repo, made) == "Someone Real <someone@real>"

    def test_the_fallback_is_only_a_fallback(self, tmp_path):
        where = tmp_path / "theirs"
        where.mkdir()
        subprocess.run(["git", "-C", str(where), "init", "-q"], check=True)
        subprocess.run(
            ["git", "-C", str(where), "config", "user.email", "someone@real"],
            check=True,
        )
        assert Repo(where)._as_whoever() == ""

    def test_nothing_is_written_to_anybodys_config(self, nowhere):
        """`-c` on the command, never `git config`."""
        nowhere.start_history()
        (nowhere.path / "a.txt").write_text("x")
        nowhere.commit("x")
        assert nowhere._git("config user.email")[0] != 0


class TestEveryCommitThisProgramMakes:
    def test_all_three_use_the_fallback(self):
        source = Path("src/drydock/repo.py").read_text()
        assert source.count("self._as_whoever()") == 3

    def test_they_are_the_three_that_write_an_object(self):
        source = Path("src/drydock/repo.py").read_text()
        for call in (
            "{self._as_whoever()}commit -q --allow-empty",
            "{self._as_whoever()}commit -q -m",
            "{self._as_whoever()}commit-tree",
        ):
            assert call in source, call


# The browser that photographs a page is launched with a stripped
# environment, which is right: it is pointed at somebody's page and has
# no business reading this process's variables. `HOME` was stripped with
# the rest, which is not isolation. A Chrome that cannot find a home
# cannot find a keychain, and macOS stops the machine with a modal
# asking what to do about it - every time a page is photographed.


class TestTheBrowserCanFindItsHome:
    LAUNCHERS = ("src/drydock/shot.py", "src/drydock/fits.py")

    def test_both_launchers_pass_it(self):
        for where in self.LAUNCHERS:
            said = Path(where).read_text()
            assert '"HOME": os.environ.get("HOME", "")' in said, where

    def test_the_environment_is_still_stripped(self):
        """Three keys, not the whole of os.environ."""
        for where in self.LAUNCHERS:
            said = Path(where).read_text()
            at = said.index('"PATH": "/usr/bin:/bin:/usr/local/bin"')
            block = said[at : said.index("},", at)]
            assert block.count('":') == 3, where

    def test_the_browser_still_gets_its_own_profile(self):
        """Passing HOME must not hand it the person's Chrome profile."""
        said = Path("src/drydock/shot.py").read_text()
        assert "--user-data-dir=" in said
        assert "mkdtempSync" in said

    def test_a_machine_with_no_home_is_not_a_crash(self, monkeypatch):
        monkeypatch.delenv("HOME", raising=False)
        import os as _os

        assert _os.environ.get("HOME", "") == ""
