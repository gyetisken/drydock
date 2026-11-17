"""The reviewer must fail closed.

It is the last gate before a change is kept, and the one failure it must never
have is being read as approval when it did not actually answer.
"""

from drydock.reviewer import _verdict


def test_an_approval_is_an_approval():
    v = _verdict({"approved": True, "reason": "does the item", "noticed": []})
    assert v["approved"]


def test_a_missing_verdict_is_not_approval():
    assert not _verdict({})["approved"]
    assert "did not return a verdict" in _verdict({})["reason"]


def test_a_reason_without_a_verdict_is_still_not_approval():
    v = _verdict({"reason": "looks fine to me", "noticed": []})
    assert not v["approved"]


def test_noticed_things_are_carried_without_blocking():
    v = _verdict({"approved": True, "reason": "ok", "noticed": ["the README is stale"]})
    assert v["approved"]
    assert v["noticed"] == ["the README is stale"]
