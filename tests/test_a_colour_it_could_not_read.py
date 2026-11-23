"""Every element on a page measured at 1.06:1, and the page was fine.

An engineer building the AURA site said so itself, in its own report:

    The look tool's contrast measurement cannot parse oklch(): with the
    palette in oklch it reported every element at ~1.06:1

The measurement scraped the first three numbers out of whatever
`getComputedStyle` returned and read them as 0-255 channels. That held
while every browser answered `rgb(17, 17, 17)`. It stopped holding when
they started answering in the space the author wrote in - `oklch(0.25
0.02 60)` gave `[0.25, 0.02, 60]`, which is very nearly black whatever
the colour actually was, so ink and ground both came back black and
every ratio came back about one.

The same page told the critic nothing else either. The shot was one
capture of a fixed window, so a hero at 100svh filled it and the four
sections below were never in the picture. The critic said that too:
"Neither shot shows any of the four sections".

Both are measurements the program claimed to have made and had not.
A ratio computed from a colour nobody resolved is worse than no ratio,
and a picture of the top of a page offered as a picture of the page is
worse than no picture.
"""

import http.server
import threading

import pytest

from drydock.probe import look
from drydock.shot import WIDTHS, find_browser, take

MODERN = """<!DOCTYPE html><html lang="en"><head><title>Modern colour</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { background: oklch(0.97 0.012 85); color: oklch(0.25 0.02 60);
         font: 16px/1.6 system-ui; padding: 2rem; }
  .faint-oklch { color: oklch(0.90 0.01 85); }
  .fine-hex    { color: #222222; }
  .faint-hex   { color: #f2ede4; }
  .fine-lab    { color: lab(20% 2 8); }
</style></head><body>
  <h1>Colour the old parser could not read</h1>
  <p class="fine-hex">This hex text is dark on light and is readable by anybody.</p>
  <p class="faint-hex">This hex text is nearly the background and is not readable.</p>
  <p>This oklch body text is dark on light and is readable by anybody.</p>
  <p class="faint-oklch">This oklch text is nearly the ground and is not readable.</p>
  <p class="fine-lab">This lab text is dark on light and is readable by anybody.</p>
</body></html>"""

TALL = """<!DOCTYPE html><html lang="en"><head><title>Tall</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { margin: 0; font: 16px/1.6 system-ui; background: #fff; color: #111 }
  .arrival { height: 100svh; display: grid; place-items: center }
  section { height: 900px; padding: 2rem }
  #last { background: #102a1c; color: #f6f1e8 }
</style></head><body>
  <div class="arrival"><h1>The arrival fills the window</h1></div>
  <section id="one"><h2>The first section</h2><p>Under the fold.</p></section>
  <section id="two"><h2>The second section</h2><p>Further under it.</p></section>
  <section id="last"><h2>The last section</h2><p>The end of the page.</p></section>
</body></html>"""


@pytest.fixture(scope="module")
def serve(tmp_path_factory):
    root = tmp_path_factory.mktemp("colour-pages")
    (root / "modern.html").write_text(MODERN)
    (root / "tall.html").write_text(TALL)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def modern(serve):
    if not find_browser():
        pytest.skip("no browser on this machine")
    return look(f"{serve}/modern.html", 1440)


def unreadable(seen) -> list[str]:
    return [u["said"] for u in seen.unreadable]


class TestModernColourIsMeasured:
    def test_it_ran(self, modern):
        assert modern.ran, modern.error

    def test_readable_oklch_is_not_called_unreadable(self, modern):
        """The whole of the fault: every element came back failing."""
        assert not any("oklch body text" in s for s in unreadable(modern))

    def test_readable_lab_is_not_called_unreadable(self, modern):
        assert not any("lab text" in s for s in unreadable(modern))

    def test_readable_hex_still_passes(self, modern):
        assert not any("hex text is dark" in s for s in unreadable(modern))

    def test_unreadable_oklch_is_still_caught(self, modern):
        """Measuring correctly has to mean catching the real ones too,
        or this traded a false alarm for a blind spot."""
        assert any("oklch text is nearly the ground" in s for s in unreadable(modern))

    def test_unreadable_hex_is_still_caught(self, modern):
        assert any("hex text is nearly the background" in s for s in unreadable(modern))

    def test_the_ratios_are_not_all_the_same_number(self, modern):
        """They were: about 1.06, for everything on the page."""
        ratios = {u["ratio"] for u in modern.unreadable}
        assert len(ratios) == len(modern.unreadable)

    def test_the_failing_ratios_are_plausible(self, modern):
        for u in modern.unreadable:
            assert 1.0 <= u["ratio"] < 4.5, u


class TestAColourItCannotResolveIsNotGuessedAt:
    def test_there_is_somewhere_to_record_it(self):
        from drydock.probe import Looked

        assert Looked(width=390).unresolved == 0

    def test_a_page_of_ordinary_colour_resolves_all_of_it(self, modern):
        assert modern.unresolved == 0

    def test_it_is_reported_rather_than_counted_as_a_failure(self):
        from drydock.probe import Looked

        said = Looked(width=390, unresolved=3).worth_saying()
        assert any("could not resolve" in s for s in said)
        assert any("Nothing is claimed about them" in s for s in said)

    def test_nothing_unresolved_says_nothing(self):
        from drydock.probe import Looked

        assert not any(
            "could not resolve" in s for s in Looked(width=390).worth_saying()
        )

    def test_the_browser_resolves_it_rather_than_a_regex(self):
        """A list of syntaxes would be out of date the moment CSS gained
        another one. A canvas knows whatever this browser knows."""
        from pathlib import Path

        said = Path("src/drydock/probe.py").read_text()
        assert "getContext('2d'" in said
        assert "getImageData" in said
        assert "paint.fillStyle = said" in said

    def test_an_invalid_colour_is_detected_rather_than_inherited(self):
        """fillStyle keeps its old value when given nonsense, so it is
        set twice from two different sentinels and compared."""
        from pathlib import Path

        said = Path("src/drydock/probe.py").read_text()
        assert "if (paint.fillStyle !== first) return null;" in said


class TestThePictureIsOfTheWholePage:
    @pytest.fixture(scope="class")
    def shots(self, serve, tmp_path_factory):
        if not find_browser():
            pytest.skip("no browser on this machine")
        into = tmp_path_factory.mktemp("shots")
        return {s.width: s for s in take(f"{serve}/tall.html", into)}

    def test_both_widths_were_taken(self, shots):
        assert set(shots) == {"desktop", "phone"}

    def test_each_is_taller_than_the_window_it_opened_in(self, shots):
        """The page is an arrival plus 2,700px of sections. A picture the
        height of the window is a picture of the arrival."""
        for name, s in shots.items():
            assert s.path.stat().st_size > 1000
            assert _height(s.path) > WIDTHS[name][1], name

    def test_the_window_is_still_the_size_a_phone_is(self, shots):
        """Resizing the viewport to the document height is the obvious
        way and it is wrong: `100svh` grows with it and the page below
        gets pushed off. Measured when it was tried - the phone picture
        came back 5,534px tall with the hero repeated down it."""
        from pathlib import Path

        said = Path("src/drydock/shot.py").read_text()
        assert "captureBeyondViewport: true" in said
        assert "clip: { x: 0, y: 0, width, height: full, scale: 1 }" in said

    def test_the_phone_picture_is_still_phone_width(self, shots):
        assert _width(shots["phone"].path) == WIDTHS["phone"][0]

    def test_the_desktop_picture_is_still_desktop_width(self, shots):
        assert _width(shots["desktop"].path) == WIDTHS["desktop"][0]

    def test_a_very_tall_page_is_capped_rather_than_unbounded(self):
        from pathlib import Path

        said = Path("src/drydock/shot.py").read_text()
        assert "const TALLEST = 12000;" in said
        assert "TALLEST," in said

    def test_the_recorded_heights_are_still_the_floor(self):
        """Backward compatible: a short page is still photographed at the
        height it always was."""
        assert WIDTHS == {"phone": (390, 1800), "desktop": (1440, 2200)}


def _ihdr(path) -> tuple[int, int]:
    import struct

    raw = path.read_bytes()
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


def _width(path) -> int:
    return _ihdr(path)[0]


def _height(path) -> int:
    return _ihdr(path)[1]


class TestPartialCoverageIsReported:
    """A review of the top of a page must not read as a review of the
    page. The full-page capture ended that for ordinary pages; the cap
    would have reintroduced it one cap higher, in silence."""

    def shot(self, **kw):
        from pathlib import Path as P

        from drydock.shot import Shot

        return Shot(width="phone", path=P("/x"), **kw)

    def test_a_whole_page_says_nothing(self):
        said = self.shot(page=4200, took=4200)
        assert said.whole
        assert said.said() == ""

    def test_a_cut_one_says_where_it_stopped(self):
        said = self.shot(page=40000, took=12000)
        assert not said.whole
        assert "top 12000 pixels of a page 40000 tall" in said.said()
        assert "nothing is claimed about it" in said.said()

    def test_a_shot_with_no_numbers_is_taken_as_whole(self):
        """Backward compatible: an older capture reported "ok" and no
        sizes, and a picture with nothing said about it is the picture
        it always was."""
        assert self.shot().whole

    def test_the_critic_is_told(self):
        from pathlib import Path as P

        said = P("src/drydock/critic.py").read_text()
        assert "short = [s.said() for s in shots if not s.whole]" in said
        assert "Judge what you can see and say plainly that the rest was" in said

    def test_the_engineer_is_told(self):
        from pathlib import Path as P

        said = P("src/drydock/look.py").read_text()
        assert "NOT ALL OF IT" in said
        assert "short = [s.said() for s in fresh if not s.whole]" in said

    def test_the_cap_exists_and_is_generous(self):
        from pathlib import Path as P

        said = P("src/drydock/shot.py").read_text()
        assert "const TALLEST = 12000;" in said
