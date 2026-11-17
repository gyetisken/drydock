"""Which items may be worked on at the same time.

This is the one piece of concurrency in the program and it is the piece
where being wrong is expensive: two workers editing the same file produce a
conflict and an item rolled back for a reason that was never about the work.
So the rules are strict, and every way they could let two items collide is
pinned here.
"""

from drydock.models import Item
from drydock.waves import how_much_faster, overlap, plan_waves


def item(number: int, files=None, needs=None) -> Item:
    return Item(
        id=number,
        title=f"item {number}",
        rationale="because",
        files=files if files is not None else [f"src/{number}.ts"],
        verify_with="tests",
        needs=needs or [],
    )


def shape(waves) -> list[list[int]]:
    return [[i.id for i in w.items] for w in waves]


class TestDependencies:
    def test_a_chain_stays_a_chain(self):
        items = [item(1), item(2, needs=[1]), item(3, needs=[2])]
        assert shape(plan_waves(items)) == [[1], [2], [3]]

    def test_items_that_need_nothing_go_together(self):
        items = [item(1), item(2), item(3)]
        assert shape(plan_waves(items)) == [[1, 2, 3]]

    def test_everything_waiting_on_the_first_item(self):
        """The usual shape: item one makes the suite able to say anything."""
        items = [item(1), item(2, needs=[1]), item(3, needs=[1]), item(4, needs=[1])]
        assert shape(plan_waves(items)) == [[1], [2, 3, 4]]

    def test_a_diamond(self):
        items = [
            item(1),
            item(2, needs=[1]),
            item(3, needs=[1]),
            item(4, needs=[2, 3]),
        ]
        assert shape(plan_waves(items)) == [[1], [2, 3], [4]]

    def test_work_already_landed_is_not_waited_for(self):
        items = [item(1), item(2, needs=[1]), item(3, needs=[1])]
        assert shape(plan_waves(items, done={1})) == [[2, 3]]


class TestFilesColliding:
    def test_two_items_touching_the_same_file_do_not_share_a_wave(self):
        items = [item(1, files=["src/a.ts"]), item(2, files=["src/a.ts"])]
        assert shape(plan_waves(items)) == [[1], [2]]

    def test_a_glob_covers_what_is_under_it(self):
        """`src/**/*.ts` and `src/hours.ts` are going to meet."""
        items = [item(1, files=["src/**/*.ts"]), item(2, files=["src/hours.ts"])]
        assert shape(plan_waves(items)) == [[1], [2]]

    def test_different_directories_are_fine(self):
        items = [item(1, files=["src/hours.ts"]), item(2, files=["public/site.css"])]
        assert shape(plan_waves(items)) == [[1, 2]]

    def test_an_item_that_names_no_files_goes_alone(self):
        """Not knowing what it will touch is not the same as knowing it
        touches nothing."""
        items = [item(1, files=[]), item(2, files=["src/a.ts"])]
        assert shape(plan_waves(items)) == [[1], [2]]

    def test_a_bare_glob_collides_with_everything(self):
        items = [item(1, files=["**/*"]), item(2, files=["src/a.ts"])]
        assert shape(plan_waves(items)) == [[1], [2]]

    def test_leading_dot_slash_is_the_same_path(self):
        items = [item(1, files=["./src/a.ts"]), item(2, files=["src/a.ts"])]
        assert overlap(items[0], items[1])


class TestItNeverStops:
    def test_a_cycle_falls_back_to_the_written_order(self):
        """A slower run is better than a run that stops."""
        items = [item(1, needs=[2]), item(2, needs=[1])]
        assert shape(plan_waves(items)) == [[1], [2]]

    def test_a_dependency_that_will_never_land(self):
        """It does not block the items that can be done. The stuck one is
        still attempted, last, rather than dropped."""
        items = [item(2, needs=[99]), item(3)]
        waves = plan_waves(items)
        assert shape(waves) == [[3], [2]]
        assert "cannot be satisfied" in waves[-1].why

    def test_every_item_appears_exactly_once(self):
        items = [
            item(1),
            item(2, needs=[1], files=["a/x"]),
            item(3, needs=[1], files=["b/y"]),
            item(4, needs=[2], files=["a/x"]),
            item(5, files=["c/z"]),
        ]
        seen = [i.id for w in plan_waves(items) for i in w.items]
        assert sorted(seen) == [1, 2, 3, 4, 5]
        assert len(seen) == len(set(seen))

    def test_nothing_in_means_nothing_out(self):
        assert plan_waves([]) == []


class TestWhatItSaysItBought:
    def test_it_says_nothing_when_nothing_was_gained(self):
        items = [item(1), item(2, needs=[1])]
        assert how_much_faster(plan_waves(items)) == ""

    def test_it_counts_what_runs_alongside(self):
        items = [
            item(1),
            item(2, needs=[1], files=["a/x"]),
            item(3, needs=[1], files=["b/y"]),
        ]
        said = how_much_faster(plan_waves(items))
        assert "3 items in 2 rounds" in said
