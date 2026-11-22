---
name: dependency-upgrade
description: Raise a dependency across a major version and repair what it breaks. Use for framework and library upgrades where the API has changed.
command: /upgrade
task: Upgrade {what} and repair everything the new version breaks.
asks: which dependency, and to what version
---

# Upgrading a dependency across a major version

A major version is a promise that something you rely on has been removed. The
work is not the version number; it is finding what you were using that no
longer exists, and the compiler only tells you about some of it.

## Plan

Pin down what is actually in use before reading any release notes. A
migration guide describes every change in the library; only a fraction of
them touch this codebase, and that fraction is discoverable from imports
and call sites. Record the current version, the target, and how far apart
they are: two majors is two migrations, and doing them in one step means a
failure could belong to either.

Name the surfaces that fail silently rather than at compile time -
reflection, configuration naming classes as strings, service loader
entries, anything the build does not check - and the places a version is
pinned more than once: a second build file, a dependency management block,
a lockfile, a container image.

An item here is verified by the suite, not by the build. The parts that
break silently are exactly the parts a compiler does not see, and where
integration tests exercise the upgraded library they matter more than the
unit tests do.

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

