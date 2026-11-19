"""How much ceremony a job gets.

Every number that decides how hard this program works was a constant
somewhere in the module that happened to need it: how many turns the
engineer gets, how long before it is stopped, how many attempts an item is
allowed, whether the reviewer reads the diff, whether anybody looks at the
page. Six files, no single place to see them, and no way to say "this is a
one-line fix, do not spend forty minutes on it".

So they live here, together, as one object that is decided once and then
carried. Nothing is cleverer than it was; it is the same decisions in one
place, where they can be chosen rather than inherited.

Three of them cannot be chosen away, at any profile:

  - the inspector, which counts tests and matches silenced ones, weakened
    assertions and committed credentials
  - the confinement hook, which keeps a worker inside the repository
  - the commit and revert, which is what makes a failed item cost nothing

Those are not ceremony. They are the reason the output can be believed, and
a profile that switched them off would be a different program.
"""

import re
from dataclasses import dataclass, replace

FAST = "fast"
BALANCED = "balanced"
DEEP = "deep"

# When somebody is looked to about what the page looks like.
NEVER = "never"
AT_THE_END = "at the end"
EVERY_ITEM = "every item"


@dataclass(frozen=True)
class Policy:
    """What this job is worth spending."""

    profile: str = BALANCED

    # How the work is cut up. The planner is told these as a range rather
    # than a number, because the right answer depends on the work and the
    # wrong answer in either direction is expensive: too many items and
    # every one carries the fixed cost of being checked, too few and an
    # item is too large for one sitting.
    fewest_items: int = 4
    most_items: int = 7

    # What one engineer gets for one item.
    turns: int = 60
    minutes: float = 12.0
    # A retry has more to do than the attempt before it.
    retry_minutes: float = 18.0

    # How many times an item may be tried again after being sent back, and
    # how many times a worker that was taken away may be replaced. The
    # second is not a retry: nothing was learned, so it does not count.
    attempts: int = 2
    revivals: int = 2

    # Whether the reviewer reads the diff against the item. The one thing a
    # profile may genuinely turn off, because the verifier and the
    # inspector both still run and both are code.
    read_the_diff: bool = True

    # When the page is looked at. `EVERY_ITEM` is not every item in
    # practice: an item the planner marked as not worth looking at, or
    # whose diff touches nothing visible, is still skipped.
    look_at_it: str = EVERY_ITEM

    # Whether an item verified by its tests must also build. Off only where
    # the two commands are the same thing.
    build_as_well: bool = True

    @property
    def say(self) -> str:
        """One line, for the record and for whoever is watching."""
        looks = {
            NEVER: "nobody looks at the page",
            AT_THE_END: "the page is looked at once, at the end",
            EVERY_ITEM: "the page is looked at as it is built",
        }[self.look_at_it]
        return (
            f"{self.profile}: {self.fewest_items}-{self.most_items} items, "
            f"{self.attempts} attempts each, "
            f"{'the diff is read' if self.read_the_diff else 'no diff review'}, "
            f"{looks}"
        )


PROFILES = {
    # Small, low-risk work: a page, a prototype, a fix somebody is waiting
    # on. Few items, because each one costs three or four minutes of being
    # checked whatever it contains. The diff is not read - the verifier
    # builds it and runs its tests, the inspector reads it for the things
    # that are checked by matching rather than by judgement - and somebody
    # looks at the finished thing once rather than at every step toward it.
    FAST: Policy(
        profile=FAST,
        fewest_items=2,
        most_items=3,
        attempts=2,
        read_the_diff=False,
        look_at_it=AT_THE_END,
    ),
    # What this program did before there were profiles. Kept identical on
    # purpose: a default that changes under somebody is not a default.
    BALANCED: Policy(profile=BALANCED),
    # Work where being wrong is expensive: authentication, money, a
    # migration, anything that touches data somebody cannot get back.
    DEEP: Policy(
        profile=DEEP,
        fewest_items=4,
        most_items=12,
        turns=80,
        minutes=18.0,
        retry_minutes=25.0,
        attempts=3,
        read_the_diff=True,
        look_at_it=EVERY_ITEM,
    ),
}


def of(profile: str | None) -> Policy:
    """The policy for a named profile, or the default for anything else."""
    return PROFILES.get((profile or "").strip().lower(), PROFILES[BALANCED])


# Work that is not allowed to be done cheaply, however it was asked for.
#
# Narrow on purpose. Every production coding agent makes a person choose
# between a fast path and a planned one - Factory's Spec Mode, Cline's Plan
# mode, Aider's architect - and none of them classifies automatically,
# because classifying from a sentence is guessing from the weakest signal
# anybody has. This does not try to be a classifier. It only refuses to let
# a handful of specific, nameable kinds of work take the cheap road.
#
# The asymmetry is the whole argument, and it is not symmetrical in cost:
# reading a one-line fix too carefully wastes twenty minutes, and treating
# a migration as a one-line fix loses data. So this only ever raises, it
# only fires on words that name the work rather than describe it, and what
# it did is said out loud.
RISKY = (
    (
        "a migration",
        re.compile(
            r"\b(migrat(e|ion|ing)|backfill|re-?index|"
            r"(alter|drop|rename)\s+(table|column|index)|"
            r"schema\s+(change|update|migration)|"
            r"(add|remove|change)\s+a?\s*(column|table|constraint))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "who is allowed in",
        re.compile(
            r"\b(auth(entication|orisation|orization|z|n)?|login|log\s?in|"
            r"sign\s?(in|up)|session\s+(token|cookie)|permission|"
            r"access\s+control|rbac|oauth|jwt|password\s+(reset|hash)|"
            r"api\s+key|credential|secret)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "money",
        re.compile(
            # Not `price`. A price shown on a card is a number on a page;
            # the coffee site this was first tried on says "fiyat" three
            # times and handles no money at all. What is meant here is
            # money moving.
            r"\b(payment|billing|invoice|refund|checkout|stripe|"
            r"charge\s+(the|a|their)|take\s+(a\s+)?payment|"
            r"card\s+details|subscription\s+(plan|billing))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "removing data",
        re.compile(
            # Not `file`. A deleted source file is in git and the item that
            # deleted it is one revert away; what is meant here is the kind
            # of removal nothing gives back.
            r"\b(delete|remove|purge|truncate|wipe|drop)\b[^.]{0,40}?"
            r"\b(data|record|row|user|account|customer|table|"
            r"history|upload|backup)s?\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class Raised:
    """Whether this work has a floor under it, and what put it there."""

    floor: str
    why: str

    def __bool__(self) -> bool:
        return bool(self.floor)


def floor_for(task: str) -> Raised:
    """The least ceremony this work may be done with.

    Empty when nothing in the task names one of the few kinds of work that
    cannot be done cheaply. It says what it matched, because a floor nobody
    can see is a floor nobody can argue with.
    """
    said = (task or "").strip()
    for what, pattern in RISKY:
        found = pattern.search(said)
        if found:
            return Raised(
                DEEP,
                f'this touches {what} - "{_tidy(found.group(0))}"',
            )
    return Raised("", "")


def _tidy(said: str) -> str:
    return re.sub(r"\s+", " ", said).strip()[:60]


def at_least(policy: Policy, floor: str) -> Policy:
    """Raise a policy to a floor, keeping anything already stronger.

    Some work is not allowed to be done cheaply however it was asked for.
    Lowering is never automatic - a person may always ask for less, and is
    told - but raising is, because the cost of being wrong about a
    migration is not symmetrical with the cost of twenty extra minutes.
    """
    # No floor is no raise. Without this, an empty floor reads as BALANCED
    # through `.get(floor, 1)` and quietly *lowers* a job somebody asked to
    # have done fast - the one thing this function says it never does. It
    # only showed when something started passing "" for "nothing raised
    # it", which is the honest way to say that.
    if not floor:
        return policy
    ranked = {FAST: 0, BALANCED: 1, DEEP: 2}
    if ranked.get(policy.profile, 1) >= ranked.get(floor, 1):
        return policy
    return of(floor)


def as_told(policy: Policy, **changes) -> Policy:
    """A policy with named changes, for a caller who knows better."""
    return replace(policy, **changes)
