"""Whether a job produces something a person looks at.

Measured on run 20261125-141215, a paging fix: "the first page to the
last" matched, so a worker was told to direct a look, wrote a paragraph
explaining why it was not directing one, and that paragraph was stored
as the run's art direction. Six of eighteen backend phrasings matched
the same way.

It costs more than a paragraph. The answer also decides whether the
web-design skill is loaded - 8,827 characters into the engineer's
briefing - whether the critic looks, and whether `begin` is asked to
direct anything.

No model, no clock, no network.
"""

import inspect

import pytest

from drydock import detect, session


@pytest.fixture
def backend(tmp_path):
    """A repository with code and nothing anybody looks at."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    return tmp_path


@pytest.fixture
def empty(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.fixture
def serves_pages(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "public").mkdir()
    return tmp_path


class TestTheOneThatBrokeIt:
    TASK = (
        "Walking the article feed from the first page to the last is meant to "
        "return every article exactly once. Check whether that actually holds "
        "when many articles share the same sort value, and if it does not, fix "
        "it and prove the fix with a test."
    )

    def test_the_paging_task_is_not_a_visual_one(self, backend):
        assert detect.has_a_face(backend, self.TASK) is False

    def test_the_word_still_matches_which_is_why_the_rest_of_the_rule_exists(self):
        """The fix is not a smaller word list. `page` still matches; what
        changed is that one ambiguous word is not enough on its own in a
        repository with nothing anybody looks at."""
        assert detect.FACES.search(self.TASK.lower())


class TestBackendSensesOfTheSameWords:
    @pytest.mark.parametrize(
        "task",
        [
            "add pagination to the articles endpoint",
            "the page size parameter is ignored",
            "return the next page token in the response",
            "fetch the second page of results from the API",
            "a page fault in the cache layer",
            "define the service interface between the two systems",
            "site reliability work on the ingest queue",
            "the app crashes on a malformed row",
            "cursor pagination loses rows when the sort value repeats",
            "make the sync idempotent",
            "write the migration for the new column",
            "upgrade Spring Boot to 3.2",
        ],
    )
    def test_none_of_these_ask_for_a_palette(self, backend, task):
        assert detect.has_a_face(backend, task) is False


class TestGenuineVisualWorkIsStillFound:
    @pytest.mark.parametrize(
        "task",
        [
            "add a dashboard for the admin",
            "the UI is cramped on mobile",
            "improve the UX of the signup flow",
            "build a landing page for the new product",
            "add a blog to the marketing site",
            "the frontend needs a dark mode",
            "redesign the portal navigation",
            "build a storefront with a cart",
            "make the home page read on a phone",
            "Build a website for a luxury boutique hotel in Miami Beach",
        ],
    )
    def test_an_unambiguous_word_decides_on_its_own(self, backend, task):
        """These only ever mean a screen, so the repository does not get
        to overrule them."""
        assert detect.has_a_face(backend, task) is True


class TestGreenfieldKeepsTheBenefitOfTheDoubt:
    """In an empty folder "build a site" is a new thing and almost
    certainly a screen. This is the case the repository cannot speak to."""

    @pytest.mark.parametrize(
        "task",
        [
            "build a site for my pool business",
            "build an app for tracking workouts",
            "build an interface for reviewing flagged activity",
        ],
    )
    def test_an_ambiguous_word_is_enough_when_there_is_nothing_here(self, empty, task):
        assert detect.has_a_face(empty, task) is True

    def test_but_not_when_nothing_matches_at_all(self, empty):
        assert detect.has_a_face(empty, "write a CLI that renames files") is False


class TestWhatIsOnDiskDecidesOutright:
    @pytest.mark.parametrize(
        "task",
        [
            "the first page of the site looks wrong",
            "fix the layout of the pricing page",
            "add pagination to the testimonials",
            "make the sync idempotent",
        ],
    )
    def test_a_repository_that_serves_pages_has_a_face(self, serves_pages, task):
        """Whatever the request says. The strongest signal there is."""
        assert detect.has_a_face(serves_pages, task) is True

    @pytest.mark.parametrize("where", detect.A_FACE_ON_DISK)
    def test_every_place_pages_live_counts(self, tmp_path, where):
        (tmp_path / ".git").mkdir()
        (tmp_path / where).mkdir(parents=True)
        assert detect.has_a_face(tmp_path, "make the sync idempotent") is True

    def test_the_disk_is_read_before_the_words(self):
        source = inspect.getsource(detect.has_a_face)
        assert source.index("A_FACE_ON_DISK") < source.index("FACES.search")


class TestNothingElseChanged:
    def test_no_new_word_list_was_added(self):
        """The fix is a rule over the signals that were already there."""
        source = inspect.getsource(detect)
        assert source.count("re.compile(") == 2
        for invented in ("brochure", "wizard", "looks wrong", "stylesheet"):
            assert invented not in source

    def test_the_four_ambiguous_words_are_named_once(self):
        assert detect.ALSO_MEANS_SOMETHING_ELSE.pattern.count("|") == 3
        for word in ("page", "site", "app", "interface"):
            assert word in detect.ALSO_MEANS_SOMETHING_ELSE.pattern

    def test_both_callers_still_ask_the_same_question(self):
        assert "from .detect import has_a_face" in inspect.getsource(
            session.Session._has_a_face
        )
        from drydock import cli

        assert "has_a_face(repo, run.task)" in inspect.getsource(
            cli._read_and_plan_in_one
        )

    def test_an_unreadable_repository_falls_back_to_the_word(self, tmp_path):
        """A path that cannot be listed is not a reason to decide no."""
        assert detect.has_a_face(tmp_path / "gone", "build a site") is True

    def test_no_task_is_not_a_visual_task(self, backend):
        assert detect.has_a_face(backend, "") is False
        assert detect.has_a_face(backend, None) is False
