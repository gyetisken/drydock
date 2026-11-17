---
name: migration
description: Move a codebase from one framework, library, language level or API to another without losing behaviour. Use for any "from X to Y" change where the old and new sides can be told apart.
command: /migrate
asks: what you are migrating from and to
task: Migrate {what}. Nothing that worked before may stop working, and nothing that was being checked may stop being checked.
---

# Migration

Every migration is the same shape wearing different clothes. Something old and
something new express the same intent differently, and the work is moving every
expression across without changing what any of them mean.

The danger is never that it breaks. A migration that breaks is a migration that
gets fixed. The danger is that it appears to succeed: the build is green, the
diff looks right, and something that used to be checked is no longer being
checked by anything.

## Survey

**Find the number that would notice.** Before touching anything, find the count
that would drop if the migration quietly lost something, and record it. In a
test suite that is the number of tests that run. In an API it is the number of
routes served. In a schema it is the number of records that round-trip. If no
such number exists, the first item of the plan is to create one, because
without it there is nothing to verify against and every later check is an
opinion.

Record it per unit — per class, per module, per file — not only as a total. A
total hides a loss in one place behind a gain in another.

**Find every surface, including the ones that are not named after the thing.**
Search for the old API by what it imports and what it calls, not by filename.
Helpers, fixtures, base classes and utilities use the old API too and are the
ones missed by anything that works from a naming pattern.

**Find the compatibility layer.** Most migrations ship one: a shim, a bridge, a
vintage engine, a legacy flag, a polyfill, a deprecated-but-working alias. It
is the single most useful thing in the migration and the single most dangerous.
Useful, because it lets the old and new sides run side by side so the work can
be done in pieces. Dangerous, because while it is present, code nobody has
migrated still works, and the suite cannot tell you how far along you are.

**Find the second build file.** A Gradle build beside a Maven one, a
`requirements.txt` beside a `pyproject.toml`, a Dockerfile that pins its own
version. Each has its own dependency list, and a migration that updates one of
them is half a migration.

**Find out whether the runner can even see the new thing.** A test runner, a
loader or a bundler too old to discover the new format will report success
having done nothing at all. Establish the version in use and whether it
supports the target, before anything else is planned.

## Plan

**Make the measuring instrument honest first.** Pin the runner, the loader, the
version that can actually see both sides. Until that is done, every green build
is meaningless, and a plan that puts this anywhere but first has every item
after it resting on nothing.

**Bring the compatibility layer in early and take it out last.** Adding it is
what lets the suite keep passing while the work is in pieces. Removing it is
the item that proves the migration finished: anything nobody converted stops
working at that moment, which is exactly what you want to happen while someone
is watching.

**Separate the mechanical from the judged, and do the mechanical first.** Work
that cannot change behaviour — expanding wildcard imports into explicit ones,
renaming a symbol with no semantic difference, reformatting — is verified by
compiling. Doing it first also makes the rest legible, because afterwards each
file states plainly what it actually depends on.

**Convert the things that are depended on before the things that depend on
them.** Helpers before their callers, base classes before subclasses, shared
fixtures before the tests that use them. The other order means every item
breaks the ones already done.

**Give each thing with no mechanical equivalent its own item.** Where the old
API and the new one differ in behaviour rather than spelling, the conversion is
a decision, not a substitution. One decision per item means that when an item
fails, the failure points at one decision instead of twelve.

**Order by blast radius, not by convenience.** The first items should be the
ones whose failure is cheapest to understand.

## Engineer

**The silent trap is an API that still compiles and means something else.**
This is the failure mode worth slowing down for, and it has three common forms:

- *Arguments that reorder.* The old call and the new call take the same types
  in a different order. Where the types differ the compiler catches it; where
  they are all the same type it compiles and asserts something else entirely.
  A blanket find-and-replace breaks loudly in some files and silently in
  others, and only the loud ones get looked at.
- *Annotations, decorators and attributes that are simply ignored.* The new
  framework does not recognise the old marker. It does not complain; it does
  nothing. The setup never runs, the cleanup never runs, the rule never
  applies, and every test passes.
- *Replacements that look equivalent and are not.* The new API covers a
  narrower scope, or catches later, or no longer interrupts. Read what the
  replacement actually guarantees rather than matching it by name.

**Never convert something by removing the part that was failing.** Deleting an
assertion, skipping a case, loosening a check or catching and swallowing makes
the suite green by making it blind. If a case genuinely cannot be expressed on
the new side, say so and leave it failing — an honest red is worth more than a
green that lies.

**Leave the behaviour alone.** A migration is not a refactor and not an
upgrade. Improvements noticed along the way are worth reporting and are not
worth doing in the same change, because the moment the diff contains both, the
migration can no longer be verified by the thing that was supposed to verify
it.

### Traps worth knowing, by ecosystem

These are examples of the three forms above, not the list. The point of
reading them is to recognise the shape when it appears somewhere else.

- **JUnit 4 to 5.** `assertEquals(message, expected, actual)` becomes
  `assertEquals(expected, actual, message)` — reordered, and silent when all
  three are objects. `@Rule` and `@ClassRule` are ignored by Jupiter entirely.
  `@Test(expected=X)` accepted the exception from anywhere in the method;
  `assertThrows` only covers the lambda. `@Test(timeout=N)` becomes
  `assertTimeoutPreemptively`, not `@Timeout`, which lets the body finish
  first and so cannot stop a genuine hang. `TemporaryFolder` is not `@TempDir`.
  Surefire below 2.22 cannot discover Platform tests and reports success
  having run none.
- **Python 2 to 3.** Integer division, dict views that are no longer lists, and
  implicit string/bytes coercion all change meaning without changing syntax.
- **Spring Boot 2 to 3.** Every `javax.*` import becomes `jakarta.*`; a
  dependency that still ships `javax` classes keeps compiling and fails at
  runtime.
- **JavaScript to TypeScript.** `any` converts a file without migrating it, and
  a build that does not fail on implicit `any` will not tell you which files
  were only nominally done.
- **Callbacks to promises, or sync to async.** An un-awaited call returns a
  promise that is truthy, so a condition on it is always true and an error
  inside it is never seen.
- **Database or schema migrations.** A nullable column filled by a default is
  not the same as one filled from the old data; row counts match either way.

## Verify

**Colour is not the check. The count is.** A green run that executed fewer
units than the baseline recorded means the migration lost something, silently,
which is worse than a failure — a failure is visible.

Compare per unit where the baseline has per-unit numbers. Something that
quietly stops being expanded — a parameterized class, a generated set, a
data-driven table — drops its count by a multiple, and a total can hide it
behind a gain somewhere else.

**A suite that runs zero and passes has failed.** Treat an empty run as a
failure, always, no matter what the build says.

**The migration is finished when the compatibility layer is gone and the count
still holds.** Until then it is in progress, however complete the diff looks.
