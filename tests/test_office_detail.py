"""What the office is allowed to say about each station.

The room is the part of this program people like, and until now it was the
part that knew least: nine desks, five states, and a one-line note that was
overwritten every time anything happened. Everything else a station did -
when it started, what it ran, what it decided and about which item - was in
the log and shown to nobody.

Three of its claims were also false, and all three said success:

  - `on_gate` is called for an engineer's question, a planner's answer, a
    restart and a split. The handler mapped every unrecognised one onto the
    Reviewer with `passed` true, so the Reviewer was shown as done - with a
    note about a restart - for items it had never read.
  - the Verifier's baseline state was closed by the browser, off the test
    figures, so the log said it started and never stopped.
  - reading a finished run back never touched the room at all, so it kept
    nine idle desks: "waiting for the station before it", said about a job
    that ended two days ago.

So the states come off the log here, and what the log does not carry is
said to be missing rather than filled in.
"""

from pathlib import Path

from drydock.crew import GATE_STATION, what_each_did
from drydock.pace import events_in

HERE = Path(__file__).resolve().parents[1] / "src" / "drydock"
CHAT = (HERE / "static" / "chat.js").read_text()
OFFICE = (HERE / "static" / "office.js").read_text()
SESSION = (HERE / "session.py").read_text()


def by_name(rows: list[dict]) -> dict[str, dict]:
    return {r["name"]: r for r in rows}


def worked(agent: str, at: str, note: str = "") -> dict:
    return {
        "kind": "agent.state",
        "agent": agent,
        "state": "working",
        "note": note,
        "at": at,
    }


def finished(agent: str, at: str, state: str = "done", note: str = "") -> dict:
    return {
        "kind": "agent.state",
        "agent": agent,
        "state": state,
        "note": note,
        "at": at,
    }


class TestStatusMapping:
    def test_a_station_that_reported_nothing_is_idle(self):
        rows = by_name(what_each_did([]))
        assert len(rows) == 9
        assert {r["state"] for r in rows.values()} == {"idle"}

    def test_the_last_thing_a_station_said_is_its_state(self):
        rows = by_name(
            what_each_did(
                [
                    worked("Planner", "10:00:00", "turning it into items"),
                    finished("Planner", "10:00:30", note="3 items"),
                ]
            )
        )
        assert rows["Planner"]["state"] == "done"
        assert rows["Planner"]["note"] == "3 items"

    def test_a_refusal_is_not_a_pass(self):
        rows = by_name(
            what_each_did(
                [
                    finished(
                        "Reviewer", "10:01:00", "failed", "it did more than the item"
                    ),
                ]
            )
        )
        assert rows["Reviewer"]["state"] == "failed"

    def test_a_skipped_station_stays_skipped(self):
        rows = by_name(
            what_each_did(
                [
                    finished(
                        "Architect",
                        "10:00:01",
                        "skipped",
                        "the task already decided it",
                    ),
                    {"kind": "run.summary", "at": "10:05:00"},
                ]
            )
        )
        assert rows["Architect"]["state"] == "skipped"

    def test_a_station_still_working_when_the_run_ended_is_not_working(self):
        """The one claim this must never make. A desk whose monitor is still
        animating in a run that stopped an hour ago is the office lying
        about the present tense."""
        rows = by_name(
            what_each_did(
                [
                    worked("Engineer", "10:02:00", "item 1"),
                    {"kind": "run.error", "at": "10:03:00"},
                ]
            )
        )
        assert rows["Engineer"]["state"] == "cut"
        assert "ended before" in rows["Engineer"]["note"] or rows["Engineer"]["note"]

    def test_a_station_that_never_ran_is_not_called_waiting(self):
        """While a run is going, idle means waiting for the station before
        it. After it ends, that desk was simply never needed."""
        rows = by_name(
            what_each_did(
                [
                    finished("Planner", "10:00:30"),
                    {"kind": "run.summary", "at": "10:05:00"},
                ]
            )
        )
        assert rows["Critic"]["state"] == "never"
        assert rows["Planner"]["state"] == "done"

    def test_the_words_for_both_exist_in_the_window(self):
        assert "cut:" in CHAT and "never:" in CHAT
        assert "never ran in this job" in CHAT


class TestWhatEachStationDid:
    def test_time_is_the_work_not_the_span(self):
        """The Engineer is at its desk once per item. Reporting first-start
        to last-stop would call most of the run time it spent working."""
        rows = by_name(
            what_each_did(
                [
                    worked("Engineer", "10:00:00"),
                    finished("Engineer", "10:00:20"),
                    worked("Engineer", "10:10:00"),
                    finished("Engineer", "10:10:40"),
                ]
            )
        )
        engineer = rows["Engineer"]

        assert engineer["seconds"] == 60
        assert engineer["began"] == "10:00:00"
        assert engineer["ended"] == "10:10:40"
        assert len(engineer["visits"]) == 4

    def test_a_spell_that_never_ended_claims_no_time(self):
        rows = by_name(
            what_each_did(
                [
                    worked("Engineer", "10:00:00"),
                    {"kind": "run.error", "at": "10:30:00"},
                ]
            )
        )
        assert rows["Engineer"]["seconds"] is None

    def test_midnight_does_not_make_a_negative_duration(self):
        rows = by_name(
            what_each_did(
                [
                    worked("Engineer", "23:59:50"),
                    finished("Engineer", "00:00:10"),
                ]
            )
        )
        assert rows["Engineer"]["seconds"] == 20

    def test_tool_calls_are_kept_against_the_station_that_made_them(self):
        rows = by_name(
            what_each_did(
                [
                    {
                        "kind": "agent.tool",
                        "agent": "Engineer",
                        "what": "Write",
                        "detail": "server.js",
                        "at": "10:00:05",
                    },
                    {
                        "kind": "agent.tool",
                        "agent": "Analyst",
                        "what": "Read",
                        "detail": "package.json",
                        "at": "10:00:06",
                    },
                ]
            )
        )
        assert rows["Engineer"]["tool_calls"] == 1
        assert rows["Engineer"]["tools"][0]["detail"] == "server.js"
        assert rows["Analyst"]["tool_calls"] == 1

    def test_the_real_count_survives_the_cap_on_what_is_sent(self):
        """Keeping the last forty is a transport decision. Reporting forty
        when there were three hundred would be a different claim."""
        rows = by_name(
            what_each_did(
                [
                    {
                        "kind": "agent.tool",
                        "agent": "Engineer",
                        "what": "Edit",
                        "detail": f"file{n}.js",
                        "at": "10:00:00",
                    }
                    for n in range(120)
                ]
            )
        )
        engineer = rows["Engineer"]

        assert engineer["tool_calls"] == 120
        assert len(engineer["tools"]) == 40
        assert engineer["tools"][-1]["detail"] == "file119.js"

    def test_a_verdict_is_recorded_against_its_item(self):
        rows = by_name(
            what_each_did(
                [
                    {
                        "kind": "gate",
                        "id": 2,
                        "who": "critic",
                        "station": "Critic",
                        "passed": False,
                        "note": "the hours band overflows on a phone",
                        "at": "10:04:00",
                    },
                ]
            )
        )
        (verdict,) = rows["Critic"]["gates"]

        assert verdict == {
            "item": 2,
            "passed": False,
            "note": "the hours band overflows on a phone",
            "at": "10:04:00",
        }

    def test_only_the_three_gates_are_verdicts(self):
        """`restarted` and `split` arrive the same way and are not
        judgements. Counted as verdicts they are a station approving work it
        never saw."""
        rows = by_name(
            what_each_did(
                [
                    {
                        "kind": "gate",
                        "id": 1,
                        "who": "restarted",
                        "passed": True,
                        "note": "restart 1 of 2",
                        "at": "10:01:00",
                    },
                    {
                        "kind": "gate",
                        "id": 1,
                        "who": "asked",
                        "passed": True,
                        "note": "which font?",
                        "at": "10:01:30",
                    },
                    {
                        "kind": "gate",
                        "id": 1,
                        "who": "split",
                        "passed": True,
                        "note": "now three pieces",
                        "at": "10:02:00",
                    },
                ]
            )
        )
        assert all(not r["gates"] for r in rows.values())

    def test_a_station_nobody_has_heard_of_is_ignored(self):
        """An older log, or a renamed station. It must not appear as a
        tenth desk and must not take the reader down with it."""
        rows = what_each_did(
            [
                worked("Archivist", "10:00:00"),
                {"kind": "agent.tool", "agent": "Archivist", "at": "10:00:01"},
            ]
        )
        assert len(rows) == 9

    def test_a_log_that_stops_mid_line_is_still_read(self, tmp_path):
        log = tmp_path / "run.log"
        log.write_text(
            '{"kind": "agent.state", "agent": "Planner", "state": "done",'
            ' "note": "3 items", "at": "10:00:30"}\n'
            '{"kind": "agent.state", "agent": "Engin\n'
        )
        rows = by_name(what_each_did(events_in(log)))
        assert rows["Planner"]["state"] == "done"


class TestTheSourceOfTheMislabel:
    """Fixed where it was made, not worked around where it showed."""

    def test_the_gate_names_the_station_it_belongs_to(self):
        assert 'station=GATE_STATION.get(who, "")' in SESSION

    def test_only_a_named_station_gets_a_state_from_a_gate(self):
        assert "station = GATE_STATION.get(who)" in SESSION
        assert '}.get(who, "Reviewer")' not in SESSION

    def test_the_window_no_longer_keeps_its_own_copy_of_the_map(self):
        assert 'critic: "Critic" }[e.who] || "Reviewer"' not in CHAT
        assert "const who = e.station;" in CHAT

    def test_the_verifier_closes_its_own_baseline_state(self):
        """It was the browser doing this, off the baseline figures, so the
        log never recorded the station finishing."""
        where = SESSION.index('"baseline",')
        after = SESSION[where : where + 1200]
        assert 'agent="Verifier"' in after and 'state="done"' in after

    def test_the_three_gates_are_named_in_one_place(self):
        assert set(GATE_STATION.values()) == {"Inspector", "Reviewer", "Critic"}


class TestChoosingADesk:
    """The canvas is not an accessible control, so it is never the only way
    in: the list beside the room is a list of buttons."""

    def test_the_room_can_be_clicked(self):
        assert "function whoIsAt(" in OFFICE
        assert "canvas.onclick" in OFFICE

    def test_the_desk_the_monitor_and_the_chair_are_one_target(self):
        assert "row >= c.y - 1 && row < c.y + 4" in OFFICE

    def test_the_list_is_buttons_with_a_pressed_state(self):
        assert 'class="who-row' in CHAT and "<button" in CHAT
        assert "aria-pressed=" in CHAT
        assert "Office.pick(b.dataset.who)" in CHAT

    def test_a_run_event_never_moves_the_selection(self):
        """`at()` is what the crew calls. If it touched the selection, the
        pane would jump off the station somebody was reading."""
        at = OFFICE.index("    at(id, st, note) {")
        assert "chosen" not in OFFICE[at : OFFICE.index("\n    },", at)]

    def test_the_detail_pane_has_somewhere_to_live(self):
        assert 'id="who-detail"' in (HERE / "web.py").read_text()
        assert 'aria-live="polite"' in (HERE / "web.py").read_text()


class TestTheWindowSaysWhatIsMissing:
    def test_absent_timings_are_named_as_absent(self):
        assert "start not recorded" in CHAT
        assert "end not recorded" in CHAT

    def test_a_station_with_no_tool_calls_says_so(self):
        assert "No tool calls recorded for this station." in CHAT

    def test_a_capped_tool_list_says_what_it_is_showing(self):
        assert "last ${was.tools.length} of ${was.tool_calls}" in CHAT

    def test_a_finished_run_builds_the_room_from_the_record(self):
        replay = CHAT[CHAT.index("async function replay(") :]
        assert "Office.reset()" in replay[:900]
        assert "(r.crew || []).forEach" in replay[:900]

    def test_the_record_is_served_with_the_run(self):
        web = (HERE / "web.py").read_text()
        assert '"crew": crew.what_each_did(events_in(' in web


class TestWhatARunThatIsOverLooksLike:
    """Reading a finished run back used to leave the room exactly as the
    last reset left it: nine idle desks, an empty whiteboard and a suite
    that had "not run yet" on it."""

    def test_the_stale_note_is_not_shown_under_a_contradicting_state(self):
        """The Verifier's last words on an old log are "running the build
        and the suite". Printed under a desk the log shows as cut off, that
        is the office saying it is still running."""
        assert 's.state === "cut" || s.state === "never"' in CHAT

    def test_the_board_is_rebuilt_from_the_record(self):
        replay = CHAT[CHAT.index("async function replay(") :]
        assert "Office.board(r.items.map(" in replay[:2000]
        assert "Office.suite(" in replay[:2000]

    def test_the_suite_count_is_not_borrowed_from_the_baseline(self):
        """A run whose items never ran a suite has no count of its own, and
        showing the baseline figure as the result would be the before
        number wearing the after number's label."""
        replay = CHAT[CHAT.index("async function replay(") :]
        assert "r.results.map(x => x.tests_run).filter(n => n > 0)" in replay[:2000]

    def test_the_per_item_count_is_served(self):
        assert '"tests_run": r.tests_run,' in (HERE / "web.py").read_text()


class TestTheOneThingItCannotAttribute:
    def test_the_engineer_desk_says_whose_tool_calls_these_are(self):
        """Session passes one reporter into the item loop, named Engineer,
        so the Reviewer's and the Critic's tool calls are recorded against
        the Engineer. Fixing that means threading a station through
        orchestrate; saying so costs a sentence and is true today."""
        assert 'id === "Engineer" && (was.tools || []).length' in CHAT
        assert "Per-station attribution is" in CHAT
