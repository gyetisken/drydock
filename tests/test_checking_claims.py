"""Whether the page does what somebody said it would.

The probe reports facts: the text, the headings, the links and where they
go, how many rows are in each list. Deciding whether "the hours show the
seven-day week" is true of those facts needs meaning, so a model is asked.

What keeps that honest is the shape of the answer. Every verdict quotes
the thing on the page it rests on, and the quote is then looked for in
the facts. A verdict whose evidence is not there is not a verdict - it
becomes "could not check", which is true and useless, rather than "met",
which is useful and false.

So the model supplies meaning and arithmetic supplies the check on it.
"""

from dataclasses import dataclass, field

from drydock.claims import MET, MISSING, UNKNOWN, Checked, Report, _said, _tool


@dataclass
class Page:
    """What the probe found, as the checker is handed it."""

    title: str = "Gulf Coast Roasters"
    text: str = "Pazartesi 07:00-16:00\nSalı 07:00-16:00\nMenü"
    headings: list = field(default_factory=lambda: ["Menü", "Ziyaret"])
    links: list = field(default_factory=lambda: ["Menüyü gör", "(941) 555-0142"])
    going: list = field(
        default_factory=lambda: [
            {"said": "(941) 555-0142", "to": "tel:+19415550142"},
            {"said": "Menüyü gör", "to": "#menu"},
        ]
    )
    lists: list = field(
        default_factory=lambda: [{"what": "dl", "rows": 7, "said": "Pazartesi Salı"}]
    )


def answered(*checks) -> Report:
    claims = [c["claim"] for c in checks]
    return _said({"checks": list(checks)}, claims, Page())


class TestTheThreeAnswers:
    def test_a_verdict_whose_evidence_is_on_the_page_stands(self):
        report = answered(
            {"claim": "there is a menu", "verdict": MET, "evidence": "Menü", "why": ""}
        )
        (one,) = report.checks

        assert one.verdict == MET
        assert one.quoted

    def test_a_count_counts_as_evidence(self):
        """ "a dl with 7 rows" is evidence of a different kind, and the
        number in it is what there is to check."""
        report = answered(
            {
                "claim": "seven days",
                "verdict": MET,
                "evidence": "a dl with 7 rows",
                "why": "",
            }
        )
        assert report.checks[0].verdict == MET

    def test_where_a_link_goes_is_evidence(self):
        """Without hrefs, "a phone number you can tap" cannot be settled:
        the number is plainly in the text and whether it is a tel: link is
        the whole question."""
        report = answered(
            {
                "claim": "the phone number is tappable",
                "verdict": MET,
                "evidence": "tel:+19415550142",
                "why": "",
            }
        )
        assert report.checks[0].verdict == MET

    def test_missing_is_a_verdict_about_the_page_too(self):
        report = answered(
            {
                "claim": "there is a booking form",
                "verdict": MISSING,
                "evidence": "Menü",
                "why": "nothing about booking",
            }
        )
        assert report.checks[0].verdict == MISSING
        assert report.checks[0].settled

    def test_could_not_check_is_left_alone(self):
        """It is a claim about this tool rather than about the page, and
        it has no evidence to verify."""
        report = answered(
            {
                "claim": "the button works when clicked",
                "verdict": UNKNOWN,
                "evidence": "",
                "why": "clicking is behaviour",
            }
        )
        assert report.checks[0].verdict == UNKNOWN


class TestEvidenceThatIsNotThere:
    def test_a_verdict_resting_on_nothing_is_downgraded(self):
        """The failure that matters: words that sound right, a verdict of
        met, and somebody reads it as checked."""
        report = answered(
            {
                "claim": "there is a booking form",
                "verdict": MET,
                "evidence": "Rezervasyon yap",
                "why": "",
            }
        )
        (one,) = report.checks

        assert one.verdict == UNKNOWN
        assert not one.quoted
        assert "not found on the page" in one.why
        assert "Rezervasyon yap" in one.why

    def test_a_missing_verdict_is_held_to_it_as_well(self):
        """Saying something is absent is also a claim about the page."""
        report = answered(
            {
                "claim": "no prices",
                "verdict": MISSING,
                "evidence": "a price list nobody wrote",
                "why": "",
            }
        )
        assert report.checks[0].verdict == UNKNOWN

    def test_an_empty_quote_is_not_evidence(self):
        report = answered(
            {"claim": "there is a menu", "verdict": MET, "evidence": "", "why": ""}
        )
        assert report.checks[0].verdict == UNKNOWN

    def test_whitespace_and_case_do_not_defeat_a_real_quote(self):
        """A quote that crossed a line in the page should still match."""
        report = answered(
            {
                "claim": "the hours start at seven",
                "verdict": MET,
                "evidence": "PAZARTESI   07:00-16:00",
                "why": "",
            }
        )
        assert report.checks[0].verdict == MET


class TestNothingIsQuietlyDropped:
    def test_a_claim_nobody_answered_comes_back_unchecked(self):
        report = _said(
            {
                "checks": [
                    {
                        "claim": "there is a menu",
                        "verdict": MET,
                        "evidence": "Menü",
                        "why": "",
                    }
                ]
            },
            ["there is a menu", "there is a map"],
            Page(),
        )

        assert len(report.checks) == 2
        unchecked = [c for c in report.checks if c.claim == "there is a map"]
        assert unchecked[0].verdict == UNKNOWN
        assert "no answer came back" in unchecked[0].why

    def test_nothing_claimed_is_said_plainly(self):
        assert Report().say == "nothing was claimed"

    def test_the_count_separates_the_three(self):
        report = answered(
            {"claim": "a", "verdict": MET, "evidence": "Menü", "why": ""},
            {"claim": "b", "verdict": MISSING, "evidence": "Menü", "why": ""},
            {"claim": "c", "verdict": UNKNOWN, "evidence": "", "why": ""},
        )
        assert report.say == "1 met, 1 missing, 1 could not be checked"


class TestWhatItIsToldToDo:
    def test_the_three_answers_are_the_only_ones(self):
        verdicts = _tool().schema["properties"]["checks"]["items"]["properties"]
        assert set(verdicts["verdict"]["enum"]) == {MET, MISSING, UNKNOWN}

    def test_evidence_is_required_of_it(self):
        required = _tool().schema["properties"]["checks"]["items"]["required"]
        assert "evidence" in required

    def test_it_is_told_the_quote_will_be_looked_for(self):
        from drydock.claims import SYSTEM

        assert "looked for in the page afterwards" in SYSTEM
        assert "could not check" in SYSTEM

    def test_it_is_told_which_way_being_wrong_is_expensive(self):
        from drydock.claims import SYSTEM

        assert "somebody will read it as checked" in SYSTEM

    def test_it_is_given_no_tools(self):
        import inspect

        from drydock import claims

        source = inspect.getsource(claims.check)
        assert 'tools=""' in source, "the claude path hands it none"
        assert "tools=[]" in source, "the api path hands it none either"
        # And `Write` is not refused, because the answer comes back
        # through a file - the mistake made twice already elsewhere.
        refused = source.split("without=")[1].split('"')[1]
        assert "Write" not in refused


class TestNothingToDo:
    def test_no_claims_is_not_a_model_call(self):
        from drydock.claims import check

        report, spend = check(None, [], Page())

        assert report.checks == []
        assert spend.dollars == 0.0


class TestTheShapeOfOneCheck:
    def test_settled_means_it_is_about_the_page(self):
        assert Checked(claim="a", verdict=MET).settled
        assert Checked(claim="a", verdict=MISSING).settled
        assert not Checked(claim="a", verdict=UNKNOWN).settled
