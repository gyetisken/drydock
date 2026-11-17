"""What is kept between jobs, and what is deliberately not.

The point of remembering is that nothing is read for twice. The risk is the
opposite: handing a later job something that was true three commits ago.
Both sides are pinned here, because only one of them is visible when it goes
wrong.
"""

from pathlib import Path

from drydock.memory import Memory, _words


def fresh(tmp_path: Path) -> Memory:
    return Memory(repo=str(tmp_path))


class TestTheLook:
    def test_a_direction_is_kept_with_the_day_it_was_decided(self, tmp_path):
        memory = fresh(tmp_path)
        memory.direct("Limewash ground, one amber accent, Instrument Serif.")
        assert "amber" in memory.direction
        assert memory.directed_on

    def test_an_empty_direction_is_not_kept(self, tmp_path):
        """A designer that produced nothing has not directed anything, and
        recording that would skip the designer on every later job."""
        memory = fresh(tmp_path)
        memory.direct("   ")
        assert memory.direction == ""
        assert memory.directed_on == ""

    def test_the_look_survives_a_commit(self, tmp_path):
        """Unlike a reading of the code. How a project looks was a decision,
        not an observation, and a new commit does not undecide it."""
        memory = fresh(tmp_path)
        memory.direct("One accent, used for anything you act on.")
        memory.learn(["surefire is pinned at 2.22.2"], "abc123")

        assert "surefire" not in memory.briefing("def456")
        assert memory.direction


class TestAnswers:
    def test_the_same_question_asked_again(self, tmp_path):
        memory = fresh(tmp_path)
        memory.answered("where is the test command defined?", "package.json", "abc")
        assert memory.recall("where is the test command defined?", "abc")

    def test_the_same_question_asked_differently(self, tmp_path):
        """Nobody asks the same question the same way twice."""
        memory = fresh(tmp_path)
        memory.answered(
            "which file decides whether an item is allowed to stay?",
            "orchestrate.py, in execute().",
            "abc",
        )
        assert memory.recall("what decides whether an item stays, which file?", "abc")

    def test_a_different_question_is_not_an_answer(self, tmp_path):
        memory = fresh(tmp_path)
        memory.answered("where is the test command defined?", "package.json", "abc")
        assert not memory.recall("how does the designer pick a palette", "abc")

    def test_an_answer_does_not_outlive_the_code_it_described(self, tmp_path):
        """An answer about a file that has since changed is not an answer,
        it is a memory of one."""
        memory = fresh(tmp_path)
        memory.answered("where is the test command?", "package.json", "abc")
        assert not memory.recall("where is the test command?", "def")

    def test_answers_from_older_commits_are_dropped_as_new_ones_arrive(self, tmp_path):
        memory = fresh(tmp_path)
        memory.answered("question one", "answer one", "abc")
        memory.answered("question two", "answer two", "def")
        assert len(memory.answers) == 1
        assert memory.answers[0]["commit"] == "def"

    def test_an_empty_question_recalls_nothing(self, tmp_path):
        memory = fresh(tmp_path)
        memory.answered("where is the test command?", "package.json", "abc")
        assert not memory.recall("   ", "abc")
        assert not memory.recall("is it the a of", "abc")


class TestWhichWordsCarryAQuestion:
    def test_filler_is_dropped(self):
        assert _words("what is the thing that does this") == {"thing"}

    def test_a_plural_is_the_same_word(self):
        assert _words("the item stays") == _words("an item stay")

    def test_a_tense_is_the_same_word(self):
        """'compared' and 'compares' were two questions until this."""
        assert _words("the count is compared") == _words("it compares the count")

    def test_a_double_s_is_left_alone(self):
        assert "pass" in _words("does it pass")

    def test_short_words_are_not_mangled(self):
        """Stripping an ending off a short word leaves something that is not
        a word and matches things it should not."""
        assert "used" in _words("where is it used")
        assert "runs" in _words("what runs it")


class TestItSurvivesBeingClosed:
    """Saving and loading were two hand-written lists, and a field added to
    the class was added to neither. The look and the answers were kept for
    the length of one run and silently thrown away - which looks exactly
    like a feature that does not work."""

    def test_everything_on_the_class_is_written_and_read_back(self, tmp_path):
        memory = Memory(repo=str(tmp_path))
        memory.toolchain = "npm / TypeScript"
        memory.build_command = "npm run build"
        memory.test_command = "npm test"
        memory.last_test_count = 24
        memory.direct("Limewash ground, one amber accent.")
        memory.answered("where is the count compared?", "verify.py", "abc")
        memory.learn(["surefire is pinned at 2.22.2"], "abc")
        memory.record("a job", 3, 4, 1.2)
        memory.save()

        back = Memory.about(tmp_path)

        assert back.toolchain == "npm / TypeScript"
        assert back.last_test_count == 24
        assert back.direction and back.directed_on
        assert back.recall("which place compares the count?", "abc")
        assert "surefire" in back.briefing("abc")
        assert back.jobs

    def test_notes_come_back_as_notes_not_dictionaries(self, tmp_path):
        memory = Memory(repo=str(tmp_path))
        memory.learn(["a fact"], "abc")
        memory.save()
        back = Memory.about(tmp_path)
        assert back.notes[0].text == "a fact"

    def test_a_memory_that_cannot_be_read_is_a_blank_one(self, tmp_path):
        """It must not take the run down with it."""
        memory = Memory(repo=str(tmp_path))
        memory.save()
        memory.path.write_text("{ not json")
        assert Memory.about(tmp_path).toolchain == ""
