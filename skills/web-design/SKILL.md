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
