---
name: greenfield
description: Build something new from nothing - a service, a site, a tool, a library - with tests from the first commit. Use when the repository is empty or holds only a README.
command: /new
task: Build {what}. Tests from the first commit, and nothing is finished until they pass.
asks: what should be built
---

# Starting from nothing

Everything else this crew does is verified against a suite that already exists.
Here there is nothing to verify against, so the first thing built is the thing
that will do the verifying. A project whose tests arrive at the end has no way
of knowing when it broke.

## Survey

There is little to survey and that is worth saying plainly rather than
inventing findings. Report what is actually present: the README if there is
one, any configuration already committed, the language and tooling if they can
be determined, and what the task statement specifies.

What matters most is what the task does not say. List the decisions that have
to be made and have not been: storage, authentication, the shape of the
interface, what counts as done. Those are the findings here.

## Plan

The first item is the skeleton that proves the loop works: project file, one
trivial function, one test for it, and a command that runs the test and passes.
Nothing after this is verifiable until that exists.

Then one feature per item, each with its test in the same item. A plan that
puts the tests in a later item will reach that item with nothing to test
against and no way back.

Order by what other things depend on. The data shapes before the logic that
uses them, the logic before the interface that exposes it.

Leave deployment, packaging and documentation to the end, and say so, so that
nobody mistakes an unfinished thing for a finished one.

## Engineer

Write the test in the same item as the code, and make it fail before making it
pass. A test written after the fact tends to assert what the code does rather
than what it was supposed to do.

Keep the first version small enough that it works. Something that does one
thing end to end is a foundation; a half-built thing with six features is a
pile.

Do not invent requirements. Where the task is silent, choose the plainest thing
that works and report the choice rather than burying it.

## Verify

The bar is that the tests exist, that they run, and that they pass. All three:
a suite that passes because it contains nothing is the failure this skill is
written to prevent.

Watch the count from the first item onwards. It should only ever go up.
