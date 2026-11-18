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

**The .gitignore belongs in that first item, before anything is installed.**
A package manager run in a repository with no ignore file puts every
downloaded dependency into the first commit - tens of thousands of files
nobody wrote, in a history where they cannot be reviewed and cannot be
removed without rewriting it. The ignore file costs one line in the item that
is being written anyway, and it has to exist before the install, not after.

**Every page exists for somebody with a question. Answer the question.**
This is the failure that passes every test and is still wrong, and it is
worth more attention than any of the others, because nothing in the
verification can catch it.

A restaurant site showed "Closed now. Opens next on Tuesday at 17:00" and
nothing else about hours. The logic was correct, the test asserted it, and it
is useless: somebody reading a restaurant's website at eleven at night wants
to know when it is open, and was told only that it is not open at eleven at
night. The live line is worth having. It is worth having *next to the week*,
never instead of it.

The shape of that mistake is general. A status derived from data is an
addition to the data, not a replacement for it. "3 unread" does not replace
the list. "Last updated 2 hours ago" does not replace the content. Whenever
an item renders something computed, ask what the visitor came for, and make
sure the page still contains it.

**Compose the page out of pieces that different items can own.** The page
itself is one item: the shell, the layout, and the order things appear in.
Everything after it is a component and the data behind it, imported into
that page. This is ordinary good structure, and it has a second effect
here - items that own separate files are worked on at the same time, and
items that all edit one page are not.

Then one feature per item, each with its test in the same item - and group
features that would be written in one sitting. The skeleton, the data and
the first page that renders it is one item, not three. Documentation and
deploy configuration go with the last piece of work rather than becoming
items of their own.

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

Do not invent requirements. Where the task is silent, choose the plainest thing
that works and report the choice rather than burying it.

## Verify

The bar is that the tests exist, that they run, and that they pass. All three:
a suite that passes because it contains nothing is the failure this skill is
written to prevent.

Watch the count from the first item onwards. It should only ever go up.

## Checked against what is current (2026-11-17)

On visual design of a small marketing website in 2026: CSS layout, typography, colour, and what makes a page look dated. Each line carries the source it came from; anything that could not be sourced was left out.

- Missing: a light-only palette is no longer the final word on how the page renders. Safari's Adaptive Dark Mode (announced 2026-11-03, Safari 27.3 beta) analyses any page that has not declared a colour scheme and, if it looks light, inverts luminosity while preserving hue - transforming gradients, text and images. Sites that declare support are left alone. The greenfield skeleton should therefore ship an explicit declaration in the first item: `<meta name="color-scheme" content="light dark">` (or `light only` to opt out) - WebKit recommends the head or `:root`, not JavaScript, and blocks scripts from detecting that the transform happened, so this cannot be papered over later. (https://webkit.org/blog/18541/introducing-adaptive-dark-mode/)
- Missing: `light-dark()` has been Baseline since May 2024 and is the current way to carry two themes in one declaration - `color: light-dark(#333b3c, #efefec)` - instead of duplicating the whole palette inside a `prefers-color-scheme` block. It only works when `color-scheme: light dark` is set, usually on `:root`, which is the same line the Safari behaviour above requires. (https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/light-dark)
- Missing: `oklch()` is Baseline Widely available and has been supported across browsers since May 2023. Its `L` is perceived lightness, so a scale built by varying L alone stays perceptually even, and it reaches beyond the sRGB gamut that hex and `hsl()` are stuck in. Hand-written hex ramps and `hsl()` lightness steps (where equal numeric steps are visibly uneven) are the dated-looking default this replaces. (https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Values/color_value/oklch)
- Missing: if the crew reaches for Tailwind, v4 changed the two things that matter here. The whole default palette moved from rgb to oklch for wider gamut, and configuration moved out of tailwind.config.js into CSS via `@theme`, where tokens are declared as native custom properties (`--color-*`, `--font-*`, `--breakpoint-*`) and exposed as CSS variables. A v3-shaped JS config is now the outdated path. (https://tailwindcss.com/blog/tailwindcss-v4)
- Missing: `text-wrap: balance` for headlines was Baseline Newly available on 2024-05-13 and was due to reach Widely available on 2026-11-13 - four days before today. Ragged two-word second lines under a hero headline are now a one-declaration fix on every engine, and are one of the clearest tells of a page nobody typeset. (https://web-platform-dx.github.io/web-features-explorer/features/text-wrap-balance/)
- Missing, and a trap: `text-wrap: pretty` is NOT Baseline. Chrome/Edge have had it since 117 and Safari since 26 (2025-09-15), but Firefox has not implemented it and has blocked Baseline since September 2025. Firefox falls back to normal wrapping with no breakage, so it is safe as progressive enhancement for body copy - but a layout or a test that assumes orphan-free paragraphs will not hold cross-browser. (https://web-platform-dx.github.io/web-features-explorer/features/text-wrap-pretty/)
- Missing: fluid type keyed to the viewport is the dated pattern. Current practice pairs container query units with clamp() - `font-size: clamp(1rem, .5rem + 3cqi, 2rem)` - so a card sets its own type scale from the space it is actually given rather than from the window. The division recommended as of 2026-09-16: media queries for page-level macro layout, container queries for any component that appears in more than one context. (https://www.smashingmagazine.com/2026/09/stop-treating-css-container-queries-traditional-media-queries/)
- Missing: scroll-driven animations became Baseline Newly available on 2026-10-27 when Firefox 159 shipped them (Chrome 115, Safari 26 preceded it). Scroll- and view-timeline reveals no longer need an IntersectionObserver or a JS animation library - which is the usual reason a small marketing site grows a JS dependency it never needed. (https://web.dev/blog/web-platform-10-2026)
- Missing, and a counterweight to the item above: `prefers-reduced-motion` is already honoured by about 50% of desktop and mobile pages, the most widely adopted user-preference query there is. Any scroll-driven or kinetic typography effect needs a reduced-motion branch, or the site is below the common bar rather than above it. (https://almanac.httparchive.org/en/2025/accessibility)
- Missing, and worth naming as off-limits: CSS anchor positioning is still Limited availability - Chrome 157, Edge 157 and Safari 27 ship it, Firefox does not, and Baseline has been blocked by Firefox since November 2026. Cross-document view transitions (`@view-transition`) are likewise Limited, blocked by Firefox for 23 months, and CSS carousel scroll markers (`::scroll-marker`) are Chrome-only. All three are Interop 2026 focus areas, which is the signal they are not yet done. Tooltips, dropdowns and page transitions must still work without them. (https://web-platform-dx.github.io/web-features-explorer/features/anchor-positioning/)
- Missing: the browser vendors published Interop 2026 on 2026-02-12 with 20 focus areas, among them container style queries, contrast-color(), advanced attr(), scroll-driven animations, scroll snap, shape(), view transitions and anchor positioning. This is the authoritative list of what is being made safe this year, and it is the right thing for the crew to check a styling decision against rather than a trends article. (https://webkit.org/blog/17818/announcing-interop-2026/)
- Missing: part of visual design IS machine-checkable, which bears directly on the skill's verification bar. Lighthouse runs axe-core and reports failing colour pairings, missing focus indicators and disabled zoom. Adding one such run to the suite in the first item costs little and catches the class of defect that currently fails most of the web. (https://web.dev/learn/accessibility/test-automated)
- Missing: the measured state of the web is the fastest guide to what looks dated. In 2025 only 30% of sites passed colour contrast; 67% explicitly removed default focus outlines (up 14 points in a year) while only ~25% adopted `:focus-visible`; 19-21% still disable pinch zoom; and 67% of desktop sites set font sizes in `px`, which ignores the reader's own text-size setting. A new site clears all four of these by default if anyone sets the rule. (https://almanac.httparchive.org/en/2025/accessibility)
- Missing: the typography defaults have moved. Variable fonts are now on 39.4% of desktop and 41.3% of mobile sites; self-hosting is the dominant delivery at ~72% while Google Fonts fell from 57% to 54% on desktop; `font-display: swap` is on ~50% of pages; WOFF2 is 65% of font requests; and `system-ui` has appeared on ~10% of sites. Two statically-weighted families loaded from a third-party stylesheet is the dated configuration, on performance and privacy as well as looks. (https://almanac.httparchive.org/en/2025/fonts)
- Missing: for a marketing site that sells, accessibility is now a legal floor and not a finishing touch. The European Accessibility Act has applied since 2025-06-28 and covers e-commerce among its listed services; the harmonised standard behind it, EN 301 549, reached V4.1.1 in September 2026 and incorporates the text of WCAG 2.2 in full. Contrast, focus and zoom decisions made in the first styling item are the cheapest place to meet it. (https://digital-strategy.ec.europa.eu/en/news/eu-becomes-more-accessible-all)
