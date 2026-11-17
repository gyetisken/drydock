"""What is remembered between jobs, and what has to be re-read.

The point of the memory is to stop paying twice for the same reading. The
risk is the opposite failure: telling the next job something that was true
three commits ago. These tests pin both sides of that.
"""

from pathlib import Path

from drydock.memory import Memory


def fresh(tmp_path: Path) -> Memory:
    m = Memory(repo=str(tmp_path))
    m.toolchain = "Maven / Java"
    m.build_command = "mvn -B -q compile"
    m.test_command = "mvn -B test"
    m.last_test_count = 838
    return m


def test_commands_survive_a_new_commit(tmp_path):
    m = fresh(tmp_path)
    brief = m.briefing("whatever-commit")
    assert "mvn -B test" in brief
    assert "838" in brief


def test_notes_are_withheld_once_the_commit_moves(tmp_path):
    m = fresh(tmp_path)
    m.learn(["surefire is pinned at 2.22.2"], "abc123")
    assert "surefire" in m.briefing("abc123")
    assert "surefire" not in m.briefing("def456")


def test_a_repository_never_worked_on_says_nothing(tmp_path):
    assert Memory(repo=str(tmp_path)).briefing("abc") == ""


def test_notes_do_not_grow_without_bound(tmp_path):
    m = fresh(tmp_path)
    for i in range(200):
        m.learn([f"fact {i}"], "abc123")
    assert len(m.notes) <= 40
