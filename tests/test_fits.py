"""Whether the page fits the screen it is on.

Seven items in one afternoon were refused for this, each time by somebody
describing what they saw. Described, it changed nothing - the engineer
cannot look at the page, so being told is all it has, and it had already
been told in prose. Measured, it is a number and an element name.
"""

from drydock.fits import Fit, why_it_does_not_fit


class TestWhatCountsAsFitting:
    def test_a_page_the_width_of_its_screen_fits(self):
        assert Fit(width=390, seen=390, needs=390).fits

    def test_a_page_wider_than_its_screen_does_not(self):
        assert not Fit(width=390, seen=390, needs=1187).fits

    def test_one_pixel_of_slack(self):
        """A rounded sub-pixel measure is not a defect."""
        assert Fit(width=390, seen=390, needs=391).fits
        assert not Fit(width=390, seen=390, needs=392).fits

    def test_a_narrower_page_is_not_a_complaint(self):
        """Short content is not a layout problem."""
        assert Fit(width=1440, seen=1440, needs=900).fits

    def test_a_measurement_that_failed_is_not_a_pass(self):
        """It is not a fail either - it is reported and skipped."""
        assert not Fit(width=390, error="there is no browser").fits


class TestWhatItSays:
    def test_it_gives_the_numbers(self, monkeypatch):
        """'The page needs 1187px and has 390px' is something to go and
        measure. 'Text is cut off' was said seven times."""
        from drydock import fits

        monkeypatch.setattr(
            fits, "measure", lambda url, w: Fit(width=w, seen=390, needs=1187)
        )
        said = why_it_does_not_fit("http://localhost:4321/", (390,))

        assert "needs 1187px" in said
        assert "has 390px" in said
        assert "797px of it is off" in said

    def test_it_names_what_is_too_wide(self, monkeypatch):
        from drydock import fits

        monkeypatch.setattr(
            fits,
            "measure",
            lambda url, w: Fit(width=w, seen=390, needs=900, wide=("section.hours",)),
        )
        assert "section.hours" in why_it_does_not_fit("http://x/", (390,))

    def test_a_page_that_fits_says_nothing(self, monkeypatch):
        from drydock import fits

        monkeypatch.setattr(
            fits, "measure", lambda url, w: Fit(width=w, seen=w, needs=w)
        )
        assert why_it_does_not_fit("http://x/", (390, 1440)) == ""

    def test_every_width_is_reported(self, monkeypatch):
        from drydock import fits

        monkeypatch.setattr(
            fits, "measure", lambda url, w: Fit(width=w, seen=w, needs=w + 500)
        )
        said = why_it_does_not_fit("http://x/", (390, 1440))

        assert "At 390px" in said
        assert "At 1440px" in said


class TestItFailsOpen:
    """A check that could not run must not refuse an item for something
    this program was unable to measure."""

    def test_no_browser_is_not_a_refusal(self, monkeypatch):
        from drydock import fits

        monkeypatch.setattr(fits, "find_browser", lambda: "")
        assert why_it_does_not_fit("http://x/", (390,)) == ""

    def test_no_node_is_not_a_refusal(self, monkeypatch):
        from drydock import fits

        monkeypatch.setattr(fits, "find_browser", lambda: "/chrome")
        monkeypatch.setattr(fits, "_node", lambda: "")
        assert why_it_does_not_fit("http://x/", (390,)) == ""

    def test_a_page_that_will_not_load_is_not_a_refusal(self, monkeypatch):
        from drydock import fits

        monkeypatch.setattr(
            fits, "measure", lambda url, w: Fit(width=w, error="it did not answer")
        )
        assert why_it_does_not_fit("http://x/", (390,)) == ""
