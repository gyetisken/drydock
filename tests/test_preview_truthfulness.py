"""What the preview panel is allowed to claim.

A small HTTP service was reported as `1 of 1 items landed` with a green
dot beside a panel showing `{"error":"not found"}`. Every part of that was
true on its own: the item did land, the server was running, and the
project has a /health endpoint and no home page, so its root is a 404.
Put together they read as the whole thing having failed.

Three facts were being shown as one. These pin them apart - and pin that
the checking happens on this side, because the frame is cross-origin and
the page cannot read the status of what it just loaded.
"""

import http.server
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from drydock.critic import Verdict as Seen
from drydock.preview import Served, what_it_serves


class Serving(http.server.BaseHTTPRequestHandler):
    """A project, for the length of one test."""

    # Replaced on the subclass each fixture builds, never mutated here.
    pages: ClassVar[dict] = {}

    def do_GET(self):
        body, kind, status = self.pages.get(
            self.path, (b'{"error":"not found"}', "application/json", 404)
        )
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def project():
    """Start a server with the given pages and hand back its url."""
    started = []

    def serve(pages: dict):
        handler = type("Handler", (Serving,), {"pages": pages})
        httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield serve
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


class TestAProjectWithAHomePage:
    def test_the_root_is_a_page(self, project):
        url = project({"/": (b"<!doctype html><h1>LUMI</h1>", "text/html", 200)})
        seen = what_it_serves(url)

        assert seen.status == 200
        assert seen.is_a_page
        assert "200" in seen.said


class TestAServiceWithNoHomePage:
    """A /health endpoint and nothing at the root is a service working
    exactly as it was asked to."""

    def test_the_root_is_reported_as_what_it_is(self, project):
        url = project(
            {
                "/health": (
                    json.dumps({"status": "ok"}).encode(),
                    "application/json",
                    200,
                )
            }
        )
        seen = what_it_serves(url)

        assert seen.status == 404
        assert not seen.is_a_page

    def test_it_is_not_called_an_error(self, project):
        """The status is a fact about the project. Describing it as a
        failure of the run is the bug this exists to stop."""
        url = project({"/health": (b"{}", "application/json", 200)})
        seen = what_it_serves(url)

        assert seen.error == ""
        assert "HTTP 404" in seen.said

    def test_the_endpoint_answers_when_asked_for_directly(self, project):
        """Nothing guesses this path - the test knows it. Pinned so that a
        future change that does offer route links has something to stand
        on."""
        url = project(
            {
                "/health": (
                    json.dumps({"status": "ok"}).encode(),
                    "application/json",
                    200,
                )
            }
        )
        seen = what_it_serves(url, "/health")

        assert seen.status == 200
        assert not seen.is_a_page, "json is not something to put in a frame"


class TestAServerThatIsNotThere:
    def test_an_unreachable_port_says_so(self):
        seen = what_it_serves("http://127.0.0.1:1")

        assert seen.status == 0
        assert not seen.is_a_page
        assert "did not answer" in seen.said

    def test_it_does_not_claim_a_status_it_did_not_get(self):
        seen = what_it_serves("http://127.0.0.1:1")
        assert "HTTP" not in seen.said


class TestWhatCountsAsSomethingToShow:
    @pytest.mark.parametrize(
        ("status", "kind", "shown"),
        [
            (200, "text/html", True),
            (200, "text/html; charset=utf-8", True),
            (201, "text/html", True),
            (200, "application/json", False),
            (200, "text/plain", False),
            (404, "text/html", False),
            (500, "text/html", False),
            (0, "", False),
        ],
    )
    def test_only_a_page_that_answered_is_framed(self, status, kind, shown):
        assert Served(status=status, content_type=kind).is_a_page is shown

    def test_a_status_with_no_content_type_is_not_assumed_to_be_a_page(self):
        assert not Served(status=200).is_a_page


class TestTheWindowSaysWhatWasObserved:
    def test_the_three_facts_are_separate_in_the_page(self):
        """The dot used to go green on the port answering and stand for
        the whole thing."""
        from pathlib import Path

        said = Path("src/drydock/static/chat.js").read_text()
        assert "standing(body)" in said
        assert "the server" in said and "this page" in said

    def test_nothing_is_framed_unless_it_is_a_page(self):
        from pathlib import Path

        said = Path("src/drydock/static/chat.js").read_text()
        assert "if (!body.is_a_page) { Pv.nothingToRender(body); return; }" in said

    def test_no_route_is_guessed(self):
        """drydock keeps no route metadata. Reading a path out of the task
        prose would be inventing one."""
        from pathlib import Path

        said = Path("src/drydock/static/chat.js").read_text()
        assert "not going to guess" in said

        # Only the preview object, and only its code: comments may discuss
        # an endpoint, and drydock's own /api routes are not the project's.
        start = said.index("const Pv = {")
        panel = said[start : said.index("\n};", start)]
        code = "\n".join(
            line for line in panel.splitlines() if not line.strip().startswith("//")
        )
        for path in ("/health", "/status", "/index.html", "/home"):
            assert path not in code, f"{path} is hardcoded"

        # The frame is built from the url it was given and nothing appended.
        assert 'iframe src="${esc(Pv.url)}' in code

    def test_the_checking_happens_on_this_side(self):
        """The frame is cross-origin, so the browser cannot read the
        status of what it loaded. If this ever moves into the page it will
        silently stop working."""
        from pathlib import Path

        said = Path("src/drydock/web.py").read_text()
        assert "preview.what_it_serves(live.url)" in said


class TestWhatTheCriticIsAllowedToJudge:
    """The same confusion, one floor down, and far more expensive there.

    A static page was written into a project whose `package.json` starts a
    JSON API. The preview ran that API, because it is what the project says
    starts it, and the critic was handed a browser's raw-JSON view of it.
    The critic said, correctly, that there is no page - and the item was
    rolled back for it. Four attempts, two reverts, a split and thirty-three
    minutes, and the thing being photographed was never the thing that had
    just been written.

    `_show_it` already says what should happen here: a project that will not
    start is "a check that did not happen, reported as such, rather than an
    item rolled back for a failure that belongs to this program". A project
    that starts and serves something other than a page is the same case.
    """

    def a_run(self, monkeypatch, url, command="npm run start"):
        """`_show_it`, with only the preview it is handed replaced. No
        browser, no model, no repository. `_show_it` imports `preview`
        inside itself, so the module is what has to be patched."""
        from drydock import orchestrate, preview

        live = SimpleNamespace(url=url, command=command)
        monkeypatch.setattr(preview, "running", lambda repo: live)
        said = []
        return orchestrate, said

    def show(self, orchestrate, said):
        return orchestrate._show_it(
            Path("/nowhere"),
            SimpleNamespace(direction="", model="opus"),
            SimpleNamespace(plain="a page", title="a page", as_asked=lambda: ""),
            lambda who, text: said.append((who, text)),
        )

    def test_a_json_api_is_not_judged_as_a_page(self, project, monkeypatch):
        url = project({"/health": (b'{"ok":true}', "application/json", 200)})
        orchestrate, said = self.a_run(monkeypatch, url)

        seen, cost = self.show(orchestrate, said)

        assert seen is None, "a critic that did not look must not return a verdict"
        assert cost == 0.0
        ((_, text),) = [s for s in said if s[0] == "critic"]
        assert text.startswith("did not look")
        assert "not a page" in text
        assert "npm run start" in text, "say what served it, or this is unfixable"

    def test_a_page_is_still_judged(self, project, monkeypatch):
        """The check must not become a way of never judging anything."""
        url = project({"/": (b"<h1>hello</h1>", "text/html", 200)})
        orchestrate, said = self.a_run(monkeypatch, url)
        reached = []
        monkeypatch.setattr(
            orchestrate,
            "why_it_does_not_fit",
            lambda url, on_event=None: reached.append(url) or "",
        )
        monkeypatch.setattr(
            orchestrate,
            "look_at_it",
            lambda *a, **k: (
                Seen(looked=True, approved=True, reason="ok", noticed=[]),
                0.0,
            ),
        )

        seen, _ = self.show(orchestrate, said)

        assert reached == [url], "a real page must reach the measurement"
        assert seen is not None and seen.approved

    def test_a_server_that_stopped_answering_is_not_a_refusal(
        self, project, monkeypatch
    ):
        """It answered when the preview started and does not now. That is
        this program's problem, not the item's."""
        orchestrate, said = self.a_run(monkeypatch, "http://127.0.0.1:1")

        seen, _ = self.show(orchestrate, said)

        assert seen is None
        assert "did not look" in said[-1][1]


class TestAPlainPageCanBeLookedAt:
    """The whole chain for the one kind of project that had none of it.

    A folder of index.html and styles.css could not be previewed, because
    nothing in it says how to start a server - so the panel had nothing to
    show and the critic was never handed a URL. The one kind of work the
    critic exists for was the one kind it could not see.

    This starts a real server on a real port and asks it a real question.
    No network leaves the machine and no model is called.
    """

    def test_it_is_started_served_and_seen_as_a_page(self, tmp_path):
        from drydock import preview

        (tmp_path / "index.html").write_text(
            "<!doctype html><title>Roasters</title><h1>Gulf Coast</h1>"
        )
        (tmp_path / "styles.css").write_text("body{background:#f4ede1}")

        live = preview.start(tmp_path)
        try:
            page = what_it_serves(live.url)
            sheet = what_it_serves(live.url, "/styles.css")

            assert page.is_a_page, page.said
            assert page.status == 200
            assert sheet.status == 200, "the page's own files have to serve too"
        finally:
            preview.stop(tmp_path)

    def test_stopping_it_actually_stops_it(self, tmp_path):
        """A static server left running holds a port and answers for a
        project that has moved on - which is how the critic ends up
        photographing something that is no longer the work."""
        from drydock import preview

        (tmp_path / "index.html").write_text("<h1>hello</h1>")
        live = preview.start(tmp_path)

        preview.stop(tmp_path)

        assert not what_it_serves(live.url).is_a_page
