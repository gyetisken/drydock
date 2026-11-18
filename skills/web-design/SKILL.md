---
name: web-design
description: How a page should look and why, for work somebody is going to look at. Use for websites, landing pages, dashboards and anything with a visible surface.
asks: what is being built and who for
---

# Making something worth looking at

The failure this exists to prevent is not ugliness. It is the page that
passes every test, does everything it was asked, and looks like it was made
by nobody for nobody. Default styling is a decision; it is just not one
anybody took.

## Design

**Decide for this business, not for businesses.** A Nolita trattoria and a
tax practice are not the same page with different words. Before any colour
is chosen, say who walks in, what they came to find, and what the place
feels like standing in it. Every later choice answers back to that sentence.

**One gesture.** A page is carried by a single idea at the top - a
photograph, a piece of type set large, one strong colour field - and then it
gets quiet. Pages that shout in six places read as cheap, and the reason is
simple: shouting everywhere is the same as shouting nowhere.

**Type is most of it.** Pick a real pairing and commit. A scale with clear
steps, not six sizes within four pixels of each other. Body text wants
generous line height and a measure of roughly 60 to 75 characters; headings
want it tight. If a page looks wrong and nothing obvious is broken, the type
scale is the first place to look.

**Space, not rules.** Sections separate by room. Borders and boxes
everywhere are what a layout looks like when nobody decided the rhythm. At
desktop width it should feel slightly too sparse; it will not when anybody
reads it.

**Colour: a ground, an ink, one accent.** The accent means something -
it is what you act on. Three accents means none of them is. Gradients,
drop shadows on everything, and glassmorphism date a page faster than any
other single choice.

**It is read on a phone, standing up.** Most people looking at a
restaurant's site are outside it deciding whether to go in. Design that
first; the desktop version is the easy one.

**Photographs: not made, but used.** Nothing here can take a photograph or
generate one, and a hand-written file named `.jpg` is a lie that passes a
build. A photograph somebody else took, licensed for this and referenced by
URL, is neither - and it is what carries most of the pages worth sitting
beside.

Use real ones, from a real source, with the URL in the markup: Unsplash
serves them directly. Give every one an aspect ratio in the CSS so nothing
jumps when it arrives, `loading="lazy"` below the fold, a real `alt`, and a
ground colour underneath in case it never comes. What is never allowed is an
image file written by the thing building the page.

**Do not try to check an image URL.** This process has no network. A worker
that goes looking for one spends the whole item on it: two of them spent a
hundred and fifty minutes between them running `curl`, turning the sandbox
off, and reaching for a web search, to prove a photograph existed. Write
the URL the direction gives you and move on. Whether the picture is the
right picture is settled by somebody looking at the page, which is a
station that already exists.

An image with no art direction is a stock photograph of a handshake. If the
direction does not say what is in the picture and what it is doing, the page
is better with type, colour and space instead.

** Nothing in this process can take one, buy one or
generate one. A layout that needs a hero image is a layout nobody here can
build, and what arrives instead is a few hundred bytes of flat colour named
.jpg. Design with type, colour, space and drawn marks. Where an image really
is required, leave a placeholder that looks like a decision - a flat field at
the right aspect ratio with the caption saying what goes there - and say in
the README what to drop in.

**Say what you will not do.** Writing down the generic version - stock hero
photo of a table, "Welcome to our restaurant", a carousel nobody asked for -
is what stops it arriving by default.

## Engineer

**One stylesheet holds the decisions.** The palette, the type scale and the
spacing live as custom properties in one place, written early, and every
later piece of work uses them. An item that invents its own values has
started a second design.

**Write the current CSS, not the CSS you learned.** A few of these replace
whole patterns and each is worth more than the line it takes:

- `light-dark()` returns one of two colours based on the active scheme, so
  dark mode is one declaration rather than a duplicated block.
- `text-wrap: balance` on headlines and `text-wrap: pretty` on body text.
  It is the cheapest visible improvement to a marketing page there is.
- `clamp()` for type and spacing, with `rem` units. Never `px` for
  `font-size`: it ignores what the reader set.
- Container queries for components that need to respond to their own box
  rather than the viewport.
- `size-adjust` and the `@font-face` metric overrides on the fallback font.
  Web fonts are the usual cause of the layout shift a hero suffers from.

**Test files never go in a routes directory.** Astro, Next, Nuxt, SvelteKit
and Remix all turn everything under their pages or routes folder into a URL.
A test file put there becomes a route, and the build tries to render it and
dies importing a test runner. Tests go beside the module they test, or in a
top-level tests directory - never in `src/pages`, `app`, `routes` or `pages`.

**The page never scrolls sideways.** Not "rarely", not "only the hero" -
never, at any width down to 320px. A page that does is the most common
broken page on the web and it is the first thing anybody notices on a
phone: the sentence runs off the edge mid-word and the last two words of
every line are gone. It has cost this crew three items across three runs
and the cause was the same each time.

Three things cause it, and they are all avoidable:

- **A full-bleed band built out of `100vw`.** `width: 100vw; left: 50%;
  transform: translateX(-50%)` is the trick everybody knows and it is
  wrong twice: `100vw` includes the scrollbar, and `left: 50%` resolves
  against the containing block, which is the padded content column rather
  than the viewport. Do it with the grid instead - give the page a grid
  with a `full` track either side of the content track, and let the band
  take `grid-column: full`. No viewport units, no transform, nothing to
  resolve against the wrong thing.
- **Display type set in fixed `rem`.** `font-size: 8.5rem` is 136px, and
  four capitals at 136px do not fit in a 390px phone. Display sizes are
  `clamp()` or they are broken on a phone: `clamp(2.5rem, 12vw, 8.5rem)`.
  A scale contrast that only holds at 1440 is not a scale contrast.
- **A grid with fixed column widths that never collapses.** Twelve columns
  at a fixed gutter is a desktop layout. On a phone it has to become one.

Then check it rather than assuming it: look at the page at 390px. If
anything is cut off at the right edge, nothing else about the item matters
yet.

**An inverted section sets its own colour.** This is the single most
common way a page that is correct in the code renders as half a page. A
palette has two ink colours and two grounds - a dark ink for the light
ground, a light ink for the dark one - and a section that flips to the dark
ground inherits the ink from the page it sits in. The headings usually get
an explicit colour because somebody was thinking about them; the second
column of the table does not, and it renders near-black on black.

Nothing in the markup is wrong when this happens, which is why reading the
code does not catch it. The hours table of a shop site was written three
times with `<td>{open} - {close}</td>` sitting right there in the row, and
three times the page showed seven day names and no times.

So: when a section inverts, set `color` on the section itself, not on the
elements inside it that you happened to think about. Then read the section
back and ask which text in it has no colour of its own - that text is
taking the page's, and the page's is the wrong one.

**Test the data, not the rendering.** A framework page is markup around a
few decisions, and the decisions are the testable part: which hours belong
to today, whether the shop is open at a given minute, how a price is
formatted, which of the seven rows gets highlighted. Put each of those in a
plain module and unit-test the module.

Do not reach for a component-rendering harness to assert what the markup
looks like. Every framework has one - Astro's container API, Testing
Library, Svelte's test utils - and each of them costs an hour of wiring,
breaks on the next minor version, and asserts the one thing somebody is
going to look at anyway. If you find yourself reading a framework's own
source inside `node_modules` to work out how to render a component in a
test, stop: that is the signal that the thing you are trying to assert is
not a test's job.

What the markup looks like is judged by somebody looking at the rendered
page. Write the unit tests for the logic, keep them fast, and let the page
be seen.

**The things a suite cannot see.** Contrast, hierarchy, a hero that pushes
the content below the fold, a form that is unusable with a thumb. No test
catches any of them, so they have to be looked at deliberately before the
work is called done.

## Verify

A page that passes its tests can still be wrong in ways the tests cannot
reach. Before calling visual work finished, look at it: at phone width, at
desktop width, and in both colour schemes if it supports them.

Check the three that are nearly always wrong first: text that fails contrast
against its background, a heading hierarchy that skips a level, and tap
targets smaller than a thumb.
