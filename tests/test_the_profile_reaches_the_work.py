"""The profile somebody chose, and whether the work ever sees it.

Measured on run 20261124-142030, which was asked for `fast`: the CLI
never passed a policy to `execute`, `execute` fell back to `of(None)`,
and `of(None)` is `balanced`. So the reviewer read the diff - which
`balanced` does and `fast` does not - and two of the run's five workers
existed because of a flag nobody had set. The record said nothing either
way, because it held no profile at all.

These are deterministic: source and resolution only, no CLI, no model.
"""

import inspect
from pathlib import Path

import pytest

from drydock import cli, orchestrate, session
from drydock.policy import BALANCED, DEEP, FAST, PROFILES, at_least, floor_for, of
from drydock.run import Run

CLI = Path("src/drydock/cli.py").read_text()


def a_run(task: str = "add a listing endpoint") -> Run:
    return Run.start(Path("/tmp/nowhere"), task)


class TestTheCliResolvesItTheWayTheAppDoes:
    def test_both_entry_points_pass_a_policy_to_execute(self):
        """The application always did. The CLI did not, and that was the
        whole defect."""
        assert "policy=_policy_of(run)" in CLI
        assert "policy=self.policy" in inspect.getsource(session)

    def test_the_planner_is_given_one_too(self):
        """Without it the planner is told the default's item range
        whatever was chosen."""
        assert "policy=policy," in CLI

    def test_the_fallback_still_exists_for_a_caller_that_names_none(self):
        source = inspect.getsource(orchestrate.execute)
        assert "policy = policy or of(None)" in source
        assert of(None).profile == BALANCED


class TestTheRiskFloorStillWins:
    """Raised, never lowered. Asking for fast does not make a migration,
    an authorization change, money or data removal cheap."""

    @pytest.mark.parametrize(
        "task,floor",
        [
            ("make the payment idempotent", DEEP),
            ("write the migration for the new column", DEEP),
            ("change the authorization rules for reviewers", DEEP),
            ("delete the archived rows", DEEP),
        ],
    )
    def test_a_risky_task_cannot_run_as_fast(self, task, floor):
        raised = floor_for(task)
        assert raised.floor == floor
        assert at_least(of(FAST), raised.floor).profile == floor

    def test_an_ordinary_task_keeps_what_was_asked_for(self):
        raised = floor_for("paging returns every article exactly once")
        assert raised.floor == ""
        assert at_least(of(FAST), raised.floor).profile == FAST

    def test_the_cli_resolves_through_the_floor_and_not_around_it(self):
        source = inspect.getsource(cli._decide_profile)
        assert "at_least(of(wanted), raised.floor)" in source
        assert "floor_for(run.task)" in source

    def test_asking_for_deep_is_never_lowered_to_fast(self):
        assert at_least(of(DEEP), "").profile == DEEP
        assert at_least(of(DEEP), FAST).profile == DEEP


class TestTheRecordSaysWhatItRanAs:
    def test_all_three_fields_exist(self):
        for field in ("profile_asked", "profile_used", "profile_floor"):
            assert field in Run.model_fields

    def test_a_plain_task_records_what_was_asked_for(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.settings.Settings.load", lambda: _Settings("balanced")
        )
        run = a_run()
        policy = cli._decide_profile(run, FAST)
        assert policy.profile == FAST
        assert run.profile_asked == FAST
        assert run.profile_used == FAST
        assert run.profile_floor == ""

    def test_a_raised_task_records_the_raise_and_the_reason(self, monkeypatch):
        monkeypatch.setattr(
            "drydock.settings.Settings.load", lambda: _Settings("balanced")
        )
        run = a_run("make the payment idempotent")
        policy = cli._decide_profile(run, FAST)
        assert policy.profile == DEEP
        assert run.profile_asked == FAST
        assert run.profile_used == DEEP
        assert "money" in run.profile_floor

    def test_the_stored_setting_is_used_when_nothing_is_asked(self, monkeypatch):
        monkeypatch.setattr("drydock.settings.Settings.load", lambda: _Settings(FAST))
        run = a_run()
        assert cli._decide_profile(run, "").profile == FAST

    def test_a_later_stage_reads_the_record_rather_than_the_setting(self, monkeypatch):
        """A change to the person's settings halfway through a run must
        not change the run."""
        run = a_run()
        run.profile_used = FAST
        monkeypatch.setattr("drydock.settings.Settings.load", lambda: _Settings(DEEP))
        assert cli._policy_of(run).profile == FAST

    def test_an_older_record_without_the_field_is_resolved_not_defaulted(
        self, monkeypatch
    ):
        monkeypatch.setattr("drydock.settings.Settings.load", lambda: _Settings(FAST))
        run = a_run()
        assert run.profile_used == ""
        assert cli._policy_of(run).profile == FAST

    def test_the_app_writes_the_same_three_fields(self):
        source = inspect.getsource(session)
        for field in ("profile_asked", "profile_used", "profile_floor"):
            assert f"self.run.{field}" in source


class _Settings:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.publish_when_done = False


class TestWhatTheProfilesStillDifferBy:
    """Pinned so the difference is a decision rather than a surprise.
    These are the only fields that differ, and the one that changes what
    a run checks is `read_the_diff`."""

    def test_fast_does_not_read_the_diff_and_balanced_does(self):
        assert PROFILES[FAST].read_the_diff is False
        assert PROFILES[BALANCED].read_the_diff is True
        assert PROFILES[DEEP].read_the_diff is True

    def test_nothing_turns_off_the_arithmetic_gates(self):
        """The verifier and the inspector are not a profile's choice.
        They are code, they cost nothing, and no profile may skip them."""
        source = inspect.getsource(orchestrate)
        assert "if policy.read_the_diff:" in source
        for always in ("verify(", "look("):
            assert always in source
        assert "if policy" not in source.split("verdict = verify(")[0][-200:]

    def test_every_profile_still_has_at_least_one_attempt_and_a_revert(self):
        for name in (FAST, BALANCED, DEEP):
            assert PROFILES[name].attempts >= 1
            assert PROFILES[name].revivals >= 1
