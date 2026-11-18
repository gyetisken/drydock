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
from typing import ClassVar

import pytest

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
