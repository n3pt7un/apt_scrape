---
name: MilHouse
description: A rental hunt graded like an Italian APE energy certificate, with Milhouse as the AI that reads every listing.
colors:
  paper: "#e9ebe6"
  sheet: "#ffffff"
  sheet-2: "#f5f6f3"
  accent-wash: "#eceee8"
  ink: "#1d1d1b"
  ink-2: "#474843"
  ink-3: "#686a64"
  hair: "#d6d8d2"
  hair-strong: "#b9bcb4"
  rail: "#1d1d1b"
  rail-ink: "#f3f3ef"
  rail-muted: "#a5a79f"
  rail-hover: "#2c2c29"
  r-0: "#00703c"
  r-1: "#138036"
  r-2: "#4aa63a"
  r-3: "#8dc63f"
  r-4: "#c9da2b"
  r-5: "#ffe01b"
  r-6: "#fbb315"
  r-7: "#f28c1e"
  r-8: "#e5561f"
  r-9: "#cf1b22"
  nd: "#9a9c95"
  mh: "#9cbcf0"
  mh-lens: "#eef4ff"
  mh-ink: "#24406e"
  destructive: "#b8161d"
typography:
  figure:
    fontFamily: "Titillium Web, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: "2rem"
    fontFeature: "\"tnum\", \"lnum\""
  headline:
    fontFamily: "Titillium Web, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: "1.75rem"
  title:
    fontFamily: "Titillium Web, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: "1.5rem"
  body:
    fontFamily: "Titillium Web, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: "1.45rem"
    fontFeature: "\"kern\""
  body-sm:
    fontFamily: "Titillium Web, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: "1.2rem"
  caption:
    fontFamily: "Titillium Web, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "1.05rem"
  label:
    fontFamily: "Titillium Web, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: "1rem"
    letterSpacing: "0.06em"
rounded:
  sm: "2px"
  md: "3px"
  lg: "4px"
  xl: "6px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
    height: "36px"
  button-outline:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
    height: "36px"
  button-ghost-hover:
    backgroundColor: "{colors.accent-wash}"
    textColor: "{colors.ink}"
  score-chevron:
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    padding: "0 14px 0 8px"
    height: "24px"
  nav-rail:
    backgroundColor: "{colors.rail}"
    textColor: "{colors.rail-muted}"
    width: "64px"
  nav-rail-active:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    height: "36px"
  status-stamp:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.sm}"
    padding: "0 4px"
    height: "16px"
  milhouse-avatar:
    backgroundColor: "{colors.mh}"
    textColor: "{colors.ink}"
    size: "28px"
---

# Design System: MilHouse

## Overview

**Creative North Star: "The Ministerial Certificate"**

Every listing is read the way an Italian APE energy label is read: a fixed ten-rung ladder from deep green to red, a black pointer arrow showing where this one landed, the number printed beside it. The interface is the certificate around that ladder: white sheets laid on a cool paper ground, ink type, one-pixel hairlines, ruled tables, and an ink-black rail that frames the sheet like the binding of an official form. It is dense, factual and quiet, built for an owner who triages at a desk and on a phone.

Colour is not decoration here. The ladder is the only chromatic system for judgement, printed at full strength exactly as the real label prints it, and it always carries a score, an energy class or a run outcome. Everything else is ink on white. A second, much smaller layer sits on top: Milhouse, the AI, who wears thick round glasses and speaks in a pale blue that appears only where he speaks or works.

Motion is functional and short, with two exceptions that carry the personality: the certificate printing its ladder while the pointer drops to the listing's rung, and Milhouse pushing his glasses up while he thinks.

**Key Characteristics:**
- One typeface (Titillium Web, 400/600/700) for everything; tabular lining figures wherever a number is compared.
- Ten-rung ladder (r-0 to r-9) as the sole scoring colour, full strength, with legible labels on every rung.
- Chevron silhouette (a bar ending in an arrow tip) for scores, energy classes and run states.
- Black pointer arrow as the universal mark of selection.
- N.D. rendered as grey diagonal hatching, never as a ladder colour.
- Flat sheets, hairline rules, 2-3px corners.
- Milhouse blue reserved for the AI's voice.

## Colors

An achromatic certificate (ink, sheet, paper, hairline) carrying one fixed ten-step energy ladder and one reserved AI blue.

### Primary
- **Certificate Ink** (ink): text, primary buttons, focus outlines, the pointer arrow, the selected-row triangle, status stamps, and (18% into sheet) the highlight behind selected text. The darkest value on every screen and the colour of every act of selection.

### Secondary
- **The APE Ladder** (r-0 Deep Classe A4 Green through r-9 Classe G Red): ten rungs, best first. Each rung maps to a ten-point score band (r-0 = 90-100, r-9 = 0-9) and, for real energy classes, A4 A3 A2 A1 B C D E F G. Labels sit in white on r-0, r-1 and r-9 and in ink on r-2 through r-8; every pairing clears 4.5:1. Run outcomes borrow the ends: completed on r-1, failed on r-9, live dot on r-3. The map's base tiles are greyscaled so pins in ladder colours are the only colour on the map.

### Tertiary
- **Milhouse Blue** (mh): the AI's avatar disc, the left rule of a reasoning trace, the border of the deep-analysis composer.
- **Lens Wash** (mh-lens): the glasses' lenses at rest, hover fill of suggested questions.
- **Milhouse Ink** (mh-ink): the AI's text: its name line, reasoning trace, "ci pensa su" label, streaming caret.

### Neutral
- **Cool Paper** (paper): the app ground behind every sheet.
- **Sheet White** (sheet): every working surface: toolbar, feed, certificate, popovers, cards.
- **Second Sheet** (sheet-2): row hover, muted fills, inline code.
- **Accent Wash** (accent-wash): ghost button hover.
- **Ink 2 / Ink 3** (ink-2, ink-3): secondary figures and metadata; ink-3 is the floor for readable text (4.5:1 on paper).
- **Hairline / Strong Hairline** (hair, hair-strong): row rules and sheet edges; input and outline-button strokes, scrollbar thumbs.
- **Rail Ink family** (rail, rail-ink, rail-muted, rail-hover): the navigation rail, phone header and tab bar.
- **Not Evaluated Grey** (nd): the stroke of N.D. hatching.
- **Destructive Red** (destructive): destructive actions only; never a score.

### Named Rules
**The Ladder Is The Only Colour Rule.** A chromatic fill must carry a score band, an energy class or a run outcome. If it carries none of these, it is ink, sheet or paper.

**The Full Strength Rule.** Ladder rungs print at their full value. Tints of a rung appear only for the unselected rungs of the ladder filter (22% mixed into sheet), so that "off" stays readable as the same rung.

**The N.D. Is Not A Score Rule.** A listing the AI never scored, or failed to score, is grey diagonal hatching labelled N.D. It never borrows a ladder colour and never reads as a low score.

**The Milhouse Speaks Blue Rule.** Milhouse blue appears only where the AI is talking, reasoning or waiting to answer. It never marks navigation, selection, links or ordinary buttons.

## Typography

**Display Font:** Titillium Web (self-hosted, 400/600/700), falling back to ui-sans-serif, system-ui
**Body Font:** Titillium Web
**Label/Mono Font:** Titillium Web for labels and keyboard hints (`kbd`); ui-monospace ("SF Mono", Menlo) only for run logs and inline code

**Character:** The Italian public-administration face, used alone. Hierarchy comes from weight and size, never from a second family.

### Hierarchy
- **Figure** (700, 1.75rem, 2rem, tabular): the certificate's headline numbers: price, size, rooms, price per square metre.
- **Headline** (700, 1.375rem): page titles; the large score chevron.
- **Title** (600, 1.125rem): sheet and dialog titles.
- **Body** (400, 0.9375rem, 1.45rem): the base size; AI answers and long reading.
- **Body small** (400/600, 0.8125rem): the working size of the interface: table rows, buttons, navigation, form fields.
- **Caption** (400, 0.75rem): addresses, metadata, small buttons.
- **Label** (600, 0.6875rem, 0.06em, uppercase, ink-3): table column heads, field names in the facts table, certificate section labels, the "APE" tag beside an energy chevron.

### Named Rules
**The Tabular Figures Rule.** Every number that is compared (prices, areas, scores, counts, durations) is set with tabular lining figures and its real unit.

**The Fixed Scale Rule.** Type sizes come from the fixed rem scale; there is no fluid display size. Weight 700 is for figures, scores and names; 600 for labels and controls.

## Layout

A sheet-on-paper desk layout built on a 4px rhythm (row heights of 32-36px, horizontal sheet padding of 16-20px).

- **Below 768px (phone):** a 48px ink header with the glasses mark, wordmark and a compact "Avvia" button; content full width; a fixed six-tab ink bottom bar (56px) with the active tab marked by a short white bar along its top edge. The feed toolbar keeps only the title, a "Filtri" button (its badge counts the settings changed), the ladder filter stretched across the row and the triage tabs; search, ricerca and order open from "Filtri" as a bottom sheet of ruled radio lists ending in "Mostra N annunci". The listing detail opens full height, with four 44px cells pinned at its foot (Preferito, Contattato, Scartato, Portale) so the verdict and the portal are a thumb's reach away. Confronta drops its label column: each row's label runs above the values and the listings share the full width; the AI's reason stops at six lines with a "Leggi tutto" that opens it in place (a touch screen shows no tooltip).
- **From 768px:** the ink icon rail (64px) replaces header and tab bar.
- **From 1024px:** Annunci splits into the feed table and the detail certificate side by side, each scrolling independently.
- **From 1280px:** the rail widens to 208px and shows labels, counts, the live-run card and the keyboard hint; the feed shows price per square metre and rooms columns.

Tables are ruled, not boxed: one ink rule under the header, one hairline under each row.

## Elevation & Depth

Flat by default. Sheets sit on paper with no shadow; depth is the tonal step from paper to sheet plus hairlines. Only things that float above the sheet (map popup, chat composer, scroll-to-bottom button, map legend, menus and dialogs) carry a single soft ink-tinted shadow. Paid or destructive actions are confirmed in the app's own dialog (ink rule under the title, Annulla beside the action, destructive red only on a delete), never the browser's.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 6px 24px -6px rgb(29 29 27 / 0.28), 0 1px 2px rgb(29 29 27 / 0.12)`): a surface lifted over the map or the feed.

### Named Rules
**The Flat Sheet Rule.** A sheet resting in the layout never casts a shadow. Only a layer floating over another layer does, and only in ink tint.

## Shapes

Nearly square corners (2px on controls and stamps, 3px on fields and sheets, 4-6px only for floating layers), one-pixel borders, and one recurring silhouette: the chevron, a bar whose right edge ends in an arrow tip (a five-point clip path with a tip of roughly half the bar height). The chevron reversed is the pointer. Chained chevrons with a notched tail form the ladder filter. Perfect circles are reserved for the glasses mark, the Milhouse avatar and live dots.

## Components

### Buttons
- **Shape:** nearly square (2px), 36px default, 32px small, 24px extra small.
- **Primary:** ink fill with white semibold text; hover lightens to 85% ink.
- **Outline:** sheet fill, strong-hairline stroke, ink text; hover turns the stroke ink.
- **Ghost:** no fill; hover fills with the accent wash.
- **Focus:** a 2px ink outline offset 2px, the same everywhere; inside ruled rows and panels a scroller would clip, the same outline is drawn 2px inside the edge.
- **On the rail:** transparent with a white 25% stroke that strengthens on hover.

### Chips (Chevrons and Stamps)
- **Score chevron:** the listing's match score, bold tabular figures on its rung colour, in three sizes (20, 24, 36px). Unscored: hatch with "N.D." in ink-3.
- **Energy chevron:** the real APE class as a letter chevron followed by a small "APE" label, so it never reads as a score.
- **Run state chevron:** uppercase bold label; queued is ink outline, running is ink fill with a live dot, completed sits on r-1, failed on r-9.
- **Stamps:** 16px ink rectangles with white uppercase bold text at the 11px label floor ("Nuovo", triage state); a discarded listing gets an outlined stamp and a struck-through title in ink-3 with a grey photo (never faded), and stays in the feed.

### Cards / Containers
- **Corner Style:** 3px.
- **Background:** sheet on paper.
- **Shadow Strategy:** none at rest (see The Flat Sheet Rule).
- **Border:** hairline.
- **Internal Padding:** 16-20px.

### Inputs / Fields
- **Style:** 36px, strong-hairline stroke, transparent on sheet, 3px corners, ink caret.
- **Focus:** stroke turns ink.
- **Search fields:** the browser's own (blue) clear button is hidden; a field that needs one draws an ink × ("Cancella ricerca").
- **Composer:** the chat composer is a floating sheet; in deep-analysis mode its stroke is Milhouse blue.

### Confirm Dialog
- **Shape:** the app's own floating sheet: title over an ink rule, the facts in ink-2, Annulla beside the action; destructive red only on a delete.
- **Paid actions ask first:** a run, wherever it starts (rail, ⌘K, Ricerche, "Salva e avvia", Riprova), says it rereads the portal and that Milhouse scores only new, changed or unscored listings, with the real average AI cost per listing over the last paid runs (and a ceiling from the last run's count) when one is on record. Rivaluta and Valuta adesso say they are one AI call. A failed run already superseded by a completed one offers that run, not Riprova.
- **Never one keystroke:** ⌘K lists runs last, only with an empty query or one starting "avvia" or "run", and never highlights one on its own; a query that asks for a run lists searches and sections, never listings. A held key never confirms, and a held P, C or X gives one verdict, not one per listing; a delete opens on Annulla.

### Navigation
- **Rail:** ink background, muted labels in semibold body small, lucide line icons at 16px. Hover fills rail-hover and brightens to rail ink. The active item becomes a white chevron tab pointing into the page, in ink text, so selection reads as the pointer arrow.
- **Phone:** six-tab ink bar with 11px labels under icons; active tab in rail ink with a white top bar.

### The Ladder (signature)
The full ten-rung label on the certificate. Bars lengthen from best to worst (38% to 100% width), each a chevron in its rung colour carrying its score band. On the right, a black reversed chevron carries the score, tied to its bar by a dotted ink leader that draws back from the pointer once it lands. The pointer arrives three ways: **printed** (first look at a certificate, or a listing's first score) the rungs wipe on left to right, best first (300ms each, 24ms apart), then the pointer drops from the top rung to its own (340ms plus 42ms per rung, ease-out-expo `cubic-bezier(0.16, 1, 0.3, 1)`); **rescored** (same listing, new score) the pointer travels from the old rung to the new one in 760ms on `cubic-bezier(0.65, 0, 0.35, 1)` while its number counts across; **switched** (j/k to another listing) it slides in 220ms ease-out-expo. Unscored: every bar hatched, a dashed N.D. box in place of the pointer. On the certificate the ladder sits beside the verdict when its section is at least 560px wide, and above it, full width up to 22rem, when narrower: the signature never shrinks to the compact version there. A compact 13px-row version (bars from 48%, labels at the 11px floor) serves the narrow columns of Confronta.

### The Ladder Filter (signature)
The same ladder as a control: ten notched chevrons chained left to right, each labelled with its floor. Picking a rung keeps that rung and everything better at full strength and tints the rest; an N.D. toggle beside it switches hatching on or strikes it out. On the phone the chain stretches across its row, so each rung (its chevron is its hit area) is as wide as the row allows.

### Selection Pointer
The selected feed row takes a pale wash and a small ink triangle at its right edge, pointing at the certificate it opened. The feed is one tab stop: Tab lands on the open row, j/k or the arrows move it (focus follows), and only the open row's triage toggles take a tab stop.

### Milhouse (the AI layer)
- **Mark:** original thick round glasses (two circles, a bridge, short temples). As the product mark, the lenses show the ladder in four bands (r-0, r-3, r-5, r-9) with rail-ink rims. As the AI's face, the lenses are lens wash.
- **Avatar:** glasses on a 28px Milhouse-blue disc, signing each answer above a Milhouse-ink name line.
- **Chat counter:** an empty chat reads from the top, the pinned listing first, and shows the glasses on a 96px Milhouse-blue disc (pushed up once as he greets) and the starter questions as a ruled list headed "Domande allo sportello", each row ending in a small chevron that turns mh-ink on hover or focus.
- **Motion:** while working, the glasses push up (2.2s loop) as a white glint crosses the lenses; loader lines fade up (350ms); the "ci pensa su" label breathes in opacity (1.6s) while the reasoning stays folded until opened; a block caret in mh-ink blinks at the end of a streaming answer.

### The Verbale (Milhouse's report)
After every run Milhouse files a verbale: the run's facts, signed and stamped like a ministerial form. It is built only from the run itself (listings examined, how many still to look at, the best score, how many reach 60, or the cause of a failure); it never invents a claim and makes no AI call. One line of his voice sits above the facts, picked by outcome (a strong match earns "Tutto va per il verso di Milhouse!", nothing green earns "Ho riletto tutto, giuro.") and by run number, so it varies between runs but never on reload.
- **Sheet:** at the head of a finished run: the Milhouse avatar, "Verbale n. 8 · F.to Milhouse" in mh-ink, his line in body ink, then ruled rows (Annunci esaminati with "X trovati per la prima volta, Y già noti" — only the count for runs made before 2026-10-11, whose split is not on record —, Valutazione AI when scores went missing, Il migliore with its score chevron, Da 60 in su only when a listing of the run has a score, Esito).
- **Not scored:** a run that finished while the AI scored none, or fewer than it failed, is not filed as seen. His line says so ("non sono riuscito a valutarne nessuno dei 5"), the Valutazione AI row reads "valutati 0 su 5" with the cause most failures share and its remedy beneath, the run page marks Analisi AI failed and the runs list adds "· non valutati". The count comes from the run's log ("X scored, Y failed") when it has one, otherwise from the run's listings; a crash with no readable cause is called an interruption, never a guessed cause.
- **Stamp:** a double-ruled rubber stamp tilted -6deg in the run outcome's ladder end ("VISTO" on r-1, "INTERROTTA" on r-9) with the date and run number. A run that was not scored stamps "NON VALUTATI" in ink-2 on the N.D. hatch: no scores, no ladder colour. It thumps in once per browser session, then stays still.
- **Strip:** the latest verbale sits above the feed on the lens wash for three days or until archived (×), with "Vedi i N" to filter the feed to the listings that run found or saw again (on the phone its own 36px button under the facts) and the best listing one tap away. A run that was not scored names the count and the cause once, with "Il rimedio" linking to the run. The run-end toast and notification only announce that the verbale is filed; the verdict lives in the verbale, which knows the scores. The one exception is a run that was not scored: its toast is a warning that names the count, the cause and the fix. Clicking a notification opens the verbale, or the run when there is nothing to read.

### Motion
State transitions run 150-250ms on colour, background and opacity. The ladder print and pointer arrival is the signature; everything else explains continuity or confirms an action:
- **One pointer, moving:** the selected-row triangle is a single object that slides from row to row (220ms); the rail's white chevron tab, the phone tab bar's white bar and the triage-tab underline travel to the new section (shared element, 220-240ms).
- **Stamps:** a triage stamp lands like an office stamp, a touch large and askew then pressed flat (280ms); the pressed triage icon pops. Only when the owner just pressed it, never when a feed renders.
- **Scartato:** a rule is drawn through the title (340ms); the row holds its place for 650ms so the stroke is seen, then sinks to the bottom of Tutti. At the desk the selection moves on at once to the next listing still in play (never into the discarded tail, which the next X would restore; failing that, the one before), so the triage loop keeps its place. A listing restored from the tail stays open at its new place. Whether a verdict moves the selection depends on the verdict alone: in Nuovi, P and C keep it, X moves on.
- **Nuovo:** the tag folds away once the listing has been seen.
- **Photos develop:** portal photos fade in from grey the first time they load in a session, over the sheet-2 slot. A missing or broken photo, or the portal's placeholder drawing, stays that plain slot with a house: never the N.D. hatch.
- **Runs:** the rule between phases fills toward the next phase when one finishes (500ms); log lines streamed in after opening settle in (220ms).
- **Ladder filter:** picking a rung switches the chain on or off in a cascade spreading from that rung (16ms per rung).

Reduced motion: loops stop and travel is removed; colour and state changes stay as 120ms fades, stamps and log lines fade in without moving, and JS-driven pointer travel and counting are skipped.

## Do's and Don'ts

### Do:
- **Do** give every score a ladder rung and every rung its own label colour (white on r-0, r-1, r-9; ink elsewhere).
- **Do** mark selection with the black pointer: the ladder pointer, the row triangle, the white chevron tab on the rail.
- **Do** set compared numbers in tabular figures with their units, and the certificate's headline numbers at the figure size.
- **Do** render missing or failed AI scores as N.D. hatching, and keep discarded listings visible, struck through.
- **Do** keep Milhouse blue for the AI's voice, and play the glasses gesture while the AI works.
- **Do** keep sheets flat, ruled with hairlines, at 2-3px corners.

### Don't:
- **Don't** use a ladder colour as decoration, branding, a link colour or a generic success/error colour outside run outcomes.
- **Don't** fill N.D. with grey-green or any rung colour,.
- **Don't** put Milhouse blue on navigation, selection or non-AI controls.
- **Don't** introduce a second typeface or a fluid display size.
- **Don't** add shadows to resting sheets or round corners beyond 6px.
- **Don't** reproduce the Simpsons character's artwork; the glasses mark is the only reference.
