# Drydock — Project Instructions

## Mission

Drydock is an **open-source, general-purpose AI coding harness** intended to take software engineering tasks from a clear request to a **verified, deliverable change**. It is not a website builder, a demo-only agent collection, or just a Claude Code wrapper.

Drydock should support backend, frontend, full-stack, infrastructure, and AI engineering work. LUMI and Nero are test fixtures/projects, not product requirements. The long-term product offers a CLI and a desktop interface using the **same core harness**. Provider flexibility matters, but do not claim engine parity without evidence.

This is also an engineering portfolio project for Applied AI / AI Infrastructure / Agent Engineering roles. The owner must be able to explain architectural decisions, agent loops, tool boundaries, safety controls, failure recovery, and benchmark methodology. Optimize for demonstrable engineering quality rather than the number of agents or features.

## Core engineering principles

1. **Correctness before speed.** Never report a task as successful unless the exact final integrated tree has passed required checks and the intended Git changes were actually committed/delivered.
2. **Protect user work.** Never discard, reset, clean, force-push, overwrite, or silently move uncommitted user changes. Ask for explicit approval before destructive actions. Check Git command exit codes and target branches.
3. **Bounded execution.** Set concrete time, attempt, and usage budgets for costly runs. Distinguish an enforced hard limit from an estimate or monitoring-only limit. Stop after the agreed limit; do not enter autonomous fix/test/retry loops.
4. **Evidence over claims.** Separate implemented, unit-tested, integration-tested, and demonstrated live capabilities. Report exact test commands, outcomes, commit IDs, and material limitations. Never describe mocked tests as end-to-end proof.
5. **Small changes.** Fix one evidenced blocker at a time. Do not add agents, abstractions, broad refactors, or performance optimizations without a specific problem and approval.
6. **Independent review.** Implementation and review should be separated. Prefer small branches, draft PRs, explicit acceptance criteria, independent review, and owner-approved merge.
7. **Safe test execution.** Deterministic CI tests must run without a Claude CLI installation, model credentials, network access, or paid LLM calls unless explicitly marked opt-in. Do not mask failures with unconditional skips or fake success.
8. **Honest security posture.** Unless isolation has been independently demonstrated, treat Drydock as a trusted-repository development tool, not a sandbox safe for hostile repositories or arbitrary untrusted code.
9. **Keep docs accurate.** README, CLI usage, tests, CI, run reports, and PR evidence must match observable behavior.

## What a completed task means

A task is **complete** only when its acceptance criteria are satisfied; the produced code is in the intended branch/commit; the final integrated state passes required verification; and the report clearly states what was run, what passed or failed, elapsed time, estimated or actual usage (as available), risks, and a reproducible reference. Partial completion must be labeled partial.

## Priorities

1. **Reliable core:** final-state verification, Git error handling, safe resume/rollback, bounded retries/timeouts, and trustworthy CI.
2. **Real workloads:** reproducible small and medium multi-file tasks across different project types; track success and failure without hiding either.
3. **Harness observability:** inspectable agent/tool traces, decisions, context, timing, cost, and failure reasons.
4. **Open-source CLI quality:** documented setup, deterministic acceptance fixture, license, examples, and honest benchmarks.
5. **Desktop application:** user-friendly frontend built on the same reliable execution core.

Do not treat phases as permission to implement new work automatically. Ask the owner to approve scoped tasks.

## Collaboration protocol

- **Owner:** defines product goals, approves meaningful scope changes and merges.
- **Claude Code:** primary implementation agent; works in an approved branch/worktree; runs appropriate checks; supplies a draft PR with evidence.
- **Codex/ChatGPT:** independent reviewer/advisor; reads diff and verification evidence, identifies actionable issues, and distinguishes blockers from optional suggestions. Review is read-only unless the owner separately assigns implementation.
- Use Git branches and PR comments as the durable collaboration record; do not assume the agents can automatically message each other.
- Maximum **two** fix/review cycles per task without renewed owner approval.
- Do not concurrently edit the same worktree. Do not automatically merge or launch new benchmarks.

### PR checklist

- [ ] Approved scope and acceptance criteria linked
- [ ] Changed files and rationale summarized
- [ ] Relevant tests run, with command/output and exclusions
- [ ] Required checks run on the **final integrated tree**, not just isolated workers
- [ ] Git operations validated; no user edits lost
- [ ] Costs/time/attempts and limits reported accurately
- [ ] Risks, unresolved issues, and rollback path stated
- [ ] Independent review findings addressed or explicitly deferred with owner approval

## Decision and communication style

Be concise and technical. Prefer: **observed evidence → impact → smallest proposed action → acceptance criteria → risks → stop for approval**. If a test fails, identify the first material blocker rather than starting open-ended changes. State uncertainty plainly; never claim a capability is proven simply because it exists in code.
