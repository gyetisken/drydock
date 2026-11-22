"""A finished site, sixteen passing tests, thrown away over our own files.

The LUMI run built the page. `npm test` ran sixteen tests and all of
them passed. Nothing was delivered: twenty-one minutes, $6.95, and the
run ended on

    integration stopped: ... observed ... with changes: ?? .drydock-look/

`.drydock-look/` is where this program puts the pictures of the page so
a second attempt can open what the first was refused for. `discard`
keeps them **on purpose** - that is the whole reason the directory
survives a rollback. And `require_checkout` demanded `git status
--porcelain` be empty.

So two of our own decisions contradicted each other, and the one that
won threw away somebody's work and reported it as though the work had
failed.

Six places in this file touch what the program leaves behind. Four knew
it was ours - `look` writes it, `discard` keeps it, `sweep` removes it,
the review diff excludes it. Two did not. There is one list now, and
everything asks it.

The protection is unchanged. A file somebody wrote still stops an
unsafe integration, and nothing here deletes anything.
"""

import subprocess
from pathlib import Path

import pytest

from drydock.repo import OUR_FILES, OUR_LOOK, GitError, Repo, ours


@pytest.fixture
def repo(tmp_path):
    where = tmp_path / "project"
    where.mkdir()
    for args in (
        ["init", "-q"],
        [
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "before drydock",
        ],
    ):
        subprocess.run(["git", "-C", str(where), *args], check=True)
    return Repo(where)


def _on_master(repo: Repo) -> bool:
    """Whichever name `git init` gave the first branch here."""
    return "master" in repo._git("symbolic-ref --quiet --short HEAD")[1]


def pictures(repo: Repo) -> None:
    """What the critic leaves for the next attempt to open."""
    look = repo.path / OUR_LOOK
    look.mkdir(exist_ok=True)
    (look / "desktop.png").write_bytes(b"\x89PNG")
    (look / "phone.png").write_bytes(b"\x89PNG")


class TestTheExactSequenceThatFailed:
    def test_a_discarded_attempt_leaves_a_tree_integration_accepts(self, repo):
        """Engineer writes, critic photographs, the attempt is refused,
        `discard` rolls back and keeps the pictures, and the next thing
        to look at the tree is the checkout check. That is the whole of
        it, and it used to end the run."""
        (repo.path / "index.html").write_text("<h1>LUMI</h1>")
        (repo.path / "styles.css").write_text("body{}")
        pictures(repo)

        repo.discard()

        assert (repo.path / OUR_LOOK / "desktop.png").exists(), (
            "the pictures are kept on purpose - that is what discard is for"
        )
        assert not (repo.path / "index.html").exists()
        assert repo.is_clean()
        assert repo.require_checkout("master" if _on_master(repo) else "main")

    def test_the_message_that_was_reported_cannot_happen_now(self, repo):
        pictures(repo)
        assert "drydock-look" not in repo.dirt()
        assert repo.dirt() == ""

    def test_a_second_attempt_can_start_on_that_tree(self, repo):
        """The retry is the point of keeping them. It used not to get
        one, because the run ended before it."""
        pictures(repo)
        repo.discard()
        assert repo.is_clean()
        (repo.path / "index.html").write_text("<h1>LUMI</h1>")
        assert "index.html" in repo.dirt()

    def test_the_run_can_still_be_started_on_such_a_tree(self, repo):
        """`execute` refuses a dirty tree before it branches. A tree
        holding yesterday's pictures is not dirty."""
        pictures(repo)
        assert repo.is_clean() is True


class TestEveryKindOfOursIsKnown:
    @pytest.mark.parametrize("name", OUR_FILES)
    def test_the_files_a_worker_writes(self, repo, name):
        (repo.path / name).write_text("{}")
        assert repo.is_clean(), name

    def test_the_directory_and_whatever_is_under_it(self):
        assert ours(OUR_LOOK)
        assert ours(f"{OUR_LOOK}/desktop.png")
        assert ours(f"{OUR_LOOK}/nested/deeper.png")

    def test_all_of_them_together(self, repo):
        pictures(repo)
        for name in OUR_FILES:
            (repo.path / name).write_text("{}")
        assert repo.is_clean()

    def test_a_quoted_path_is_still_recognised(self):
        """Git quotes a path with a space in it."""
        assert ours(f'"{OUR_LOOK}/a file.png"')


class TestUserWorkIsStillProtected:
    def test_an_untracked_file_still_blocks(self, repo):
        (repo.path / "notes.md").write_text("mine")
        assert not repo.is_clean()
        with pytest.raises(GitError, match="notes.md"):
            repo.require_checkout("master" if _on_master(repo) else "main")

    def test_a_modified_tracked_file_still_blocks(self, repo):
        said = repo.path / "README.md"
        said.write_text("one")
        subprocess.run(["git", "-C", str(repo.path), "add", "README.md"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo.path),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "readme",
            ],
            check=True,
        )
        said.write_text("two")
        assert not repo.is_clean()
        assert "README.md" in repo.dirt()

    def test_a_staged_file_still_blocks(self, repo):
        (repo.path / "secret.env").write_text("KEY=1")
        subprocess.run(["git", "-C", str(repo.path), "add", "secret.env"], check=True)
        assert not repo.is_clean()

    def test_one_of_ours_beside_one_of_theirs_still_blocks(self, repo):
        """The dangerous reading would be "any of ours makes it clean"."""
        pictures(repo)
        (repo.path / "theirs.txt").write_text("mine")
        said = repo.dirt()
        assert "theirs.txt" in said
        assert OUR_LOOK not in said

    @pytest.mark.parametrize(
        "name",
        [
            "drydock-look",
            ".drydock-looking",
            ".drydock-look.txt",
            "src/.drydock-look/x",
            ".drydock-report.json.bak",
            "my.drydock-out.json",
        ],
    )
    def test_a_name_that_merely_resembles_ours_is_theirs(self, repo, name):
        """The list is a list, not a pattern. A worker cannot name a
        file into being ignored."""
        assert not ours(name), name

    def test_nothing_in_this_fix_deletes_anything(self, repo):
        (repo.path / "notes.md").write_text("mine")
        pictures(repo)
        repo.dirt()
        repo.is_clean()
        assert (repo.path / "notes.md").read_text() == "mine"
        assert (repo.path / OUR_LOOK / "desktop.png").exists()


class TestTheLifecycleAgreesWithItself:
    def test_discard_keeps_them_and_cleanliness_allows_them(self, repo):
        pictures(repo)
        (repo.path / "work.txt").write_text("x")
        repo.discard()
        assert (repo.path / OUR_LOOK).is_dir()
        assert repo.is_clean()

    def test_sweep_removes_them_so_they_never_reach_a_commit(self, repo):
        pictures(repo)
        for name in OUR_FILES:
            (repo.path / name).write_text("{}")
        gone = repo.sweep()
        assert OUR_LOOK in gone
        assert not (repo.path / OUR_LOOK).exists()
        assert repo.is_clean()

    def test_a_tree_holding_only_ours_has_nothing_to_commit(self, repo):
        """Otherwise an item that wrote nothing commits the pictures of
        the page it did not change."""
        pictures(repo)
        assert repo.changed_files() == []
        assert repo.commit("nothing here") is None

    def test_real_work_beside_them_is_still_committed(self, repo):
        pictures(repo)
        (repo.path / "index.html").write_text("<h1>LUMI</h1>")
        assert repo.changed_files() == ["index.html"]
        repo.sweep()
        assert repo.commit("the page") is not None

    def test_the_review_diff_still_excludes_them(self):
        source = Path("src/drydock/repo.py").read_text()
        assert (
            "f\"':(exclude){name}'\" for name in (*self.GENERATED, self.OUR_LOOK)"
            in (source)
        )

    def test_there_is_one_list_rather_than_six(self):
        source = Path("src/drydock/repo.py").read_text()
        assert source.count('".drydock-report.json"') == 1
        assert source.count('OUR_LOOK = ".drydock-look"') == 1
        assert "OURS = OUR_FILES" in source

    def test_every_cleanliness_check_asks_the_same_thing(self):
        source = Path("src/drydock/repo.py").read_text()
        assert source.count('self._git("status --porcelain")') == 3
        for place in ("def dirt", "def changed_files"):
            block = source[source.index(place) :][:900]
            assert "ours(" in block, place
        assert "status = self.dirt()" in source


# Why the attempt was discarded in the first place, which is a separate
# fault and the more expensive one. The checkout failure ended the run;
# this is what had already burned both attempts before it.


class TestAnItemMustAuthoriseWhatItsCriteriaNeed:
    """Both LUMI attempts were refused by the inspector for `server.js`.

    The item's criteria said, under "From what was asked", that `npm
    start` serves the site with one command and no build step. Its
    `files` list was package.json, .gitignore, index.html, styles.css
    and test/site.test.js. Nothing in it could serve anything.

    So the engineer wrote a server, which was the only way to meet the
    criterion, and the inspector refused it for touching a file the
    item did not name - correctly, both times. The item was unwinnable
    the moment it was written, and it got two attempts to prove it.
    """

    def flat(self, text: str) -> str:
        return " ".join(text.split())

    def test_the_planner_is_told_the_list_is_what_may_be_written(self):
        from drydock.planner import PLAN_SCHEMA

        said = self.flat(
            PLAN_SCHEMA["properties"]["items"]["items"]["properties"]["files"][
                "description"
            ]
        )
        assert "Every path this item may write" in said
        assert "a list that misses one makes the item unwinnable" in said

    def test_it_is_told_to_read_its_own_criteria_back(self):
        from drydock.planner import PLAN_SCHEMA

        said = self.flat(
            PLAN_SCHEMA["properties"]["items"]["items"]["properties"]["files"][
                "description"
            ]
        )
        assert "Read your own criteria back and ask what each one needs" in said
        assert "needs whatever serves or starts it" in said

    def test_the_case_that_caused_it_is_named(self):
        from drydock.planner import PLAN_SCHEMA

        said = self.flat(
            PLAN_SCHEMA["properties"]["items"]["items"]["properties"]["files"][
                "description"
            ]
        )
        assert "refused for `server.js`" in said

    def test_the_rule_is_in_the_planning_instructions_too(self):
        said = self.flat(Path("src/drydock/start.py").read_text())
        assert "**An item's files must cover its own criteria.**" in said
        assert "cannot be done, and will be refused for doing it" in said

    def test_the_inspector_still_refuses_an_unlisted_file(self):
        """The inspector was right both times. Nothing here loosens it -
        the fix is for the plan to authorise what it asks for."""
        source = Path("src/drydock/inspect.py").read_text()
        assert "which the item did not name" in source

    def test_the_scope_check_still_runs_before_the_opinions(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.index("report_card = look(") < source.index(
            "refusal, refused_by, unverified, from_gates = _judge("
        )
