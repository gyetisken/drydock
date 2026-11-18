"""Exercise the acceptance boundary with Git and a local test process."""

import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from drydock import orchestrate, publish
from drydock.models import Baseline, Item, Outcome, Plan
from drydock.policy import of
from drydock.run import Run
from drydock.session import Session
from drydock.verify import verify


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRYDOCK_NO_SPLIT", "1")
    repo = tmp_path / "fixture"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "left").write_text("off\n")
    (repo / "right").write_text("off\n")
    (repo / "test_flags.py").write_text(
        "from pathlib import Path\n"
        "import os\n"
        "import subprocess\n"
        "def test_flags_can_be_combined():\n"
        "    left, right = (Path(name).read_text().strip() for name in ('left', 'right'))\n"
        "    if left == right == 'on' and os.environ.get('FIXTURE_DIRTY_FAILURE'):\n"
        "        Path('unexpected').write_text('keep me')\n"
        "    if left == right == 'on' and os.environ.get('FIXTURE_LOCK_FAILURE'):\n"
        "        lock = subprocess.check_output(['git', 'rev-parse', '--git-path',"
        " 'index.lock'], text=True).strip()\n"
        "        Path(lock).touch()\n"
        "    assert (left, right) != ('on', 'on')\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Starting fixture")

    python = shlex.quote(sys.executable)
    chain = SimpleNamespace(
        build_command=f"{python} -c pass",
        test_command=f"{python} -B -m pytest -q -p no:cacheprovider test_flags.py",
        has_tests=True,
    )
    monkeypatch.setattr(orchestrate, "detect", lambda _: chain)

    def work(where, _task, item, *_args, **_kwargs):
        (where / item.files[0]).write_text("on\n")
        return {"done": True, "summary": item.title, "files_changed": item.files}, None

    monkeypatch.setattr(orchestrate, "work", work)
    return repo, chain


def item(number, name, needs=None):
    return Item(
        id=number,
        title=f"Enable {name}",
        rationale="Exercise integration",
        files=[name],
        verify_with="tests",
        needs=needs or [],
    )


def run_for(repo, *items):
    run = Run.start(repo, "Verify flags")
    run.baseline = Baseline(builds=True, tests_run=1)
    run.plan = Plan(summary="Enable flags", items=list(items))
    return run


def test_serial_acceptance_records_the_checked_commit(project, monkeypatch):
    repo, _ = project
    observed = []
    actual_verify = orchestrate.verify

    def record(where, *args):
        observed.append(
            (git(where, "rev-parse", "HEAD"), git(where, "status", "--short"))
        )
        return actual_verify(where, *args)

    monkeypatch.setattr(orchestrate, "verify", record)
    run = run_for(repo, item(1, "left"))
    orchestrate.execute(run, policy=of("fast"))

    tip = git(repo, "rev-parse", "HEAD")
    saved = Run.load(run.id)
    assert (tip, "") in observed
    assert saved.results[0].outcome is Outcome.DONE
    assert saved.results[0].commit == tip
    assert saved.results[0].verified_commit == tip
    assert saved.results[0].checks[-1].passed


@pytest.mark.parametrize("separate_build", [True, False], ids=["build", "test-alias"])
def test_build_only_preflight_runs_suite_only_on_the_integrated_commit(
    project, monkeypatch, separate_build
):
    from drydock import verify as verifier

    repo, chain = project
    if not separate_build:
        chain.build_command = chain.test_command
    before = git(repo, "rev-parse", "HEAD")
    checks = []
    actual_check = verifier.check

    def record(name, command, where):
        checks.append((name, git(where, "rev-parse", "HEAD")))
        return actual_check(name, command, where)

    monkeypatch.setattr(verifier, "check", record)
    build_item = item(1, "left").model_copy(update={"verify_with": "build"})
    run = run_for(repo, build_item)
    orchestrate.execute(run, policy=of("fast"))

    tip = git(repo, "rev-parse", "HEAD")
    assert Run.load(run.id).results[0].verified_commit == tip
    expected_builds = [("build", before), ("build", tip)] if separate_build else []
    assert checks == [*expected_builds, ("tests", tip)]


def test_worker_reporting_success_without_edits_is_blocked(project, monkeypatch):
    repo, _ = project
    before = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(
        orchestrate,
        "work",
        lambda *a, **k: (
            {"done": True, "summary": "No edits", "files_changed": []},
            None,
        ),
    )
    run = run_for(repo, item(1, "left"))
    orchestrate.execute(run, policy=of("fast"))

    result = Run.load(run.id).results[0]
    assert result.outcome is Outcome.BLOCKED
    assert result.commit is None and result.verified_commit is None
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize(
    "test_script",
    ["raise SystemExit(1)", "print('summary unavailable')", "print('1 passed')", None],
    ids=["red", "unreadable", "reduced", "missing"],
)
def test_build_mode_requires_an_existing_suite(tmp_path, test_script):
    python = shlex.quote(sys.executable)
    commands = {
        "build": f"{python} -c pass",
        "tests": f"{python} -c {shlex.quote(test_script)}" if test_script else "",
    }
    verdict = verify(tmp_path, "build", Baseline(builds=True, tests_run=2), commands)
    assert not verdict.passed
    assert verdict.check.name == "tests"


def test_an_unmeasured_existing_suite_cannot_be_skipped(tmp_path):
    python = shlex.quote(sys.executable)
    commands = {
        "build": f"{python} -c pass",
        "tests": f"{python} -c pass",
        "has_tests": True,
    }
    verdict = verify(tmp_path, "build", Baseline(builds=True, has_tests=True), commands)
    assert not verdict.passed
    assert verdict.check.name == "tests"


def test_build_output_cannot_replace_a_removed_test_command(tmp_path):
    build = f"{shlex.quote(sys.executable)} -c \"print('2 passed')\""
    commands = {"build": build, "tests": build, "has_tests": False}
    verdict = verify(tmp_path, "build", Baseline(builds=True, tests_run=2), commands)
    assert not verdict.passed
    assert verdict.check.name == "tests"


def test_individually_green_parallel_changes_can_fail_together(project):
    repo, chain = project
    start = git(repo, "rev-parse", "HEAD")
    run = run_for(repo, item(1, "left"), item(2, "right"), item(3, "later", [2]))
    orchestrate.execute(run, policy=of("fast"))

    first, rejected, dependent = Run.load(run.id).results
    assert (first.outcome, rejected.outcome, dependent.outcome) == (
        Outcome.DONE,
        Outcome.REVERTED,
        Outcome.BLOCKED,
    )
    assert not rejected.checks[-1].passed
    assert rejected.checks[-1].name == "tests"
    assert git(repo, "rev-parse", "HEAD") == first.commit
    assert git(repo, "rev-parse", "HEAD^") == start
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / "right").read_text() == "off\n"
    assert not (repo / "later").exists()
    assert verify(
        repo,
        "tests",
        run.baseline,
        {"build": chain.build_command, "tests": chain.test_command},
    ).passed


@pytest.mark.parametrize("failure", ["DIRTY", "LOCK"])
def test_an_unconfirmed_rollback_stops_and_blocks_publication(
    project, failure, tmp_path, monkeypatch
):
    repo, _ = project
    monkeypatch.setenv(f"FIXTURE_{failure}_FAILURE", "1")
    run = run_for(repo, item(1, "left"), item(2, "right"), item(3, "later", [2]))
    with pytest.raises(RuntimeError, match="expected.*observed"):
        orchestrate.execute(run, policy=of("fast"))

    saved = Run.load(run.id)
    assert [result.outcome for result in saved.results] == [
        Outcome.DONE,
        Outcome.BLOCKED,
    ]
    assert not saved.results[1].checks[-1].passed
    assert not (repo / "later").exists()
    if failure == "DIRTY":
        assert (repo / "unexpected").read_text() == "keep me"
        with pytest.raises(RuntimeError, match="expected.*observed"):
            Session.resume(saved)
        assert (repo / "unexpected").read_text() == "keep me"
    remote = local_remote(repo, tmp_path, monkeypatch)
    git(repo, "update-ref", f"refs/heads/drydock/{run.id}", saved.results[0].commit)
    ok, reason = publish.open_pull_request(repo, saved, [])
    assert not ok
    assert "observed" in reason
    assert git(remote, "for-each-ref") == ""


def local_remote(repo, tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    # The only external operation is the GitHub CLI. Pushes go to real local Git.
    gh = tmp_path / "fake-gh"
    gh.write_text("#!/bin/sh\nprintf '%s\\n' https://example.invalid/pull/1\n")
    gh.chmod(0o755)
    monkeypatch.setattr(publish, "_gh", lambda: str(gh))
    return remote


def test_publication_refuses_a_changed_run_tip(project, tmp_path, monkeypatch):
    repo, _ = project
    remote = local_remote(repo, tmp_path, monkeypatch)
    run = run_for(repo, item(1, "left"))
    orchestrate.execute(run, policy=of("fast"))
    git(repo, "commit", "--allow-empty", "-qm", "Unverified change")

    ok, _ = publish.open_pull_request(repo, run, [])
    assert not ok
    assert git(remote, "for-each-ref") == ""


def test_publication_pushes_only_the_verified_run_branch(
    project, tmp_path, monkeypatch
):
    repo, _ = project
    remote = local_remote(repo, tmp_path, monkeypatch)
    run = run_for(repo, item(1, "left"))
    orchestrate.execute(run, policy=of("fast"))
    tip = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "main")

    ok, _ = publish.open_pull_request(repo, run, [])
    assert ok
    assert git(remote, "for-each-ref", "--format=%(objectname) %(refname)") == (
        f"{tip} refs/heads/drydock/{run.id}"
    )
