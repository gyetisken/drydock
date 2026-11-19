"""What a browser can say about a page without anybody looking at it.

Most of what people mean by "test the interface" is not a matter of
opinion. A stylesheet that 404s, a script that threw on load, an image
that never arrived, a button with no accessible name, text at a contrast
nobody can read, a page that renders at 980 pixels on a phone because
nothing told it not to - the browser already knows all of it.

These run a real Chrome against a real page served on a real port, and
they skip rather than fail where there is no browser or no node: a check
that could not run has to say so, not report a clean page it never saw.
"""

import http.server
import threading

import pytest

from drydock.probe import Looked, look
from drydock.shot import find_browser

BROKEN = """<!DOCTYPE html><html><head><title>Bad</title>
<link rel="stylesheet" href="missing.css">
<script>window.addEventListener('load', () => { null.boom(); });</script>
<style>body{background:#fff;color:#111} .faint{color:#cfcfcf;font-size:14px}</style>
</head><body>
  <h1>A page with things wrong</h1>
  <p class="faint">This text is pale grey on white and nobody can read it.</p>
  <img src="gone.png" alt="a picture that is not there">
  <button></button>
  <a href="#">Go nowhere</a>
  <p>Some ordinary readable text here, for comparison.</p>
</body></html>"""

FINE = """<!DOCTYPE html><html lang="en"><head><title>Good</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{background:#fff;color:#111;font:16px system-ui}</style>
</head><body>
  <h1>A page with nothing wrong</h1>
  <p>Black on white, a viewport tag, no images and no scripts. There is
  enough text here that nobody could mistake it for an empty page.</p>
  <a href="/somewhere">A link that goes somewhere</a>
</body></html>"""

BUTTONS = """<!DOCTYPE html><html><head><title>Buttons</title>
<meta name="viewport" content="width=device-width"><style>
body{background:#fff;color:#111;font:16px system-ui} .invisible{width:0;height:0;
overflow:hidden;padding:0;border:0} button,a{display:block;margin:10px 0}
</style></head><body>
<h1>Four buttons</h1>
<button onclick="document.getElementById('out').textContent='it happened'">This one works</button>
<button>This one does nothing</button>
<button onclick="null.explode()">This one throws</button>
<button class="invisible">Nobody can press this</button>
<a href="/fine.html">A link that goes somewhere</a>
<a href="https://example.com/away" target="_blank">A link that opens a tab</a>
<a href="tel:+19415550142">(941) 555-0142</a>
<p id="out"></p>
</body></html>"""

EMPTY = """<!DOCTYPE html><html><head><title>Nothing</title>
<meta name="viewport" content="width=device-width"></head><body></body></html>"""


@pytest.fixture(scope="module")
def serve(tmp_path_factory):
    """A page, on a real port, for the length of the module."""
    root = tmp_path_factory.mktemp("pages")
    (root / "broken.html").write_text(BROKEN)
    (root / "fine.html").write_text(FINE)
    (root / "empty.html").write_text(EMPTY)
    (root / "buttons.html").write_text(BUTTONS)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def seen(serve):
    if not find_browser():
        pytest.skip("no browser on this machine")
    return look(f"{serve}/broken.html", 390)


class TestWhatItFindsOnAPageWithThingsWrong:
    def test_it_ran_at_all(self, seen):
        assert seen.ran, seen.error

    def test_a_script_that_threw_on_load(self, seen):
        assert any("threw on load" in f for f in seen.findings())

    def test_a_stylesheet_that_did_not_arrive(self, seen):
        """The commonest invisible failure: the page loads, nothing is
        styled, and every test still passes."""
        assert any("Stylesheet did not load" in f for f in seen.findings())

    def test_an_image_that_did_not_arrive(self, seen):
        assert any("gone.png" in f for f in seen.findings())

    def test_it_says_each_thing_once(self, seen):
        """A missing image arrives twice - as a request that failed and as
        an image that never completed. Said twice, a report looks longer
        than the thing is wrong."""
        assert sum("gone.png" in f for f in seen.findings()) == 1

    def test_a_missing_viewport_tag(self, seen):
        assert not seen.viewport
        assert any("980px" in f for f in seen.findings())

    def test_a_control_with_no_name(self, seen):
        assert any("has no name" in f for f in seen.findings())

    def test_a_link_to_nowhere(self, seen):
        assert any("link to nowhere" in f for f in seen.findings())

    def test_text_nobody_can_read(self, seen):
        """Arithmetic, not an opinion: luminance gives a ratio and WCAG
        puts the line at 4.5."""
        said = [f for f in seen.findings() if "contrast" in f]
        assert said, seen.findings()
        assert "1.56:1" in said[0]

    def test_the_readable_paragraph_is_left_alone(self, seen):
        assert not any("ordinary readable text" in f for f in seen.findings())


class TestWhatItSaysAboutAPageWithNothingWrong:
    def test_it_finds_nothing(self, serve):
        if not find_browser():
            pytest.skip("no browser on this machine")
        seen = look(f"{serve}/fine.html", 390)

        assert seen.ran, seen.error
        assert seen.findings() == []
        assert seen.viewport
        assert seen.words > 20

    def test_a_blank_page_is_not_a_clean_page(self, serve):
        """It loads, it 200s, it has a title, and there is nothing on it.
        The one failure a screenshot catches instantly and a test suite
        never does."""
        if not find_browser():
            pytest.skip("no browser on this machine")
        seen = look(f"{serve}/empty.html", 390)

        assert seen.blank
        assert any("blank" in f for f in seen.findings())


class TestWhatItDoesWhenItCannotLook:
    def test_a_check_that_did_not_happen_is_not_a_pass(self):
        """Fails open, like the overflow measurement. A missing browser
        has to be said rather than reported as a page with nothing wrong."""
        nowhere = Looked(width=390, error="there is no browser on this machine")

        assert not nowhere.ran
        assert nowhere.findings() == []
        assert not nowhere.blank, "nothing was seen, so nothing was blank"

    def test_a_page_that_will_not_answer_says_so(self):
        """Not as a blank page and not as a clean one. Chrome serves its
        own error document, which has words on it, so "nothing rendered"
        is the wrong test - what matters is that the document failing is
        reported."""
        if not find_browser():
            pytest.skip("no browser on this machine")
        seen = look("http://127.0.0.1:9/", 390, timeout=40)

        assert seen.error or any("did not load" in f for f in seen.findings())

    def test_the_same_failure_is_not_counted_twice(self):
        """A document that will not load is both a request that failed and
        a navigation that did."""
        if not find_browser():
            pytest.skip("no browser on this machine")
        seen = look("http://127.0.0.1:9/", 390, timeout=40)

        assert len(seen.findings()) == len(set(seen.findings()))


class TestTheThingThatMadeItLookLikeItWorked:
    def test_the_regexes_survive_the_template_literal(self):
        """The page script is sent inside a JS template literal, and a
        template literal eats one backslash: `/\\s+/` written singly
        arrives as `/s+/`, which splits on the letter s.

        It looked like it worked. A page of a hundred and seventeen words
        measured as sixteen, and the colour parser returned null for every
        colour - so the contrast check reported a clean page it had never
        looked at.
        """
        from drydock import probe

        page = probe.LOOK[probe.LOOK.index("expression: `") :]
        assert r"/\\s+/" in page
        assert r"/[\\d.]+/g" in page
        assert r"/\s+/" not in page.replace(r"/\\s+/", "")

    def test_there_is_no_backtick_anywhere_in_the_page_script(self):
        """The same trap from the other side. A backtick closes the
        template, and one in the words "a `tel:` link" - in a comment -
        stopped the whole script compiling: `SyntaxError: Unexpected
        identifier 'tel'`, no output, and the probe reported "the browser
        said nothing" about every page it was pointed at.
        """
        from drydock import probe

        page = probe.LOOK[probe.LOOK.index("expression: `") + 13 :]
        page = page[: page.index("})()`")]

        assert "`" not in page


class TestPressingWhatIsSafeToPress:
    @pytest.fixture(scope="class")
    def pressed(self, serve):
        from drydock.probe import press

        if not find_browser():
            pytest.skip("no browser on this machine")
        return {p.said: p for p in press(f"{serve}/buttons.html", 1440)}

    def test_one_that_works_is_not_a_finding(self, pressed):
        assert pressed["This one works"].wrong == ""

    def test_one_that_does_nothing_is(self, pressed):
        assert "does nothing when pressed" in pressed["This one does nothing"].wrong

    def test_one_that_throws_says_what_it_threw(self, pressed):
        said = pressed["This one throws"].wrong
        assert "threw when pressed" in said
        assert "explode" in said

    def test_one_nobody_can_reach_is_a_finding(self, pressed):
        """On the page, with no size. A test suite never sees it and a
        screenshot does not show it."""
        assert "no size" in pressed["Nobody can press this"].wrong

    def test_a_link_within_the_site_is_followed(self, pressed):
        assert pressed["A link that goes somewhere"].did.startswith("went to")

    def test_a_new_tab_is_left_alone(self, pressed):
        """A browser this never gets back."""
        one = pressed["A link that opens a tab"]
        assert not one.tried
        assert one.why == "it opens a new tab"
        assert one.wrong == "", "not pressed is not a finding about the page"

    def test_another_app_is_left_alone(self, pressed):
        one = pressed["(941) 555-0142"]
        assert not one.tried
        assert "another app" in one.why
