"""The crew runs on a subscription that is already paid for.

There were two engines: the Claude Code CLI, signed in as whoever is at
the machine and covered by their plan, and an API key billed per token.
The second billed on top of a plan already paid for, and the picker that
offered it was removed from the window a few commits ago - but the code
path stayed, every station still defaulted to `"api"`, and anything
calling a station without naming an engine got the billed one.

So the refusal is at the one place an API client is built, rather than
at each of the ten stations that could reach it: a guard spread over ten
files is a guard with nine places to forget. And every default is the
subscription, so forgetting to name an engine now costs nothing instead
of costing money.

The station code around the chokepoint is deliberately left alone.
Deleting the branch from ten modules is a separate change with its own
diff; an exception on the line that opens the connection is what
actually stops the spending, and it is testable without a network.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from drydock.agent import JUDGEMENT, Agent, OnTheSubscription
from drydock.web import StartJob, app

SOURCES = sorted(Path("src/drydock").glob("*.py"))


class TestTheCallCannotHappen:
    def test_building_a_client_raises_instead(self):
        with pytest.raises(OnTheSubscription):
            Agent(name="Planner", model=JUDGEMENT, system="s", tools=[]).run("hi")

    def test_it_says_which_station_tried(self):
        with pytest.raises(OnTheSubscription, match="Architect"):
            Agent(name="Architect", model=JUDGEMENT, system="s", tools=[]).run("hi")

    def test_it_says_what_to_do_instead(self):
        with pytest.raises(OnTheSubscription, match='engine="claude"'):
            Agent(name="X", model=JUDGEMENT, system="s", tools=[]).run("hi")

    def test_it_refuses_before_anything_is_sent(self):
        """Not after a request, and not after a key is read. The first
        statement of the method."""
        import inspect

        body = inspect.getsource(Agent.run)
        assert body.index("raise OnTheSubscription") < body.index(
            "anthropic.Anthropic()"
        )

    def test_there_is_still_only_one_place_a_client_is_built(self):
        where = [f.name for f in SOURCES if "anthropic.Anthropic(" in f.read_text()]
        assert where == ["agent.py"]


class TestNothingDefaultsToBeingBilled:
    def test_no_station_still_defaults_to_the_api(self):
        guilty = [f.name for f in SOURCES if 'engine: str = "api"' in f.read_text()]
        assert guilty == []

    def test_they_default_to_the_subscription(self):
        import inspect

        from drydock import analyst, engineer, planner, reviewer, start

        for module, name in (
            (start, "begin"),
            (planner, "plan"),
            (engineer, "work"),
            (reviewer, "review"),
            (analyst, "survey"),
        ):
            fn = getattr(module, name, None)
            if fn is None:
                continue
            said = inspect.signature(fn).parameters.get("engine")
            assert said is not None and said.default == "claude", name

    def test_a_run_record_written_without_one_is_on_the_subscription(self):
        from drydock.run import Run

        assert Run.start(Path("/x"), "t").engine == "claude"


class TestTheEdgeRefusesIt:
    def test_the_default_is_the_subscription(self):
        assert StartJob(project="/x", command="/do a").engine == "claude"

    def test_asking_for_the_api_is_an_error(self):
        with pytest.raises(ValueError, match="subscription"):
            StartJob(project="/x", command="/do a", engine="api")

    def test_it_is_refused_over_http_rather_than_mid_run(self):
        """Accepted and then refused deep inside a worker means the run
        has started and somebody is watching a spinner."""
        said = TestClient(app).post(
            "/api/start",
            json={"project": "/x", "command": "/do a", "engine": "api"},
        )
        assert said.status_code == 422

    def test_an_empty_engine_is_the_subscription_rather_than_an_error(self):
        assert StartJob(project="/x", command="/do a", engine="").engine == "claude"


class TestTheListSaysThereIsOne:
    def test_only_the_subscription_is_offered(self):
        said = TestClient(app).get("/api/state").json()
        assert [e["id"] for e in said["engines"]] == ["claude"]

    def test_no_key_is_read_to_build_the_list(self):
        page = Path("src/drydock/web.py").read_text()
        assert "ANTHROPIC_API_KEY" not in page

    def test_the_window_still_sends_the_subscription(self):
        js = Path("src/drydock/static/chat.js").read_text()
        assert 'engine: "claude", model: "opus" }' in js


class TestWhatWasDeliberatelyNotDone:
    def test_the_station_branches_are_still_there(self):
        """Honest about the shape of this change: the dead `else` in ten
        modules is a separate diff. What stops the spending is the
        chokepoint, and that is tested above."""
        import inspect

        from drydock import start

        assert 'if engine == "claude":' in inspect.getsource(start.begin)

    def test_the_reason_is_written_down_where_somebody_will_find_it(self):
        said = " ".join(Path("src/drydock/agent.py").read_text().split())
        assert "billed per token on top of a plan that is already paid for" in said
        assert "a guard with nine places to forget" in said
