"""The few choices that are not per-project.

One of them decides whether finished work leaves the machine, so the thing
pinned hardest is that a file nobody can read falls back to the default
rather than to nothing.
"""

from drydock.settings import Settings


class TestTheDefault:
    def test_work_is_published_unless_somebody_says_otherwise(self, tmp_path):
        """A run that ends on a local branch nobody can see is a run that
        ended in the terminal, which is what this exists to avoid."""
        assert Settings().publish_when_done is True


class TestItSurvivesBeingClosed:
    def test_a_choice_is_written_and_read_back(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path))
        Settings(publish_when_done=False).save()
        assert Settings.load().publish_when_done is False

    def test_nothing_saved_yet_is_the_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path / "never-written"))
        assert Settings.load().publish_when_done is True

    def test_a_file_that_cannot_be_read_is_the_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path))
        (tmp_path / "settings.json").write_text("{ not json")
        assert Settings.load().publish_when_done is True

    def test_a_setting_that_no_longer_exists_is_ignored(self, tmp_path, monkeypatch):
        """An older file must not stop the program from starting."""
        monkeypatch.setenv("DRYDOCK_HOME", str(tmp_path))
        (tmp_path / "settings.json").write_text(
            '{"publish_when_done": false, "a_setting_that_was_removed": 3}'
        )
        assert Settings.load().publish_when_done is False
