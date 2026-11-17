"""The live feed.

The crew already reports what it is doing through callbacks, because the
command line needed that before there was ever a web page. This turns those
same callbacks into a stream a browser can read, which is why the page cannot
drift out of step with the terminal: both are watching one source.

Events are dropped rather than queued without bound. A viewer who closes the
tab must not be able to stall the run by leaving a full queue behind.
"""

import json
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    # Local time, because every one of these is read by somebody sitting in
    # front of the machine. Stamped in UTC it was five hours off their own
    # clock, which makes "when did this stop" unanswerable by looking.
    at: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    def sse(self) -> str:
        payload = json.dumps({"kind": self.kind, "at": self.at, **self.data})
        return f"data: {payload}\n\n"


class Feed:
    """One run's events, fanned out to everyone watching."""

    def __init__(self, keep: int = 400) -> None:
        self._lock = threading.Lock()
        self._history: list[Event] = []
        self._listeners: list[queue.Queue] = []
        self._keep = keep
        self.finished = False
        self._sinks: list = []

    def also(self, sink) -> None:
        """Send every event somewhere else as well - a file, usually."""
        self._sinks.append(sink)

    def emit(self, kind: str, **data) -> None:
        event = Event(kind, data)
        with self._lock:
            self._history.append(event)
            del self._history[: -self._keep]
            listeners = list(self._listeners)
        for sink in self._sinks:
            try:
                sink(event)
            except Exception as exc:  # noqa: BLE001 - a sink must not stop a run
                print(f"event sink failed: {exc}")
        for listener in listeners:
            try:
                listener.put_nowait(event)
            except queue.Full:
                # A viewer that cannot keep up loses events, not the run.
                pass

    def listen(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            for event in self._history:
                q.put_nowait(event)
            self._listeners.append(q)
        return q

    def stop_listening(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def close(self) -> None:
        self.finished = True
        self.emit("run.finished")
