"""Which items get looked at.

Rendering a page and having somebody look at it costs a minute. A parser has
nothing to look at, so the check is for work that changed what somebody sees
- and the question of which work that is must not be a guess made per run.
"""

import pathlib

from drydock.orchestrate import _changes_the_view


def diff(*paths: str) -> str:
    return "\n".join(f"--- a/{p}\n+++ b/{p}\n+x" for p in paths)


class TestSomebodySeesThis:
    def test_stylesheets(self):
        for path in ("src/styles/site.css", "app.scss", "a/b/main.less"):
            assert _changes_the_view(diff(path)), path

    def test_templates_and_components(self):
        for path in (
            "src/pages/index.astro",
            "views/home.ejs",
            "src/components/Menu.tsx",
            "templates/base.html",
            "app/layout.tsx",
        ):
            assert _changes_the_view(diff(path)), path

    def test_anything_under_a_directory_that_is_rendered(self):
        assert _changes_the_view(diff("public/hero.svg"))
        assert _changes_the_view(diff("src/layouts/Base.astro"))


class TestNobodySeesThis:
    def test_logic_and_data(self):
        for path in ("src/hours/week.ts", "lib/parse.py", "cmd/main.go"):
            assert not _changes_the_view(diff(path)), path

    def test_tests(self):
        assert not _changes_the_view(diff("tests/week.test.ts"))

    def test_project_files(self):
        for path in ("package.json", "README.md", ".gitignore", "tsconfig.json"):
            assert not _changes_the_view(diff(path)), path

    def test_an_empty_diff(self):
        assert not _changes_the_view("")


def test_one_visible_file_among_many_is_enough():
    assert _changes_the_view(diff("src/hours/week.ts", "package.json", "app.css"))


def test_the_two_verdicts_do_not_share_a_name():
    """The verification says `passed`, the critic says `approved`, and both
    were once called `verdict` in the same scope. The critic approved an item
    and the loop crashed on the next line reading `.passed` off the wrong
    one. Checked across the module rather than one function, because the call
    has already moved once."""
    import inspect

    from drydock import orchestrate

    source = inspect.getsource(orchestrate)
    assert "_show_it(" in source, "the critic is no longer called at all"
    assert "verdict, spend = _show_it(" not in source
    assert "verdict = _show_it(" not in source


class TestAPageThatNeverFinishesLoading:
    """A stream, a socket, a dashboard that polls - none of them ever reach
    'loaded', so the browser waits for them. It used to wait sixty seconds
    and then raise, which is the wrong way round twice: the page most worth
    looking at is the live one, and a check that cannot run has to say so
    rather than take the run down."""

    def test_the_browser_is_told_to_take_the_picture_anyway(
        self, tmp_path, monkeypatch
    ):
        """Without this flag the picture is never written at all, and a live
        page is simply never looked at."""
        from drydock import shot

        seen: list[str] = []
        monkeypatch.setattr(shot, "find_browser", lambda: "/bin/true")
        monkeypatch.setattr(
            shot.subprocess, "run", lambda command, **kw: seen.extend(command)
        )

        shot.take("http://localhost:1/", tmp_path, widths=("desktop",))
        assert "--timeout=6000" in seen

    def test_a_browser_that_will_not_exit_is_not_an_error(self, tmp_path, monkeypatch):
        from drydock import shot

        monkeypatch.setattr(shot, "find_browser", lambda: "/bin/true")
        monkeypatch.setattr(
            shot.subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(
                shot.subprocess.TimeoutExpired(cmd="chrome", timeout=20)
            ),
        )
        assert shot.take("http://localhost:1/", tmp_path) == []

    def test_a_picture_written_before_it_hung_is_still_used(
        self, tmp_path, monkeypatch
    ):
        """Which is the usual case: the page rendered and then went on
        waiting for a connection that does not end."""
        from drydock import shot

        def writes_then_hangs(command, **kw):
            for flag in command:
                if flag.startswith("--screenshot="):
                    pathlib.Path(flag.split("=", 1)[1]).write_bytes(b"x" * 2000)
            raise shot.subprocess.TimeoutExpired(cmd="chrome", timeout=20)

        monkeypatch.setattr(shot, "find_browser", lambda: "/bin/true")
        monkeypatch.setattr(shot.subprocess, "run", writes_then_hangs)

        got = shot.take("http://localhost:1/", tmp_path, widths=("desktop",))
        assert [s.width for s in got] == ["desktop"]

    def test_a_browser_that_cannot_be_started_is_not_an_error(
        self, tmp_path, monkeypatch
    ):
        from drydock import shot

        monkeypatch.setattr(shot, "find_browser", lambda: "/nope")
        monkeypatch.setattr(
            shot.subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(OSError("no such file")),
        )
        assert shot.take("http://localhost:1/", tmp_path) == []

    def test_no_browser_at_all_says_nothing_rather_than_raising(
        self, tmp_path, monkeypatch
    ):
        from drydock import shot

        monkeypatch.setattr(shot, "find_browser", lambda: "")
        assert shot.take("http://localhost:1/", tmp_path) == []


class TestAPhoneIsNotAWindowThatHappensToBeNarrow:
    """The worst bug of the day, and it was in the measuring instrument.

    A page that says `width=device-width` gets the window width on a
    desktop browser and 980px when the browser does not believe it is a
    device - and headless Chrome does not. So a 390px window produced a
    picture of a 980px page with 390px of it showing, and every narrow
    render looked like text cut off at the right edge. Eight items were
    refused on that picture in one afternoon. The pages were fine.
    """

    def test_the_picture_is_taken_through_device_emulation(self):
        import inspect

        from drydock import shot

        source = inspect.getsource(shot)
        assert "Emulation.setDeviceMetricsOverride" in source
        assert "mobile: width < 700" in source

    def test_the_phone_width_is_a_phone(self):
        """420 was neither a common device nor narrow enough to catch
        anything. 390 is the width of the phone most people have."""
        from drydock.shot import WIDTHS

        assert WIDTHS["phone"][0] == 390

    def test_the_flag_alone_is_only_a_fallback(self):
        """It cannot emulate a device, so what it produces is a crop of a
        wide page. Kept for machines with no node, and labelled as such."""
        import inspect

        from drydock import shot

        source = inspect.getsource(shot.take)
        assert "No Node on this machine" in source

    def test_nothing_to_photograph_with_is_still_not_an_error(
        self, tmp_path, monkeypatch
    ):
        from drydock import shot

        monkeypatch.setattr(shot, "find_browser", lambda: "")
        assert shot.take("http://localhost:1/", tmp_path) == []
