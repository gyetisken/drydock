---
name: junit4-to-junit5
description: Move a Java test suite from JUnit 4 to JUnit 5 without losing a test. Use when a project depends on junit:junit 4.x and wants Jupiter.
applies_to: [Java, Maven, Gradle]
command: /migrate-junit
task: Migrate the test suite from JUnit 4 to JUnit 5. Every test must still run and pass.
---

# JUnit 4 to JUnit 5

The danger in this migration is not that it breaks. It is that it appears to
succeed. Two separate mechanisms will report a green build while running fewer
tests than before, and one of them runs no tests at all.

## Survey

Count before you plan. The number of tests the suite runs today is the only
thing that will tell you later whether the migration lost any, so record it
per class, not just as a total.

Then find each of these, because each one is a different kind of work:

- `@RunWith` — every runner needs its own answer. `Parameterized` has no
  mechanical equivalent in Jupiter and the class has to be restructured.
- `@Rule` and `@ClassRule` — Jupiter ignores these annotations entirely. A
  field left annotated does not fail to compile; it silently does nothing.
- `@Test(expected = ...)` and `@Test(timeout = ...)` — both attributes are
  gone, and both replacements change behaviour rather than syntax.
- `@Before`, `@After`, `@BeforeClass`, `@AfterClass` — renamed, and the class
  level ones also change when they run under a shared test instance.
- Assertion imports, and specifically whether they are wildcards. A wildcard
  import hides which overloads a file actually depends on.
- Helper classes with no `@Test` in them. They import JUnit assertions too and
  are easy to miss when migrating by filename pattern.
- Whether a second build file exists. A Gradle build alongside Maven has its
  own dependency list and its own test runner configuration.

## Plan

Make the runner honest first. Pin an explicit surefire version before anything
else: an old surefire cannot discover JUnit Platform tests and reports BUILD
SUCCESS having run none. Until that is pinned, every later verification is
meaningless.

Add the vintage engine early and remove it last. With both engines present the
suite keeps running while files are migrated one at a time. Removing vintage is
what proves the migration finished: while it is there, a file nobody converted
still runs and looks fine.

Separate the mechanical from the judged, and do the mechanical first while
still on JUnit 4. Expanding wildcard imports into explicit ones changes nothing
and can be verified by compiling. It also makes the next step legible, because
now each file states which assertions it uses.

Migrate the helpers before the tests that call them.

Give anything that has no mechanical equivalent its own item: parameterized
classes, rules, timeouts, expected exceptions. When one of those fails, the
failure should point at one decision.

## Engineer

The argument order trap is the one that matters. JUnit 4 is
`assertEquals(message, expected, actual)`; Jupiter is
`assertEquals(expected, actual, message)`. When all three are objects, the call
compiles after the import swap and asserts something else entirely. When the
types differ it fails to compile. So a blanket find-and-replace breaks loudly
in some files and quietly in others, and only the loud ones get noticed.

Read each assertion that carries a message. Move the message to the end.

`@Test(expected = X.class)` becomes `assertThrows`, and the two are not the
same: JUnit 4 accepts the exception from anywhere in the method including
setup, while `assertThrows` only covers the lambda. Put only the call that
should throw inside it.

`@Test(timeout = N)` becomes `assertTimeoutPreemptively`, not `@Timeout`.
Jupiter's `@Timeout` lets the body finish and then fails, so a test that can
genuinely hang will hang the build instead of failing in N milliseconds.

`TemporaryFolder` is not `@TempDir`. The rule hands back an object with
`newFile(name)` on it; the annotation injects a directory. Any call to
`newFile` has to be rewritten to create the file.

Do not convert a test by deleting the part that was failing.

## Verify

A green suite is not the check. The check is the count: if fewer tests ran than
the baseline recorded, the migration lost tests, and it lost them silently,
which is worse than a failure.

Compare per class where the baseline has per-class numbers. A parameterized
class that quietly stops being parameterized drops its count by a multiple and
the total can hide it if another class gained tests.
