"""The engine picker offered a way to start paying by mistake.

Two engines: the Claude Code CLI, signed in as whoever is at the
machine, and an API key billed per token. The window let you pick
between them, next to the model, remembered across sessions - so a
choice made once, for one run, silently governed every run after it.

Neither is a question the window should be asking. A person at their own
machine, signed in, has one way to run the crew and it is their account.
The other engine is for the places with nobody signed in: `drydock run`
takes `--engine`, the API takes the field, and CI is the whole reason it
exists. None of those is this window.

So the picker is gone and the window always runs as the account. What is
left is one line, and only when it cannot: Claude Code not being
installed is worth finding out before pressing send rather than after.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from drydock.web import StartJob, app

PAGE = Path("src/drydock/web.py").read_text()
JS = Path("src/drydock/static/chat.js").read_text()
CSS = Path("src/drydock/static/app.css").read_text()


class TestThePickerIsGone:
    def test_there_is_no_button(self):
        assert 'id="pick-engine"' not in PAGE
        assert 'id="engine-label"' not in PAGE

    def test_there_is_no_menu(self):
        assert 'id="pop-engine"' not in PAGE
        assert '$("pick-engine")' not in JS

    def test_the_model_picker_is_untouched(self):
        """One choice was removed, not both."""
        assert 'id="pick-model"' in PAGE
        assert 'id="pop-model"' in PAGE
        assert '$("pick-model").onclick' in JS

    def test_the_style_it_needed_went_with_it(self):
        assert ".pop.right" not in CSS


class TestItAlwaysRunsAsTheAccount:
    def test_the_window_sends_claude(self):
        assert 'engine: "claude", model: "opus" }' in JS
        assert "engine: S.engine" in JS

    def test_nothing_can_change_it(self):
        """Not from a menu, and not from a value left in storage by one."""
        assert "S.engine =" not in JS
        assert 'localStorage.getItem("drydock.engine")' not in JS
        assert 'localStorage.setItem("drydock.engine"' not in JS

    def test_an_old_choice_is_cleared_rather_than_left_looking_live(self):
        assert 'localStorage.removeItem("drydock.engine")' in JS

    def test_only_the_model_is_remembered_now(self):
        said = JS[JS.index("function save()") :][:220]
        assert 'localStorage.setItem("drydock.model", S.model)' in said
        assert "drydock.engine" not in said


class TestTheOtherEngineIsGone:
    """It outlived the picker by a few commits and then went too. See
    test_nothing_reaches_the_api."""

    def test_the_api_engine_is_refused_rather_than_offered(self):
        import pytest

        with pytest.raises(ValueError, match="subscription"):
            StartJob(project="/x", command="/do a", engine="api")

    def test_the_account_is_what_it_assumes_when_nothing_says(self):
        assert StartJob(project="/x", command="/do a").engine == "claude"

    def test_the_server_reports_one(self):
        said = TestClient(app).get("/api/state").json()
        assert [e["id"] for e in said["engines"]] == ["claude"]

    def test_the_budget_line_went_with_it(self):
        """A dollar cap existed for the engine that spends dollars. A
        subscription is not billed per token."""
        assert "ANTHROPIC_API_KEY" not in PAGE


class TestItSaysWhenItCannotRun:
    def test_there_is_somewhere_to_say_it(self):
        assert 'id="hint"' in PAGE

    def test_the_window_checks(self):
        assert "function drawEngine()" in JS
        assert "drawEngine();" in JS

    def test_it_says_so_only_when_claude_is_missing(self):
        said = JS[JS.index("function drawEngine()") :][:600]
        assert 'e.id === "claude"' in said
        assert "claude.ready" in said

    def test_it_says_what_follows_from_it(self):
        said = JS[JS.index("function drawEngine()") :][:600]
        assert "Nothing will run until it is" in said
        assert 'className = "hint bad"' in said

    def test_the_server_says_why(self):
        said = TestClient(app).get("/api/state").json()
        claude = next(e for e in said["engines"] if e["id"] == "claude")
        assert claude["why"] == "Claude Code is not installed on this machine"
        assert "ready" in claude
