"""Knowing which workers are running, across a restart.

A worker is a separate process holding a turn and writing files. The set
this program kept of them lived in memory, so restarting the application
forgot every one - while the workers themselves carried on. The next run
then opened the same repository with somebody else's hands already in it,
and the engineer noticed before the harness did: "there's clearly another
process concurrently writing these exact files."

So the roster is on disk, and it is treated as a cache of something the
operating system already knows: a pid and a path, trusted no further.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from drydock import engines


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "home"))
    with engines._WORKERS_LOCK:
        engines._WORKERS.clear()
    yield tmp_path
    with engines._WORKERS_LOCK:
        engines._WORKERS.clear()


def a_sleeper() -> subprocess.Popen:
    """A process that will not exit on its own, standing in for a worker."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class TestWhatIsWrittenDown:
    def test_a_worker_is_written_down_with_its_repository(self, home):
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        try:
            engines._watch(process)
            notes = list((Path(os.environ["DRYDOCK_HOME"]) / "workers").glob("*.json"))
            assert len(notes) == 1
            assert json.loads(notes[0].read_text()) == {
                "pid": process.pid,
                "repo": "/some/repo",
            }
        finally:
            process.kill()

    def test_a_worker_that_finished_is_struck_off(self, home):
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        try:
            engines._watch(process)
            engines._forget(process)
            assert not list(
                (Path(os.environ["DRYDOCK_HOME"]) / "workers").glob("*.json")
            )
        finally:
            process.kill()

    def test_a_roster_that_cannot_be_written_is_not_fatal(self, home, monkeypatch):
        """Counting workers must never be the thing that stops a run."""
        monkeypatch.setattr(engines, "_roster", lambda: (_ for _ in ()).throw(OSError))
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        try:
            engines._watch(process)  # must not raise
            assert process in engines._WORKERS
        finally:
            process.kill()


class TestOrphans:
    def test_a_worker_nobody_is_watching_is_found(self, home):
        """This is the bug. The pid is in the roster, alive, and no process
        in this program owns it - which is exactly a survivor of a restart."""
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        try:
            engines._watch(process)
            with engines._WORKERS_LOCK:
                engines._WORKERS.clear()  # the restart

            assert engines._orphans(Path("/some/repo")) == [process.pid]
        finally:
            process.kill()

    def test_an_orphan_in_another_repository_is_left_alone(self, home):
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        try:
            engines._watch(process)
            with engines._WORKERS_LOCK:
                engines._WORKERS.clear()

            assert engines._orphans(Path("/a/different/repo")) == []
        finally:
            process.kill()

    def test_a_worker_this_process_owns_is_not_an_orphan(self, home):
        """It is being watched, and stop_workers handles it properly -
        asked to stop first, so it closes its own files."""
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        try:
            engines._watch(process)
            assert engines._orphans(Path("/some/repo")) == []
        finally:
            process.kill()

    def test_a_note_about_a_dead_process_is_swept(self, home):
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        engines._watch(process)
        with engines._WORKERS_LOCK:
            engines._WORKERS.clear()
        process.kill()
        process.wait()

        assert engines._orphans(None) == []
        assert not list((Path(os.environ["DRYDOCK_HOME"]) / "workers").glob("*.json"))

    def test_a_damaged_note_is_swept_rather_than_believed(self, home):
        where = Path(os.environ["DRYDOCK_HOME"]) / "workers"
        where.mkdir(parents=True)
        (where / "nonsense.json").write_text("{ not json")

        assert engines._orphans(None) == []
        assert not list(where.glob("*.json"))


class TestStopping:
    def test_an_orphan_is_actually_stopped(self, home):
        process = a_sleeper()
        process.drydock_repo = "/some/repo"
        engines._watch(process)
        with engines._WORKERS_LOCK:
            engines._WORKERS.clear()

        assert engines.stop_workers(Path("/some/repo")) == 1
        process.wait(timeout=10)
        assert process.poll() is not None

    def test_it_says_how_many_it_stopped(self, home):
        """The number reaches the person reading the run, because a resumed
        job that had to stop two of its predecessors is worth knowing about."""
        mine = a_sleeper()
        mine.drydock_repo = "/some/repo"
        orphan = a_sleeper()
        orphan.drydock_repo = "/some/repo"
        try:
            engines._watch(mine)
            engines._watch(orphan)
            with engines._WORKERS_LOCK:
                engines._WORKERS.discard(orphan)

            assert engines.stop_workers(Path("/some/repo")) == 2
        finally:
            mine.kill()
            orphan.kill()

    def test_nothing_running_stops_nothing(self, home):
        assert engines.stop_workers(Path("/some/repo")) == 0


class TestAWorkerCannotBeTakenDownBySomebodyElse:
    """Started as an ordinary child, a worker sits in this application's
    process group along with every preview server it has started. Anything
    in that group which cleans up after itself by signalling the group -
    which is what npm does when a dev server is stopped - takes the worker
    with it. A healthy one died twice that way, mid-sentence, with neither
    of this program's own clocks anywhere near it.

    The preview was already started in its own session. The workers were
    not, which is the asymmetry that made this possible.
    """

    def test_both_kinds_of_worker_get_their_own_session(self):
        import inspect

        from drydock import engines

        source = inspect.getsource(engines)
        starts = source.count("stdin=subprocess.PIPE")
        sessions = source.count("start_new_session=True")
        assert starts == 2, "there are two places a worker is started"
        assert sessions == starts, "and each of them has to open its own session"

    def test_the_preview_keeps_its_own_too(self):
        import inspect

        from drydock import preview

        assert "start_new_session=True" in inspect.getsource(preview)
