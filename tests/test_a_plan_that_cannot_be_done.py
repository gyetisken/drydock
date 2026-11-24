"""Eighteen minutes of engineering for a verdict decided when the item
was written, and then the work was gone.

The LUMI run, measured from its own record:

    Analyst     6s      Architect  17s     Designer  138s (beside the
    Planner   136s      Engineer  1095s over two attempts, 84 tool calls

Both attempts were refused by the inspector for `server.js`. The item's
criteria said, under "From what was asked", that `npm start` serves the
site; its file list named package.json, .gitignore, index.html,
styles.css and the test file. Nothing in it could serve anything. The
engineer wrote a server because that was the only way to meet the
criterion, and the inspector refused it for touching a file the item did
not name - correctly, and the second time for the same reason as the
first, because nothing about the item had changed in between.

Then the work was discarded, and it was gone: every file untracked, so
nothing had ever reached the object database. `git fsck` found one empty
blob. A site that worked, whose sixteen tests passed.

Three things follow from that, and they are what this file is about.

A refusal repeated by the station that reads files rather than opinions
is a defect in the plan, and a second attempt cannot fix it. It is
measured by comparing the two refusals as words - not by recognising
`server.js`, which would recognise nothing else.

Work is written into the object database before it is thrown away. It
is still thrown away: a refused item has to cost nothing, and that is
what makes the rollback affordable. What was wrong was being unable to
look at it afterwards.

And the engineer finishes before it polishes, because an item that is
complete and plain can be committed and one that is three-quarters
built and beautifully typeset cannot.
"""

import subprocess
from pathlib import Path

import pytest

from drydock import orchestrate
from drydock.engineer import PROMPT
from drydock.models import ItemResult
from drydock.repo import OUR_LOOK, Repo

ORCH = Path("src/drydock/orchestrate.py").read_text()


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


def flat(text: str) -> str:
    return " ".join(text.split())


def as_code(text: str) -> str:
    """The source with its comments taken out.

    A rule that explains itself by naming the case it came from is not
    a rule that recognises that case. The distinction matters here:
    what must contain no vocabulary is the logic.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )


def as_written(text: str) -> str:
    """One line, with comment markers and string joins out of the way."""
    said = " ".join(as_code(text).split())
    return said.replace('" "', "").replace("' '", "")


class TestTheSameRefusalTwiceIsThePlansFault:
    def same(self, a, b):
        return orchestrate._the_same_refusal(a, b)

    REFUSAL = (
        "this change touches server.js, which the item did not name. "
        "The item said: package.json, .gitignore, index.html, styles.css"
    )

    def test_the_same_complaint_is_recognised(self):
        assert self.same(self.REFUSAL, self.REFUSAL)

    def test_wrapped_or_reordered_differently_is_still_the_same(self):
        other = (
            "This change touches server.js which the item did not name. "
            "The item said: index.html, styles.css, .gitignore, package.json"
        )
        assert self.same(self.REFUSAL, other)

    def test_a_different_file_is_a_different_refusal(self):
        assert not self.same(self.REFUSAL, self.REFUSAL.replace("server.js", "db.js"))

    def test_a_different_complaint_entirely_is_not_the_same(self):
        assert not self.same(
            self.REFUSAL, "the suite lost four tests and the item did not say it would"
        )

    def test_the_first_attempt_has_nothing_to_compare_against(self):
        assert not self.same(self.REFUSAL, "")
        assert not self.same("", self.REFUSAL)

    def test_it_knows_nothing_about_any_particular_refusal(self):
        """A rule that recognised `server.js` would recognise nothing
        else. This one has no vocabulary at all."""
        said = Path(orchestrate.__file__).read_text()
        body = said[said.index("def _the_same_refusal") :][:1800]
        # Past its own docstring: a rule that explains itself by naming
        # the case it came from is not a rule that recognises that case.
        body = body[body.index('"""', body.index('"""') + 3) + 3 :]
        block = as_code(body)
        for word in ("server", "npm", ".js", "start", "file list"):
            assert word not in block, word


class TestItStopsRatherThanSpendingTheSecondAttempt:
    def test_only_when_the_file_check_refused(self):
        """The inspector reads files, which is arithmetic. An opinion
        repeating itself is not the same evidence."""
        block = ORCH[ORCH.index("The same refusal twice is not an engineer") :][:2200]
        assert 'refused_by == ["inspector"]' in block

    def test_only_while_an_attempt_is_left_to_save(self):
        block = ORCH[ORCH.index("The same refusal twice is not an engineer") :][:2200]
        assert "attempt < policy.attempts" in block

    def test_it_says_whose_fault_it_is(self):
        block = as_written(
            ORCH[ORCH.index("The same refusal twice is not an engineer") :][:3200]
        )
        assert "the plan's fault rather than the engineer's" in block

    def test_it_says_what_to_do_about_it(self):
        block = as_written(
            ORCH[ORCH.index("The same refusal twice is not an engineer") :][:3200]
        )
        assert "criteria ask for something its file list does not allow" in block
        assert "Change one of them and run it again" in block

    def test_the_item_is_blocked_rather_than_quietly_passed(self):
        block = ORCH[ORCH.index("The same refusal twice is not an engineer") :][:2600]
        assert "Outcome.BLOCKED" in block
        assert "here.discard()" in block

    def test_nothing_widens_the_file_list(self):
        """Never silently expand permissions. The item is reported, not
        rewritten."""
        said = ORCH[ORCH.index("The same refusal twice is not an engineer") :][:2600]
        assert "item.files" not in said
        assert ".append" not in said

    def test_the_inspector_is_untouched(self):
        source = Path("src/drydock/inspect.py").read_text()
        assert "which the item did not name" in source
        assert "Scope as arithmetic" in source


class TestWorkIsRecoverableAfterItIsThrownAway:
    def test_a_checkpoint_reads_back_everything_including_untracked(self, repo):
        """`git stash create` is the obvious tool and is the wrong one:
        it drops untracked files, which on a greenfield item is all of
        them."""
        (repo.path / "index.html").write_text("<h1>LUMI</h1>")
        (repo.path / "styles.css").write_text("body{}")
        kept = repo.checkpoint("item 1")
        assert kept

        repo.discard()
        assert not (repo.path / "index.html").exists()
        assert repo.is_clean()

        shown = subprocess.run(
            ["git", "-C", str(repo.path), "show", f"{kept}:index.html"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert shown.strip() == "<h1>LUMI</h1>"

    def test_the_message_says_which_item_it_was(self, repo):
        (repo.path / "a.txt").write_text("x")
        kept = repo.checkpoint("item 3: the menu page")
        said = subprocess.run(
            ["git", "-C", str(repo.path), "show", "--format=%s", "-s", kept],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "item 3: the menu page" in said

    def test_our_own_pictures_are_not_in_it(self, repo):
        (repo.path / "a.txt").write_text("x")
        (repo.path / OUR_LOOK).mkdir()
        (repo.path / OUR_LOOK / "desktop.png").write_bytes(b"x")
        kept = repo.checkpoint()
        files = subprocess.run(
            ["git", "-C", str(repo.path), "show", "--name-only", "--format=", kept],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "a.txt" in files
        assert OUR_LOOK not in files

    def test_nothing_to_keep_is_an_empty_answer(self, repo):
        assert repo.checkpoint() == ""

    def test_a_tree_holding_only_our_leftovers_has_nothing_to_keep(self, repo):
        (repo.path / OUR_LOOK).mkdir()
        (repo.path / OUR_LOOK / "a.png").write_bytes(b"x")
        assert repo.checkpoint() == ""

    def test_it_moves_no_branch_and_leaves_the_tree_alone(self, repo):
        (repo.path / "a.txt").write_text("x")
        before = repo.head()
        repo.checkpoint()
        assert repo.head() == before
        assert (repo.path / "a.txt").exists()

    def test_the_result_carries_where_it_went(self):
        assert "checkpoint" in ItemResult.model_fields
        assert ItemResult.model_fields["checkpoint"].default == ""

    def test_both_discards_that_lose_an_attempt_take_one(self):
        said = ORCH.count("here.checkpoint(")
        assert said >= 2, said

    def test_the_rollback_still_happens(self):
        """The work is still thrown away. A refused item has to cost
        nothing - that is what makes the rollback affordable."""
        block = ORCH[ORCH.index("if attempt == 2:") :][:900]
        assert "here.discard()" in block
        assert "Outcome.REVERTED" in block


class TestTheEngineerFinishesBeforeItPolishes:
    def test_the_order_is_stated(self):
        assert "**Whole first, then better.**" in flat(PROMPT)

    def test_it_says_what_complete_means(self):
        said = flat(PROMPT)
        assert "the files written, the command running, the suite passing" in said

    def test_it_says_why_rather_than_only_what(self):
        said = flat(PROMPT)
        assert "An item that is complete and plain can be committed" in said
        assert "is thrown away whole when the clock runs out" in said

    def test_the_measurement_is_quoted(self):
        said = flat(PROMPT)
        assert "eight consecutive edits to the stylesheet" in said

    def test_one_pass_rather_than_a_loop(self):
        said = flat(PROMPT)
        assert "Then one pass of improvement" in said
        assert '"could be nicer" is not a defect' in said

    def test_the_independent_look_is_not_removed(self):
        """Cosmetic self-review is cut. Somebody else still looks."""
        said = flat(PROMPT)
        assert "Something that is not you will look at the result" in said

    def test_the_engineer_still_chooses_how(self):
        said = flat(PROMPT)
        assert "Your item, which is the entire scope" in said
        assert "you may do it differently when the code" in said


class TestNothingProtectiveWasTraded:
    def test_the_gates_still_run(self):
        assert "if verdict.passed and unverified:" in ORCH
        assert "report_card = look(" in ORCH
        assert "verdict = verify(" in ORCH

    def test_the_stop_checks_are_where_they_were(self):
        assert ORCH.count("_stopping(should_stop)") >= 5

    def test_the_deadline_still_ends_a_run(self):
        from drydock.session import Session

        assert Session(Path("/tmp"), "t", [], within_minutes=20).within_minutes == 20

    def test_the_attempt_bound_is_unchanged(self):
        from drydock.policy import BALANCED, DEEP, PROFILES

        assert PROFILES[BALANCED].attempts == 2
        assert PROFILES[DEEP].attempts == 3

    def test_no_timeout_was_shortened(self):
        from drydock.policy import BALANCED, PROFILES

        assert PROFILES[BALANCED].minutes == 12.0
        assert PROFILES[BALANCED].retry_minutes == 18.0
        assert PROFILES[BALANCED].turns == 60

    def test_the_isolation_is_untouched(self):
        source = Path("src/drydock/engines.py").read_text()
        assert '"matcher": "Bash|Read|Edit|Write|Glob|Grep|NotebookEdit"' in source
        assert '("--setting-sources", "")' in source

    def test_our_leftovers_still_do_not_count_as_your_changes(self, repo):
        (repo.path / OUR_LOOK).mkdir()
        (repo.path / OUR_LOOK / "a.png").write_bytes(b"x")
        assert repo.is_clean()
