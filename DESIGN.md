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

<!-- impeccable:design-map -->
Name: AgentFox
Colors: primary: brand-crimson #c8285a; neutral: ink #1a1916; status: verdict-allowed #18794e; primary: brand-crimson-press #a91f4a; primary: night-crimson #f0668d; neutral: ink-2 #4a4740 (+9 more in the sidecar)
Fonts: Archivo (hero H1 only, normal width); IBM Plex Sans (section headings 40px/500, titles, lead, body, small); Geist Mono (mono)
Spacing: gutter-phone 20px, gutter 32px, head-gap 48px, section-tablet 80px, section 112px, wrap 1200px
Radius: badge 4px, control 8px, panel 10px, card 12px, pill 999px
North Star: "The Ruled Ledger"
Rules:
- The One Voice Rule. Crimson marks the primary action, "us" (the AgentFox column, our bars, step numbers) and the call under check.
- The Errors Are Not Brand Rule. Blocked is vermilion (verdict-blocked), never crimson, and always carries a word.
- The Heading Stands Alone Rule. No eyebrow, kicker or pill above a heading.
- The Mono Means Code Rule. Geist Mono is used only for commands, tool names, arguments and measured values.
- The Lifted Once Rule. Only the call under check is lifted.
Don't:
- Don't put an eyebrow, kicker or uppercase tracked label above a heading.
- Don't nest cards more than two deep; a step is one card holding its mock, with the mock's rows as hairlines.
- Don't put abstract taxonomy before product proof; real UI (terminal, comparison table) comes first.
- Don't use crimson for errors or blocked verdicts; those are vermilion with a word.
- Don't add a second authored motion beside the timeline draw; reveals are a plain fade-up.
- Don't lift anything with a shadow except the held call and things that float.
Do:
- Do open every section with a centred Plex heading and one lead under it, nothing above the heading; content sits on the same centre axis.
- Do reserve crimson for the primary action and the call under check, including "our" row, bar and value in proofs.
- Do separate content with 1px hairlines and open an index or proof with a 1px ink rule.
- Do set code, tool calls and measured values in Geist Mono, the hero H1 in Archivo, and everything else in Plex.
- Do read canvas and chart colours from the `--af-*` tokens so both themes stay correct.
- Do show the finished state of any motion when the visitor prefers reduced motion.
Full: .impeccable/design-full.md (read a section when you need its detail). Where it disagrees with this map, the map wins: on 2026-11-21 the homepage went back to centred Plex section heads, card-held steps and crimson on "us", and the five-verb index was removed.
