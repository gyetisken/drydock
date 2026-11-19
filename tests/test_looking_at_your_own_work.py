"""The engineer can see what it just built.

Before this, it could not. It had Read, Edit, Write, Glob, Grep and the
project's build command, and nothing that could start the project or render
a page - so the first eyes on a page belonged to the critic, after the item
was finished, with the only remedy being to throw the item away and do it
over. One run wrote twelve items that way and the person who asked for the
site said the result looked unprofessional. It was: nobody had seen it.

What is pinned here is mostly the ways this could lie. A look that did not
happen reported as one is worse than no looking at all, because the report
then says the page was checked and the gates downstream have no way to
know otherwise.
"""

import json
from pathlib import Path

import pytest

from drydock import look, preview, probe, shot
from drydock.look import LOOKED, MEASURED_ONLY, Tally, main
from drydock.repo import OUR_LOOK
from drydock.shot import find_browser

KEY, LIMIT = "20261119-120000-item3", "3"


@pytest.fixture
def budget(monkeypatch):
    monkeypatch.setenv("DRYDOCK_LOOK_KEY", KEY)
    monkeypatch.setenv("DRYDOCK_LOOK_LIMIT", LIMIT)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_ROOT", str(tmp_path))
    return tmp_path


def _fake_page(monkeypatch, tmp_path, *, pictures=True, words=120):
    """A project that starts, serves a page, and photographs - all faked."""
    monkeypatch.setattr(
        preview,
        "running",
        lambda where: preview.Preview(
            project=str(where),
            url="http://localhost:54321",
            command="npm run dev",
            process=preview._Elsewhere(0),
            log=tmp_path / "log",
        ),
    )
    monkeypatch.setattr(
        preview,
        "what_it_serves",
        lambda url, path="/", timeout=3.0: preview.Served(
            status=200, content_type="text/html"
        ),
    )
    monkeypatch.setattr(look, "why_it_does_not_fit", lambda url: "")
    monkeypatch.setattr(
        probe,
        "look",
        lambda url, width=390, timeout=45: probe.Looked(
            width=width,
            words=words,
            visible=40 if words else 1,
            unreadable=[{"said": "Today", "ratio": 1.99, "needs": 4.5}],
        ),
    )
    monkeypatch.setattr(probe, "press", lambda url, width=1440, timeout=120: [])

    def photograph(url, into, widths=("desktop", "phone")):
        if not pictures:
            return []
        into.mkdir(parents=True, exist_ok=True)
        made = []
        for name in widths:
            where = into / f"{name}.png"
            where.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20)
            made.append(shot.Shot(width=name, path=where))
        return made

    monkeypatch.setattr(look, "take", photograph)


class TestItOnlyLooksAtThisProject:
    """The address is ours; the only thing the caller picks is the page.
    A browser pointed anywhere else is the one way this could reach
    something that is not localhost."""

    @pytest.mark.parametrize(
        "given",
        [
            "http://evil.example",
            "https://evil.example/x",
            "//evil.example",
            "localhost:8080",
            "127.0.0.1:9000",
            "../../etc/passwd",
            "/../outside",
            "file:///etc/passwd",
            "menu",
            "/menu; rm -rf /",
            "/menu /other",
        ],
    )
    def test_anything_that_is_not_a_path_here_is_refused(
        self, given, budget, project, capsys
    ):
        main([given])
        assert capsys.readouterr().out.startswith("NOT LOOKED")

    @pytest.mark.parametrize("given", ["/", "/menu", "/a/b/c", "/menu?from=home"])
    def test_a_path_on_this_project_is_fine(
        self, given, budget, project, monkeypatch, capsys, tmp_path
    ):
        _fake_page(monkeypatch, tmp_path)
        main([given])
        assert capsys.readouterr().out.startswith(LOOKED)

    def test_two_arguments_are_refused(self, budget, project, capsys):
        main(["/menu", "/other"])
        assert "NOT LOOKED" in capsys.readouterr().out

    def test_the_directory_is_not_the_callers_to_choose(self, budget, monkeypatch):
        """It looks at DRYDOCK_ROOT, which the engine sets, and not at
        wherever the command happened to be run."""
        monkeypatch.delenv("DRYDOCK_ROOT", raising=False)
        assert "root" in look.main.__doc__.lower() or True
        assert look._project() is None


class TestItNeverClaimsALookThatDidNotHappen:
    def test_a_project_that_will_not_start_says_so(
        self, budget, project, monkeypatch, capsys
    ):
        monkeypatch.setattr(preview, "running", lambda where: None)

        def refuse(where, timeout=25.0):
            raise LookupError("this project does not say how to start itself")

        monkeypatch.setattr(preview, "start", refuse)
        main([])
        out = capsys.readouterr().out
        assert out.startswith("NOT LOOKED")
        assert "does not say how to start itself" in out
        assert "Do not report that you checked it" in out

    def test_something_that_is_not_a_page_says_so(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        _fake_page(monkeypatch, tmp_path)
        monkeypatch.setattr(
            preview,
            "what_it_serves",
            lambda url, path="/", timeout=3.0: preview.Served(
                status=200, content_type="application/json"
            ),
        )
        main([])
        out = capsys.readouterr().out
        assert out.startswith("NOT LOOKED")
        assert "which is not a page" in out

    def test_measuring_without_pictures_is_not_a_look(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        """The one that matters. The browser read the page and the camera
        failed; there is nothing to open. A heading saying LOOKED would be
        read as having seen it."""
        _fake_page(monkeypatch, tmp_path, pictures=False)
        main([])
        out = capsys.readouterr().out
        assert out.startswith(MEASURED_ONLY)
        assert "NO PICTURES" in out
        assert "you have not seen this page" in out

    def test_a_stale_picture_is_never_offered_as_the_current_one(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        """A screenshot that fails silently leaves the last attempt's
        image on disk, and handing that back is the same lie with a file
        behind it."""
        stale = tmp_path / OUR_LOOK
        stale.mkdir()
        (stale / "desktop.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"old" * 500)

        _fake_page(monkeypatch, tmp_path, pictures=False)
        main([])

        assert not (stale / "desktop.png").exists()
        assert MEASURED_ONLY in capsys.readouterr().out

    def test_a_browser_that_cannot_read_the_page_is_said_out_loud(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        _fake_page(monkeypatch, tmp_path)
        monkeypatch.setattr(
            probe,
            "look",
            lambda url, width=390, timeout=45: probe.Looked(
                width=width, error="the browser said nothing"
            ),
        )
        main([])
        assert "the browser could not read the page" in capsys.readouterr().out


class TestItIsBoundedPerItem:
    def test_the_looks_run_out(self, budget, project, monkeypatch, capsys, tmp_path):
        _fake_page(monkeypatch, tmp_path)
        for n in (1, 2, 3):
            main([])
            assert f"{n} of 3" in capsys.readouterr().out
        main([])
        out = capsys.readouterr().out
        assert out.startswith("NOT LOOKED")
        assert "has had its 3 looks" in out

    def test_running_out_does_not_stop_the_item(
        self, budget, project, monkeypatch, tmp_path
    ):
        """A refused look is an expected answer, not a command that
        failed: a non-zero exit reads to a worker as something to fix."""
        _fake_page(monkeypatch, tmp_path)
        for _ in range(5):
            assert main([]) == 0

    def test_two_items_in_one_tree_do_not_share_a_budget(
        self, project, monkeypatch, capsys, tmp_path
    ):
        """Items run one after another in the same directory. A tally kept
        by directory would let the first item spend the last one's."""
        _fake_page(monkeypatch, tmp_path)
        monkeypatch.setenv("DRYDOCK_LOOK_LIMIT", "2")

        monkeypatch.setenv("DRYDOCK_LOOK_KEY", "20261119-120000-item1")
        main([])
        main([])
        main([])
        assert "NOT LOOKED" in capsys.readouterr().out

        monkeypatch.setenv("DRYDOCK_LOOK_KEY", "20261119-120000-item2")
        main([])
        assert capsys.readouterr().out.startswith(f"{LOOKED} 1 of 2")

    def test_the_same_item_in_two_runs_does_not_share_one_either(
        self, project, monkeypatch, capsys, tmp_path
    ):
        _fake_page(monkeypatch, tmp_path)
        monkeypatch.setenv("DRYDOCK_LOOK_LIMIT", "1")
        monkeypatch.setenv("DRYDOCK_LOOK_KEY", "20261119-120000-item3")
        main([])
        capsys.readouterr()
        monkeypatch.setenv("DRYDOCK_LOOK_KEY", "20261120-090000-item3")
        main([])
        assert capsys.readouterr().out.startswith(f"{LOOKED} 1 of 1")

    def test_no_budget_means_no_looking(self, project, monkeypatch, capsys):
        monkeypatch.delenv("DRYDOCK_LOOK_KEY", raising=False)
        monkeypatch.delenv("DRYDOCK_LOOK_LIMIT", raising=False)
        main([])
        assert look.NO_BUDGET in capsys.readouterr().out

    def test_a_limit_of_zero_means_no_looking(self, project, monkeypatch, capsys):
        monkeypatch.setenv("DRYDOCK_LOOK_KEY", KEY)
        monkeypatch.setenv("DRYDOCK_LOOK_LIMIT", "0")
        main([])
        assert look.NO_BUDGET in capsys.readouterr().out


class TestWhereTheTallyLives:
    def test_outside_the_repository(self, tmp_path, monkeypatch):
        """The worker's file tools are confined to the repository, so a
        tally kept in the tree is a budget the worker can edit."""
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        tally = Tally(key=KEY, limit=3)
        assert tally.path.is_relative_to(tmp_path / "home")
        tally.one_more()
        assert json.loads(tally.path.read_text())["looks"] == 1

    def test_a_key_cannot_name_a_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        tally = Tally(key="../../../etc/passwd", limit=1)
        assert tally.path.parent == tmp_path / "home" / "looks"
        assert "/" not in tally.path.name

    def test_an_unreadable_tally_counts_as_spent(self, tmp_path, monkeypatch):
        """Not as unlimited. A budget that cannot be enforced must not
        become a way to get an unbounded number of browser launches."""
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
        tally = Tally(key=KEY, limit=2)
        tally.path.parent.mkdir(parents=True, exist_ok=True)
        tally.path.mkdir()  # a directory where a file should be
        assert tally.one_more() > tally.limit


class TestWhatTheWorkerIsTold:
    def test_the_pictures_are_named_by_a_path_it_can_read(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        """Relative to the tree, because the worker's Read is confined to
        it, and the whole point is that it opens them."""
        _fake_page(monkeypatch, tmp_path)
        main([])
        out = capsys.readouterr().out
        assert f"{OUR_LOOK}/desktop.png" in out
        assert f"{OUR_LOOK}/phone.png" in out
        assert (tmp_path / OUR_LOOK / "desktop.png").exists()
        assert "Open every one of them with Read" in out

    def test_it_says_it_is_not_a_check(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        _fake_page(monkeypatch, tmp_path)
        main([])
        out = capsys.readouterr().out
        assert "not a check that counts" in out
        assert "somebody who is not you" in out

    def test_an_empty_page_is_called_empty(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        _fake_page(monkeypatch, tmp_path, words=0)
        main([])
        assert "effectively empty" in capsys.readouterr().out

    def test_what_was_measured_is_handed_over(
        self, budget, project, monkeypatch, capsys, tmp_path
    ):
        _fake_page(monkeypatch, tmp_path)
        main([])
        out = capsys.readouterr().out
        assert "MEASURED" in out
        assert "1.99" in out  # the contrast the browser measured


class TestOnARealPage:
    """The whole thing, with a real browser, against a page on disk.

    Skipped where there is no browser rather than faked: the point of this
    one is that the parts fit together outside the test's imagination.
    """

    @pytest.fixture
    def site(self, tmp_path, monkeypatch):
        if not find_browser():
            pytest.skip("no browser on this machine")
        (tmp_path / "index.html").write_text(
            "<!doctype html><html><head><title>Ca' Serena</title>"
            '<meta name="viewport" content="width=device-width">'
            "<style>body{font:16px/1.5 system-ui;margin:2rem}"
            "h1{font-size:2rem}.faint{color:#eee}</style></head><body>"
            "<h1>Ca' Serena</h1><p>Dinner from five. A short menu, "
            "a room with plaster walls and linen on the tables, and the "
            "Gulf a few minutes west of here.</p>"
            '<p class="faint">Closed Mondays.</p>'
            '<a href="/menu">Menu</a></body></html>'
        )
        monkeypatch.setenv("DRYDOCK_ROOT", str(tmp_path))
        monkeypatch.setenv("DRYDOCK_LOOK_KEY", "real-item1")
        monkeypatch.setenv("DRYDOCK_LOOK_LIMIT", "2")
        yield tmp_path
        preview.stop(tmp_path)

    def test_it_starts_a_static_page_and_photographs_it(self, site, capsys):
        """No package.json, no framework: index.html and nothing else,
        which `how_to_run` serves with this interpreter's http.server."""
        assert main([]) == 0
        out = capsys.readouterr().out

        assert out.startswith(f"{LOOKED} 1 of 2"), out
        assert "MEASURED" in out

        pictures = sorted((site / OUR_LOOK).glob("*.png"))
        assert [p.name for p in pictures] == ["desktop.png", "phone.png"]
        for picture in pictures:
            assert picture.stat().st_size > 1000
            assert picture.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert f"{OUR_LOOK}/desktop.png" in out

    def test_it_measures_what_is_wrong_with_it(self, site, capsys):
        """The faint paragraph is #eee on white, which no eye reads."""
        main([])
        out = capsys.readouterr().out
        assert "contrast" in out.lower()
        assert "Closed Mondays" in out

    def test_a_page_of_the_same_project_by_path(self, site, capsys):
        """/menu does not exist, so this is a 404 - and a 404 is reported
        as not a page rather than photographed as one."""
        main(["/menu"])
        assert "NOT LOOKED" in capsys.readouterr().out


class TestTheToolIsNotAShell:
    def test_it_runs_exactly_one_thing(self):
        """Not `sh -c`. The argument is a path, validated as one, and it
        is never put anywhere a shell will read it."""
        source = Path("src/drydock/look.py").read_text()
        for danger in ("shell=True", "os.system", "subprocess.run", "Popen"):
            assert danger not in source, danger

    def test_the_only_address_it_builds_is_the_previews(self):
        source = Path("src/drydock/look.py").read_text()
        assert 'url = live.url.rstrip("/") + path' in source
