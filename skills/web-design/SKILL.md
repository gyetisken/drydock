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

## Plan

Six lines, because you are writing the direction and not the stylesheet.
The whole of how to build a page is under `## Engineer`, where the person
building it will read it; none of that belongs here.

- **Direct for this business, not for businesses.** A Nolita trattoria and
  a tax practice are not the same page with different words. Say who walks
  in, what they came to find, and what the place feels like standing in it.
  Every later choice answers back to that sentence.
- **Name the one gesture.** A page is carried by a single idea at the top
  and then it gets quiet. Say what that idea is here; a page that shouts in
  six places reads as cheap.
- **Say what the generic version would be** - the stock hero of a table,
  "Welcome to our restaurant", the carousel nobody asked for - so it cannot
  arrive by default.
- **Say what pictures are available, and leave the rest open.** Nothing
  here can take or generate a photograph, and inventing an image file is
  the one thing that is never allowed. Everything else is a live option:
  real photographs the request or the repository supplies, licensed ones
  referenced by URL, illustration, a drawn mark used at size, type and
  colour carrying the page on their own. Say what exists and what it
  shows; where nothing does, say what kind of imagery would suit and let
  whoever builds it decide what is reachable. "No images" is a decision
  about this page, not a rule - do not make it for a business whose whole
  appeal is how a place looks, and do not write it as a requirement.
- **Intent, not values.** Name a colour the way a person does - "a deep
  oxblood, not a web red" - and leave the hex, the type scale, the
  spacing and the breakpoints to whoever has the page in front of them.
  The same goes for how many sections the page has, how many tests it
  carries, which framework builds it and what the directory is called:
  none of those is a direction, and naming one without a reason the
  request gave you is deciding somebody else's job from further away.
- **It is read on a phone, standing up.** Most people looking at a
  restaurant's site are outside it deciding whether to go in. Direct that
  first; the desktop version is the easy one.

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

**Photographs: never made here, sometimes available.** Nothing in this
process can take a photograph, buy one, or generate one, and a file of flat
colour named `.jpg` is a lie that passes a build. That rules out one thing
and one thing only: inventing the image file.

Which of the two remaining paths is right depends on what you were actually
given, so look before you choose.

*If the request, the direction or the repository supplies real images* - a
URL to a licensed photograph, files already committed, an asset directory -
use them, and design around them. Give every one an aspect ratio in the CSS
so nothing jumps when it arrives, `loading="lazy"` below the fold, a real
`alt`, and a ground colour underneath for when it does not come. Do not try
to check a URL: this process has no network, and a worker that goes looking
spends the whole item on it - two of them spent a hundred and fifty minutes
between them running `curl`, turning the sandbox off and reaching for a web
search, to prove a photograph existed. Write the URL you were given and move
on; whether it is the right picture is settled by somebody looking at the
page, which is a station that already exists.

*If nothing supplies them*, design with type, colour, space and drawings
made here. A layout whose whole idea is a hero *photograph* is one nobody
here can build; a layout carried by a hero that somebody draws is not,
and an illustrated page is a direction you may take rather than a
consolation for one you could not. Where an image really is
required, leave a placeholder that looks like a decision - a flat field at
the right aspect ratio, captioned with what goes there - and say in the
README what to drop in.

Either way: an image with no art direction is a stock photograph of a
handshake. If nothing says what is in the picture and what it is doing, the
page is better with type, colour and space instead.

**Say what you will not do.** Writing down the generic version - stock hero
photo of a table, "Welcome to our restaurant", a carousel nobody asked for -
is what stops it arriving by default.

## Engineer

Before calling visual work finished, look at it - at phone width, at
desktop width, and in both colour schemes if it supports them. No test
catches what is wrong there, which is why it has to be looked at
deliberately: text that fails contrast against its background, a heading
hierarchy that skips a level, a hero that pushes the content below the
fold, and tap targets smaller than a thumb.

**Pictures.** Nothing here can take, buy or generate a *photograph*, and
flat colour named `.jpg` is a lie that passes a build. That rules out the
photograph and nothing else. Images the request, the direction or the
repository supplies are yours to use, each with an aspect ratio in the
CSS so nothing jumps, `loading="lazy"` below the fold, a real `alt` and a
ground colour underneath; `brand/logo.svg` may already be there.

Where nothing supplies one there are two answers and they are not
ranked. **You can draw it** - an SVG you write is a real asset and not a
placeholder, and it ships with the page. **You can look for a
photograph**, if the engineer's instructions gave you the command for
it: start with what the project already has, then search. What it finds
is free to use and carries its licence and author; record both, and put
the attribution on the page when the licence asks.

Which one is a judgement about the subject. A real place, object or
person is usually weaker drawn: a photograph is the thing, an
illustration is an impression of it. An idea, a service or a brand is
often stronger drawn, because there is nothing to photograph and a stock
image of the wrong thing is worse than a good mark.

Either way, a picture with no art direction is a stock photograph of a
handshake. And "no pictures" is a decision about this page, not a rule -
do not make it silently for something whose appeal is how it looks.

**Space is a decision, not what is left over.** Room between sections and
around a headline is the point. A content column that stops halfway
across a wide section because that is where the words ran out is a
different thing, and when it happens twice on one page the page is
telling you something is missing from it rather than that it is
breathing. What answers it - a second column, a drawing, a figure, a
different grid, or genuinely nothing - is yours to decide.

**One stylesheet holds the decisions.** The palette, the type scale and the
spacing live as custom properties in one place, written early, and every
later piece of work uses them. An item that invents its own values has
started a second design.

**Write the current CSS, not the CSS you learned.** A few of these replace
whole patterns and each is worth more than the line it takes:

- `color-scheme: light dark` on `:root`, or `<meta name="color-scheme">`
  in the head. Safari inverts the luminosity of any page that has not
  declared one and leaves alone any page that has, so this is the
  difference between choosing how the page renders in dark mode and
  having it chosen. It also has to be set for the next line to work.
- `light-dark()` returns one of two colours based on the active scheme, so
  dark mode is one declaration rather than a duplicated block.
- `oklch()` for anything with steps in it. Its lightness is perceived
  lightness, so a ramp built by varying L alone stays even; the same ramp
  in hex or `hsl()` has visibly uneven steps, and that unevenness is one
  of the clearest tells of a palette nobody looked at.
- `text-wrap: balance` on headlines - the cheapest visible improvement to
  a marketing page there is, and available everywhere. `text-wrap: pretty`
  on body text is progressive enhancement only: Firefox has not shipped
  it, so it is safe to set and never safe to rely on. Do not write a
  layout or a test that assumes paragraphs have no orphans.
- `clamp()` for type and spacing, with `rem` units. Never `px` for
  `font-size`: it ignores what the reader set.
- Container queries for components that need to respond to their own box
  rather than the viewport.
- `size-adjust` and the `@font-face` metric overrides on the fallback font.
  Web fonts are the usual cause of the layout shift a hero suffers from.

Four things a new page should simply get right, because most of the web
does not: colour contrast that passes, a visible focus style - `:focus-visible`
rather than deleting the outline - pinch zoom left enabled, and font sizes
in `rem` so the reader's own text setting still means something.

Anything that moves on scroll needs a `prefers-reduced-motion` branch, or
the page is below the common bar rather than above it. And three things
are not settled enough to depend on: CSS anchor positioning, cross-document
view transitions, and scroll marker pseudo-elements. Tooltips, dropdowns
and page transitions still have to work without them.

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

