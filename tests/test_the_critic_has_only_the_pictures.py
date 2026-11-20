"""The critic went looking for files it was never given.

Nine evaluations, read out of their own session transcripts. The minimum
useful sequence happened twice:

    Read desktop.png -> Read phone.png -> Write verdict     5 turns, 19-23s

Every other run went hunting first. It read the two pictures, then tried
index.html, styles.css, hours.js, corso.test.js - none of which are in the
directory it is given - and then reached for ToolSearch to find something
that would let it. Across nine runs: 27 failed reads and 15 ToolSearch
calls, none of which returned anything.

The correlation is clean. Every run that used ToolSearch took nine turns
or more; every run that did not finished in five. Two runs never produced
a verdict at all: they spent the turn budget hunting.

    A3  15 tool calls   7 failed reads   5 ToolSearch   no verdict
    C2  10 tool calls   2 failed reads   4 ToolSearch   no verdict
    B2   3 tool calls   0 failed reads   0 ToolSearch   correct refusal

The same thing happens in production. Corso C's real critic tried
index.html and styles.css, was refused by the confinement hook, and then
spent seventy-nine seconds thinking before writing "I can only read inside
.drydock-look".

The cause is a mismatch rather than a defect. The item handed to the
critic lists acceptance criteria that are only checkable in the source -
"the hours are <table> markup, not a list", "an anchor whose href is a
tel: URL", "add one test to test/corso.test.js" - while the critic is
given two pictures. It goes looking because it was asked for something it
cannot see.

So the prompt now says what it has, what is not its job, and that hunting
for either is wasted. Opus had already worked this out on its own - "source
files were not present in the directory given to me, so the HTML/CSS
assertions this item lists could not be verified" - which is the behaviour
this makes the default instead of a discovery.
"""

from drydock import critic


def flat(text: str) -> str:
    return " ".join(text.split())


PROMPT = flat(critic.PROMPT)
SYSTEM = flat(critic.SYSTEM)


class TestItIsToldWhatItHas:
    def test_the_pictures_are_named_as_everything(self):
        assert "They are all you have, and they are enough" in PROMPT

    def test_it_is_pointed_at_the_rendered_result(self):
        assert "you are here for the rendered result" in PROMPT

    def test_judged_against_what_was_asked_for(self):
        assert "judged against what the person asked for" in PROMPT
        assert "{brief}" in critic.PROMPT


class TestItIsToldWhatIsNotItsJob:
    def test_the_source_level_assertions_are_named(self):
        """Named concretely, because the item says them concretely."""
        for example in (
            "the hours are table markup rather than a list",
            "a phone number is an anchor with a tel: href",
            "that a test was added",
        ):
            assert example in PROMPT, example

    def test_it_is_told_which_gates_own_them(self):
        assert "The build, the suite, the inspector and the reviewer" in PROMPT
        assert "they refuse on their own" in PROMPT

    def test_it_is_told_not_to_hunt_for_the_files(self):
        assert "Do not go looking for the files" in PROMPT

    def test_it_is_told_not_to_hunt_for_a_tool(self):
        """ToolSearch was fifteen calls across nine runs and returned
        nothing. It is not forbidden here - tool permissions are not
        this change - it is explained."""
        assert "do not go looking for a tool that would let you" in PROMPT

    def test_it_is_told_why(self):
        assert "the files are not in this directory" in PROMPT
        assert "every turn spent trying is a turn not spent on the page" in PROMPT


class TestItStillJudgesIndependently:
    """The point of the station. If this change makes it quieter about a
    bad page, it has broken the only gate that can see."""

    def test_it_must_still_say_what_it_cannot_see(self):
        assert "Say what you cannot see, and judge what you can" in PROMPT

    def test_the_question_still_asks_whether_the_page_is_good(self):
        assert "is the page good?" in PROMPT

    def test_the_brief_is_still_the_standard(self):
        assert "judged against is the brief" in SYSTEM

    def test_following_the_direction_is_still_not_enough(self):
        assert "follows the direction to the letter and is still a bad page" in SYSTEM
        assert "never a reason on their own" in SYSTEM

    def test_it_still_refuses_for_what_it_can_see(self):
        assert "Refuse when what this item owed the brief is not on the page" in SYSTEM
        assert "badly enough that a person would notice" in SYSTEM

    def test_the_two_objective_checks_are_untouched(self):
        assert "text that overflows or is clipped at either width" in SYSTEM
        assert "text a person cannot read against its background" in SYSTEM

    def test_it_still_judges_one_item_rather_than_the_page(self):
        assert "Judge this item, not the whole page" in critic.SYSTEM

    def test_it_still_has_to_point_at_what_it_saw(self):
        assert "Be specific and point at what you are looking at" in SYSTEM


class TestTheThreeOutcomesSurvive:
    """A prompt change must not quietly undo the fail-open fix."""

    def test_an_error_is_still_not_an_approval(self):
        v = critic._could_not("the answer was not readable")
        assert not v.verified and not v.approved

    def test_a_real_refusal_is_still_a_refusal(self):
        v = critic.Verdict(looked=True, approved=False, reason="cut off", noticed=[])
        assert v.verified and not v.approved

    def test_an_approval_is_still_an_approval(self):
        v = critic.Verdict(looked=True, approved=True, reason="right", noticed=[])
        assert v.verified and v.approved

    def test_one_bounded_repair_is_still_there(self):
        import inspect

        source = inspect.getsource(critic.look)
        assert "for attempt in (1, 2):" in source
        assert "MalformedAnswer" in source


class TestNothingElseMoved:
    def test_the_prompt_still_carries_every_field(self):
        for field in ("{brief}", "{direction}", "{item}"):
            assert field in critic.PROMPT, field

    def test_the_brief_still_comes_before_the_direction(self):
        assert PROMPT.index("{brief}") < PROMPT.index("{direction}")

    def test_the_direction_is_still_context_rather_than_the_standard(self):
        assert "Context for what was intended, not the standard" in PROMPT

    def test_it_still_reads_both_images(self):
        assert "desktop.png" in PROMPT and "phone.png" in PROMPT
        assert "Read both images" in PROMPT

    def test_the_tools_it_is_given_are_unchanged(self):
        import inspect

        source = inspect.getsource(critic.look)
        assert 'tools="Read"' in source
        assert (
            'without="Bash Edit Glob Grep NotebookEdit WebFetch WebSearch Task"'
            in source
        )
