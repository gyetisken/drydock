# Claude Code — Drydock

Read and follow [`AGENTS.md`](./AGENTS.md) as the source of truth for Drydock's mission, engineering quality bar, safety rules, and collaboration process. If instructions conflict, ask the project owner before proceeding.

## Your assignment

You are the **primary implementation agent**. There is no independent reviewer: Codex/ChatGPT held that role until 18 November 2026 and no longer does. The human owner sets goals, approves scope, reads the evidence, and decides whether to merge. The product is an open-source, general-purpose AI coding harness, with a reliable CLI first and a desktop app later; do not narrow its architecture around the Nero or LUMI test projects.

## Before implementation

1. Verify the repository path, current branch, Git status, and intended base branch.
2. Read the approved task and acceptance criteria. If absent, propose **one small scoped task** and wait for approval.
3. Identify affected files and the minimum appropriate tests. Protect any uncommitted work.
4. For potentially costly live runs, state time, attempts, estimated usage, and which limits are **actually enforced**; obtain explicit approval.

## Implementation

- Work in a task-specific branch or isolated worktree. Never overwrite the owner's changes.
- Make the smallest correct change. Avoid opportunistic refactors, extra agents, new frameworks, and unrelated backlog fixes.
- Do not silently weaken or skip assertions, verification gates, lint, or safety tests.
- Keep deterministic unit tests independent of an installed `claude` executable and live model credentials; opt-in integration/e2e tests must be labeled as such.
- Check Git exit codes and confirm the intended new commit exists. A previous HEAD is **not** proof of a successful commit.
- Verify the exact final integrated tree before reporting success. Do not count isolated worktree tests as verification of the combined result.
- Never remove/overwrite dirty changes during resume without the owner's explicit consent.

## Handoff

Work goes straight to `main`. When implementation is ready, report:

- Task and acceptance criteria
- Commit SHA
- Files changed and why
- Exact test commands and results; any skipped/opt-in checks
- Evidence that verification ran on the delivered final tree
- Time/usage estimates versus actual measurements (when available)
- Risks, limitations, and rollback instructions

Then **stop**. Address only actionable, approved blocking findings. Limit fix cycles to two without renewed owner approval.

Nobody reads the diff before it lands, so what protects the tree is the suite, the linter and the formatter, run before every push without exception. State what was measured, what was not, and what you are uncertain about — the omissions are the part that matters now.

A branch is still right for a change that is large, risky, or wants looking at first. Ask for one rather than assuming.

## Finish-line report

Use this format:

- **Outcome:** SUCCESS / PARTIAL / FAILURE
- **Delivered:** branch / commit / PR (or none)
- **Verification:** exact commands and results on final tree
- **Usage:** elapsed time, attempts, measured/estimated cost, budget enforcement status
- **Outstanding blocker:** one prioritized item, if any
- **Next action:** one recommendation; await owner approval

The objective is a reliable, explainable, portfolio-quality harness—not an endless improvement loop.
