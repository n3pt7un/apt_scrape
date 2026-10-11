---
version: 1
slug: "src-web"
primary_target: "src/web"
related_targets: []
---

## Scope

The whole React SPA in `src/web` (Annunci feed + detail, Mappa, Confronta, Ricerche, Run, Preferenze). Visitor mode: **Operate**.

## Audience and job

One owner hunting a rental (Bologna). Desk: tune configs, launch and watch runs, deep triage, ask the AI about a listing. Phone: check what the last run found and triage fast. Success: a matching listing spotted and judged within seconds of a run finishing; failures (scrape, enrichment, AI scoring) visible as failures.

## Constraints

- Italian UI. Light theme (certificate world).
- Data is sparse: many listings lack detail fields; AI verdict `Error` must render as "non valutato", never as a low score.
- Components: shadcn/ui base plus libraries indexed on 21st.dev (prompt-kit, Magic UI, Motion Primitives), restyled to this world. 21st.dev's own registry needs auth; the same components install from their public registries.
- Chat is ephemeral (no persistence). Streamlit stays alongside, untouched.

## Direction contract

THESIS: Every listing is graded like an Italian APE energy label: its match score sits on a fixed ten-rung green-to-red ladder, and a black pointer arrow marks where it lands, so a verdict reads before a number does. Refuses the white SaaS dashboard with a blue accent, photo-card grids, star ratings and percent badges.

OWN-WORLD: A ministerial certificate. White sheets on a cool paper ground, ink #1D1D1B, Titillium Web (the Italian public-administration face) for everything, one-pixel ink hairlines, ruled tables. Colour comes only from the ladder (A4 deep green through G red), always carrying a score or an energy class, never decoration. The chevron (a bar with an arrow tip) is the shape for scores, energy classes and filter rungs. Selection is the black pointer arrow. An ink-black navigation rail frames the sheet. Missing or failed scores are grey diagonal hatching marked N.D.

STORY: Open the app and the newest listings are already ranked by match, unseen ones marked. Narrow by ladder rung, triage state, search; open one and read its certificate: price, size, rung, the AI's reason against your criteria. Ask the AI, mark it preferito/scartato/contattato, compare two or three, see them on the map, jump to the portal. Launch a run and watch it live; write a new search; edit the criteria the AI judges with.

FIRST VIEWPORT: Desktop 1440. Left: ink rail (wordmark, Annunci, Mappa, Confronta, Ricerche, Run, Preferenze; live run status at its foot). Main top: toolbar with search, ricerca select, the ladder filter (ten clickable rungs), triage tabs (Tutti, Nuovi, Preferiti, Contattati, Scartati) and the primary "Avvia run". Below: two panes. Feed table ~58% (thumb, title + address, €/mese, m², €/m², locali, score chevron right-aligned on a shared column, triage marks; scartati struck through). Detail certificate ~42%: price and size set large in tabular figures, the full ten-rung ladder with the pointer at this listing's rung, AI reason, facts table, chat composer. Phone: feed full width, detail opens as a full-height sheet.

FORM: Classe energetica (APE label ladder), position 1 on the ordered grounded list, chosen by the owner as IMPECCABLE'S PICK over the rolled Affittasi direction; seed key 4f986ee8. Kept disciplines: niente sparisce (scartati struck, never deleted), map pin diameter on a fixed score ramp, tabular figures with real units, j/k keyboard focus moves the detail. Signature interaction: the pointer arrow slides to the selected listing's rung (220ms, exponential ease-out); the toolbar ladder filter is the same object, clickable.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Adaptations (cited after the first finish review)

- The AI chat lives in a "Chiedi all'AI" tab of the certificate: it needs a full-height pane with a pinned composer, and on the phone a tab is the only way to keep the composer reachable.
- The listing photo stays above the facts: thumbnails are often the fastest judgement signal; price, size and the ladder follow immediately.
- "Preferenze" is labelled "Criteri" (page title "Criteri di valutazione"): it names what the page edits and fits the six-tab phone bar.
- The desk shell (icon rail) starts at 768px, the owner's in-app pane width; the split feed + certificate starts at 1024px.

## Unresolved

- None open. Product name settled as MilHouse.
