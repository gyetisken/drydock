"""The event feed, which is the only thing standing between a run and a
window showing nothing.

A job here takes minutes and the person watching it will refresh the page,
close the laptop, come back later. Every one of those is a new listener
asking for everything that has happened, and the run is still emitting
while it reads. So the two things pinned here are that a late arrival gets
the whole story, and that one slow or broken viewer cannot touch the run.
"""

import queue

from drydock.events import Feed


class TestWhatALateArrivalSees:
    def test_everything_that_already_happened(self):
        feed = Feed()
        feed.emit("item.start", id=1)
        feed.emit("item.done", id=1)

        q = feed.listen()
        assert [q.get_nowait().kind for _ in range(2)] == ["item.start", "item.done"]

    def test_a_long_run_is_not_truncated_on_refresh(self):
        """This is the bug: the queue handed to a new viewer had a fixed
        size, and a job that had emitted more events than that raised on
        the way in. The person refreshed the page mid-run and got an error
        instead of the run."""
        feed = Feed()
        for i in range(2000):
            feed.emit("agent.tool", id=i)

        q = feed.listen()
        assert q.qsize() == 2000

    def test_there_is_room_left_for_what_happens_next(self):
        """The replay fills the queue and the run carries on filling it."""
        feed = Feed()
        for i in range(2000):
            feed.emit("agent.tool", id=i)
        q = feed.listen()

        for i in range(500):
            feed.emit("agent.tool", id=i)

        assert q.qsize() == 2500

    def test_the_oldest_events_do_eventually_go(self):
        """Unbounded history on a day-long run is a leak. The file on disk
        is the record; this is a window."""
        feed = Feed(keep=10)
        for i in range(50):
            feed.emit("agent.tool", id=i)

        q = feed.listen()
        assert q.qsize() == 10
        assert q.get_nowait().data["id"] == 40


class TestNothingStopsTheRun:
    def test_a_viewer_that_cannot_keep_up_loses_events_not_the_run(self):
        feed = Feed(keep=1)
        slow = queue.Queue(maxsize=1)
        feed._listeners.append(slow)

        for i in range(10):
            feed.emit("agent.tool", id=i)  # must not raise

        assert slow.qsize() == 1

    def test_a_sink_that_throws_does_not_stop_the_run(self):
        """The sink is a file write. A full disk must not end the job."""
        feed = Feed()

        def broken(event):
            raise OSError("no space left on device")

        feed.also(broken)
        feed.emit("item.start", id=1)

        assert feed.listen().qsize() == 1

    def test_a_viewer_that_left_is_forgotten(self):
        feed = Feed()
        q = feed.listen()
        feed.stop_listening(q)
        feed.stop_listening(q)  # twice, because a browser closing races

        feed.emit("item.done", id=1)
        assert q.qsize() == 0


def test_closing_says_so_once():
    feed = Feed()
    q = feed.listen()
    feed.close()

    assert feed.finished
    assert q.get_nowait().kind == "run.finished"


def test_every_event_carries_a_time_somebody_can_read():
    """Stamped UTC, these read five hours off the clock on the machine
    showing them."""
    from datetime import datetime

    feed = Feed()
    feed.emit("item.start", id=1)
    at = feed.listen().get_nowait().at

    assert at[:2] == datetime.now().strftime("%H")
