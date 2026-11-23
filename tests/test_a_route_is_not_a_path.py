"""A door locked from both sides, and a suite nobody ran.

Three defects, all of them found by one benchmark rather than reasoned
about, and all three in the gap between two parts that each behaved
correctly on its own.

`drydock-look /rooms` was refused twice over. The confiner reads every
argument that is not a switch as a filesystem path, resolves it, and
refuses anything landing outside the project - so `/rooms` was the
directory `/rooms` at the root of the disk. The worker then tried
`drydock-look rooms/`, which the confiner allowed because it is inside
the project and the tool refused because a route has to begin with `/`.
Four of that run's six look calls went on the attempt, and three of the
site's four pages were never seen by anybody.

The suite went the same way. An item on a greenfield job is verified by
the build, because the baseline had no tests. `verify` read that as "this
project has no tests" and returned the build's verdict - so the moment
the engineer wrote a suite, the suite stopped being the thing that had to
pass. One run recorded `tests_run: 0` and "compiles" for a project whose
own `npm test` passes fourteen tests, and the acceptance for an entire
website was that its static site generator exited 0.

And the critic was shown the front door of a four-page site and asked
what it thought of the site.

What is pinned here: the route rule is one rule read by both ends of the
door, it refuses everything a path traversal is spelt as, the exemption
is one command's arguments and not a loosening of the fence, a build
item runs a real suite when there is one without running it twice, and
every look says which pages it establishes anything about and which it
does not.
"""

import inspect
import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

import pytest

from drydock import confine, critic, look, orchestrate, preview, verify
from drydock.models import Baseline, Check
from drydock.route import LOOK, is_route, slug


def flat(text: str) -> str:
    """One line, so an assertion is not a claim about where it wraps."""
    return " ".join(text.split())


# --------------------------------------------------------------------------
# The rule itself
# --------------------------------------------------------------------------


class TestWhatCountsAsARoute:
    @pytest.mark.parametrize(
        "said",
        [
            "/",
            "/rooms",
            "/rooms/",
            "/dining/menus",
            "/a/b/c.html",
            "/rooms?guests=2",
            "/a-b_c.~d",
            "/visit?a=1&b=%20",
        ],
    )
    def test_a_page_of_the_project(self, said):
        assert is_route(said) is True

    @pytest.mark.parametrize(
        "said",
        [
            "rooms/",  # the spelling the worker fell back to
            "rooms",
            "",
            ".",
            "../rooms",
        ],
    )
    def test_anything_not_beginning_with_a_slash(self, said):
        assert is_route(said) is False


class TestItRefusesEveryWayUpwards:
    @pytest.mark.parametrize(
        "said",
        [
            "/..",
            "/../",
            "/../etc/passwd",
            "/a/..",
            "/a/../b",
            "/a/../../etc/passwd",
            "/rooms/../../../../etc/shadow",
            "/a/b/../../../c",
        ],
    )
    def test_a_dot_dot_segment(self, said):
        """The pattern this replaced had a comment saying `..` was refused
        and a character class that allowed it: `.` and `/` were both in
        it, so `/../../etc` matched."""
        assert is_route(said) is False

    @pytest.mark.parametrize(
        "said",
        [
            "/a%2e%2e/b",
            "/%2e%2e/etc",
            "/%2E%2E%2Fetc",
            "/a%2f..%2fb",
            "/%2fetc%2fpasswd",
        ],
    )
    def test_a_dot_dot_spelt_as_an_escape(self, said):
        """A percent escape in the path is refused outright rather than
        decoded and re-checked, because every decode is another chance to
        disagree with whoever decodes it next."""
        assert is_route(said) is False

    def test_an_escape_is_still_allowed_in_the_query(self):
        """Where it is ordinary and cannot become a path segment."""
        assert is_route("/search?q=%20two%20words") is True

    @pytest.mark.parametrize(
        "said",
        [
            "/a/./b",
        ],
    )
    def test_a_single_dot_segment_is_harmless(self, said):
        """It goes nowhere. Refusing it would buy nothing and `.` has to
        stay in the class for `/a/b/c.html`."""
        assert is_route(said) is True


class TestItRefusesEverythingThatIsNotThisSite:
    @pytest.mark.parametrize(
        "said",
        [
            "http://elsewhere/",
            "https://elsewhere/x",
            "file:///etc/passwd",
            "//evil.example.com/x",
            "///evil",
            "/x:8080",
            "/user@host",
            "localhost:3000/x",
        ],
    )
    def test_a_scheme_a_host_or_a_port(self, said):
        """A browser pointed somewhere else is the one way this command
        could reach anything but the preview it started."""
        assert is_route(said) is False

    def test_a_protocol_relative_url_is_the_one_that_looks_like_a_path(self):
        """`//host/path` is a host. It is the only refusal here that a
        character class alone would have let through."""
        assert is_route("//evil.example.com/rooms") is False
        assert is_route("/evil.example.com/rooms") is True  # one slash: a path

    @pytest.mark.parametrize(
        "said",
        [
            "/a b",
            "/a\tb",
            "/a\nb",
            "/a\rb",
            "/a\0b",
            " /a",
            "/a ",
            "/a\\b",
            "/a|b",
            "/a;b",
            "/a$b",
            "/a`b",
            "/a>b",
            "/a&b",
            "/a'b",
            '/a"b',
        ],
    )
    def test_anything_two_readers_could_read_as_two_things(self, said):
        assert is_route(said) is False

    def test_it_does_not_crash_on_what_is_not_a_string(self):
        for nonsense in (None, 7, [], {}, b"/rooms"):
            assert is_route(nonsense) is False


class TestWhereThePicturesGo:
    def test_the_home_page_keeps_the_top(self):
        """Everything that already reads pictures looks there."""
        assert slug("/") == ""

    def test_every_other_route_gets_its_own(self):
        assert slug("/rooms") == "rooms"
        assert slug("/rooms/") == "rooms"
        assert slug("/a/b") == "a-b"

    def test_the_query_is_not_part_of_the_directory(self):
        assert slug("/visit?x=1") == "visit"

    def test_it_cannot_name_a_directory_outside_itself(self):
        """Belt and braces: `is_route` has already refused these, and a
        name that escapes would be the one that mattered."""
        for said in ("/../x", "/a/../../b", "/..%2f.."):
            assert "/" not in slug(said)
            assert ".." not in slug(said)


# --------------------------------------------------------------------------
# The confiner: one command's arguments, and nothing else
# --------------------------------------------------------------------------


@pytest.fixture
def project():
    root = Path(tempfile.mkdtemp()).resolve()
    (root / "rooms").mkdir()
    (root / "src").mkdir()
    return root


def allowed(command: str, root: Path) -> bool:
    return confine._shell_offence(command, root) is None


class TestTheLookToolMayBeGivenARoute:
    def test_the_case_that_was_refused(self, project):
        assert allowed(f"{LOOK} /rooms", project)

    def test_the_home_page_with_no_argument(self, project):
        assert allowed(LOOK, project)

    def test_several_routes_at_once(self, project):
        assert allowed(f"{LOOK} /rooms /dining/ /visit", project)

    def test_a_route_that_matches_nothing_on_disk(self, project):
        """`/dining` is not a directory here, and that is the point: it
        is an address on the project's own server, not a file."""
        assert not (project / "dining").exists()
        assert allowed(f"{LOOK} /dining", project)

    def test_a_relative_path_inside_the_project_still_works(self, project):
        """It is not a route, so it is judged as a path - and it is one
        that lands inside, which it always was."""
        assert allowed(f"{LOOK} rooms", project)


class TestTheFenceIsNotLoosened:
    @pytest.mark.parametrize(
        "command",
        [
            "cat /rooms",
            "cat /etc/passwd",
            "ls /rooms",
            "head /etc/hosts",
            "grep x /etc/passwd",
            "find / -name id_rsa",
            "sed -n 1p /etc/passwd",
        ],
    )
    def test_another_command_given_the_same_argument(self, command, project):
        """The exemption is one command name. Every other command's
        arguments are still resolved and still have to land inside."""
        assert not allowed(command, project)
        assert "outside this project" in confine._shell_offence(command, project)

    @pytest.mark.parametrize(
        "command",
        [
            "curl /rooms",
            "wget /rooms",
            "nc localhost 80",
            "ssh host",
            "chmod 777 /",
        ],
    )
    def test_a_command_that_was_never_allowed(self, command, project):
        assert not allowed(command, project)

    @pytest.mark.parametrize(
        "argument",
        [
            "/../../etc/passwd",
            "//evil.example.com/x",
            "/a%2e%2e/b",
            "/etc/../etc/passwd",
        ],
    )
    def test_the_look_tool_given_something_that_is_not_a_route(self, argument, project):
        """It falls through to being judged as a path, and a path that
        lands outside is refused exactly as it was before."""
        assert not allowed(f"{LOOK} {argument}", project)

    def test_a_url_is_stopped_by_the_tool_rather_than_by_the_hook(
        self, project, monkeypatch, capsys
    ):
        """Said plainly because it is the one that looks like a hole and
        is not. `http://elsewhere/` has no leading slash, so the hook
        reads it as a relative filename, resolves it inside the project
        and has no reason to refuse it - it is a path that goes nowhere.
        What must never happen is the browser being pointed at it, and
        that is the tool's refusal, which runs before anything starts."""
        assert allowed(f"{LOOK} http://elsewhere/", project)
        monkeypatch.delenv("DRYDOCK_LOOK_KEY", raising=False)
        look.main(["http://elsewhere/"])
        out = capsys.readouterr().out
        assert out.startswith("NOT LOOKED")
        assert "is not a path on this project" in out
        assert is_route("http://elsewhere/") is False

    def test_a_route_cannot_smuggle_a_second_command(self, project):
        for command in (
            f"{LOOK} /rooms && cat /etc/passwd",
            f"{LOOK} /rooms; cat /etc/passwd",
            f"{LOOK} /rooms | cat /etc/passwd",
        ):
            assert not allowed(command, project)

    def test_a_route_cannot_carry_a_substitution(self, project):
        for command in (
            f"{LOOK} /$(whoami)",
            f"{LOOK} /`whoami`",
            f"{LOOK} /${{HOME}}",
            f"{LOOK} /rooms > /etc/passwd",
        ):
            assert not allowed(command, project)

    def test_the_absolute_path_refusal_still_works_for_the_look_tool(self, project):
        """A path is still a path when it is not a route: this one has a
        space in it, so it is not a route, and it is outside."""
        assert not allowed(f'{LOOK} "/etc/some file"', project)

    def test_one_name_decides_it(self):
        source = inspect.getsource(confine._one_command)
        assert "looking = name == LOOK" in source
        assert "if looking and is_route(word):" in source


class TestOneRuleReadByBoth:
    def test_the_hook_and_the_tool_import_the_same_one(self):
        assert (
            "from .route import LOOK, is_route"
            in Path("src/drydock/confine.py").read_text()
        )
        assert (
            "from .route import is_route, slug"
            in Path("src/drydock/look.py").read_text()
        )

    def test_the_old_pattern_is_gone(self):
        """Two rules for one question is how this defect existed."""
        assert "PATH_ONLY" not in Path("src/drydock/look.py").read_text()

    def test_the_name_is_said_once(self):
        """`confine` is a hook on every tool call and `engines` is the
        whole worker stack, so the name lives where both can import it
        for nothing."""
        from drydock import engines

        assert engines.LOOK == confine.LOOK == LOOK
        assert LOOK in confine.ALLOWED

    def test_the_validator_costs_the_hook_nothing(self):
        """It is imported on every tool call, so it may not drag the
        worker stack behind it."""
        source = Path("src/drydock/route.py").read_text()
        assert "import re" in source
        for heavy in ("preview", "probe", "shot", "subprocess", "urllib"):
            assert f"import {heavy}" not in source


class TestTheToolAgreesWithTheHook:
    def test_what_the_hook_passes_the_tool_accepts(self, project, monkeypatch, capsys):
        """A route the confiner lets through must not then be refused by
        the tool for being spelt wrongly. That disagreement is the whole
        defect."""
        monkeypatch.delenv("DRYDOCK_LOOK_KEY", raising=False)
        for said in ("/rooms", "/dining/", "/a/b/c.html"):
            assert allowed(f"{LOOK} {said}", project)
            look.main([said])
            out = capsys.readouterr().out
            # It gets as far as the budget, which is the first thing past
            # the argument check.
            assert "is not a path on this project" not in out

    def test_what_the_tool_refuses_says_why_in_full(self, monkeypatch, capsys):
        monkeypatch.delenv("DRYDOCK_LOOK_KEY", raising=False)
        look.main(["/../etc"])
        out = capsys.readouterr().out
        assert "NOT LOOKED" in out
        assert "no scheme, host, port or `..`" in out


# --------------------------------------------------------------------------
# Several routes, and saying which
# --------------------------------------------------------------------------


class TestTheLookToolTakesSeveralRoutes:
    def test_there_is_a_cap_on_one_command_line(self):
        assert look.AT_ONCE == 6

    def test_over_the_cap_is_refused_before_anything_starts(self, monkeypatch, capsys):
        monkeypatch.delenv("DRYDOCK_LOOK_KEY", raising=False)
        look.main([f"/p{n}" for n in range(look.AT_ONCE + 1)])
        out = capsys.readouterr().out
        assert "NOT LOOKED" in out
        assert f"{look.AT_ONCE} is the most this takes" in out

    def test_one_bad_route_refuses_the_whole_line(self, monkeypatch, capsys):
        """Not "the good ones were looked at and one was not" - the
        command was not understood, so nothing is claimed."""
        monkeypatch.delenv("DRYDOCK_LOOK_KEY", raising=False)
        look.main(["/rooms", "/../etc"])
        out = capsys.readouterr().out
        assert "NOT LOOKED" in out
        assert "is not a path on this project" in out

    def test_the_same_page_twice_is_one_page(self):
        source = inspect.getsource(look.main)
        assert 'if path.rstrip("/") not in [p.rstrip("/") for p in seen_already]' in (
            source
        )

    def test_a_page_costs_a_look_rather_than_an_invocation(self):
        """Otherwise one call could photograph six pages against a budget
        of two, and the budget exists to bound browser launches."""
        source = inspect.getsource(look.main)
        at = source.index("for path in paths:\n        nth = budget.one_more()")
        assert "if nth > budget.limit:" in source[at : at + 400]
        assert "not_looked_at.append(path)" in source[at : at + 400]

    def test_it_says_which_pages_it_establishes_anything_about(self):
        source = inspect.getsource(look.main)
        assert '"ROUTES"' in source
        assert "looked at:" in source
        assert "not looked at:" in source

    def test_a_page_it_could_not_reach_is_named_rather_than_inferred(self):
        source = flat(inspect.getsource(look.main)).replace('" "', "")
        assert "Say so in your report rather than describing them" in source

    def test_nothing_looked_at_still_says_not_looked(self):
        """The heading is the contract. A worker that sees anything else
        at the top of this output has been told something was
        established."""
        source = inspect.getsource(look.main)
        assert "if not looked_at:" in source
        assert "return _not_looked(" in source[source.index("if not looked_at:") :]

    def test_each_route_photographs_into_its_own_directory(self):
        source = inspect.getsource(look._one_page)
        assert "if slug(path):" in source
        assert "into = into / slug(path)" in source

    def test_the_pictures_are_named_where_they_actually_are(self):
        """A report that says to open `.drydock-look/desktop.png` for a
        picture at `.drydock-look/rooms/desktop.png` is an unopenable
        path in a sentence telling you to open it."""
        source = inspect.getsource(look._photograph)
        assert (
            'where = OUR_LOOK if into.name == OUR_LOOK else f"{OUR_LOOK}/{into.name}"'
            in (source)
        )

    def test_a_second_route_s_pictures_are_found_on_a_retry(self):
        source = inspect.getsource(orchestrate._one_item)
        assert 'any(looked.rglob("*.png"))' in source


class TestFindingTheOtherPages:
    def _page(self, body: str) -> str:
        return f"<html><body>{body}</body></html>"

    def _serve(self, monkeypatch, html: str, content_type: str = "text/html"):
        class Answer:
            headers: ClassVar[dict] = {"Content-Type": content_type}

            def read(self, _n=None):
                return html.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(
            "urllib.request.urlopen", lambda *a, **k: Answer(), raising=False
        )

    def test_it_reads_the_links_the_page_makes(self, monkeypatch):
        self._serve(
            monkeypatch,
            self._page('<a href="/rooms/">R</a><a href="/dining/">D</a>'),
        )
        assert preview.routes_on("http://x", cap=5) == ["/rooms/", "/dining/"]

    def test_the_home_page_is_never_one_of_them(self, monkeypatch):
        self._serve(monkeypatch, self._page('<a href="/">Home</a><a href="/x">X</a>'))
        assert preview.routes_on("http://x", cap=5) == ["/x"]

    def test_one_page_per_route_however_it_is_spelt(self, monkeypatch):
        self._serve(
            monkeypatch,
            self._page('<a href="/rooms">A</a><a href="/rooms/">B</a>'),
        )
        assert preview.routes_on("http://x", cap=5) == ["/rooms"]

    def test_it_is_capped(self, monkeypatch):
        self._serve(
            monkeypatch,
            self._page("".join(f'<a href="/p{n}">{n}</a>' for n in range(20))),
        )
        assert len(preview.routes_on("http://x", cap=2)) == 2

    def test_a_stylesheet_and_a_favicon_are_not_pages(self, monkeypatch):
        """The first attempt matched any `href` and came back with
        exactly these two."""
        self._serve(
            monkeypatch,
            '<link rel="icon" href="/assets/favicon.svg">'
            '<link rel="stylesheet" href="/assets/aura.css">'
            + self._page('<a href="/rooms/">R</a>'),
        )
        assert preview.routes_on("http://x", cap=5) == ["/rooms/"]

    def test_a_link_straight_to_a_file_is_not_a_page(self, monkeypatch):
        self._serve(
            monkeypatch,
            self._page('<a href="/menu.pdf">M</a><a href="/rooms">R</a>'),
        )
        assert preview.routes_on("http://x", cap=5) == ["/rooms"]

    def test_somewhere_else_is_never_one_of_them(self, monkeypatch):
        self._serve(
            monkeypatch,
            self._page(
                '<a href="https://elsewhere/x">E</a>'
                '<a href="//evil.example.com/y">P</a>'
                '<a href="/../etc/passwd">U</a>'
                '<a href="/rooms">R</a>'
            ),
        )
        assert preview.routes_on("http://x", cap=5) == ["/rooms"]

    def test_a_single_page_site_costs_one_page(self, monkeypatch):
        """Proportional to what is there rather than to what might be."""
        self._serve(monkeypatch, self._page("<p>no links</p>"))
        assert preview.routes_on("http://x", cap=2) == []

    def test_anything_that_is_not_html_is_not_read(self, monkeypatch):
        self._serve(monkeypatch, '{"a":"/rooms"}', content_type="application/json")
        assert preview.routes_on("http://x", cap=2) == []

    def test_a_server_that_does_not_answer_is_not_a_failure(self, monkeypatch):
        def refuse(*a, **k):
            raise OSError("nothing there")

        monkeypatch.setattr("urllib.request.urlopen", refuse, raising=False)
        assert preview.routes_on("http://x", cap=2) == []


class TestTheCriticSeesMoreThanTheFrontDoor:
    def test_it_takes_other_routes(self):
        assert "also" in inspect.signature(critic.look).parameters

    def test_each_one_is_photographed_into_its_own_directory(self):
        source = inspect.getsource(critic.look)
        assert (
            'take(url.rstrip("/") + path, scratch / (slug(path) or "page"))' in source
        )

    def test_a_route_that_will_not_photograph_is_named_not_dropped(self):
        source = inspect.getsource(critic.look)
        assert "missed.append(path)" in source
        assert "not photographed: " in source

    def test_it_is_told_which_page_is_in_which_directory(self):
        source = inspect.getsource(critic.look)
        assert "The pages you have, and where:" in source

    def test_it_is_told_not_to_judge_what_it_was_not_shown(self):
        source = flat(inspect.getsource(critic.look))
        assert "You have not seen these. Do not describe them" in source
        assert "not let them count for or against the item" in source

    def test_a_short_picture_on_any_page_is_still_reported(self):
        source = inspect.getsource(critic.look)
        assert (
            "short = [s.said() for _, p in pages for s in p if not s.whole]" in source
        )

    def test_the_run_decides_how_many_and_it_is_small(self):
        assert orchestrate.CRITIC_ALSO == 2

    def test_they_come_from_the_page_rather_than_from_a_guess(self):
        source = inspect.getsource(orchestrate._show_it)
        assert "preview.routes_on(live.url, cap=CRITIC_ALSO)" in source
        assert "also=also" in source

    def test_which_routes_were_looked_at_is_said_out_loud(self):
        source = inspect.getsource(orchestrate._show_it)
        assert 'on_event("critic", "looking at " + ", ".join(("/", *also)))' in source


# --------------------------------------------------------------------------
# The suite that was never run
# --------------------------------------------------------------------------


GREENFIELD = Baseline(
    builds=True, tests_run=0, tests_failed=0, tests_skipped=0, has_tests=False
)
ESTABLISHED = Baseline(
    builds=True, tests_run=9, tests_failed=0, tests_skipped=0, has_tests=True
)
TEST_OUTPUT = "# tests 14\n# pass 14\n# fail 0\n"
BUILD_OUTPUT = "built 4 pages into dist/\n"


class TestABuildItemStillRunsARealSuite:
    def _run(self, monkeypatch, commands, base=GREENFIELD, passing=True, detail=None):
        ran = []

        def record(name, command, repo):
            ran.append((name, command))
            said = detail or (TEST_OUTPUT if name == "tests" else BUILD_OUTPUT)
            return Check(
                name=name, command=command, passed=passing, seconds=0.1, detail=said
            )

        monkeypatch.setattr(verify, "check", record)
        return verify.verify(Path("/x"), "build", base, commands), ran

    AURA: ClassVar[dict] = {
        "build": "npm run build",
        "tests": "npm test",
        "has_tests": True,
    }
    SAME: ClassVar[dict] = {
        "build": "npm test",
        "tests": "npm test",
        "has_tests": True,
    }
    NO_TESTS: ClassVar[dict] = {
        "build": "npm run build",
        "tests": "npm run build",
        "has_tests": False,
    }

    def test_the_case_that_was_measured(self, monkeypatch):
        """A greenfield site whose engineer wrote a suite. The run
        recorded `tests_run: 0` and "compiles"; the suite passes 14."""
        verdict, ran = self._run(monkeypatch, self.AURA)
        assert ("tests", "npm test") in ran
        assert verdict.tests_run == 14
        assert verdict.passed is True

    def test_the_build_still_runs_first(self, monkeypatch):
        """An item verified by its tests must still leave something that
        builds, and that was true before this."""
        _, ran = self._run(monkeypatch, self.AURA)
        assert ran == [("build", "npm run build"), ("tests", "npm test")]

    def test_a_broken_build_still_fails_before_the_suite(self, monkeypatch):
        verdict, ran = self._run(monkeypatch, self.AURA, passing=False)
        assert verdict.passed is False
        assert verdict.reason == "the tests may pass but it no longer builds"
        assert ran == [("build", "npm run build")]

    def test_a_failing_suite_now_fails_the_item(self, monkeypatch):
        """This is the point. It could not fail before, because it never
        ran."""
        verdict, _ = self._run(
            monkeypatch,
            self.AURA,
            detail="# tests 14\n# pass 13\n# fail 1\n",
        )
        assert verdict.passed is False
        assert "1 tests failing" in verdict.reason

    def test_a_build_that_is_the_suite_runs_once(self, monkeypatch):
        """`"build": "npm test"` is what a worker writes when there is
        nothing to compile. Running it twice would be the duplicate this
        must not introduce."""
        verdict, ran = self._run(monkeypatch, self.SAME, detail=TEST_OUTPUT)
        assert len(ran) == 1
        assert verdict.tests_run == 14
        assert verdict.reason == "compiles, 14 tests pass"

    def test_a_project_with_no_tests_is_unchanged(self, monkeypatch):
        """The escape exists for this: demanding a suite here refuses an
        item for something nobody did wrong."""
        verdict, ran = self._run(monkeypatch, self.NO_TESTS)
        assert ran == [("build", "npm run build")]
        assert verdict.passed is True
        assert verdict.reason == "compiles"

    def test_an_established_suite_was_always_run(self, monkeypatch):
        """`needs_suite` was already true there, so this changes nothing
        for a project that had tests before the run started."""
        _, ran = self._run(monkeypatch, self.AURA, base=ESTABLISHED)
        assert ("tests", "npm test") in ran


class TestTheArithmeticIsUntouched:
    def test_a_dropped_count_still_refuses(self):
        source = inspect.getsource(verify.verify)
        assert "the suite reported success but ran 0 tests" in source
        assert "down from" in source

    def test_the_decision_is_the_exit_status(self):
        source = inspect.getsource(verify.verify_build)
        assert "passed=result.passed" in source

    def test_the_escape_asks_whether_there_is_a_suite(self):
        source = inspect.getsource(verify.verify)
        assert 'a_suite = bool(commands.get("has_tests"))' in source
        assert "and not a_suite" in source

    def test_the_per_item_check_still_leaves_the_suite_to_integration(self):
        """Deliberate, and the thing that keeps this from being a second
        run of the same tests on the same tree."""
        source = inspect.getsource(orchestrate._one_item)
        assert 'if item.verify_with == "build" and (build or commands["tests"]):' in (
            source
        )


class TestItWorksOnARealProject:
    """One project on disk, one node process, no model anywhere near it."""

    @pytest.fixture
    def built(self, tmp_path):
        (tmp_path / "package.json").write_text(
            # The file by name, not a glob. A glob is expanded by
            # whatever shell npm happens to use and matched nothing on
            # CI, so this asserted the pipeline and measured the shell.
            '{"name":"x","private":true,"type":"module","scripts":'
            '{"build":"node build.js","test":"node --test tests/a.test.js"}}'
        )
        (tmp_path / "build.js").write_text("console.log('built 1 page');\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "a.test.js").write_text(
            "import test from 'node:test';\n"
            "import assert from 'node:assert';\n"
            "test('one', () => assert.equal(1, 1));\n"
            "test('two', () => assert.equal(2, 2));\n"
        )
        return tmp_path

    @pytest.mark.skipif(
        subprocess.run(["which", "node"], check=False, capture_output=True).returncode
        != 0,
        reason="no node on this machine",
    )
    def test_the_suite_runs_and_the_count_is_recorded(self, built):
        from drydock.detect import detect

        chain = detect(built)
        commands = {
            "build": chain.build_command,
            "tests": chain.test_command,
            "has_tests": chain.has_tests,
        }
        assert commands["has_tests"] is True
        assert commands["build"] != commands["tests"]
        verdict = verify.verify(built, "build", GREENFIELD, commands)
        assert verdict.passed is True
        assert verdict.tests_run == 2
