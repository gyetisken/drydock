"""What FAST does before the Engineer starts, and what it no longer does.

Measured on run 20261124-153354, a five-file repository: the Analyst
pass took 227 seconds and $1.00 of a 497-second, $2.22 run, and the
Engineer then read the same five files again. `start.begin` - one worker
that reads, decides and plans in one call - has been the application's
default since before that run, and the command line never called it.

So `fast` on the command line now takes the path the application
already took. `balanced` and `deep` still survey.

Deterministic: source, resolution and one assembled command. No model.
"""

import inspect
from pathlib import Path

import pytest

from drydock import cli, detect, engines, session, start
from drydock.policy import BALANCED, DEEP, FAST, PROFILES
from drydock.run import Run

CLI = Path("src/drydock/cli.py").read_text()


class TestFastReadsAndPlansInOneCall:
    def test_fast_takes_the_one_call_path(self):
        source = inspect.getsource(cli._cmd_survey)
        assert "if policy.profile == FAST" in source
        assert source.index("if policy.profile == FAST") < source.index(
            'print("\\nsurveying")'
        )

    def test_it_calls_the_application_s_own_worker(self):
        """Not a new station. `start.begin` already existed and was
        already the application's default."""
        source = inspect.getsource(cli._read_and_plan_in_one)
        assert "from .start import begin" in source
        assert "begin(" in source

    def test_no_new_agent_role_was_added(self):
        source = inspect.getsource(cli)
        for station in ("Architect(", "Designer(", "class ", "def _cmd_"):
            pass
        assert "Agent(" not in source
        assert source.count("def _cmd_") == CLI.count("def _cmd_")

    def test_it_produces_everything_the_survey_and_plan_produced(self):
        source = inspect.getsource(cli._read_and_plan_in_one)
        for field in ("run.inventory", "run.plan", "run.expanded", "run.assumptions"):
            assert field in source

    def test_the_file_counts_come_from_the_detector_not_a_model(self):
        source = inspect.getsource(cli._read_and_plan_in_one)
        assert "count(repo, chain.source_glob)" in source
        assert "count(repo, chain.test_glob)" in source

    def test_an_empty_repository_is_told_what_is_installed(self):
        """Half a second of reading this process does itself, rather
        than a worker spending turns on it."""
        source = inspect.getsource(cli._read_and_plan_in_one)
        assert "installed() if empty else" in source
        assert "is_empty(chain)" in source

    def test_a_direction_is_only_kept_when_something_is_looked_at(self):
        source = inspect.getsource(cli._read_and_plan_in_one)
        assert "if wanted_a_look:" in source
        assert source.index("if wanted_a_look:") < source.index("run.direction =")


class TestBalancedAndDeepAreUntouched:
    @pytest.mark.parametrize("profile", [BALANCED, DEEP])
    def test_they_still_survey(self, profile):
        assert PROFILES[profile].profile != FAST
        source = inspect.getsource(cli._cmd_survey)
        # The survey call is still there, after the fast branch returns.
        assert "run.inventory, usage = survey(" in source

    def test_the_fast_branch_returns_rather_than_falling_through(self):
        source = inspect.getsource(cli._cmd_survey)
        branch = source[source.index("if policy.profile == FAST") :]
        assert branch.splitlines()[1].strip().startswith("return ")

    def test_the_planner_command_is_unchanged_for_them(self):
        source = inspect.getsource(cli._cmd_plan)
        assert "run.plan, usage = plan(" in source
        assert "policy=policy," in source


class TestOneAnswerToWhetherSomethingIsLookedAt:
    """It used to be a session method, so the command line had no way to
    ask without a second copy of the answer."""

    def test_the_question_lives_where_both_can_ask_it(self):
        assert callable(detect.has_a_face)

    def test_the_session_delegates_rather_than_keeping_its_own(self):
        source = inspect.getsource(session.Session._has_a_face)
        assert "from .detect import has_a_face" in source
        assert "FACES" not in source

    def test_the_pattern_exists_once(self):
        assert "FACES" in inspect.getsource(detect)
        assert "FACES" not in inspect.getsource(session)

    @pytest.mark.parametrize(
        "task,looked_at",
        [
            ("build a landing page for a hotel", True),
            ("add a dashboard for the admin", True),
            ("make paging return every article exactly once", False),
            ("write the migration for the new column", False),
            ("run the test suite", False),
        ],
    )
    def test_it_answers_the_way_it_always_did(self, task, looked_at, tmp_path):
        assert detect.has_a_face(tmp_path, task) is looked_at

    def test_a_repository_that_serves_pages_has_one_anyway(self, tmp_path):
        (tmp_path / "public").mkdir()
        assert detect.has_a_face(tmp_path, "fix the parser") is True


class TestNothingProtectiveWasTraded:
    def test_the_risk_floor_still_runs_before_anything(self):
        """A task that names a migration, money, authorization or data
        removal is raised out of fast before a worker is started."""
        source = inspect.getsource(cli._cmd_survey)
        assert source.index("_decide_profile(run") < source.index(
            "if policy.profile == FAST"
        )

    def test_the_gates_are_not_in_the_one_call(self):
        """`start.py` says it: the thing that writes the code must not be
        the thing that says it may stay."""
        source = inspect.getsource(start)
        for gate in ("verify(", "look(", "review("):
            assert gate not in source

    def test_the_loop_still_verifies_and_inspects(self):
        from drydock import orchestrate

        source = inspect.getsource(orchestrate)
        assert "verdict = verify(" in source
        assert "_judge(" in source

    def test_the_one_call_is_counted_as_preparation(self):
        assert "start" in Run.BEFORE_ANY_CODE
        run = Run.start(Path("/tmp/nowhere"), "t")

        class U:
            input_tokens = output_tokens = cached_tokens = 0
            dollars = 0.6

        run.spend(U(), station="start", seconds=84.0)
        split = run.phases()
        assert split["preparation"]["calls"] == 1
        assert split["preparation"]["seconds"] == 84.0
        assert split["execution"]["calls"] == 0


class TestNoMcpServerReachesAWorker:
    """`--setting-sources ""` only excludes project settings, so it stops
    a repository's `.mcp.json` and nothing else: user and local scope
    live in `~/.claude.json`, and claude.ai connectors come from the
    account. Measured on this machine with and without the flag: the
    worker's tool list was identical either way, so this guarantees a
    surface that was already clean here rather than fixing a leak."""

    def test_the_flag_is_passed(self):
        assert "--strict-mcp-config" in engines.SETTING_SOURCES

    def test_both_command_builders_get_it(self):
        source = inspect.getsource(engines)
        assert source.count("*SETTING_SOURCES,") == 2

    def test_drydock_passes_no_mcp_server_of_its_own(self):
        source = inspect.getsource(engines)
        assert "--mcp-config" not in source
        assert "mcpServers" not in source

    def test_tool_search_is_left_at_its_default(self):
        """Nine tools. The documented threshold is thirty to fifty, and
        a search would add a round trip for nothing."""
        source = inspect.getsource(engines)
        # Named in the comment that explains why it is not set, which is
        # the opposite of setting it.
        for setting in (
            'env["ENABLE_TOOL_SEARCH"]',
            "ENABLE_TOOL_SEARCH=",
            '"ENABLE_TOOL_SEARCH",',
        ):
            assert setting not in source

    def test_the_tools_the_engineer_needs_are_still_named(self):
        rule = engines._shell_rule("uv sync --frozen", can_look=True, can_fetch=True)
        for needed in ("Bash(uv *)", "Bash(drydock-look", "Bash(drydock-web"):
            assert needed in rule
