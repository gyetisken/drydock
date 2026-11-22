"""Most requests are one sentence, and one sentence was the whole brief.

"A site for a bike shop" is a real request. Handed to an engineer as the
only thing anybody wrote down, it invents a bike shop - a different one
each run - and the plan is built against whichever one it invented. The
expansion that did exist was `direction`, and `direction` is about how a
thing looks: it is written only for work somebody looks at, so a payments
endpoint got no expansion at all and the reviewer judging it had never
been told what the job was.

So the one worker that already reads, decides and plans writes the
request out as well, in the same sitting, and says what it settled that
nobody said. No new station: it has the repository open and it is already
making every one of these decisions - it just was not writing them down.

Four things hold it in place, and they are what this file is about.

It is stored apart from the request. `brief` is what the person asked
for; `expanded` is one worker's reading of it. Merged into one block, a
reading is enforced exactly as hard as a price somebody named, which is
the failure the "From what was asked / Decided here" split already exists
to stop one level down.

It never outranks the request. `as_briefed` puts the request first and
says in words that the expansion loses every disagreement.

It scales. A vague creative request earns a real brief; a backend request
earns behaviour and edge cases; a small fix earns two sentences and must
not become a redesign.

And it is shown before it is built against. The approval screen is the
only moment a wrong reading can be caught for free.
"""

from pathlib import Path

from drydock import orchestrate, reviewer, start
from drydock.run import Run


def flat(text: str) -> str:
    """One line, so an assertion is not a claim about where prose wraps."""
    return " ".join(text.split())


SYSTEM = flat(start.SYSTEM)
SCHEMA = start._tool().schema
JS = Path("src/drydock/static/chat.js").read_text()
CSS = Path("src/drydock/static/app.css").read_text()
SESSION = Path("src/drydock/session.py").read_text()


def a_run(task="a site for a bike shop", objective=""):
    run = Run.start(Path("/x"), task)
    run.objective = objective
    return run


class TestTheTwoAreKeptApart:
    def test_the_request_is_not_touched(self):
        run = a_run("a site for a bike shop")
        run.expanded = "A shop for commuters, not racers."
        assert run.task == "a site for a bike shop"
        assert run.brief == "a site for a bike shop"

    def test_the_expansion_has_its_own_field(self):
        assert "expanded" in Run.model_fields
        assert "assumptions" in Run.model_fields
        assert a_run().expanded == ""
        assert a_run().assumptions == []

    def test_it_is_not_the_design_direction(self):
        """`direction` is written only for work somebody looks at. A
        payments endpoint has none and still needs saying what it is
        for."""
        assert "direction" in Run.model_fields
        assert "expanded" in Run.model_fields
        run = a_run()
        run.expanded = "Idempotent by Idempotency-Key."
        assert run.direction == ""
        assert run.expanded in run.as_briefed

    def test_nothing_changes_when_nothing_was_written_out(self):
        run = a_run("fix the footer phone number")
        assert run.as_briefed == run.brief == "fix the footer phone number"

    def test_whitespace_is_not_an_expansion(self):
        run = a_run()
        run.expanded = "   \n  "
        assert run.as_briefed == run.brief


class TestTheRequestWins:
    def test_the_request_comes_first(self):
        run = a_run("plain HTML and CSS, no frameworks")
        run.expanded = "A React single-page app would suit this."
        said = run.as_briefed
        assert said.index("plain HTML and CSS") < said.index("React")

    def test_it_says_which_one_loses(self):
        run = a_run()
        run.expanded = "something"
        said = run.as_briefed
        assert "anything here that disagrees with it is wrong and loses" in said
        assert "It is context, not the standard" in said

    def test_an_earlier_objective_still_outranks_both(self):
        """`brief` already ranks the original request over this
        instruction. The expansion goes under the whole of that, not
        between them."""
        run = a_run(task="carry on", objective="a site for a bike shop")
        run.expanded = "The shop is in Sarasota."
        said = run.as_briefed
        assert said.index("a site for a bike shop") < said.index("carry on")
        assert said.index("carry on") < said.index("The shop is in Sarasota")

    def test_the_planner_is_not_fed_its_own_expansion(self):
        """Planning reads the request. Feeding it back what it wrote last
        time is how a reading becomes the record of what was asked."""
        begin_call = SESSION[SESSION.index("started, usage = begin(") :][:600]
        assert "self.run.brief," in begin_call
        assert "as_briefed" not in begin_call


class TestItReachesTheThreeStationsThatBuildAndJudge:
    def test_the_engineer_gets_it(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        block = source[source.index("report, usage = work(") :][:700]
        assert "run.as_briefed," in block

    def test_the_critic_gets_it(self):
        import inspect

        assert "brief=run.as_briefed," in inspect.getsource(orchestrate._show_it)

    def test_the_reviewer_gets_it_at_all(self):
        """It had no idea what the job was. It read an item and a diff."""
        import inspect

        assert "brief=run.as_briefed," in inspect.getsource(orchestrate._judge)
        assert "brief" in inspect.signature(reviewer.review).parameters

    def test_the_reviewer_is_told_it_is_not_the_standard(self):
        assert "You are not judging the change against this" in flat(reviewer.PROMPT)
        assert flat(reviewer.PROMPT).index("{brief}") < reviewer.PROMPT.index(
            "{criteria}"
        )

    def test_a_run_with_no_expansion_hands_the_reviewer_the_request(self):
        run = a_run("fix the footer")
        assert run.as_briefed == "fix the footer"

    def test_the_reviewer_survives_being_given_nothing(self):
        said = reviewer.PROMPT.format(
            brief="  ",
            id=1,
            title="t",
            rationale="r",
            criteria="c",
            files="f",
            summary="s",
            diff="d",
        )
        assert said


class TestWhatTheWorkerIsAskedFor:
    def test_there_are_two_new_fields_and_both_are_required(self):
        assert "brief" in SCHEMA["properties"]
        assert "assumptions" in SCHEMA["properties"]
        assert "brief" in SCHEMA["required"]
        assert "assumptions" in SCHEMA["required"]

    def test_assumptions_are_a_list_of_lines(self):
        assert SCHEMA["properties"]["assumptions"]["type"] == "array"
        assert SCHEMA["properties"]["assumptions"]["items"]["type"] == "string"

    def test_the_answer_is_read_back(self):
        said = start._said(
            {
                "brief": "  A shop for commuters.  ",
                "assumptions": ["no prices were given", "   ", "the city is Sarasota"],
                "summary": "s",
                "items": [],
            }
        )
        assert said.brief == "A shop for commuters."
        assert said.assumptions == ["no prices were given", "the city is Sarasota"]

    def test_an_older_answer_without_them_still_reads(self):
        said = start._said({"summary": "s", "items": []})
        assert said.brief == ""
        assert said.assumptions == []

    def test_the_worked_example_shows_them(self):
        """The CLI engine is given a shape to answer in. A field missing
        from it comes back empty every time."""
        source = Path("src/drydock/start.py").read_text()
        example = source[source.index('\'{"findings"') :][:600]
        assert '"brief": "..."' in example
        assert '"assumptions": ["..."]' in example


class TestItScalesToWhatWasAsked:
    def test_a_vague_creative_request_earns_a_real_brief(self):
        assert "the audience, the character of the thing" in SYSTEM
        assert 'what "good" means for this particular business' in SYSTEM

    def test_a_backend_request_earns_a_different_one(self):
        assert "the behaviour, the interface, the edge cases" in SYSTEM
        assert "conventions this repository already" in SYSTEM

    def test_a_small_fix_earns_two_sentences(self):
        assert "**A small fix earns two sentences.**" in SYSTEM
        assert "is not an invitation to redesign the footer" in SYSTEM

    def test_the_schema_says_the_same_thing_to_a_worker_reading_only_it(self):
        said = flat(SCHEMA["properties"]["brief"]["description"])
        assert "scaled to" in said
        assert "a small fix earns two sentences and must not become a redesign" in said


class TestTheThingsItMustNotDo:
    def test_it_may_not_invent_a_business(self):
        assert "It never invents facts." in SYSTEM
        for thing in ("prices nobody named", "addresses", "opening hours", "staff"):
            assert thing in SYSTEM, thing

    def test_it_may_not_invent_an_integration(self):
        assert "no third-party service, no integration" in SYSTEM
        assert "no requirement the person did not ask for" in SYSTEM

    def test_placeholder_content_is_named_as_a_decision(self):
        assert "Placeholder content is a decision and is named as one" in SYSTEM

    def test_it_may_not_prescribe_the_typing(self):
        assert "no hex values, no spacing scales, no file layouts" in SYSTEM
        assert "no library choices unless the person named one" in SYSTEM

    def test_a_constraint_is_repeated_rather_than_softened(self):
        assert "not softened into a preference and not quietly widened" in SYSTEM

    def test_it_may_not_contradict_the_request(self):
        assert "And it never argues with the request." in SYSTEM
        assert "the request is right and the brief is wrong" in SYSTEM

    def test_the_schema_repeats_the_invention_rule(self):
        said = flat(SCHEMA["properties"]["brief"]["description"])
        assert "No fact the person did not give" in said
        assert "Nothing in it may disagree with what they asked for" in said


class TestSplittingIsStillDiscouraged:
    def test_one_item_is_still_a_real_answer(self):
        """A richer brief is a reason to describe more, not to cut the
        work into more pieces."""
        assert "**One item is a real answer.**" in SYSTEM
        assert "Splitting a cohesive job to reach a number" in SYSTEM

    def test_a_page_and_its_stylesheet_are_still_one_item(self):
        assert "A page and the stylesheet it needs are one item." in SYSTEM

    def test_checking_items_are_still_refused(self):
        assert "a checking item" in SYSTEM

    def test_the_floor_is_still_one(self):
        from drydock.policy import BALANCED, FAST, PROFILES

        assert PROFILES[FAST].fewest_items == 1
        assert PROFILES[BALANCED].fewest_items == 1


class TestAssumptionsAreSaidOutLoudRatherThanAsked:
    def test_they_are_their_own_list(self):
        assert "**Say what you assumed, separately.**" in SYSTEM

    def test_an_empty_list_is_a_fine_answer(self):
        assert "An empty list is a fine answer" in SYSTEM
        assert "Inventing entries to look thorough" in SYSTEM

    def test_the_approval_screen_is_the_question(self):
        """Rather than a new place to stop and ask, which would be a new
        flow and a new piece of interface for a question the existing one
        already puts."""
        assert "Do not stop to ask a question that the approval screen" in SYSTEM


class TestItIsShownBeforeItIsBuiltAgainst:
    def test_the_run_keeps_both(self):
        assert "self.run.expanded = started.brief" in SESSION
        assert "self.run.assumptions = list(started.assumptions)" in SESSION

    def test_the_approval_event_carries_both(self):
        block = SESSION[SESSION.index("def _after_plan") :][:900]
        assert "expanded=self.run.expanded," in block
        assert "assumptions=list(self.run.assumptions)," in block

    def test_the_window_draws_it_on_the_approval_card(self):
        assert "function understood(e)" in JS
        card = JS[JS.index('"plan.ready": (e)') :][:500]
        assert "${understood(e)}" in card

    def test_nothing_is_drawn_when_there_is_nothing(self):
        said = JS[JS.index("function understood(e)") :][:900]
        assert 'if (!brief && !took.length) return "";' in said

    def test_an_empty_assumption_is_not_counted(self):
        said = JS[JS.index("function understood(e)") :][:900]
        assert '.filter(a => (a || "").trim())' in said

    def test_it_is_folded_rather_than_another_panel(self):
        said = JS[JS.index("function understood(e)") :][:1200]
        assert '<details class="understood">' in said
        assert ".understood {" in CSS

    def test_it_says_this_is_not_what_was_asked_for(self):
        said = JS[JS.index("function understood(e)") :][:1400]
        assert "Nothing here was asked for" in said
        assert "What you actually asked for wins over all of it" in said

    def test_the_assumptions_are_escaped(self):
        said = JS[JS.index("function understood(e)") :][:1200]
        assert "esc(a)" in said

    def test_it_sits_above_the_items_and_the_button(self):
        card = JS[JS.index('"plan.ready": (e)') :][:700]
        assert card.index("${understood(e)}") < card.index('<div class="card">')


class TestNothingDownstreamChanged:
    def test_the_gates_still_run(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "if verdict.passed and unverified:" in source
        assert "a required check could not be completed" in source

    def test_the_stop_checks_are_untouched(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.count("_stopping(should_stop)") >= 5

    def test_the_rollback_is_untouched(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "here.discard()" in source

    def test_the_deadline_is_untouched(self):
        from drydock.session import Session

        assert Session(Path("/tmp"), "t", [], within_minutes=20).within_minutes == 20

    def test_the_single_engineer_path_is_untouched(self):
        """One item, one engineer. A brief is more words, not more
        workers."""
        source = Path("src/drydock/orchestrate.py").read_text()
        assert "def _one_item(" in source
        assert "while attempt <= policy.attempts:" in source


# The four shapes of request this was built for. None of them calls a
# model - the expansion is one worker's answer and paying to find out
# what it says today is not a test. What is testable is the thing that
# actually broke runs: whether what the person said survives the trip to
# the station that builds it and the stations that judge it, with the
# ranking intact.


def what_each_station_reads(task, expanded="", objective="", assumptions=()):
    """The one string the engineer, the reviewer and the critic are given."""
    run = a_run(task, objective)
    run.expanded = expanded
    run.assumptions = list(assumptions)
    return run, run.as_briefed


class TestAVagueRestaurantWebsite:
    REQUEST = "a website for my restaurant"
    EXPANDED = (
        "A neighbourhood restaurant in a town that eats early. The person "
        "arriving wants to know what kind of room it is, what is on, and "
        "how to get a table tonight. Warm rather than minimal."
    )

    def test_the_sentence_is_still_the_sentence(self):
        run, said = what_each_station_reads(self.REQUEST, self.EXPANDED)
        assert run.task == self.REQUEST
        assert said.startswith(self.REQUEST)

    def test_the_expansion_arrives_marked_as_a_reading(self):
        _, said = what_each_station_reads(self.REQUEST, self.EXPANDED)
        assert self.EXPANDED in said
        assert "It is context, not the standard" in said

    def test_nothing_invented_becomes_a_requirement(self):
        """Hours, prices and an address are the three a restaurant brief
        invents. If one arrives it arrives below the line that says it
        loses to the request."""
        _, said = what_each_station_reads(self.REQUEST, self.EXPANDED)
        mark = said.index("What that was taken to mean")
        assert said.index(self.EXPANDED) > mark

    def test_the_assumptions_are_carried_for_the_approval_screen(self):
        run, _ = what_each_station_reads(
            self.REQUEST,
            self.EXPANDED,
            assumptions=["no menu was given, so the dishes are placeholders"],
        )
        assert run.assumptions == ["no menu was given, so the dishes are placeholders"]

    def test_an_assumption_is_not_in_what_the_stations_are_judged_on(self):
        """It is shown to the person, not enforced on the engineer. A
        guess that reaches the criteria is a guess with the force of a
        requirement."""
        _, said = what_each_station_reads(
            self.REQUEST, self.EXPANDED, assumptions=["the dishes are placeholders"]
        )
        assert "the dishes are placeholders" not in said


class TestADetailedWebsiteRequest:
    REQUEST = (
        "One page, plain HTML and CSS, no frameworks and no build step. "
        "index.html and styles.css, no other files. Phone (941) 555-0142. "
        "Three service cards in this order: tune-up, flat repair, wheel build."
    )

    def test_every_fixed_thing_survives_verbatim(self):
        _, said = what_each_station_reads(
            self.REQUEST, "A shop for commuters who ride every day."
        )
        for fixed in (
            "no frameworks",
            "index.html and styles.css",
            "(941) 555-0142",
            "tune-up, flat repair, wheel build",
        ):
            assert fixed in said, fixed

    def test_a_contradicting_expansion_is_ranked_below_it(self):
        _, said = what_each_station_reads(
            self.REQUEST,
            "A small React app would carry the card layout more cleanly.",
        )
        assert said.index("no frameworks") < said.index("React")
        assert "anything here that disagrees with it is wrong and loses" in said

    def test_a_request_that_was_already_a_brief_may_have_no_expansion(self):
        run, said = what_each_station_reads(self.REQUEST)
        assert said == self.REQUEST
        assert run.expanded == ""


class TestASmallBugFix:
    REQUEST = "the footer phone number is wrong, it should be (941) 555-0142"

    def test_no_expansion_means_nothing_changed_at_all(self):
        run, said = what_each_station_reads(self.REQUEST)
        assert said == run.brief == self.REQUEST
        assert "What that was taken to mean" not in said

    def test_two_sentences_do_not_turn_into_a_second_document(self):
        _, said = what_each_station_reads(
            self.REQUEST, "The number in the footer is stale. Replace it."
        )
        assert len(said) < 4 * len(self.REQUEST) + 600

    def test_the_rule_is_in_the_prompt_rather_than_hoped_for(self):
        assert "**A small fix earns two sentences.**" in SYSTEM

    def test_one_change_can_still_skip_the_plan_entirely(self):
        """`needs_a_plan` is what keeps a copy change from being
        ceremony. A brief is more words, not more process."""
        assert "needs_a_plan" in SCHEMA["properties"]
        assert "a copy change, a colour, a rename" in flat(
            SCHEMA["properties"]["needs_a_plan"]["description"]
        )


class TestABackendPaymentTask:
    REQUEST = "make POST /payments idempotent"
    EXPANDED = (
        "Two identical requests with the same Idempotency-Key must charge "
        "once and return the same response. Concurrent duplicates must not "
        "both proceed. A key reused with a different body is an error, not "
        "a replay."
    )

    def test_work_nobody_looks_at_now_gets_a_brief(self):
        """This is the gap. `direction` is written only for work somebody
        looks at, so an endpoint got no expansion at all."""
        run, said = what_each_station_reads(self.REQUEST, self.EXPANDED)
        assert run.direction == ""
        assert self.EXPANDED in said

    def test_the_reviewer_of_an_endpoint_knows_what_the_job_is(self):
        import inspect

        assert "brief=run.as_briefed," in inspect.getsource(orchestrate._judge)

    def test_the_prompt_asks_for_behaviour_rather_than_a_look(self):
        assert "the behaviour, the interface, the edge cases" in SYSTEM
        assert "what correctness means here" in SYSTEM

    def test_it_is_told_to_follow_what_the_repository_already_does(self):
        assert "conventions this repository already follows" in SYSTEM

    def test_no_integration_is_invented_for_it(self):
        """A payments brief invents Stripe. This one may not."""
        assert "no third-party service, no integration" in SYSTEM
