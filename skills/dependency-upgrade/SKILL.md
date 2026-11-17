---
name: dependency-upgrade
description: Raise a dependency across a major version and repair what it breaks. Use for framework and library upgrades where the API has changed.
---

# Upgrading a dependency across a major version

A major version is a promise that something you rely on has been removed. The
work is not the version number; it is finding what you were using that no
longer exists, and the compiler only tells you about some of it.

## Survey

Pin down what is actually in use before reading any release notes. A migration
guide describes every change in the library; only a fraction of them touch this
codebase, and the fraction is discoverable by reading imports and call sites.

Record the current version, the target version, and how far apart they are. Two
majors is two migrations, and doing them in one step means a failure could
belong to either.

Look for the parts that fail silently rather than at compile time: reflection,
configuration files naming classes as strings, service loader entries, anything
the build does not check.

Note whether the dependency appears in more than one place. A second build
file, a dependency management block, a lockfile and a container image can each
pin a version independently.

## Plan

One major version per item, in order. Skipping intermediate versions is
tempting and makes the failure impossible to attribute.

Raise the version first, as its own item, and let it break. The list of compile
errors is better evidence than any guess about what will break, and it costs
one build to get.

Then one item per cluster of errors that share a cause. Twenty call sites that
all changed the same way are one item; one call site that needs a decision is
another.

Deprecations that still work are not part of this. They are a separate task
and mixing them in makes the diff unreviewable.

## Engineer

Change the version, compile, and read the errors before touching anything else.

Where the new API offers a direct replacement, use it. Where it does not,
stop and report rather than inventing an approximation that compiles.

Resist the urge to modernise the code you are passing through. The reviewer of
this diff should see only what the upgrade required.

## Verify

Compiling is not enough for this kind of change, because the parts that break
silently are exactly the parts the compiler does not see. Run the suite.

If the project has integration tests that exercise the upgraded library, they
matter more here than the unit tests do.
