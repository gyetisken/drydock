"""A project's history, read as the conversation it was.

It was a card at the top of an empty thread - "Earlier in this project" -
with a row per run and a click to replay one, which replaced everything
on screen. Coming back to a project looked like opening a filing cabinet
rather than returning to a chat, and the thing it is most often compared
to is a chat.

So the rows are messages now: what was asked, what came back, oldest
first, and the box at the bottom carries on from there.

That made a second thing visible. A job that was a question had nothing
to show, because the answer went to the feed and to memory and nowhere
durable - so a hello came back in the history as "Nothing was planned",
which is true and is not what was said.
"""

from pathlib import Path

from drydock.run import Run

CHAT = (
    Path(__file__).resolve().parents[1] / "src" / "drydock" / "static" / "chat.js"
).read_text()
CSS = (
    Path(__file__).resolve().parents[1] / "src" / "drydock" / "static" / "app.css"
).read_text()
WEB = (Path(__file__).resolve().parents[1] / "src" / "drydock" / "web.py").read_text()


class TestTheAnswerIsKept:
    def test_a_run_can_carry_one(self, tmp_path):
        run = Run.start(tmp_path, "how are you?")
        run.answer = "Well, thanks - ready when you are."
        run.save()

        back = Run.load(run.id)
        assert back.answer == "Well, thanks - ready when you are."

    def test_a_run_that_was_never_asked_anything_carries_none(self, tmp_path):
        assert Run.start(tmp_path, "build a page").answer == ""

    def test_the_answering_path_writes_it_down(self):
        session = (
            Path(__file__).resolve().parents[1] / "src" / "drydock" / "session.py"
        ).read_text()
        answering = session[session.index("def _answer(") :]
        answering = answering[: answering.index("\n    def ")]

        assert answering.count("self.run.answer =") == 2, (
            "both the fresh answer and the remembered one are answers"
        )
        assert answering.count("self.run.save()") >= 2

    def test_it_is_served_with_the_history(self):
        assert '"answer": r.answer,' in WEB

    def test_a_job_with_only_an_answer_is_still_history(self):
        """It planned nothing and spent nothing by the old test, so it was
        filtered out of the project's history as noise - which deleted the
        conversation."""
        assert "or r.answer)" in WEB


class TestTheThreadReadsLikeOne:
    def test_the_card_is_gone(self):
        assert "Earlier in this project" not in CHAT
        assert 'class="past' not in CHAT
        assert ".past" not in CSS, "the styles went with it"

    def test_the_oldest_job_is_at_the_top(self):
        """A chat reads downward. The history list arrives newest first."""
        assert "runs.slice().reverse()" in CHAT

    def test_what_was_asked_is_shown_as_what_was_asked(self):
        assert "youSaid(r.task, before)" in CHAT

    def test_an_answer_is_shown_instead_of_a_count_of_items(self):
        job = CHAT[CHAT.index("function pastJob(") :]
        job = job[: job.index("\n}")]
        assert "r.answer" in job
        assert job.index("r.answer") < job.index("Nothing was planned")

    def test_only_a_few_are_shown_unasked(self):
        assert "earlierHere(p.runs, 4)" in CHAT
        assert "earlier job" in CHAT

    def test_older_ones_load_above_the_newer_ones(self):
        """Appended, they would arrive in the wrong order and read as the
        newest. `say` takes somewhere to put them for this."""
        assert "before.parentNode.insertBefore(el, before)" in CHAT
        assert "pastJob(r, more)" in CHAT

    def test_opening_a_project_lands_at_the_bottom(self):
        """Where the conversation is, and where the box is."""
        opening = CHAT[CHAT.index("function openProject(") :]
        opening = opening[: opening.index("\n}")]
        assert 'scrollTop = $("thread").scrollHeight' in opening
        assert "scrollTop = 0" not in opening
