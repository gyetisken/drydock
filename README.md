# drydock

A crew of agents changes a codebase, and proves the result still works.

The hard part of handing work to a model is not getting it to write code. It
is knowing whether what came back is real. drydock answers that
mechanically: every change is one commit, every commit is checked by four
gates before it is allowed to stay, and anything that fails one is reverted
before the next change begins. Nothing lands on your default branch, and
nothing lands at all by being asserted.

It runs locally and drives the Claude Code CLI you are already signed in to.

## The problem it is built around

An agent that edits a repository can make the suite green four ways:

1. Fix the code. The only one anybody wants.
2. Change the test to match the bug.
3. Delete the test.
4. Add `@Disabled`, `skip`, `xfail`, or `return` at the top of the body.

Three of those look identical to the first in a terminal, in a diff summary,
and in a chat reply saying "all tests pass". So the suite is counted before
the work starts and counted again after, per item, and an item that leaves it
smaller is reverted. Silencers are matched in the diff directly. It is not a
prompt asking the model to behave; it is arithmetic over two numbers.

## The crew

Nine stations. Four of them can refuse, and two of those are code rather
than a model.

```mermaid
flowchart LR
  A[Analyst<br/><i>reads the repo</i>] --> B[Architect<br/><i>picks the stack</i>]
  B --> D[Designer<br/><i>decides how it looks</i>]
  D --> P[Planner<br/><i>writes the items</i>]
  P --> E[Engineer<br/><i>writes the code</i>]
  E --> V{Verifier<br/><b>code</b>}
  V --> I{Inspector<br/><b>code</b>}
  I --> R{Reviewer<br/>reads the diff}
  R --> C{Critic<br/>looks at the page}
  C --> L[(commit)]
  V -. sends it back .-> E
  I -. sends it back .-> E
  R -. sends it back .-> E
  C -. sends it back .-> E
  E -. asks .-> P
```

| Station | What it does | Can refuse |
|---|---|---|
| **Analyst** | Reads the repository and reports what is there | |
| **Architect** | Chooses the toolchain and the shape | |
| **Designer** | Decides the palette, type and composition before anything is built | |
| **Planner** | Turns it into items: as few as the work honestly needs, each one a working state | |
| **Engineer** | Writes one item. Can stop and ask the planner a question rather than guess | |
| **Verifier** | Builds it and runs the suite, and compares the test count to the baseline | ✓ code |
| **Inspector** | Reads the diff for silenced tests, weakened assertions, committed secrets, and files whose bytes do not match their extension | ✓ code |
| **Reviewer** | Reads the diff against what the item said it would do | ✓ |
| **Critic** | Renders the page in a headless browser and looks at it, at phone and desktop width | ✓ |

The Critic exists because a page can pass every test and still be wrong. It
has caught an hours table that rendered seven day names and no times: the
markup was correct, the times were near-black on a black ground, and no test
can see that.

## Two things it does that other tools do not

**It reverts.** A change that fails verification is undone before the next
one starts, so the repository is never left in a state nobody checked. Other
agents report the failure and leave the files where they are.

**It detects a weakened test.** Not "it reviews the diff" — it counts. If an
item removes a test, adds a `skip`, or turns an assertion into a tautology,
that is matched in the diff and the item goes back, whatever the suite says.

## What a finished run leaves behind

A branch — `drydock/<run id>` — with one commit per item, and a draft pull
request whose body is the evidence rather than a summary:

- the test count before any of this, and now
- each item that landed, with its commit
- what each of the four gates said about each commit
- what was planned and did not land, and why

The diff is the description of the change. The body is the part a reviewer
cannot get from the diff.

## Running it

Needs Python 3.13, [uv](https://docs.astral.sh/uv/), and the
[Claude Code CLI](https://claude.com/claude-code) signed in. `gh` as well, if
you want pull requests opened.

```bash
uv sync
uv run drydock app          # http://127.0.0.1:8400
```

Then say what you want in plain language. There are commands — `/new`,
`/do`, `/fix`, `/ask`, `/audit`, `/migrate`, `/upgrade`, `/check` — but you
do not have to type them. What you write is routed by reading it, with a
regular expression rather than a model call.

The same thing from a terminal, one stage at a time:

```bash
uv run drydock survey --repo ~/code/thing --task "Add a /health endpoint"
uv run drydock plan         # the items, to read before anything runs
uv run drydock run          # work them
uv run drydock show         # what happened
```

## Confinement

A worker is started with a `PreToolUse` hook that resolves the real path of
every file it touches and blocks anything outside the repository it was
given. This is not the permission list: `--allowedTools` pre-approves, it
does not restrict, and a deny pattern broad enough to cover the parent
directory also covers the repository. The hook was written after an Analyst,
given an empty folder, read drydock's own source to find something to report.

## Skills

A skill is one Markdown file with sections addressed to individual stations,
so the planner and the engineer are given different parts of it. They carry
the kind of knowledge that does not come from reading the repository.

- `greenfield` — building from nothing, with tests from the first commit
- `web-design` — what makes a page look made rather than generated
- `migration` — moving a codebase from one thing to another
- `dependency-upgrade` — raising a version without breaking what used it

```bash
uv run drydock skills
```

## Tests

```bash
uv run pytest -q
```

249 of them, and they are mostly about failures that looked like successes: a
green suite whose test count could not be read, a finished item thrown away
for want of a report, a design decision that never reached the engineer who
writes the CSS, a resumed run that quietly dropped the skills it was working
under.

## Built with

Python 3.13 · FastAPI · server-sent events · the Claude Code CLI as the
worker · git worktrees for items that can run at the same time · headless
Chrome for the Critic · no database.
