"""The one station that can see was never heard from, and the item shipped.

Corso C. The critic started the page, took both screenshots, read them,
judged them and wrote its verdict. Then:

    could not look at it: Expecting ',' delimiter: line 1 column 2911

`structured` parses the answer file with a bare `json.loads`, and the
reason string had an unescaped character two and a half thousand
characters in. The exception reached `_show_it`'s broad `except`, which
reported one line under the engineer and returned `None` - and `None`
from that station means "nothing to report", which is exactly what a
clean page looks like from `_judge`. No gate decision was recorded. The
item was accepted on the verifier, the inspector and the reviewer, and
the run said 1/1.

The run before it recorded three critic decisions and the one before that
four, so nothing in the pipeline was wrong. What was wrong is that a
verdict that was produced and lost could not be told apart from a page
with nothing wrong with it.

Three outcomes now, not two, and the third blocks delivery.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from drydock import critic, orchestrate
from drydock.critic import Verdict, look
from drydock.engines import EngineUnavailable, MalformedAnswer
from drydock.models import Item, Outcome
from drydock.policy import of


def item(**kw) -> Item:
    return Item(
        **{
            "id": 1,
            "title": "the page",
            "rationale": "r",
            "files": ["public/index.html"],
            "verify_with": "tests",
            "worth_looking_at": True,
            **kw,
        }
    )


class TestWhereItBroke:
    """The parse itself, pinned at the line that did it."""

    def test_a_malformed_answer_is_its_own_error(self, tmp_path):
        """Not EngineUnavailable: that means nothing was written and the
        machine may be at fault. This means the work was done and the
        answer was lost on the way out, which is worth one more ask."""
        assert issubclass(MalformedAnswer, RuntimeError)
        assert not issubclass(MalformedAnswer, EngineUnavailable)

    def test_it_carries_what_was_written(self):
        exc = MalformedAnswer("bad", '{"approved": tru')
        assert exc.text == '{"approved": tru'

    def test_the_parse_is_no_longer_bare(self):
        source = Path("src/drydock/engines.py").read_text()
        assert "payload = json.loads(out.read_text())" not in source
        assert "raise MalformedAnswer(" in source

    def test_the_exact_corso_c_payload_shape(self):
        """A reason string with an unescaped quote in it."""
        written = '{"approved": true, "reason": "the "card" reads well"}'
        with pytest.raises(ValueError):
            json.loads(written)


class TestTheThreeOutcomes:
    def test_approved(self):
        v = Verdict(looked=True, approved=True, reason="it is right", noticed=[])
        assert v.verified and v.approved and not v.failed

    def test_rejected(self):
        v = Verdict(looked=True, approved=False, reason="the table is cut", noticed=[])
        assert v.verified and not v.approved and not v.failed

    def test_error(self):
        v = critic._could_not("the answer was not readable")
        assert not v.verified
        assert not v.approved, "an error must never read as approval"
        assert v.failed

    def test_no_browser_is_still_an_absence_rather_than_an_error(self):
        """A machine that cannot take a screenshot has no such check, and
        holding every item against a check nobody can run would stop
        every run on such a machine. That is deliberate and stays."""
        v = Verdict(looked=False, approved=True, reason="no browser", noticed=[])
        assert v.verified, "this is an absent capability, not a lost verdict"


def _engine(monkeypatch, answers):
    """A critic engine that returns, or raises, what the test says."""
    calls = {"n": 0}

    class Fake:
        def __init__(self, **_):
            pass

        def structured(self, *a, **k):
            calls["n"] += 1
            nth = answers[min(calls["n"], len(answers)) - 1]
            if isinstance(nth, Exception):
                raise nth
            return nth, 0.11, 1

    monkeypatch.setattr(critic, "ClaudeCodeEngine", Fake)
    monkeypatch.setattr(
        critic, "take", lambda url, into, **k: [SimpleNamespace(width="desktop")]
    )
    return calls


class TestOneBoundedRecovery:
    def test_a_malformed_answer_is_asked_once_more(self, monkeypatch, tmp_path):
        calls = _engine(
            monkeypatch,
            [
                MalformedAnswer("bad json", '{"approved": tru'),
                {"approved": True, "reason": "it is right", "noticed": []},
            ],
        )
        verdict, spent = look("http://x", "d", "i", tmp_path)
        assert calls["n"] == 2, "it did not try again"
        assert verdict.verified and verdict.approved
        assert spent == pytest.approx(0.11), "only the second ask is paid for"

    def test_the_pictures_are_not_taken_again(self, monkeypatch, tmp_path):
        """The expensive half. Two browser launches to recover a parse
        error would cost more than the error."""
        shots = {"n": 0}

        def count(url, into, **k):
            shots["n"] += 1
            return [SimpleNamespace(width="desktop")]

        _engine(
            monkeypatch,
            [MalformedAnswer("bad", ""), {"approved": True, "reason": "ok"}],
        )
        monkeypatch.setattr(critic, "take", count)
        look("http://x", "d", "i", tmp_path)
        assert shots["n"] == 1

    def test_the_second_ask_says_what_went_wrong(self, monkeypatch, tmp_path):
        asked = []

        class Fake:
            def __init__(self, **_):
                pass

            def structured(self, scratch, system, prompt, shape, **k):
                asked.append(prompt)
                if len(asked) == 1:
                    raise MalformedAnswer("bad", "")
                return {"approved": True, "reason": "ok"}, 0.1, 1

        monkeypatch.setattr(critic, "ClaudeCodeEngine", Fake)
        monkeypatch.setattr(
            critic, "take", lambda url, into, **k: [SimpleNamespace(width="d")]
        )
        look("http://x", "d", "i", tmp_path)
        assert "could not be read" in asked[1]
        assert "could not be read" not in asked[0], "do not warn before it happens"

    def test_it_is_asked_at_most_twice(self, monkeypatch, tmp_path):
        calls = _engine(monkeypatch, [MalformedAnswer("bad", "")])
        verdict, _ = look("http://x", "d", "i", tmp_path)
        assert calls["n"] == 2, "bounded at one recovery"
        assert not verdict.verified
        assert not verdict.approved

    def test_a_missing_verdict_is_also_worth_one_more_ask(self, monkeypatch, tmp_path):
        """It answered in the right shape and left the verdict out."""
        calls = _engine(
            monkeypatch,
            [{"reason": "I looked"}, {"approved": False, "reason": "the table is cut"}],
        )
        verdict, _ = look("http://x", "d", "i", tmp_path)
        assert calls["n"] == 2
        assert verdict.verified and not verdict.approved
        assert "table is cut" in verdict.reason

    def test_a_verdict_missing_twice_is_an_error_not_an_approval(
        self, monkeypatch, tmp_path
    ):
        calls = _engine(monkeypatch, [{"reason": "I looked"}])
        verdict, _ = look("http://x", "d", "i", tmp_path)
        assert calls["n"] == 2
        assert not verdict.verified
        assert not verdict.approved

    def test_an_engine_that_cannot_run_is_not_retried(self, monkeypatch, tmp_path):
        """Nothing was written and nothing will be. Asking again spends a
        second failure."""
        calls = _engine(monkeypatch, [EngineUnavailable("no claude on PATH")])
        verdict, _ = look("http://x", "d", "i", tmp_path)
        assert calls["n"] == 1
        assert not verdict.verified
        assert not verdict.approved
        assert "could not run" in verdict.failed

    def test_a_first_time_answer_costs_one_ask(self, monkeypatch, tmp_path):
        calls = _engine(monkeypatch, [{"approved": True, "reason": "right"}])
        verdict, spent = look("http://x", "d", "i", tmp_path)
        assert calls["n"] == 1
        assert verdict.verified and verdict.approved
        assert spent == pytest.approx(0.11)


class TestTheGateReportsIt:
    def test_show_it_no_longer_returns_nothing_on_an_error(self, monkeypatch):
        """`None` means "nothing to report", which is what a clean page
        looks like. That is the whole defect."""
        source = Path("src/drydock/orchestrate.py").read_text()
        handler = source[
            source.index("except Exception as exc:  # noqa: BLE001 - the run") :
        ]
        assert "return Seen(" in handler[:700]
        assert "failed=" in handler[:700]

    def test_judge_keeps_errors_apart_from_refusals(self):
        import inspect as _i

        source = _i.getsource(orchestrate._judge)
        assert "if not answer.verified:" in source
        assert "unverified.append(answer.failed)" in source
        assert source.index("if not answer.verified:") < source.index(
            "elif not answer.approved:"
        )

    def test_judge_returns_the_unverified_list(self):
        import inspect as _i

        assert "return _with_the_usual_cause" in _i.getsource(orchestrate._judge)
        assert "refused_by, unverified" in _i.getsource(orchestrate._judge)


class TestDeliveryIsPrevented:
    def test_an_unverified_item_is_not_committed(self):
        import inspect as _i

        source = _i.getsource(orchestrate._one_item)
        block = source[source.index("if verdict.passed and unverified:") :]
        assert "here.discard()" in block[:900]
        assert "Outcome.BLOCKED" in block[:900]
        assert "visual verification could not be completed" in block[:900]

    def test_it_is_decided_before_the_commit(self):
        import inspect as _i

        source = _i.getsource(orchestrate._one_item)
        assert source.index("if verdict.passed and unverified:") < source.index(
            "here.commit("
        )

    def test_it_does_not_spend_another_engineer_attempt(self):
        """There is nothing for the engineer to fix, and another attempt
        would render the same page and lose the same verdict."""
        import inspect as _i

        source = _i.getsource(orchestrate._one_item)
        block = source[source.index("if verdict.passed and unverified:") :][:900]
        assert "return ItemResult(" in block
        assert "attempt + 1" not in block

    def test_the_error_is_reported_under_the_critic(self):
        import inspect as _i

        source = _i.getsource(orchestrate._one_item)
        block = source[source.index("if verdict.passed and unverified:") :][:900]
        assert 'on_gate(item, "critic", False' in block


class TestNothingElseMoved:
    def test_the_verifier_still_decides_first(self):
        import inspect as _i

        source = _i.getsource(orchestrate._one_item)
        assert source.index("verdict = verify") < source.index("report_card = look(")

    def test_the_inspector_still_refuses_on_its_own(self):
        import inspect as _i

        source = _i.getsource(orchestrate._one_item)
        assert 'refused_by = ["inspector"]' in source

    def test_the_reviewer_is_unchanged(self):
        import inspect as _i

        source = _i.getsource(orchestrate._judge)
        assert 'if name == "reviewer":' in source
        assert 'on_gate(item, name, answer["approved"], answer["reason"])' in source

    def test_a_clean_page_still_lands(self, monkeypatch, tmp_path):
        _engine(monkeypatch, [{"approved": True, "reason": "right", "noticed": []}])
        verdict, _ = look("http://x", "d", "i", tmp_path)
        assert verdict.approved and verdict.verified and not verdict.failed

    def test_a_bad_page_is_still_refused_as_a_refusal(self, monkeypatch, tmp_path):
        _engine(monkeypatch, [{"approved": False, "reason": "the table is cut"}])
        verdict, _ = look("http://x", "d", "i", tmp_path)
        assert not verdict.approved
        assert verdict.verified, "a real refusal is not an error"

    def test_the_single_item_path_is_untouched(self):
        import inspect as _i

        assert "if len(items) == 1:" in _i.getsource(orchestrate._work_a_wave)

    def test_the_stop_checks_are_untouched(self):
        source = Path("src/drydock/orchestrate.py").read_text()
        assert source.count("_stopping(should_stop)") >= 5

    @pytest.mark.parametrize("profile", ["fast", "balanced", "deep"])
    def test_the_attempt_budget_did_not_move(self, profile):
        p = of(profile)
        assert p.attempts >= 2 and p.revivals == 2

    def test_an_item_nobody_looks_at_is_unaffected(self):
        """The critic only runs when the item is visual. An unverified
        list is empty for everything else, so nothing else can be
        blocked by this."""
        import inspect as _i

        source = _i.getsource(orchestrate._judge)
        assert "if run.direction and by_eye:" in source
        assert Outcome.BLOCKED is not None  # the enum the block uses
        assert item(worth_looking_at=False).worth_looking_at is False
