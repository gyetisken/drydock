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

## Plan

How the work is cut up is not this skill's to decide. The planning rules
you were given already say it - one item when the job is one cohesive
piece, several when the pieces can genuinely fail on their own and be
worked on at the same time - and they outrank anything here. What
follows is what is particular about building from nothing, not a
different way of splitting.

**Tests arrive with the code that they test, in the same item.** A plan
that puts the tests in a later item reaches that item with nothing to
test against and no way back. Whatever the first item is, it ends with a
command that runs a suite and passes.

**The .gitignore belongs in the first item, before anything is
installed.** A package manager run in a repository with no ignore file
puts every downloaded dependency into the first commit - tens of
thousands of files nobody wrote, in a history where they cannot be
reviewed and cannot be removed without rewriting it. It costs one line
in the item being written anyway, and it has to exist before the
install, not after.

**Every page exists for somebody with a question. Answer the question.**
This is the failure that passes every test and is still wrong, and
nothing in the verification can catch it.

A status derived from data is an addition to the data, never a
replacement for it. "3 unread" does not replace the list. "Last updated
2 hours ago" does not replace the content. Whenever something rendered
is computed rather than written, ask what the visitor came for and make
sure the page still contains it.

That is a rule about not *removing* what somebody came for. It is not a
licence to add machinery: if the request did not ask for something
computed, the plainest page that answers the question is the answer, and
a thing recomputed at runtime is a thing to write, test, review and keep
working.

Order by what other things depend on: the data shapes before the logic
that uses them, the logic before the interface that exposes it.

Leave deployment, packaging and documentation to the end, and say so, so
that nobody mistakes an unfinished thing for a finished one.

## Engineer

A suite that passes because it contains nothing is the failure this skill
exists to prevent. The tests have to exist, to run, and to pass - and the
count only ever goes up from the first item onwards.

Write the test in the same item as the code, and write it before the code it
covers - then run that one test and watch it fail. A test written after the
fact tends to assert what the code does rather than what it was supposed to
do, and one that has never failed has not been shown to test anything.

That is the one test, not the suite. Running the whole suite afterwards to
show it passes is somebody else's job and is done for you either way.

Keep the first version small enough that it works. Something that does one
thing end to end is a foundation; a half-built thing with six features is a
pile.

Never improvise an asset. A hand-written bitmap named `.jpg` is not a
photograph; it is a lie that passes a build. The same goes for a font
licence and an API key: if an item needs something this process cannot
produce, the item is not done - say so and leave a placeholder that is
obviously a placeholder.

Referencing somebody else's is a different thing and is allowed. A
photograph licensed for this and fetched from a real source by URL was not
improvised, and a page with the right one on it is a different page. Give
it an aspect ratio so nothing moves when it arrives, a real `alt`, and a
ground colour underneath for when it does not.

Use the URL you were given and do not try to check it. There is no network
here, and a worker that goes looking spends the whole item on it.

Do not invent requirements. Where the task is silent, choose the plainest thing
that works and report the choice rather than burying it.
