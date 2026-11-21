---
name: AgentFox
description: The control layer for everything your agents do; a white, ruled, editorial site with one crimson voice.
colors:
  brand-crimson: "#c8285a"
  brand-crimson-press: "#a91f4a"
  on-brand: "#ffffff"
  ink: "#1a1916"
  ink-2: "#4a4740"
  muted: "#6b675f"
  ground: "#ffffff"
  subtle: "#f5f5f3"
  hairline: "#e4e2dd"
  hairline-strong: "#d2cfc8"
  night-ground: "#0e0f13"
  night-ink: "#ecedf1"
  night-crimson: "#f0668d"
  verdict-allowed: "#18794e"
  verdict-held: "#9b5a00"
  verdict-blocked: "#c2301d"
typography:
  display:
    fontFamily: "Archivo, IBM Plex Sans, sans-serif"
    fontSize: "64px"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 106"
  statement:
    fontFamily: "Archivo, IBM Plex Sans, sans-serif"
    fontSize: "clamp(26px, 2.7vw, 40px)"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.025em"
    fontVariation: "'wdth' 116"
  headline:
    fontFamily: "Archivo, IBM Plex Sans, sans-serif"
    fontSize: "clamp(32px, 3.4vw, 50px)"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-0.02em"
    fontVariation: "'wdth' 106"
  index-verb:
    fontFamily: "Archivo, IBM Plex Sans, sans-serif"
    fontSize: "clamp(30px, 3.2vw, 46px)"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontVariation: "'wdth' 106"
  title:
    fontFamily: "IBM Plex Sans, -apple-system, Segoe UI, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "-0.01em"
  lead:
    fontFamily: "IBM Plex Sans, -apple-system, Segoe UI, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.55
  body:
    fontFamily: "IBM Plex Sans, -apple-system, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  small:
    fontFamily: "IBM Plex Sans, -apple-system, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  mono:
    fontFamily: "Geist Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  badge: "4px"
  control: "8px"
  panel: "10px"
  card: "12px"
  pill: "999px"
spacing:
  gutter-phone: "20px"
  gutter: "32px"
  head-gap: "64px"
  section-tablet: "80px"
  section: "136px"
  wrap: "1200px"
components:
  button-primary:
    backgroundColor: "{colors.brand-crimson}"
    textColor: "{colors.on-brand}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 20px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.brand-crimson-press}"
  button-secondary:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 20px"
    height: "44px"
  button-secondary-hover:
    backgroundColor: "{colors.subtle}"
  button-small:
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "36px"
  copy-chip:
    backgroundColor: "{colors.subtle}"
    textColor: "{colors.ink-2}"
    typography: "{typography.mono}"
    rounded: "{rounded.control}"
    height: "36px"
  verdict-tag:
    typography: "{typography.small}"
    rounded: "{rounded.pill}"
    padding: "0 10px"
    height: "24px"
  closing-band:
    backgroundColor: "{colors.night-ground}"
    textColor: "{colors.night-ink}"
    padding: "112px 0"
---

# Design System: AgentFox

## Overview

**Creative North Star: "The Ruled Ledger"**

The public site reads like a well-set reference document about authority over agent actions: a white ground, ink type, and the page structured by hairline rules rather than boxes. Sections open with an editorial split, a large Archivo heading on the left and one supporting line on the right, and their content is laid out as ruled indexes, hairline tables and rows. Nothing sits above a heading.

One crimson carries all the emphasis. It marks the primary action and the call under check (the held tool call, our row in a comparison, our bar in a chart, the `$` of a command). Everything else is ink at three strengths on white. The signature image is the hero's gate canvas: an agent's traffic drawn as stacked ink ridge lines, with a thin crimson gate at the centre where calls stop or pass.

Density is generous: 136px section rhythm, a 1200px wrap, 64px between a section head and its body. Light and dark themes share every rule; dark swaps the token values via `data-theme` (or the system preference), and the closing band is always dark.

**Key Characteristics:**
- White ground, ink type, a single crimson accent for the action and the call under check.
- Archivo, slightly expanded (width 106, statement line 116), for headings and display lines; IBM Plex Sans for reading; Geist Mono only for code, tool names and values.
- Editorial split section heads, no label above a heading.
- Hairline rules and ruled indexes instead of card grids.
- The line-art gate canvas as the visual signature.
- One authored motion: the timeline rail drawing down to the held call.

## Colors

A near-monochrome warm-neutral palette with one crimson voice; status colours appear only as verdicts.

### Primary
- **Gate Crimson** (brand-crimson): the primary button, the held call in the timeline, our row/bar/value in every comparison, the `$` prompt in commands, link-style actions ("Read the research"), the gate in the hero canvas and selection tint. Pressed state uses **Pressed Crimson** (brand-crimson-press). In dark theme it lifts to **Night Crimson** (night-crimson).

### Neutral
- **Ledger Ink** (ink): headings, the heavy top rule of an index or proof pair, primary text.
- **Second Ink** (ink-2): leads, body copy in indexes and tables.
- **Margin Grey** (muted): fine print, table headers, sources, arrows at rest.
- **Paper White** (ground): the page ground and the surface of every panel.
- **Wash** (subtle): copy-chip fill, hover fill; mixed 70% into the ground for alternate section bands.
- **Hairline** (hairline) and **Strong Hairline** (hairline-strong): every rule, row divider and secondary-button border; the timeline rail before it turns crimson.
- **Night Ground** (night-ground) / **Night Ink** (night-ink): the closing call-to-action band, dark in both themes.

### Verdicts
- **Allowed** (verdict-allowed), **Held** (verdict-held), **Blocked** (verdict-blocked): only inside verdict tags, the hero's verdict chips and product mockups, always as text on a 12% tint of itself with a 6px dot, never as fills or section colours.

### Named Rules
**The One Voice Rule.** Crimson marks the primary action and the call under check, and nothing else. If two things on a screen are crimson, one of them is the action and the other is "ours" in the proof.

**The Errors Are Not Brand Rule.** Blocked is vermilion (verdict-blocked), never crimson, and always carries a word.

## Typography

**Display Font:** Archivo with its width axis (fallback IBM Plex Sans)
**Body Font:** IBM Plex Sans (fallback -apple-system, Segoe UI, sans-serif)
**Label/Mono Font:** Geist Mono (fallback ui-monospace, Menlo)

**Character:** A sturdy, instrument-like grotesk set slightly wide for the voice, against a plain humanist sans for reading. Mono appears only where the value is code.

### Hierarchy
- **Display** (500, 64px, 1.05, -0.035em, width 106): the hero headline only. Steps to 48px under 960px and 36px under 640px.
- **Statement** (600, clamp 26-40px, 1.1, width 116): the vision line above the hero headline. A statement, set in ink, not a label.
- **Headline** (500, clamp 32-50px, 1.08, width 106): every section heading, left column of the split head; 28px on phones.
- **Index verb** (500, clamp 30-46px, line-height 1): the verbs of a ruled index (Discover, Govern, Protect, Test, Prove); a smaller variant (clamp 22-28px) for secondary indexes.
- **Title** (600, 18px, 1.35): step and pair headings.
- **Lead** (400, 18px, 1.55, ink-2): the one line beside a heading; 16px on phones.
- **Body** (400, 15px, 1.6); **Small** (400, 13px) for fine print and sources.
- **Mono** (400, 12-13px): commands, tool calls, arguments.

### Named Rules
**The Heading Stands Alone Rule.** No eyebrow, kicker or pill above a heading. The heading carries the section.

**The Mono Means Code Rule.** Geist Mono is used only for commands, tool names, arguments and measured values.

## Layout

A centred 1200px wrap with a 32px gutter (20px under 640px, 16px under 400px). Sections run 136px top and bottom (80px under 960px), alternating with a washed band bounded by hairlines. Section heads are a two-column grid (7fr / 5fr, 64px column gap, bottom-aligned), collapsing to one column under 960px; a head without a lead spans the full width.

Ruled indexes use a 4fr / 7fr / 20px grid (verb, text, arrow) with 30px row padding. The timeline is a 44px-indented list whose rows are a 220px step name beside the content. Three-step sequences use a three-column grid with subgrid rows so captions share one baseline, collapsing to one column under 960px. The hero fills the viewport (720-900px) with the copy at the bottom, centred, over a radial fade of the ground; the works-with strip sits on a hairline at the fold. On phones the canvas becomes a 320px band above the copy, and a sticky primary button appears once the hero buttons scroll away.

## Elevation & Depth

Flat. Depth comes from rules and the washed alternate band, not shadows. The only shadows on the public site belong to things that float (the mobile menu, the hero's verdict chips) and to the held call in the timeline, which carries a soft crimson-tinted drop (`0 18px 40px -24px` of 70% crimson) as the page's one lifted surface.

### Named Rules
**The Lifted Once Rule.** Only the call under check is lifted. Everything else lies on the page.

## Shapes

Rules do the work of containers: a 1px ink rule opens an index or a proof pair, 1px hairlines separate rows. Where a box is unavoidable (comparison tables, step panels, the held call), corners are gently rounded: 8px for buttons and chips, 10px for the held-call panel, 12px for comparison containers. Tags and status dots are fully round. The timeline rail is a 2px line with 12px ring stations.

## Components

### Buttons
- **Shape:** gently rounded (8px), 44px tall (36px small variant in the header).
- **Primary:** crimson fill, white text, 15px/500, 20px side padding; pressed crimson on hover. One per view, plus the header's small one.
- **Secondary:** ground fill, ink text, strong-hairline border; wash on hover.
- **Ghost:** only on the dark closing band, light text with a 18% white border.
- **Focus:** 2px crimson outline at 3px offset.
- **Arrow:** a 12px diagonal arrow nudges up-right 2px on hover.

### Verdict tags
- **Style:** 24px pill, 12px/500 text in the verdict colour on a 12% tint of it, preceded by a 6px dot.
- **State:** allowed, held, blocked; neutral muted for "would have".

### Copy chip
- 36px wash field on a hairline, mono command prefixed by a crimson `$`, a 36px copy button split off by a hairline.

### Navigation
- 64px sticky bar, 85% ground with 12px blur and a bottom hairline. Brand left, text links (14px, ink-2 to ink on hover), then GitHub and theme icon buttons, Sign in, and the small primary. Under 640px links collapse into a details menu panel (10px radius, floating shadow).

### Ruled Index (signature)
The control-plane list: an ink top rule, hairline row dividers, an Archivo verb, a 17px line of ink-2 text, and a muted arrow. On hover or focus the verb and arrow turn crimson and the arrow shifts 4px right. Rows stagger in 80ms apart when revealed.

### Moment-of-Action Timeline (signature)
Four stations on a 2px rail that is hairline-strong for its first 74% and grades into crimson at the end. Only the last station, the held call, is boxed: crimson ring, crimson-tinted border and the page's one lifted shadow. Motion: the rail scales down from the top over 1500ms on the standard ease, stations follow at 300 / 650 / 1050ms, and the held box lands at 1500ms. With reduced motion, or before scripts run, it shows the finished state.

### Gate Canvas (signature)
Hero background on a canvas: stacked ink ridge lines with pulses for calls, a thin crimson vertical gate at the centre, harmless look-alikes passing and a real attack stopping with a crimson flash and a verdict chip. Colours are read from the theme tokens, so it follows light and dark. Decorative, hidden from assistive tech, one still frame under reduced motion.

### Proof Pair
A heavy ink rule over each pair, no box. Rows of name / 10px rounded track / value; our track and value in crimson, others in strong hairline and ink. Tracks grow from zero when revealed.

### Closing Band
Night ground in both themes, centred Archivo heading, light lead, copy chip, primary and ghost buttons.

## Do's and Don'ts

### Do:
- **Do** open every section with the editorial split: Archivo heading left, one lead right, nothing above the heading.
- **Do** reserve crimson for the primary action and the call under check, including "our" row, bar and value in proofs.
- **Do** separate content with 1px hairlines and open an index or proof with a 1px ink rule.
- **Do** set code, tool calls and measured values in Geist Mono, and everything else in Plex or Archivo.
- **Do** read canvas and chart colours from the `--af-*` tokens so both themes stay correct.
- **Do** show the finished state of any motion when the visitor prefers reduced motion.

### Don't:
- **Don't** put an eyebrow, kicker or uppercase tracked label above a heading.
- **Don't** lay out features as a grid of boxed cards; use a ruled index.
- **Don't** use crimson for errors or blocked verdicts; those are vermilion with a word.
- **Don't** add a second authored motion beside the timeline draw; reveals are a plain fade-up.
- **Don't** lift anything with a shadow except the held call and things that float.
