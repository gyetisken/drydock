"""A dev server that outlived the directory it was serving.

Items in a wave each run in their own worktree, and both the critic and
now the engineer start the project there to look at it. The worktrees are
removed in a `finally` when the wave ends; the servers were not stopped
first. So a node process carried on, holding a deleted directory, still
answering on its port and still written down in the roster - and the next
look at that project found a preview that answers and serves whatever it
last built.
"""

import inspect
from pathlib import Path

from drydock import orchestrate, preview


class TestTheOrderIsTheWholePoint:
    def test_the_server_is_stopped_before_the_tree_is_removed(self):
        source = inspect.getsource(orchestrate._work_a_wave)
        tidy = source.index("_no_longer_serving(where)")
        drop = source.index("repo.drop_worktree(where)")
        assert tidy < drop

    def test_every_tree_the_wave_made_is_tidied(self):
        source = inspect.getsource(orchestrate._work_a_wave)
        assert source.count("_no_longer_serving(where)") == 1
        assert "for where in trees.values():" in source


class TestItNeverTakesAWaveDown:
    def test_a_preview_that_cannot_be_stopped_is_not_an_error(self, monkeypatch):
        def refuse(_repo=None):
            raise OSError("no such process")

        monkeypatch.setattr(preview, "stop", refuse)
        orchestrate._no_longer_serving(Path("/nowhere"))

    def test_a_tree_with_no_preview_is_fine(self, tmp_path):
        assert preview.running(tmp_path) is None
        orchestrate._no_longer_serving(tmp_path)


class TestWhatItActuallyStops:
    def test_a_written_down_preview_is_struck_off(self, tmp_path):
        """The roster is the part that outlives everything: a note saying
        a port serves this project, read by the next look at it."""
        written = preview.Preview(
            project=str(tmp_path),
            url="http://localhost:65535",
            command="npm run dev",
            # Pid 0 is nobody, which is what a dead preview is.
            process=preview._Elsewhere(0),
            log=tmp_path / "log",
        )
        preview._write_down(written)
        note = preview._roster() / preview._note_name(tmp_path)
        assert note.exists()

        orchestrate._no_longer_serving(tmp_path)

        assert not note.exists()
