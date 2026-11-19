"""The mark, and the two places it has to live in.

It is drawn twice: inline in the page, where its colours are theme
variables, and in favicon.svg, where they are written down because a tab
strip can be light or dark and the page cannot tell it which. Two copies
of the same path is the shape of bug this project has had twice already -
a plan schema that drifted from its copy, a gate map in Python and again
in JavaScript - so the copies are pinned to each other here.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "drydock" / "static"
FAVICON = (STATIC / "favicon.svg").read_text()
PAGE = (STATIC.parent / "web.py").read_text()

PATHS = re.compile(r'd="([^"]+)"')


def shapes(svg: str) -> list[str]:
    return [re.sub(r"\s+", " ", d).strip() for d in PATHS.findall(svg)]


class TestTheTwoCopiesAgree:
    def test_the_page_and_the_favicon_draw_the_same_mark(self):
        page = PAGE[PAGE.index('<svg class="mark"') : PAGE.index("</svg>")]
        assert shapes(page) == shapes(FAVICON), (
            "the mark was changed in one place and not the other"
        )

    def test_there_are_three_layers(self):
        assert len(shapes(FAVICON)) == 3


class TestWhatEachOneIsFor:
    def test_the_favicon_carries_its_own_colours(self):
        """`currentColor` in a tab strip is black on black half the time.

        Read off the attributes rather than the file: the first version of
        this searched the whole text and failed on the word appearing in a
        comment explaining why it is not used."""
        fills = re.findall(r'fill="([^"]+)"', FAVICON)

        assert fills, "the favicon paints nothing"
        assert "currentColor" not in fills
        assert set(fills) == {"#162742", "#ffffff"}

    def test_the_page_follows_the_theme(self):
        page = PAGE[PAGE.index('<svg class="mark"') : PAGE.index("</svg>")]
        assert "var(--markbg)" in page
        assert "var(--markink)" in page

    def test_the_tick_is_a_hole_and_not_a_stroke(self):
        """At sixteen pixels a stroke laid over the top layer closes up
        into a smudge. A hole stays a tick."""
        assert 'fill-rule="evenodd"' in FAVICON
        assert "stroke" not in FAVICON

    def test_the_page_asks_for_it(self):
        assert '<link rel="icon" href="/static/favicon.svg"' in PAGE


class TestNothingIsLeftLyingAbout:
    def test_the_old_mark_file_is_gone(self):
        """It was never referenced by anything - a third copy of the mark,
        dead since it was written."""
        assert not (STATIC / "mark.svg").exists()
