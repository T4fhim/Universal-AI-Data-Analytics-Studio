# Phase 4 — design-reference analysis and design plan

Status: **analysis + proposal, nothing built, nothing committed.** First written 2026-10-26 from the 29 files in
`C:\Users\mdabu\OneDrive\Pictures\New folder`; **revised twice the same day** as the base theme was narrowed, first to four,
then to the two images now in `...\New folder\theme`. Waiting on the decisions in §9.

> Process note: `plans/two-week-ship-plan.md` says "write no new plan docs". This file exists because the
> design-language work was requested explicitly. Move or delete it freely; it is untracked.

## Revision summary (read this first)

**Final decision (latest instruction):** the two images in `...\New folder\theme` are the core basis of the theme and layout:
**B4** (`da814a0f`, a spec-sheet screen) and **C6** (`81d355ee`, the ImHex hex editor). **C6 is the final layout and theme**; B4
contributes components and information idioms (key/value sheet, quote strip, numbered tabs, editable cell). Where they
disagree, C6 wins (T6). I keep the working name **"Instrument"** for the theme. Everything about it is in **Part T**
(T0–T10, right after §1): measured dock rectangles, a character-cell grid, a measured colour system, and a verified
**"50 % rule"** (every category fill is its key colour at 50 % opacity over the pane, all ten pass 4.5 : 1 for text).

**What changed since the first version of this file:**
- **B1** (Bloomberg-style 4-pane) and **B8†** (signal screen), which were in the base set earlier, are now **stepping stones**,
  as are the other 25 images: sources of *new graph and visualisation types*, re-skinned in the C6 language (T9). They no
  longer set the theme. The amber/crimson chrome of B1/B8† is dropped; B4's amber survives only as the editable-cell fill and its
  crimson only as an alert bar (T6).
- §3.8, §4 (roles + priority changes), §5 (concept, packs, tokens), §6, §7 and §9 were rewritten to match.
  Sections not mentioned (§2 per-image notes, §3.1–3.7 cross-cutting findings) are unchanged first-pass notes; where they describe
  a modern-dark default (ember/lime accent, rounded cards) they apply to **optional skins only**.
- New findings: text contrast in C6 is 8–14 : 1 almost everywhere, but **non-text contrast is weak** (focus border 1.79 : 1,
  scrollbar thumb 2.36 : 1) and C6 has **only one chart** (T8, T10).
- **All 11 open questions were answered** (§9): fixed layout with resizable/minimisable panes, blue-only chrome with amber editable
  cells and one crimson alert bar, dark only, base theme + Tier 1 charts before launch, 11 px / 16 px density exactly as C6,
  OpenRouter as the chart reference, headless primitives instead of shadcn, all four niche charts kept (Tier 3), images stay local.

## 0. How this was produced, and how far to trust it

- Every image was opened and read at full size. Tall images (OpenRouter 1763×16101, UTA 1200×8176, Bournemouth
  1200×2396, Churn 1200×2133) were cut into overlapping tiles. Both GIFs were sampled at 5 frames each.
- **Measured** (pixel statistics, ±2 per channel because of 4-level quantisation): backgrounds, accent hexes,
  the OpenRouter categorical palette, WCAG contrast of the repo's current tokens. Marked `≈#hex`.
- **Eyeballed** (not measurable from pixels): font families, stroke widths, corner radii, spacing. Marked
  "looks like". Treat font names as candidates to verify, not facts.
- **Caveats:** Habits (A8) is a photo of a phone, so its colours are skewed by lighting and glare. Churn (A1) and
  E-TechInvest (A4) look AI-generated: some text is garbled and values are illustrative. Both GIFs are low
  resolution and I did not measure animation timing. I could not tell which numbers in any image are real data.
- Several references are third-party product screenshots (Bloomberg ×5, Interactive Brokers, Binance/TradingView,
  Finviz, ImHex). They are inspiration only. Do not copy their layout pixel-for-pixel and do not use their marks.
- **Part T measurement limits:** C6 (ImHex) is close to native size, so its px values are credible; B4 is downsampled, so only
  ratios are used. Font identities stay candidates because I did not match glyph shapes. Fills and edges were measured on JPEG
  data (±3 per channel).
- **Folder state changed mid-task:** `theme/` held four images, then three, then the final two (B4, C6). Every statement about
  "the base" in this file refers to the latest state.

## 1. The corpus in one screen

29 images fall into four families. They disagree on purpose, which is useful: the "average" is not one look.

| Family | n | What it is | Dominant feel |
|---|---|---|---|
| **A. Modern dark product UI** | 10 | SaaS/crypto/AI dashboards, a rankings site, mobile apps, brand posters | near-black, one hot accent, rounded cards, soft glow |
| **B. Finance / stock terminals** | 9 | Bloomberg ×5, Interactive Brokers, TradingView-style, "Holy Grail" trader, Finviz map | black, amber/green/red, ultra-dense, hairline panes |
| **C. Vintage / scientific / retro-technical** | 6 | 1977 CRT plot, terminal UI demo, ASCII roguelike, IPv4 Hilbert map, weather sounding, hex editor | black, phosphor yellow/green/red, monospace, vector-ish |
| **D. Editorial infographic / print** | 4 | Felton-style annual report, Bournemouth fact-boards, car-brand infographic, Nobel mosaic | slate/black/white, 3-colour discipline, big numerals, rules |

Two things dominate: **dark backgrounds** (27 of 29; only the Nobel mosaic is white, and the SUI mock sits on light
grey around dark phones) and **a data palette that is saturated, not pastel** (the OpenRouter hues are the
clearest example).

## Part T — Final base: C6 layout and theme, B4 as the second core

Everything in Part T was re-read at 2–3× zoom and measured with pixel scans. Convention: `≈` = measured (±3 per channel, JPEG
noise); **(derived)** = computed from measured values; **(inferred)** = deduced, not measurable; **(proposal)** = my recommendation,
not in the image.

### T0. The decision and what each image contributes

Your latest instruction: `theme/` holds exactly two images, **B4** (`da814a0f`) and **C6** (`81d355ee`); they are the core basis,
and **C6 (the ImHex screenshot) is the final layout and theme**. So:

| | Role | Why it matters |
|---|---|---|
| **C6** ImHex hex editor, 1199×702 | **Final layout + theme.** Dock geometry, chrome, tabs, tables, colours, type, status strip, hex/region view, code well, plot well | Close to native size **(inferred)**: ≈6.3 px character advance, 16 px table rows, the proportions of a real tool |
| **B4** spec sheet, 736×522 (dated 5-Apr-2016) | **Second core: components and information idioms.** Key/value sheet, quote strip, numbered tabs/sections, three-column sheet, editable cell | Downsampled, so only ratios are trusted |
| B1 (4-pane), B8† (signal screen) | **Stepping stones** (no longer base). Source of tile heat grid, signal matrix, legend/axis flags, stacked panes, chord | Re-skinned in the C6 language (T9) |
| All other images | Stepping stones or optional skins (T9, §10) | |

**Where C6 and B4 disagree, C6 wins.** The conflicts and my resolutions are listed in T6; the two that need your confirmation
are the amber and crimson of B4 (decision 2 in §9).

### T1. The shared DNA, and what is unique to each

Shared by B4 and C6 (so these are the theme's non-negotiables):

1. **Panes with a title/tab bar**, no cards, no shadows, radius 0–3 px.
2. **Near-black canvas in three or four flat greys**, 1–3 px gutters, 1 px borders.
3. **Selection = a flat blue fill** (tab, radio, selected state).
4. **Table/sheet rows**: header band, label column + value column, right-aligned numerals, hairline row separation.
5. **Monospace type with tabular figures**, one size per pane; weight is not used for hierarchy.
6. **Dense rows** (C6 16 px with ≈11 px text; B4 ≈19 px rows) and zero outer margins.
7. **A footer/status strip** carrying machine state (C6: FPS, time, memory; B4: contact lines, timestamp).

Unique to **C6** (and therefore the layout): docking with focused/unfocused tab colours, menu bar + toolbar, zebra tables, a
**character-cell hex grid with region colours**, line-numbered code well, plot well, slim scrollbars, 17 px status strip.
Unique to **B4**: numbered tabs/sections (`1)`, `3)`, `7)`), a two-row quote strip, a three-column sheet, amber labels and an
amber editable cell, a crimson title bar, an embedded mini chart.

### T2. Geometry and proportions (C6 measured, ≈1:1 px; `ch` = character advance ≈ 6.3 px)

**Window 1199×702.** Layout map with measured rectangles:

```
x:   0 ............ 523 | 526 ......... 822 | 825 ............ 1198
y:   0 +-------------------------------------------------------------+
    36 | Chrome band: menu row + toolbar row, one flat colour (36 px)  |
    37 +--------------------------+------------------+---------------+
       | Hex editor (tab 14 px)   | Data Inspector   | Pattern editor|
       | 523 x 444  (43.6 %)      | 296 x 444 (24.7%)| 374 x 320     |
       |                          |                  |   (31.1 %)    |
   357 |                          |                  +---------------+
   359 |                          |                  | Data          |
   481 +--------------------------+------------------+ Information   |
   483 | Pattern Data (table)  823 x 197   (31 % of dock height)      | 374 x 321
   680 +--------------------------------------------+---------------+
   683 | status strip: separator 2 px, strip 685-701 (17 px)          |
   701 +-------------------------------------------------------------+
```

| Measure | Value | In rows / chars |
|---|---|---|
| Dock area | y 37–680 = 643 px (91.6 % of window) | |
| Columns | **43.6 / 24.7 / 31.1 %** (523 / 296 / 374 px) | ≈ 1.75 : 1 : 1.26 |
| Left two columns, rows | **69 / 31 %** (444 / 197 px); the bottom pane spans both | ≈ 2.25 : 1 |
| Right dock, rows | **50 / 50 %** (320 / 321 px) | |
| Gutter | 2–3 px; 1 px border `≈#424146` on the focused pane, `≈#212026` otherwise | |
| Chrome band | 36 px | 2.25 rows |
| Tab | 14 px high; width = text + ≈13 px each side ('Hex editor' = 10 ch = 63 px → tab ≈ 89 px); top corners ≈3 px | |
| Table row pitch | **16 px** | **2.5 ch** |
| Table header | 14–15 px | ≈ 0.9 row |
| Hex-grid row pitch | **12 px** (dense mode) | 1.9 ch |
| Code line pitch | 12 px | |
| Status strip | 17 px (+2 px separator) | ≈ 1 row |
| Scrollbar | ≈9 px, thumb `≈#4f4f50` | |
| Hex byte cell | **3 ch = 18 px** (two digits + separator); group gap +8 px; 16 bytes per row | |
| Address column | `000000:` + space = 8 ch = 50 px at x 6 | |
| ASCII twin column | x 379–497, 118 px for 16 glyphs ≈ 7.4 px each | |
| Pattern Data columns | Name 24 % · Colour 5 % · Offset 19 % · Size 7 % · Type 12 % · Value 33 % | |

**The whole UI sits on a character-cell grid**: widths are multiples of `ch`, row heights are 2.5 ch (table) or 1.9 ch (dense
grid). On the web that suggests sizing in `ch` and `rem` rather than px, and it keeps the hex/cell grid pixel-clean.

Rules to carry over (scale-free):

1. Primary pane ≈ 44 % of the width; two secondary columns ≈ 25 % and ≈ 31 %.
2. Top work area ≈ 69 % of height, a full-width table/log pane ≈ 31 %.
3. The right column splits in half: an editor over a plot.
4. Gutters are hairlines (2–3 px); **there is no margin around anything**.
5. One flat chrome band (36 px) and a 17 px status strip frame the dock.

**B4 geometry (ratios only, original size unknown):** three content columns **30 / 33 / 33 %** with ≈5 px gutters; tab and
header strips ≈0.8 × row; two-row quote strip ≈2.5 rows; section header bars ≈0.85 row; key/value rows 1 row (≈19 px at 736 px wide).

### T3. Colour (C6 measured, then B4)

**C6 surfaces and chrome**

| Role | Hex | Notes |
|---|---|---|
| Chrome band, tab strip, title bars | `≈#252525` | one flat colour for menu, toolbar and tab strips |
| Pane content | `≈#151618` | the default panel |
| Well (code editor, plot) | `≈#111111` | one step below the pane |
| Well frame | `≈#262626` | |
| Table header row | `≈#303030` | |
| Zebra alternate row | `≈#202325` over `#151618` | +≈11 lightness steps |
| Status strip | `≈#151618`, separator `≈#2c2c30` | |
| Pane border | focused `≈#424146`; unfocused `≈#212026` | |
| Scrollbar | track `≈#0e0e0e`, thumb `≈#4f4f50` | thumb vs track only 2.36 : 1 |

**C6 blue family (the single accent)**

| Role | Hex |
|---|---|
| Focused active tab | `≈#2e6aac` (white text 5.57 : 1) |
| Unfocused active tab | `≈#22416c` |
| Inactive tab | `≈#101824` |
| Field / combo box | `≈#243854`; arrow button `≈#2e527e` |
| Button (enabled) / (disabled) | `≈#264a72` / `≈#1c3050` |
| Radio selected / unselected | `≈#3d97f8` (6.02 : 1 on pane) / `≈#1c3050` |
| Data line (entropy plot) | `≈#4d6fa9` (3.74 : 1 on the well: passes 3 : 1 for graphics only) |
| Colour-preview well | `≈#4e5a92` |

**Text:** values `≈#e5e6e7` (**14.49 : 1** on pane, 12.27 on chrome, 10.56 on header); row labels `≈#d4d5d7`; hex literals green `≈#39993e`
(5.22 : 1 on the well); line numbers teal and struct keywords blue (eyeballed, not measured).

**The region palette and the 50 % rule (derived, verified).** Swatch key colours (measured): red `≈#d52d21`, green `≈#279f27`, purple
`≈#9963c3`, pink `≈#e775c3`, yellow `≈#c3bd27`. Five more are recovered from the fills (derived): blue `#2376b0`, teal `#23bec8`,
orange `#ef8220`, grey `#838280`, brown `#8f5e50`. **Every grid fill equals the swatch at 50 % opacity over the pane colour**
(`#131416`): predicted vs measured red `#74201c` / `#752121`, green `#1d5a1e` / `#215721`, purple `#563c6c` / `#513f63`, pink
`#7d446c` / `#7b4b6f`, yellow `#6b681e` / `#696927` — within ±9 per channel. Contrast of `#e5e6e7` on these fills:

| Fill | red | yellow | green | purple | pink | blue | teal | orange | grey | brown |
|---|---|---|---|---|---|---|---|---|---|---|
| Text on 50 % fill | 8.55 | **4.64** | 6.63 | 7.44 | 5.76 | 8.09 | 5.10 | 5.69 | 6.98 | 8.47 |
| Swatch on pane | 3.64 | 9.16 | 5.24 | 4.25 | 6.66 | 3.70 | 7.99 | 6.80 | 4.72 | 3.35 |

All ten pass 4.5 : 1 for text on the fill (yellow is the closest) and 3 : 1 for the swatch as a graphic. This is the theme's most
reusable idea: **a key colour at full strength for a swatch, a line or a legend; the same colour at 50 % behind text**. It also
explains B1's "strong/mild" tile pairs (S1 in T9) and gives every categorical series a text-safe background automatically.

**B4 additions (measured):** amber `≈#ff9f27` (4 samples; 8.83 : 1 on the C6 pane, 9.21 on the well, black text on it 10.06), crimson
`≈#a50f27`–`#b1152d` (white 7.79 : 1), B4's own greys (section bars `#333`–`#393939`, unselected tab `#272121`, selected tab
`#2d4b69`/`#274b75`, which C6's blue replaces), teal mini-chart fill, white values `≈#dddddd`.

### T4. Typography and the character grid

- **One monospace face, one size per pane.** C6's measured advance is ≈6.3 px and glyph height with descender ≈12 px, i.e. a
  **≈11 px** monospace in the JetBrains-Mono class **(candidate, not verified)**. Decision 8: **11 px data, 16 px rows, exactly as C6**.
- Hex digits are upper-case, zero-padded, grouped in 8s; the address column ends in `:`; ASCII is a twin column. Units and
  suffixes are small, trailing, same size.
- No bold anywhere in C6. Hierarchy comes from **position (tab strip, header band), colour (accent only for selection) and
  alignment**, not weight or size. B4 uses bold only for the quote strip price.
- Title Case for tabs and buttons (`Hex editor`, `Auto evaluate`), sentence case for rows, lower-case identifiers as-is.
- Right-align numerals, left-align text; never centre a data column.

### T5. Components (what to build once)

C6-derived (the final theme):

| # | Component | Anatomy and rules (measured where noted) |
|---|---|---|
| K1 | **Pane** | Tab strip doubles as the title bar; × close at the right end; 1 px border (focused `#424146`); no radius except ≈3 px on tab tops; no shadow |
| K2 | **Dock layout** | 3 columns + a full-width bottom pane + a right column split 50/50; 2–3 px resizable gutters; tabs can group panes; layout is persisted |
| K3 | **Tab strip** | 14 px; three states: focused-active `#2e6aac`, unfocused-active `#22416c`, inactive `#101824`; optional B4 numbering `1)` |
| K4 | **Chrome band** | 36 px, flat `#252525`: menu text row, then a toolbar row of 16 px icon buttons and a dataset combo |
| K5 | **Field / combo** | `#243854` fill, arrow button `#2e527e`, no border radius beyond 2 px; label to the left in text colour |
| K6 | **Button and radio** | Square buttons `#264a72`/disabled `#1c3050`; radio dot `#3d97f8` selected / `#1c3050` not; groups laid out inline with 2 ch gaps |
| K7 | **Status strip** | 17 px, key/value pairs with small glyphs (FPS, memory `237.18 MB / 31.95 GB`); right side clock/zone |
| K8 | **Table** | Header band `#303030`, 16 px rows, **zebra** `#151618`/`#202325`, sort arrow, column swatch cell, 1 px column rules, expandable rows |
| K9 | **Tree-table** | K8 + expand arrows, indentation 1 ch per level, a colour-swatch column, offset/size/type/value in mono, type names coloured |
| K10 | **Inspector** | Two-column Name/Value K8, then radio groups below (`Little Endian / Big Endian`, `Decimal / Hexadecimal / Octal`) |
| K11 | **Cell grid** | Character grid: address gutter, 16 cells in 2 groups of 8, **3 ch per cell**, 12 px rows, per-region 50 % fills, **ASCII twin column**, header row of column indices, a one-line range/selection readout below |
| K12 | **Code well** | `#111111` well, line numbers in teal, literals green, an "Auto evaluate" toggle and a `264 / 8192` counter beneath |
| K13 | **Plot well** | `#111111` inside a `#262626` frame, 1 px muted-blue line, faint dotted grid at quarter steps, mono tick labels, rotated axis title, slim vertical scrollbar for zoom |
| K14 | **Scrollbar** | ≈9 px, track `#0e0e0e`, thumb `#4f4f50` |

B4-derived (second core; applied inside C6's grammar):

| # | Component | Anatomy and rules |
|---|---|---|
| K15 | **Key/value sheet** | Grey section header bar with a number (`3) Notes`), then rows of dim label + bright value, right-aligned values; three columns 30/33/33 % |
| K16 | **Quote strip** | Two rows of `label value` pairs (label dim, value bright, delta coloured, micro-sparkline) above a sheet |
| K17 | **Numbered sections and tabs** | `1) Contract Information`, `4) Contracts | CT »`; the number is the keyboard shortcut |
| K18 | **Editable cell** | A solid fill (B4: amber `#ff9f27`, black text) marks the one value you can change; everything else is read-only text |
| K19 | **Alert bar** | A full-width solid bar for system-level state (B4: crimson `#a50f27`, white text). Proposal: reserved for errors/blocking states, one per window |

### T6. Where B4 and C6 disagree, and how I resolved it

| Topic | B4 | C6 | Resolution (proposal) |
|---|---|---|---|
| Accent | amber inputs + crimson bar | blue selection only | **C6**: blue is the only chrome accent. Amber survives only as the editable-cell fill (K18) and crimson only as K19 |
| Selected tab | `#2d4b69` | `#2e6aac` (focused), `#22416c` (unfocused) | **C6**, including the focused/unfocused distinction |
| Structure | stacked boxes in 3 columns | docked panes | **C6** docking; B4's sheet becomes a *view inside a pane* |
| Labels | amber text | plain light text | **C6** plain labels; amber only for editable values |
| Tabs | numbered `1)` | un-numbered | **Numbered optional** (K17) because it gives keyboard shortcuts for free |
| Row height | ≈19 px | 16 px | **16 px rows, exactly as C6 (decision 8)**; 12 px only inside the cell grid; one row-height variable so a roomier mode can be added later |
| Font | proprietary terminal face | mono 11 px | **C6** |

### T7. What it means for UADAS (the final layout, mapped)

| C6 pane | UADAS pane (same position and proportions) |
|---|---|
| **Hex editor** (43.6 %, top-left) | **Data grid** — dataset preview. Column-index header (`c00 c01 …`), row-offset gutter, cells filled by **column-type region at 50 %**, twin "preview/null-mask" column, selection readout `Rows 1–200 of 1.2M · selection r12:c3–c5 (3 cells)` |
| **Data Inspector** (24.7 %) | **Inspector** — Name/Value for the selected cell or column (type, nulls, min, max, distinct), then radio groups (representation: Decimal / Scientific, Locale) |
| **Pattern editor** (31.1 % top; tabs Pattern editor · Bookmarks · Strings) | **Rule editor** — cleaning/stage parameters as a line-numbered well with Auto evaluate and a `processed / total` counter; tabs: Rule editor · Saved views · Text columns |
| **Data Information** (31.1 % bottom, "Entropy") | **Profile plot** — distribution/histogram/density of the selected column, same plot-well style |
| **Pattern Data** (full-width bottom) | **Schema / lineage tree-table** — name, type swatch (the column-type colour), position, size, type, value; derivation shown as expandable parents |
| **Chrome band** | File / Edit / View / Help + toolbar (open, save, undo, redo, **dataset combo**) |
| **Status strip** | Job state, memory, version, UTC time |
| B4 sheet | A **Dataset card** or **Result detail** view inside the Inspector or a tab of the right dock |

**Five areas (Data · Clean · Analyze · Visualize · Report) and a dynamic layout — decision 3.** The layout, palette and chrome stay exactly
C6's; there is no extra navigation control. Instead every pane is **dynamic**:

- **Resize** — drag any gutter; sizes persist per user. Defaults are the T2 proportions (43.6 / 24.7 / 31.1 % wide, 69 / 31 % tall, right column 50 / 50).
- **Minimise / collapse** — each pane's tab strip has a collapse control; a collapsed pane becomes a 14 px tab strip (title only) and its
  neighbours take the space. Double-clicking a tab strip collapses or restores it.
- **Maximise** — a pane can fill the whole dock area (and restore), so a table, list or chart can be enlarged on demand.
- **Tab groups** — panes that share a slot (Rule editor · Saved views · Text columns) switch by tab, as in C6.
- **The five areas** are views the user opens from the **View menu** (and numbered shortcuts `1`–`5`): *Data* focuses the data grid and
  schema tree, *Clean* the rule editor and inspector, *Analyze* the inspector and profile plot, *Visualize* maximises the chart pane,
  *Report* opens the sheet/export view. Each only **reveals, focuses or resizes** existing panes; it never swaps in a different
  layout, so what the user sees always looks like C6. *(This is my reading of decision 3; the exact pane choices per area are a
  proposal.)*
- **Launch scope:** resize, collapse, maximise and tab groups. Drag-to-rearrange (free docking) comes after launch (decision 1).

### T8. Accessibility and Impeccable fit

- **Text contrast is excellent**: `#e5e6e7` is 14.49 : 1 on the pane, 12.27 on chrome, 10.56 on the table header, 8.23 on the unfocused tab.
  The weakest text pair is the 50 % yellow fill (4.64 : 1) and white on the focused tab (5.57 : 1) — both pass.
- **Non-text contrast needs work**: the pane focus border is only **1.79 : 1** (unfocused 1.12), the scrollbar thumb **2.36 : 1**, and the entropy line **3.74 : 1**.
  The web version needs a visible focus ring (≥3 : 1) and a stronger thumb; keep the faint borders as decoration only.
- **Colour-only meaning**: region colours must always be paired with the text/value (C6 already prints the bytes and a swatch column); never let a fill carry state alone.
- **Hit targets**: 16 px rows and 14 px tabs are below WCAG 2.2's 24 px target guidance (SC 2.5.8) for interactive controls; decision 8 keeps 16 px rows and 11 px text, so compensate with `rem`/`ch` sizing (browser zoom scales the layout), invisible ≥24 px hit areas on small controls, and a single row-height variable.
  The repo's `a11y-rules.json` holds structural rules only (names, focus, shortcuts, tab order) and no contrast or size thresholds, so WCAG defaults apply; its two other a11y files are still unread.
- **Keyboard**: docked panes need focus order, a way to move/resize panes by key, and numbered shortcuts (K17).
- **Impeccable's craft floor:** C6/B4 avoid nearly everything the floor refuses (same-size cards, hero-metric template, kickers, gradient text, glass, soft-shadow rounded rectangles).
  Pin in `DESIGN.md` as intentional: monospace (it is data), dense rows, zebra, solid-colour fills at 50 %, and the lack of a hero metric. Fewer pins than any other family needs.
- **Licence/trade dress:** ImHex is an open-source project; **check its licence and copy no code, icons or assets** — we take layout and colour principles only. B4/B1/B8† are Bloomberg-style screens: do not reproduce `<GO>` strings, function codes, wordmarks or screen compositions.

### T9. Stepping stones: how everything else feeds the final theme

**Re-skin rules** for any imported chart or component: flat (radius 0–3 px), hairline borders, panel greys from T3, **blue as the only
accent**, categorical colours from the region palette at full strength for lines/legends and **at 50 % behind text**, monospace
numerals, no glow, no decorative gradients, a one-line readout beneath (the C6 range/selection line).

| Source | What to add to the app | In the C6 language |
|---|---|---|
| **B1** 4-pane (now a stepping stone) | **S1 tile heat grid** (5 × N tiles, name · value · delta · sparkline), **S3 legend-as-readout** table, **axis flags** and a cyan date chip, area-to-baseline line, in-table 2-segment sparklines, **S5 chord** + ranked table, 4-pane workspace split (54/46 × 44/56) | Tiles use the **50 % rule**: strong tile = key colour at 50 %, mild tile = key colour at ≈25 %; text `#e5e6e7`; selected tile = black fill + light border |
| **B8†** | **S2 signal matrix** (checks × windows), status chips, **S4 stacked shared-axis panes** (4 : 2 : 1), candle + indicator set | Chips and matrix cells as 50 % fills; markers by shape (▲▼◆●) |
| **A6 OpenRouter — the chart reference (decision 9)** | Stacked / 100 % stacked columns (+ Linear/Log, Absolute/Percentage, hatched last bucket), treemap, dumbbell on a log axis, scatter with Pareto + pin, ranked list | Square bars with 1–2 px gaps, controls as K5/K6, series colours from the region palette at full strength, fills behind text at 50 % |
| **A1 / A2** | Area line with end dot, donut + legend table, histogram with value labels, KPI mini-charts | Area to baseline, no glow, donut as flat ring + K8 legend |
| **A3 / A4** | Hex-bin map, gauge, **matrix heat map with numbers**, alert callouts, log terminal | Matrix → cells with numbers (K11 style); gauge flat; log = a K8 table with level colours |
| **A5 mount** | Small multiples on a shared axis, capsule range bars, strip plot, terrain contour | Shared-axis panes (S4), squared range bars; terrain Tier 3 |
| **A7 SUI** | Hatch/stipple pattern fills, waffle, barcode distribution bar, monochrome heat map | Pattern fills **kept** as the colour-independent channel; waffle/heat map as K11 grids |
| **A8 Habits** | Calendar / contribution heat map | K11 grid, 12 px cells, one key colour per series |
| **A9 Resource Overview** | Bracket tags `[ label: value ]`, thermal stacked columns | Bracket tags = K16 chips (terminal-native) |
| **A10 HydraDB** | Pixel-square scatter/tree | Optional Tier 3 canvas chart |
| **B2/B3/B5/B6/B7** | Candles + volume, Bollinger/EMA overlays, normalised comparison, dot-range rows, in-cell data bars | Finance-flavoured chart set |
| **B9 Finviz** | Sector → ticker treemap, size-scaled labels, diverging colour | 50 % fills on a flat treemap |
| **C1–C5** | Phosphor plots, TUI widgets, glyph grid, Hilbert map, skew-T | Optional **Phosphor** skin; char-cell renderer fits K11 |
| **D1–D4** | Mirrored step chart, pie grid, pictogram bars, radar, mosaic, timeline | Optional **Editorial** report skin; individual charts in the C6 style |

Dropped from the base: rounded cards, glow/bloom, fade-to-transparent decorative fills, lime/ember/orange brand accents,
big-number "hero metric" tiles, the amber/crimson chrome of B1/B8†, LCD/pixel display faces.

### T10. Risks and open questions specific to the final theme

- **Two images, one chart reference.** C6 contains a single plot (entropy). There is **no base reference for multi-series charts,
  legends or stacked panes**; those come from stepping stones and need a design pass of their own.
- **Onboarding vs density.** A dock of five panes can intimidate someone who has just uploaded a CSV. Plan a calm first-run state
  (a single pane with one field and a hint) and a responsive fallback (panes → tabs below ≈900 px). C6 is desktop-only.
- **Docking on the web is real work.** Decision 1 sets the first cut: a fixed arrangement with resizable gutters, collapse/maximise and
  tab groups; free drag-docking later. Decision 11 drops the ship plan's shadcn/Tailwind defaults (rounded cards fight this theme) in
  favour of headless primitives with our own flat CSS.
- **Light mode:** decision 5 is dark only, so there is no light variant to derive.
- **The 50 % rule on a light surface** would need re-checking if a light mode is ever added; not needed now.
- **Fonts and sizes:** decision 8 fixes 11 px / 16 px as in C6. The font family is still a candidate until chosen and licence-checked (T4);
  the accessibility trade-off is recorded in §9.
- I read `workspace-layout.json` only down to its dock definitions (Dataset Explorer left, Console/Log tabbed bottom, Chart/Data
  Table tabbed right, Assistant split below): that arrangement is compatible with C6's dock but is **not the same**.

## 2. Per-image breakdown

> Note (after the final decision): **C6 and B4 are the base**; Part T supersedes these first-pass notes for them. Every other entry
> (A, B1–B3, B5–B9, C1–C5, D) is a **stepping-stone** note, mined in T9 for new graphs and visualisations.

Format: *what it is* — **UI elements** — **style/background** — **palette (measured)** — **visualisations** —
**layout/harmony note**. File prefix in brackets is the first 8 characters of the filename.

### Family A — modern dark product UI

**A1 · Churn Prediction dashboard** [7057570b] — browser-framed SaaS page, 1200×2133.
- UI: macOS traffic lights + URL bar; left sidebar with small-caps group labels (OVERVIEW / ANALYTICS / CUSTOMERS /
  AUTOMATION / SETTINGS), line icons, active row = orange-tinted pill; H1 + subtitle; date-range button + Filters button;
  4 KPI cards (label, small orange icon top-right, big number, ▲▼ delta with "vs prior period"); "Daily" select;
  info (i) icons on card titles; table with avatar + name/email, plan/price, red probability pill, relative dates,
  risk-factor chips (brown tint, orange text), "⋯" row menu; user card pinned bottom-left; footnote captions under charts.
- Style: warm-charcoal dark, 1px borders, ~12px radius, no shadows, one accent.
- Palette: page ≈`#161616`, card ≈`#1a1a1a`, active nav ≈`#222226`, accent orange ≈`#f2621e`, success green ≈`#4eaf68`,
  amber ≈`#f3aa32`, danger red (pill) deep brick. Text: primary ≈`#d8d8d9`.
- Viz: orange area line (gradient to transparent, glowing end dot, 0–100% y); donut with centre total + legend rows
  with proportional bars (red/orange/amber/green); vertical histogram with value labels above bars; horizontal
  "impact" progress bars with icons; probability pills.
- Layout: sidebar ≈18% + main. Row pattern **4 KPIs → 1 hero trend → 1 breakdown → 2-up → 1 table**. Equal gutters (~16 px).

**A2 · Vaultify (crypto yield)** [8de19ce8] — Dribbble-style shot, 1200×900.
- UI: rounded device card on grey; sidebar card (logo, search, nav with nested items marked by coloured squares, "New"
  chip, support/settings, profile card with online dot); date-range pill; **inverted white pill button** ("Ethereum
  Network"); 3 KPI cards each carrying a *mini chart*; range pills (Today / Last week / … / Year, selected = outlined pill);
  table with token icons, green "+$" deltas, outlined status chips (Fixed amber, Flexible green), 3-segment liquidity
  pill bars (green/amber/red), "⋯" menu, hovered row highlight.
- Style: soft near-black cards on lighter near-black, glow on the selected KPI (orange outline + bloom).
- Palette: card ≈`#121212`–`#161616`, orange ≈`#d88552`/`#e8743b`, purple ≈`#6f69cb`, amber ≈`#fbcd72`, green ≈`#22ab6c`.
- Viz: orange noisy line with faint area + **secondary dashed sine-like "54W Trendline"**; crosshair (dotted vertical + dot) +
  tooltip card; KPI micro-charts: orange candle/lollipop bars with glow, purple gradient bars, amber segmented dash-bars.
- Layout: sidebar ≈26% + main; KPI ×3 → hero → table.

**A3 · ORION data visualisation** [3a22871c] — 736×414.
- UI: top nav (Statistics / **Overview** underlined / Dashboard / Analytics), search, 6-cell KPI strip with icon + label +
  number + sparkline/progress/delta; radial gauge card with a bolt icon, 3-row param table with coloured progress lines;
  map card with zoom +/−, locate buttons and range pills (1W 1M **3M** 1Y ALL, selected = solid blue); two bottom tiles
  (one filled bright blue); "Sales Figures" ribbon with orange and blue progress overlays; footer strip.
- Style: navy glass cards ≈`#14142c`, 12px radius; electric blue is the brand.
- Palette: navy ≈`#14142c`, blue ≈`#233299`→`#063afe`, red ≈`#c7273e`, yellow-hot top of the ramp, orange/blue progress.
- Viz: **hexagon-bin heat map** (blue → indigo → dark → red → yellow); 270° gradient arc gauge (blue→cyan) with big
  "64,3 %" and end ticks; sparklines; progress lines.
- Layout: dense strip on top, then **1/3 + 2/3** (gauge+table+tiles | big map), then a ribbon.

**A4 · E-TECHINVEST email deliverability** [4c00b802] — 941×1672, "cyber-ops" look.
- UI: block logo (4 bars white/orange), circuit-trace header and footer with glowing nodes, envelope/lock hero icons;
  5-cell KPI strip with circular outline icons separated by hairlines (total/delivered/spam/bounced/last-updated);
  panels with 1px borders and corner notches, uppercase titles; "HIGH RISK AREAS" warning badge; outlined **alert
  callouts** (triangle icon, red text); domain `select`; key/value list with green check circles; 3 metric rows with outlined
  circle icons; **log terminal** with level colours (INFO green, WARN orange, ERROR red) and a scrollbar; "All Events" select.
- Style: pure black, neon orange, mix of condensed grotesque headings and monospace logs.
- Palette: bg ≈`#040404`, orange ≈`#fa460a` (brand) / hot cell ≈`#e63606`, green ≈`#72be48`, text ≈`#f5f5f5`.
- Viz: **5×5 matrix heat map with numbers inside** (single-hue dark-brown→bright-orange, black cell borders, row/col
  band labels, axis titles); radial score ring "82/100 GOOD"; orange area+line with point dots (y 0–100); **semi-circular
  gauge** with ticks 0/25/50/75/100 % and a green→orange split; metric rows.
- Layout: strip → **2-up (matrix | reputation)** → gauge + metric rows → full-width log. Alerts sit at the bottom of the
  panel they describe.

**A5 · "mount" climbing app** [fd58bb38] — 1200×900.
- UI: pill-segmented top nav (selected = dark pill; primary action = pale-blue filled pill), trip header capsule with
  avatar stack, panel header = round icon button + title + prev/next + "⋯"; "New view" accent link; timeline log with
  circular step markers and detail cards.
- Style: black device bezel ≈`#0a0a0a`, very large radii (~36 px), glassy panels, pastel-lime + pale-blue accents,
  slate-teal outer background ≈`#6f8890`.
- Palette: lime ≈`#d6ee8a`, pale blue ≈`#a6cad2`, orange/red for high intensity, white pins.
- Viz: **steps = rounded bars in two overlaid opacities with a vertical gradient wash and dashed verticals**;
  **respiration = dot/strip plot with capsule outliers in a translucent band labelled max/min**; **heart rate = floating
  capsule range-bars coloured by intensity (blue→lime→orange→red)**; **isometric topographic terrain with a dashed route,
  pins, and a compass ring**.
- Layout: header → **1/3 column of 3 small multiples with a shared 10a–4p axis | 2/3 hero over the log**.

**A6 · OpenRouter "AI Model Rankings"** [Screenshot…openrouter.ai] — the newest reference, 1763×16101 (12 tiles).
- UI: top bar (workspace switcher, ⌘K search, nav with "Rankings" active), segmented section tabs with icons
  (Text/Image/Video/Speech/…; lime underline on the active one), **sticky left rail of anchors** with the active row
  tinted ≈`#121a0a` and lime text, sections each = icon + title + muted subtitle + top-right controls
  (select, **Absolute|Percentage** segmented control, **Linear|Log** toggle, "Show Pareto" switch, "Find a model…" pin
  search), **two-column ranked lists** (rank, logo, name, underlined "by author", value, ▲▼ delta coloured), "Show more"
  expanders, info banner, long-form "How these rankings are measured", footer with link columns, theme switcher
  (sun/moon/monitor), newsletter field + lime button.
- Style: near-black with a faint blue-green cast, hairline rules, no cards-in-cards; a single lime brand accent.
- Palette: page ≈`#020a0a`/`#03080b`, card/select ≈`#0e1216`, **lime ≈`#c6fe02`**, delta green/red.
  **Categorical (measured, in order of prominence):** pink `#fe6ab2`, teal `#02c6a2`, blue `#028afe`, orange `#fe8242`,
  vermilion `#fe4602`, green `#3eb272`, steel-blue `#4682b6`, dark-green `#2e8a56`, orchid `#da72d6`, cyan `#3ee2d2`,
  amber `#feba2a`, yellow-green `#9ace32`, salmon `#f27e82`, slate-violet `#7a6aee`, dark-magenta `#82027e`.
  Treemap group hues: General orange `#fe8242`, Agent violet `#7e6aee`, Code green `#3eb272`, Data blue `#028afe`.
- Viz (12 distinct): **stacked column time series** with a Linear/Log toggle and a **hatched final (incomplete) bucket**;
  **100 % stacked columns** (market share, open/closed, languages, programming, tool calls, images, context length —
  the same component re-skinned seven times); **treemap with logo + label per tile and a legend with shares**; **dumbbell /
  dot-range plot on a log axis** (cost per session, 4 turn-buckets, value labels on every dot); **scatter with pin &
  Pareto** (price vs index score, dots coloured by author); **bubble/scatter** (throughput vs price); ranked lists with
  coloured dot + share.
- Layout: left rail ≈230 px + a ≈1175 px content column. **Every section is the same module**: header / controls /
  chart / 2×5 ranked list. This repeatability is the main harmony lesson in the whole corpus.

**A7 · SUI crypto app (4 phones)** [860170b9] — 736×1308, grey-blue backdrop `#c9d1d3`, screens ≈`#141517`.
- UI: search with `/` shortcut chip, pair/time selectors with icon buttons, titled cards with a range pill ("1M"), big
  number triplets, folder-style category tiles with ± %, asset list with token icons, bottom tab bar, **AI-assistant
  chat** (user bubbles dark mono, assistant bubbles *light* with dark text, inline mini-cards with sparklines, attachment
  + send).
- Style: **monochrome** — greys + white, one mint ≈`#4ec9a0` for positive and a red for negative; **pattern fills instead of
  colour** (hatch, stipple); mono type for numbers and chat, sans for labels.
- Viz: hollow/solid candlesticks with a dotted last-price line and boxed price tag; **grouped bars hatched vs solid**;
  **waffle chart** (square grid, graded opacity, proportional legend); **barcode "distribution bar"** (many thin ticks,
  one segment highlighted) for Holders; **monochrome square-grid heat map** (transactions by week); **smooth area wave
  with tooltip card** (long/short ratio).

**A8 · Habits (iOS, photographed)** [3d135272] — 736×981.
- UI: segmented Single/Weekly/**Yearly**, per-habit cards (icon, name, flame streak, day count, badge), month labels,
  round "+" FAB.
- Palette: empty cells ≈`#4a4e7a`, per-habit hue: blue, violet (+ orange highlights), green ramp (4 intensities), orange,
  pink. Glass cards over a deep navy gradient.
- Viz: **calendar/contribution heat map, one hue per series**, rounded 3 px cells, current day outlined.

**A9 · "Resource Overview"** [19557e6f] — 735×851.
- UI: **square-bracket tags** `[ GPU's: 24 ]` and bracketed legend items, a bracketed row of small squares on top (loading
  / pagination feel), pill selects ("1 day ∨", "Type: A100 GPUs ∨"), uppercase **LCD/dot-matrix display heading**, mono
  labels, panel with a visible grid of 1px cells behind the chart.
- Palette: bg ≈`#040404`, fire ramp red ≈`#bd3024` → orange ≈`#e17848` → amber ≈`#efbd64` → pale yellow, text ≈`#f1f0c8`.
- Viz: **hour-by-hour narrow stacked columns with a thermal (fire) series palette** and tiny gaps.

**A10 · HydraDB poster** [6a621ee0] — 1600×1200.
- UI: pixel-art logo + wordmark, pixel/mono slab headline, **faint vertical column grid**, solid orange corner squares
  `#fe561a`, annotation boxes (square with X) labelled with values, dotted connector lines.
- Viz: **voxel/pixel-square branching "tree"** in heat colours (dark red → orange → yellow → white) — a stylised
  similarity/vector-search or dendrogram; looks like a decorative hero but is a legitimate "dot-matrix scatter" look.

### Family B — finance / stock terminals

**B1 · Bloomberg 4-pane** [31454318] — 648×400. Quadrants: AUDUSD **line+area chart with orange crosshair price line and
Last/Close/High/Low/Average tooltip**; **equity-index table** (grouped Americas/EMEA/Asia-Pacific headers, green/red
numerics, 2Wk micro-column); **chord diagram "Trade Flow"** (country arcs, orange/purple chords) beside a ranked table;
**"Macro Movers" tile heat map** (solid red/green tiles with ticker, %, price, micro-sparkline; tabs Movers/Forex/Sovereign).
Style: black, amber headers/tabs, thin grey gutters, `99<GO>` function hints, orange action buttons.

**B2 · Bloomberg "ALLINONE" + clocks + MOST + IMAP** [62a18fd6] — 1199×1587. **8 world-clock strip** (city in amber with
colour underlines); **3 stacked normalised time-series sharing one x-axis**, each with a boxed legend ("Normalized as of …")
and **end-of-line price flags** (coloured label boxes on the right axis); **area filled between 0 and the line in dark
brick** `≈#5f2922`; **table with in-cell blue data bars** (Value, Val 60'), tabs (Volume/Chg Up/Chg Down/**Value**/Δ AVAT);
**treemap by sector sized by weight, red↔green diverging**, nested sub-industry captions, ±3 legend bar.

**B3 · Bloomberg "DRSK" (Tesla default risk)** [dfa73688] — 735×627. Function-key row (red CANCEL, green keys); window
title; **amber editable input cells** (black text) vs a grey read-only cell; dual-axis line (white probability, green
price) with Track/Zoom crosshair; **category-coloured risk histogram (IG1…IG10: green→yellow→red, selected bar cyan)**;
**dot-range comparison rows** (TSLA cyan dot, Median orange diamond, Wtd Avg magenta diamond on a hairline range);
news ticker band; promo banner.

**B4 · Bloomberg "KOM6" security description** [da814a0f] — 736×522. Spec sheet: blue title bars, numbered section
tags `3) Notes 4) Contracts 5) Price Chart`, month strip, key/value tables (amber labels, white values), **orange highlighted
value cell** `≈#fe9e2e`, radio groups (cyan), mint intraday area chart, tab strip with the active tab in blue `≈#2e4666`.

**B5 · Bloomberg iPad app** [91a00b1e] — 768×1024. Left icon rail with uppercase labels; quote header (symbol, price,
green delta) + Today / Summary key-value columns; range tabs (1d…10y, selected bold); **overlay chips with × and the
series' own colour** (Bollinger Bands, SMA, Dell, Google, HP); **percent-change comparison chart with grey Bollinger band +
dashed mean**; volume bars; tabs (News & Info / Key Statistics / …); news list; bottom ticker with ▲▼ colour.

**B6 · Interactive Brokers TWS "Mosaic"** [fb4eea1b] — 910×510. Blue gradient title bars `≈#0c2d78`, order-entry ticket
(Bid/Ask boxes, BUY/SELL, dropdown chips), quote panel with red price badge, **10-min candles + volume**, **monitor
watch-list with solid green/red %-change cells and round status dots**, activity/trades table, news feed, docking tabs.

**B7 · Binance BNB 4h chart** [1303961e] — 1200×1200. Timeframe bar (active = red), drawing-tool row, **indicator legend
rows with gear/× and live values and ▲▼** (EMA2 orange, EMA4 cyan, EMA10 magenta, EMA60 blue, EMA130 green); **candles + 5
EMA overlays + Fibonacci retracement (23.6/38.2/50/61.8/100 %, dashed white) + Gann fan (green rays 1/8…1/1)**; yellow
circle + dashed vertical annotation; **MACD (histogram green/red + DIF/DEA lines), RSI (cyan, dashed 20/50/80 guides),
KDJ (white J, green K, red D)** — all panes share the time axis and have **price axes on both sides**.

**B8 · "Holy Grail" trader (TATAMOTORS hourly)** [657fbc46] — 1200×720. **Signal matrix** (indicators × lookbacks, cells
N / S[1] / B[1] coloured amber/green on brown); **status chips** (IMPULSE Dn red fill, NEGATIVE CROSS orange, No Trend
white, "NO TRADING ZONE" violet bar); candles with **Bollinger band as filled dark-violet region + dashed edges**, EMA
lines, triangle/diamond signal markers; right-axis **colour-coded price flags**; MACD histogram (blue/violet), ADX with
±DI, volume histogram (yellow). The visual quality is poor (garish, low contrast) but the *information design* — a status
matrix next to the chart — is worth keeping.

**B9 · Finviz S&P heat map** [732aef72] — 1200×1198, slate page `≈#262a32`, huge condensed title.
**Treemap: sector → industry → ticker**, tile area = market cap, **label size scales with tile area**, sector captions above,
industry captions inside a thin header bar, 1 px dark gutters; **diverging scale: red `≈#f6363a` ← neutral `≈#424656` → green**,
saturation = magnitude.

### Family C — vintage / scientific / retro-technical

**C1 · 1977 CRT simulation (GIF, 68 frames)** [5b16ad71] — 450×338. **Dotted yellow vector plot** (`≈#e8c24a`) of a
Lagrangian mesh with a **red/magenta phosphor bloom** in the lower half, framed axes with Hershey-style labels (R-AXIS,
Z-AXIS, title line "CYCLE 1621 TIME 1.78E+00"), vignette, scanline softness; the mesh deforms frame by frame. This is the
canonical *vintage data visualisation* look: monochrome phosphor on black, dotted instead of solid lines, built-in
title/caption block, and motion as time.

**C2 · termui dashboard (GIF, 12 frames)** [097565d6] — 543×374. **Boxes with the title embedded in the border**
(Text Box, List, Sparkline, Gauge, Bar Chart, dot-mode and braille-mode line charts), box-drawing characters, ANSI-16
palette (green `≈#16a61a`, cyan `≈#34b0ba`, red `≈#8c0f11`, yellow, magenta), block sparklines (cyan and red), text gauge
with centred %, **dot-mode and braille line charts**, bars with the value drawn *inside* the bar base, live-scrolling data.

**C3 · Cogmind (ASCII game)** [c9693173] — 550×400. 4 quadrants split by dark-red rules; **cells are glyphs, not pixels**;
effect clouds are **glyph heat maps** (magenta/blue gas, green field-of-view with concentric squares, orange→yellow fire),
grey structure outlines, red hover label strip. Value to us: a "text-mode cell grid" renderer and a quadrant split.

**C4 · IPv4 Census Map (Hilbert curve)** [573db33f] — 600×480. **Space-filling-curve map** of the address space, /8 blocks
labelled by owner, **jet-style rainbow heat** (blue→cyan→green→yellow→red) with a vertical **0–100 % utilisation legend**, a
**prefix-size legend** (green squares sized /8…/24), title + date range, footnote with sample size and source. Black, tiny
labels, extreme density.

**C5 · SHARPpy sounding** [ff3680c7] — 1011×867. **Skew-T log-P** (red temperature, green dew-point, cyan wet-bulb, white
dotted parcel, blue slanted isotherms, grey pressure lines, red height labels), **wind-barb column**, **wind-speed bar
column with layer colours (red/green/yellow/cyan)**, **hodograph (polar rings, colour-coded height segments)**,
theta-E and storm-relative profiles, a dense **parameter table in monospace**, analogue-match tables, **probability
curves** (green/orange/red/magenta lines), hazard label in magenta. Black, saturated primaries, 1 px lines.

**C6 · ImHex hex editor** [81d355ee] — 1199×702. Docked panels with tab strips; **hex grid with a categorical background
colour per parsed region** (green/red/olive/purple/teal) mirrored in the ASCII column; **data inspector** (name/value
table + radio groups); **pattern tree-table** (expand arrows, colour swatch column, offset/size/type/value in mono with
teal types); **entropy line chart** `≈#5b86c5`; status bar with FPS/memory. Useful for a *raw-file inspector* in the import flow.

### Family D — editorial infographic / print

**D1 · Felton-style "communication report"** [7d90ae22] — 1200×960, slate `≈#363a4a`.
- **Four equal columns, each its own colour** (cyan, coral, yellow, light-blue), hairline column dividers, and the **same
  module sequence in every column so rows align across columns**: heading with coloured hairline → big light-weight mono
  numeral → small-caps label + caption → ranked list with a **thin coloured underline as its bar** → paired stats → mirrored
  hourly chart → monthly step chart with value labels → senders/recipients numerals → footer facts.
- Viz: **mirrored step chart (sent above as a coloured line, received below as white-stippled fill)**; **step line with
  value labels at each step**; underline bars; big numerals as the primary "chart".

**D2 · Bournemouth "Propagation #1" fact-boards** [32ad1d8c] — 1200×2396. Black, **only red `≈#fe1a1a` + greys + white**.
Hairline section rules with tiny uppercase labels; **building-footprint timeline map by era**; UK silhouette in red with white
dots and **concentric radius rings**; **paired horizontal bars (grey vs red)** with % labels; vertical bars with rotated
labels; **icon verdicts** (smiley/sad, ✓/✕ in red circles); **bundled spline "streams" down a Jan→Dec axis** (peak-times by
visitor group); **figure-ground street map** (red blocks, grey streets, one white highlighted building) + compass + scale
1:5000 + a **red ribbon elevation profile**; **12 pies** in a 4×3 grid with square legends; **pictogram people with big red
%**; **vertical event timeline with callouts**.

**D3 · "Driven by Brand" infographic** [ca6f5fa1] — 1200×8176. Black, white sans, **numbered sections 01–06 each with its
own accent** (red, orange, yellow, blue, green, red), full-width white rules, **LED dot-matrix map** behind copy.
Viz: **heart-unit rating rows (20 hearts, partial fill, green/yellow/red by tier, score in tier colour)**; **bars ending in
car silhouettes** (3 series: green/yellow/red) with a 0–0.8 axis; **parallel line chart with thick translucent ribbons vs
thin dotted lines** across 23 categories (vertical tick gridlines, rotated labels); **radar (hexagon, 5 series, concentric
dotted rings, boxed axis labels)**; **2×2 perceptual map with brand logos as points**; icon "findings". Each block ends in
a "Takeaways" strip: speedometer icon + accent-coloured title + check-bubble bullets.

**D4 · Nobel nominees & laureates 1901–1964** [92bc03ae] — 1200×667, **white** page, Russian UI.
**Stacked mosaic (year × country) with a 2-letter code in every cell**, teal/green family for Europe and Scandinavia,
beige for US & Canada, pink for Russia, greys for others; **one country highlighted in yellow `≈#fefe3e`**; blue dots =
laureate countries; **tooltip card with portrait + text + nominee ranking**; tab bar (Literature/Peace/Medicine/…),
**Relative | Absolute switch**, gradient legend; year ticks.

## 3. Cross-cutting findings

### 3.1 Backgrounds (measured, most common colour per image)

| Bucket | Hex | Seen in |
|---|---|---|
| Pure/near black | `≈#040404` | A4, A9, A10, B1–B4, B6–B8, C2, C3, C4, C5, D2, D3 |
| Warm charcoal | `≈#161616`–`#1c1c1c` | A1, A2, A5 (bezel `#0a0a0a`), B5, C1 |
| Neutral dark grey | `≈#141414` | A7 screens, C6 |
| Cool navy | `≈#14142c` | A3 |
| Slate | `≈#262a32`, `≈#363a4a` | B9, D1 |
| Blue-green black | `≈#020a0a` | A6 (OpenRouter) |
| White | `≈#fcfcfc` | D4 |
| Light grey surround | `≈#c9d1d3`, slate-teal `≈#6f8890` | A7, A5 (outside the device) |

Panels sit one step lighter than the page in A1/A2/A5/A6, or are separated by a **1 px hairline only** in the
B-family and A4/A9/A10 (no fill change). Both are valid "layering" models; the repo's current tokens only have the first.

### 3.2 Accent colours (measured)

| Accent | Hex | Where | Role in the reference |
|---|---|---|---|
| Ember orange | `≈#f2621e`, `≈#fa460a`, `≈#fe561a` | A1, A4, A9, A10 | single hot accent on black |
| Lime | `≈#c6fe02` | A6 | brand/active state, primary button |
| Electric blue | `≈#063afe`/`#028afe` | A3, A6 | brand, "open" series |
| Amber (terminal) | `≈#fe9e2e` | B1–B4 | headers, editable values, labels |
| IB blue | `≈#0c2d78` | B6 | title bars |
| Red-only | `≈#fe1a1a` | D2 | whole infographic uses red + greys |
| Pale blue / lime pair | `≈#a6cad2`, `≈#d6ee8a` | A5 | pill + steps |
| Phosphor yellow / green | `≈#e8c24a`, `≈#16a61a` | C1, C2 | monochrome-phosphor looks |
| Highlight yellow | `≈#fefe3e` | D4 | "the one thing to look at" |
| Gain/loss | red `≈#f6363a` (B9); green/red candles (B7) | B-family | direction |

### 3.3 Palette roles to define (what the references actually use)

1. **Categorical, 12–15 hues, high saturation, tuned for dark** — A6 is the template (list in A6 above). Order matters:
   pink, teal, blue, orange come first because they are the largest/most frequent series.
2. **Sequential single-hue** — A4 matrix (dark brown → bright orange), A9 fire ramp (red → orange → amber → pale yellow),
   A8 per-habit 4-step ramps.
3. **Sequential multi-hue / "thermal"** — A10 (dark red → orange → yellow → white), C4 jet (blue→cyan→green→yellow→red).
4. **Diverging** — B9 (red ↔ slate neutral ↔ green), B2 (dark red ↔ dark green), A3 (blue ↔ near-black ↔ red ↔ yellow).
5. **Direction/status** — green up / red down with ▲▼ glyphs (A1, A2, A6, B5, B6); amber for caution (A2 chips, A4 WARN).
6. **Tier colouring** — green/yellow/red by threshold (D3 hearts, B3 histogram bins).
7. **Neutral support** — 3–4 greys for "other", grid, empty cells (A8 empty cells, D2 greys, B7 axis).

### 3.4 Typography observed (candidates; verify before choosing)

| Voice | Looks like | Seen in | Use for |
|---|---|---|---|
| Neo-grotesque / geometric sans, tight tracking | Inter, Poppins, Aeonik-like | A1, A2, A3, A5, A6 | UI, headings, tabular numbers |
| Monospace (light for big numerals, regular for data) | Geist Mono / Plex Mono / Akkurat Mono-like | A7, A9, A10, C-family, D1 | numerals, tickers, logs, ranks |
| Condensed heavy display | Bebas Neue / Oswald-like | B9 title, D2 headings, A4 brand | poster/report titles only |
| LCD / dot-matrix / pixel display | custom | A9 heading, A10 headline | one hero line per screen at most |
| Terminal bitmap | proprietary / ProggyClean-like | B1–B6, C2, C5 | terminal skin only |
| Serif italic (footnotes) | — | D3 | methodology notes in editorial reports |

Numerals: **tabular figures everywhere** (A1 KPIs, A6 lists, D1 columns). Small-caps/uppercase micro-labels with wide
tracking are common (A1, A4, A9, D1, D2, D3).

### 3.5 Line, stroke and fill vocabulary

- **1 px hairlines** for panes, rules, grids; **dotted** baselines (D1) and **dashed** trendlines/guides (A2, B7, D2).
- **Pattern fills as a colour substitute**: hatch (A7), stipple (D1), hatched partial bucket (A6). These keep
  meaning when colour is lost, which the repo's a11y contract needs.
- **Gradient-to-transparent area fills** under a bright line (A1, A2, A4, A5) with a **glowing end dot**.
- **Glow / bloom** on selected items (A2 KPI, A4 circuit nodes, A5 capsule bars, C1 phosphor).
- **Bars**: 1–3 px gaps; square (A1, A6), fully rounded capsules (A5), 3 px-rounded cells (A8), narrow "barcode" ticks (A7, A9).
- **Direct labels** on ends (B2 price flags, B7 axis flags, D1 step values, D2 percentages) rather than legends where possible.
- **Both-side y axes** on technical charts (B7); **left-only, muted** on modern dashboards.

### 3.6 Chrome vocabulary (components worth building once)

KPI tile with delta · KPI strip with hairline dividers · panel with title + control cluster · segmented control
(Absolute|Percentage, Linear|Log) · range pills (1W…ALL) · select with prefix label (`Type: A100 GPUs ∨`) · status chip
(outlined / tinted) · outlined alert callout · bracket tag `[ label: value ]` · tab strip (icon + label, lime underline) ·
sticky anchor rail · ranked list (rank, logo, name, "by author", value, delta, colour dot) · table with in-cell bars,
sparkline cells, solid-colour %-cells · key/value spec sheet · signal matrix · overlay chips with × and series colour ·
price flag on axis · tooltip card (with crosshair) · log terminal with level colours · world-clock strip · ticker band ·
chat panel with inverted assistant bubble · timeline with step markers · pin/Pareto toggles · info (i) tooltip on titles.

### 3.7 Layout and harmony: how clusters are arranged

1. **Strip → hero → breakdown → detail** (A1, A2, A4, A5): 3–6 KPIs, one wide time-series, one part-to-whole, then a table.
2. **Repeatable section module** (A6): header / controls / chart / 2×5 ranked list, repeated per metric. Cheapest way to
   make 12 different charts feel like one product.
3. **Aligned columns** (D1): the same module order in every column so row *n* lines up across the page.
4. **Small multiples with a shared axis** (A5, B2, B7): 3 stacked charts on one time axis; legend inside each pane.
5. **Quadrant / mosaic dock** (B1, B6, C3): equal gutters (1–2 px), each pane with its own title bar and "Options".
6. **1/3 + 2/3 split** (A3, A5): a narrow stack of numbers beside one large visual.
7. **Rhythm numbers (approximate, eyeballed):** gutters 12–16 px (A1/A4), 24 px between major blocks; card padding
   16–24 px; KPI card ≈ 120 px tall; panel radius 8–12 px (A1/A4), 20–36 px (A5); control height ≈ 32–36 px.
8. **Alerts live inside the panel they refer to** (A4), never as a global banner.
9. **One accent per view.** Where several hues appear they are *data* (A6), never chrome.

Wireframes of the archetypes to build are in §6.

### 3.8 The two "special" families (revised after the final decision)

- **C6 (the ImHex tool) and B4 (the spec sheet)** are the base — Part T. Their character is exactly the "vintage-technical" one the
  brief asked for: a monospace character grid, dense tool chrome, flat greys, region-coloured data.
- **Stock / terminal screens (B1, B2, B3, B5–B8†, B9)** are **stepping stones**: finance charts, the tile heat grid and the signal
  matrix, re-skinned in the C6 language. Their amber/crimson chrome is dropped.
- **Vintage (C1–C5, D2/D3)**: phosphor-dot vector plots with a caption block, box-drawing TUI widgets, Hilbert/space-filling maps,
  skew-T/polar plots, print-style red/grey infographics are **optional skins** ("Phosphor" for C, "Editorial" for D) and a handful of
  unusual charts. The base already shares their monospace data, hairlines and title/caption habits.

## 4. Visualisation catalogue (everything seen)

Tier 1 = fits the Plotly-only path in the ship plan (D9). Tier 2 = needs a custom client component or heavy Plotly
shaping. Tier 3 = niche, post-launch. The core already registers these chart types in
`uadas_core/visualization/chart_registry.py`: bar, pie, line, scatter, histogram, box_plot, heatmap, bubble, treemap,
radar, waterfall, funnel, and since step 7.4 candlestick ("Reg" below). Plotly-route names are trace types/features to confirm at implementation.

| # | Visualisation | Seen in | Build route | Tier |
|---|---|---|---|---|
| V01 | Line / multi-line | A1, A2, A5, B1, B3, B5 | Plotly `scatter` (Reg `line`) | 1 |
| V02 | Area with gradient to transparent + end dot | A1, A2, A4, B4 | `scatter` fill + shapes | 1 |
| V03 | Step line, mirrored step, value labels | D1 | `scatter` `line_shape: hv`, pattern fill | 2 |
| V04 | Candlestick / OHLC + volume | B6, B7, B8, A7 | `candlestick` + `bar`, subplots | 1 |
| V05 | Indicator panes on a shared x (MACD, RSI, KDJ, ADX) | B7, B8 | `make_subplots` shared x, guides as shapes | 2 |
| V06 | Overlays: EMA/SMA, Bollinger band + dashed mean | B5, B7, B8 | extra traces + fill `tonexty` | 2 |
| V07 | Fibonacci levels, Gann fan, trendlines, markers | B7, B8 | shapes/annotations | 3 |
| V08 | Normalised comparison with fill-to-zero + end price flags | B2, B5 | `scatter` fill `tozeroy` + annotations | 2 |
| V09 | Dual-axis lines | B3, B7 | `yaxis2` | 1 |
| V10 | Crosshair + tooltip card | A2, A7, B1 | hover template + spikes | 1 |
| V11 | Stacked column time series (+ Linear/Log, hatched last bucket) | A6, A9 | `bar` stack, `pattern` | 1 |
| V12 | 100 % stacked columns (re-skinned many ways) | A6 | `barnorm: percent` | 1 |
| V13 | Narrow thermal stacked bars | A9 | `bar` + sequential series palette | 1 |
| V14 | Grouped hatched vs solid bars | A7 | `bar` `pattern` | 1 |
| V15 | Paired horizontal bars (compare vs base) | D2 | `bar` `orientation: h` | 1 |
| V16 | Horizontal progress bars in lists / in-cell data bars | A1, A3, B2, D1 | HTML/CSS, not Plotly | 2 |
| V17 | Histogram with value labels; category-coloured bins | A1, B3 | Reg `histogram`/`bar` + per-bar colours | 1 |
| V18 | Unit / pictogram bars (hearts, people, cars) | D3, D2 | custom SVG | 2 |
| V19 | Floating capsule range bars; strip/dot-range | A5 | shapes or custom | 2 |
| V20 | Dumbbell / dot-range on log axis with labels | A6, B3 | `scatter` markers + lines | 2 |
| V21 | Mini charts in KPI cards (lollipop, bars, dash bars, sparkline) | A2, A3, A7 | tiny SVG | 1 |
| V22 | Barcode / distribution bar | A7 | custom SVG | 3 |
| V23 | Waffle / unit-square grid | A7 | `heatmap` with gaps | 2 |
| V24 | Treemap (diverging colour; categorical with logos) | B2, B9, A6 | Reg `treemap` + customisation | 1 |
| V25 | Donut with centre total + legend rows | A1 | `pie` `hole` | 1 |
| V26 | Pie grid (small multiples) | D2 | `pie` ×12 | 1 |
| V27 | Radial gauge / semi-gauge / score ring | A3, A4 | `indicator` gauge or SVG | 2 |
| V28 | Marimekko / stacked mosaic with cell codes | D4 | `bar` variable width | 2 |
| V29 | Matrix heat map with numbers in cells | A4 | Reg `heatmap` + text | 1 |
| V30 | Calendar / contribution heat map (per-series hue) | A8 | `heatmap` + gaps | 2 |
| V31 | Monochrome square-grid heat map | A7 | `heatmap` | 1 |
| V32 | Hexagon-bin map heat | A3 | custom (no native hexbin) | 3 |
| V33 | Tile heat map (solid ±% tiles with sparkline) | B1, B6 | HTML grid | 2 |
| V34 | Scatter / bubble with pin + Pareto frontier | A6 | Reg `scatter`/`bubble` + line | 1 |
| V35 | Radar / spider (concentric dotted rings) | D3 | Reg `radar` | 1 |
| V36 | 2×2 perceptual map (logos as points) | D3 | `scatter` + images | 3 |
| V37 | Ribbon vs dotted lines across categories | D3 | `scatter` widths | 2 |
| V38 | Chord diagram | B1 | custom (D3) | 3 |
| V39 | Bundled spline streams on a time axis | D2 | custom SVG/D3 | 3 |
| V40 | Vertical event timeline with callouts | D2 | custom | 2 |
| V41 | Choropleth/silhouette map with point cloud + radius rings | D2 | `scattergeo`/GeoJSON | 3 |
| V42 | Isometric terrain contour with route | A5 | `surface`/`contour` | 3 |
| V43 | Figure-ground map, ribbon elevation profile | D2 | custom | 3 |
| V44 | Hilbert / space-filling map | C4 | custom canvas | 3 |
| V45 | Skew-T, hodograph, wind barbs, polar profiles | C5 | `scatterpolar` + custom | 3 |
| V46 | Phosphor dotted-vector plots with caption block | C1 | renderer preset | 2 |
| V47 | Terminal widgets: box-title borders, braille/dot lines, block sparklines, text gauge | C2 | canvas/SVG char-cell renderer | 3 |
| V48 | Glyph-grid (ASCII) heat maps | C3 | char-cell renderer | 3 |
| V49 | Byte-grid with regional colouring + entropy line | C6 | custom (import inspector) | 3 |
| V50 | Pixel-square "voxel" scatter/tree | A10 | canvas | 3 |
| V51 | LED dot-matrix map | D3 | canvas | 3 |
| V52 | Terminal log pane (level colours) | A4 | HTML | 1 |
| V53 | Signal matrix + status chips | B8 | HTML grid | 2 |
| V54 | Ranked leaderboard (logo, value, delta, dot) | A6, A1 | HTML | 1 |
| V55 | Key/value spec sheet + editable cells | B3, B4 | HTML | 1 |
| V56 | World-clock / ticker strips | B2, B5 | HTML | 3 |

**Roles and priority changes after the final decision.** The base (C6, B4) contributes *components* and one chart; everything else is a
stepping stone. Rows above keep their original tier except these changes:

| Change | Why |
|---|---|
| **V58 cell/byte grid with region colouring + offset gutter** (K11, C6): **Tier 1** | It becomes the **dataset preview grid**, the centrepiece of the layout |
| **V59 tree-table with colour swatches** (K9, C6): **Tier 1** | Schema / lineage view in the full-width bottom pane |
| **V60 distribution/entropy line in a plot well** (K13, C6): **Tier 1** | The only chart in the base; it is the profile plot and the template for the Plotly skin |
| **Inspector table, zebra table, key/value sheet, quote strip** (K8, K10, K15, K16): **Tier 1** | Base components, not charts |
| V10 crosshair + readout: **Tier 1**, rendered as a one-line readout under the plot | C6's range/selection line is the pattern |
| V33 tile heat grid (S1, from B1): stays **Tier 2** | Stepping stone; tiles use the 50 % rule (T3) |
| **V57 signal matrix** (S2, from B8†): **Tier 2** | Good data-quality grid; chips as 50 % fills |
| V05 stacked indicator panes, V06 overlays: stay **Tier 2** | **No base reference** for multi-pane charts (T10) |
| V38 chord diagram (B1): stays **Tier 3** | Custom, post-launch |
| A-family modern-dark charts (V11–V14, V19–V21, V23, V27, V30 …) | **Stepping stones**, rendered flat in the C6 language (T9) |

Not seen in any reference but already registered in the core: funnel, waterfall, box plot. They will need to be
restyled to the same language, not designed from scratch.

## 5. Proposed design language (a recommendation, to be approved)

### 5.1 Concept

**"Glass-box instrument."** *(Final.)* The theme is C6's docked workbench (measured geometry, flat greys, one blue accent, a character
grid) with B4's sheet idioms inside it. Every number is a labelled readout — Name/Value inspector, key/value sheet, a selection
readout under every grid — which serves the existing "glass box" product idea (every value shows its provenance). Optional
skins reuse the same layout and tokens. The earlier proposals (a modern-dark default with rounded cards; an amber/crimson
terminal chrome) are **withdrawn as defaults**.

### 5.2 Token layers (replace the 3-surface subset in `apps/web/src/theme/tokens.css`)

*(Final: the concrete values are in T3/T4 — surfaces `#252525` / `#151618` / `#111111`, accent blue `#2e6aac`, the region palette with the
50 % rule, sizes in `ch`/rem. The `ember`, `lime` and amber accent rows below apply to optional skins only.)*

Current tokens: 3 surfaces + border, 3 text roles, one blue accent ramp, 4 status colours, 6 spacing steps, 3 radii,
3 font sizes. Contrast check of what exists today (dark theme): muted text `#7d8797` on `#14171c` = **4.95:1** (passes)
but on `#232833` = **4.07:1** (fails 4.5:1 for body text); accent `#5a8bf0` on `#14171c` = 5.46:1. The references need more:

| Layer | Contents | Source of truth in refs |
|---|---|---|
| Surface | page, panel, raised, overlay, hairline, hairline-strong | §3.1 |
| Text | primary, secondary, muted, on-accent, mono | §3.4 |
| Accent set | `ember` (orange), `lime`, `cobalt`; one active per theme | §3.2 |
| Data palettes | categorical-15, sequential-thermal, sequential-single-hue, diverging-rg, diverging-bl-rd, status, neutral-4 | §3.3 |
| Stroke | hairline 1 px, guide-dash, grid, series 1.5–2 px, glow | §3.5 |
| Pattern | hatch, stipple, dotted — *named* patterns that map to categories | §3.5 |
| Shape | radius 4/8/12/20, capsule, bracket, notch corner | §3.6 |
| Type | sans, mono, display (condensed), LCD/pixel (hero only), tabular numerals on | §3.4 |
| Density | one density (C6: 16 px rows, 11 px text) via a single row-height variable; no second mode at launch (decision 8) | T2 |

Single source: tokens in JSON generate `tokens.css` **and** the Plotly templates, so UI and charts cannot drift.

### 5.3 Theme packs

1. **Instrument (the only default theme)** — C6 layout and theme with B4's sheet components: near-black flat greys, one blue accent,
   50 %-rule region fills, 16 px rows on a character grid, 11 px monospace tabular numerals, radius 0–3 px, no glow. Dark only
   (decision 5). Full spec: Part T.
2. **Phosphor (optional, post-launch)** — C1–C5: monochrome yellow/green on black, dotted lines, title+caption block, optional
   scanline/bloom (reduced-motion safe). Only if the niche charts (decision 6) need it.
3. **Editorial (optional, report export, post-launch)** — D-family: slate or white, big light mono numerals, hairline rules.

The former "Reading" skin (modern dark, rounded cards) is **dropped** (decision 5). A pack = token set + chart preset + chrome preset;
the layout system and data palettes are shared.

### 5.4 Where "vintage" lives in the main theme

*(Final.)* Per the brief, vintage should be part of the main look. C6 and B4 *are* that look: monospace character grid, dense tool
chrome, hairlines, numbered tabs. Proposed extras for the base: bracket tags for key/value facts (A9), pattern fills for
categories (A7, as the colour-independent channel), a title+caption block above every chart (C1/C4 do this), and tabular mono
numerals everywhere. An LCD/pixel display face (A9/A10) is **left out** (it fights the density rules in T2). CRT bloom and
scanlines stay in Phosphor only.

### 5.5 Accessibility facts the references force us to decide

- Many refs use **dim grey text on black**, **colour-only meaning** (red/green) and **tiny sizes**. The repo's contract in
  `assets/ui-contract/a11y-*.json` wins: ≥4.5:1 for text, ≥3:1 for chart marks and UI strokes, colour never the only
  channel. The references' hatch/stipple/glyph (▲▼) habits are *useful* here — adopt them as the second channel. (`a11y-rules.json`
  has no numeric thresholds, so the numbers above are WCAG defaults.)
- Glow and bloom are decoration; they must not carry information and must respect `prefers-reduced-motion`/contrast modes.
- Neon-on-black halation is hard on some readers: provide a "softer black" surface (`≈#0e1216`, as A6 cards) as default.

### 5.6 Interaction with Impeccable

I have read `SKILL.md`, the launcher, and `reference/craft-floor.md`, and grepped the engine source; I have **not** read
the other 40 reference playbooks. From what I read:
- `impeccable context` loads `PRODUCT.md` and `DESIGN.md`. **Writing those two files (init + document) is the cheapest
  way to make Impeccable follow our language**, before any fork.
- Its "Refuse" list will flag several things this corpus does constantly: **hero-metric template** (every dashboard here),
  **sparklines and progress rings**, **gradient fills**, **zero-offset glow**, **monospace "as costume"**, **section numbers
  01/02** (D3), **eyebrow/kicker labels** (A1, D1, D2 — the only line marked a hard ban), and **same-size icon cards**. The
  floor says a pinned brief or committed visual world overrides everything *except* a marked ban, so DESIGN.md must pin
  these as intentional and drop the eyebrow habit.
- Forking its source is only worth it if we need new rules; it is Apache-2.0. Decide after reading the playbooks.

## 6. Layout archetypes to build (wireframes)

*(Final.)* The **default workbench** is C6's: measured rectangles in **T2**, pane-by-pane mapping in **T7**. The four wireframes
below are the *secondary* archetypes for report pages and optional skins; the Terminal workspace one is only a stepping stone now.

```
Overview (A1/A2/A4)                     Section document (A6)
+--------+---------------------------+   +------+----------------------------+
| nav    |  H1 + date + filters      |   | rail | icon  Title      [sel][seg]|
| rail   +----+----+----+----+-------+   | (an- | muted subtitle              |
|        | K1 | K2 | K3 | K4 |       |   | chor)| +------------------------+  |
|        +----+----+----+----+-------+   |      | |   chart (shared module)|  |
|        |  hero time-series         |   |      | +------------------------+  |
|        +--------------+------------+   |      | 1. name   val  d  6. ...    |
|        | part-to-whole | distribution|  |      | 2. ...                      |
|        +--------------+------------+   |      | (repeat module per metric)  |
|        | table                       |  +------+----------------------------+
+--------+---------------------------+

Terminal workspace (B1/B6/B7)           Editorial report (D1/D2/D3)
+-----------+-----------+              +--------+--------+--------+--------+
| pane      | pane      |              | col A  | col B  | col C  | col D  |
| (title bar| (table)   |              | num    | num    | num    | num    |
|  options) +-----------+              | list   | list   | list   | list   |
+-----------+ pane      |              | mirrored chart per col, rows align |
| pane      | (heat map)|              +--------+--------+--------+--------+
+-----------+-----------+
```

A fifth archetype, the **multi-pane synchronised stack** (B7), is used inside the Terminal pack for time-series work.

## 7. Plan (phased; each phase ends in something you can look at)

*(Final, with all decisions applied; each phase ends in something you can look at.)*

**Progress (2026-10-26, branch `phase-4/instrument-design-system`, nothing committed):**
- **Step 0 (partly done).** `a11y-rules.json` has 8 *structural* rules (interactive names, input labels, focus reachability, dialog focus
  trap, duplicate shortcuts, dock titles, decorative-illustration descriptions, tab order) and **no contrast or size thresholds**, so
  decision 8 does not conflict with it; `a11y-descriptors.json`, `a11y-interaction-patterns.json` and `ui-behaviour-rules.md` are still
  unread. `ui-constants.json` records the old desktop table as 24 px rows with alternating colours; the web theme now uses 16 px (decision 8).
  `workspace-layout.json` is read to its dock section only.
- **Step 1 done.** `assets/design-reference/manifest.json` (29 entries, roles, measured palettes, sha256, catalogue ids; images stay local)
  with `tests/assets/test_design_reference_manifest.py` (5 tests, including "no image is committed").
- **Step 2 done.** `assets/design-tokens/instrument.json` is the single source; `scripts/build_design_tokens.py` generates
  `apps/web/src/theme/tokens.css`, `tokens.resolved.json`, `assets/design-tokens/plotly-template.json` and `contrast-report.md`
  (**63 of 63 contrast pairs pass**; a deliberately broken token fails 19). `tests/assets/test_design_tokens.py` (8 tests) pins contrast,
  generated-file freshness, the 50 % rule against the measured fills, Plotly template validity, and that every CSS variable the old mock
  shell uses is still defined. A dev-only gallery at `/tokens.html` was checked in a real browser, and the old mock shell still renders.
  `tsc`, `oxlint` and `vite build` pass; the full pytest suite has **not** been run (only `tests/assets`).
  An independent code review found one real bug (four legacy aliases such as `--text-primary: var(--text-primary)` referenced themselves,
  so text colours silently fell back to the browser default); fixed, now guarded by a generator validation step and a CSS-integrity test,
  and confirmed in the browser (`--text-primary` resolves to `#e5e6e7`). The 50 % rule now uses the measured base `#131416`, so fills are
  exact inverses of the derived keys. `tests/assets` is at 69 passed.
- **Step 3 done (shell and dynamic panes).** `apps/web/src/workbench/` (Workbench, Pane, ChromeBand, StatusStrip, panes, icons, CSS) replaces
  the old mock shell (`App.tsx`/`App.css` deleted and the legacy token aliases removed). Built on `react-resizable-panels` and Radix
  menubar/tabs with our own flat CSS (decision 11). Checked in a real browser at 1199x702: panes measure 525x445, 296x445, 372x322 (x2) and
  824x200 against T2's 523x444, 296x444, 374x320 and 823x197; keys 1-5, F6, Escape, collapse, maximise, gutter arrows, persistence across
  reload and Reset layout all work; no console warnings. Two independent reviews (code and accessibility) found real defects, all fixed and
  re-verified: Radix returned focus to the View trigger and the shortcut guard then ignored every key; collapse and maximise dropped focus;
  maximise is now pure CSS so no pane remounts or loses state; gutters, the disabled dataset list and the menu groups got names; a live
  region announces actions; focus and selected-tab states survive Windows high-contrast; icon buttons are 24 px wide.
- **Step 4 done (core components).** `apps/web/src/components/`: `controls.tsx` (Button, Select, RadioGroup, AlertBar), `tables.tsx` (sortable zebra
  DataTable with aria-sort and a swatch column, which also serves as the inspector; TreeTable as an ARIA treegrid with the full arrow-key model and one Tab
  stop), `sheet.tsx` (numbered sections, key/value list, two-row quote strip, the one editable value), `components.css`, plus a dev gallery at
  `/components.html`. Themed slim scrollbars are in `index.css`. Checked in a real browser: sorting flips `aria-sort` and orders rows, the tree-table keys
  (Up/Down/Home/End/Left/Right/Enter) behave, and **axe-core finds 0 violations on the gallery (43 rules passed) and, in the earlier step-3 run, on the shell**; it caught one real
  defect (a nested `<div>` inside the quote strip's `<dl>`), now fixed. An independent code review found real issues, all fixed (browser shortcuts like Alt+Left
  swallowed by the tree, keys meant for a control inside a cell, a clipped sort-button hit area, plus several smaller ones). `tests/assets` is at 69 passed.
- **Not done in step 4:** K17 numbered *tabs* (the numbered section bars exist; tab numbering waits for a use), keyboard cell navigation inside DataTable, virtualised rows
  (the 200k-row preview is step 5), and the components are not used by the workbench panes yet (step 5 wires them to data).
- **Step 5 done (data views wired to the API; rule editor not built).** New `apps/web/src/api/` (openapi-fetch over generated `schema.d.ts`,
  allauth sign-in, TanStack Query keys and hooks) and `workbench/{data.tsx,dataContext.ts,views/}`: sign-in inside the Data pane, the calm first-run pane,
  upload (picker or drop; the first upload creates "Untitled project"), a virtualised cell grid (K11, `components/grid.tsx`: 16 px rows, server paging and
  sort, `aria-activedescendant`), inspector, schema and lineage tree-tables, and a completeness plot (K13). Checked in a real browser against the real dev
  API (Django `JOBS_EAGER=1`, MinIO): sign-in, wrong password, sign-out, a new account's first upload, a 21 MB / 200,000-row CSV (3.2 M px scroll height, about
  35 DOM rows, sorting on the server, Ctrl+End, PageDown), schema click selecting the column in grid, inspector and plot, upload failure showing the API's
  own message, a session ended behind the app's back (401 returns to sign-in and drops cached data). 40 scroll jumps in 0.8 s made 0 requests until the
  scroll settled, then 1. axe-core: 0 violations, 47 rules passed (signed in, grid focused). `tsc`, oxlint, `vite build` clean; `tests/assets` 69 passed.
  Independent code and accessibility reviews found real defects, all fixed: scroll storms exceeding the 120/min preview budget (now settled for 150 ms, 4xx not
  retried), a cached account surviving session expiry or a new sign-in, an upload outliving sign-out, `crypto.randomUUID` failing off localhost, focus lost
  at upload, sign-in and sign-out (now aria-disabled buttons, focus to the pane or grid), silent sort and upload progress (now announced), Space scrolling
  the grid, F6 ignored in fields, forced-colours borders, menu shortcut contrast, `aria-selected` announcing focus as selection, off-by-one row readout.
- **Not done in step 5:** the K12 rule editor and the Report and Chart tabs (hints only); a real distribution profile (the plot shows completeness from
  the summary; the `profile_dataset` stage job comes with the stage views); signup, email-verification and reset screens; an organization or project picker
  (first org, first project); narrow-screen tabs (decision 10); datasets past the first 200 are not listed; rows past 1,000,200 cannot be scrolled to (the API
  rejects offsets above 1,000,000; the readout says so); a session ended elsewhere is not announced to screen readers.
- **Non-text contrast (WCAG 1.4.11) fixed, as discreetly as the check allows.** Fields, selects and buttons are flat fills only 1.5 : 1 against the pane, and
  the blue type mark under a grid header was 2.7 : 1 on the header band. Now: a new token `border.control` (`#5073a0`, a lighter step of the field-button hue,
  3.14 : 1 on chrome, 3.71 : 1 on the pane) is drawn as a 1 px `box-shadow` outside each control, so no layout moves and it reads as a bevel, not an outline;
  inactive controls are exempt and carry none; the button on the crimson alert bar takes the bar's white text colour. A new `mark` token group holds the
  five header marks (blue lightened to `#2f86c6`, 3.36 : 1; the other four equal their region keys and already passed). `scripts/build_design_tokens.py` now
  enforces 81 contrast pairs (was 67; 14 added). Still open: 24 px targets for fields and header cells (2.5.8), manual screen-reader checks of the grid
  (NVDA, JAWS, VoiceOver), text-spacing overrides clipping 16 px rows (1.4.12).
- **Step 6 done (chart skin).** The skin is client-side: the server still returns plain Plotly figures from the unchanged core chart classes, and the web app
  draws them with `layout.template` from the generated `assets/design-tokens/plotly-template.json` (now with defaults for all 12 registered trace types,
  a dotted quarter grid, the legend in one row above the plot, region-palette sequential and diverging colour scales, polar axes, mode-bar colours).
  `apps/web/src/charts/`: `plotly.ts` (Plotly.js 3.6.0, the version paired with the Python plotly 6.8.0, loaded on demand so it never reaches the main
  bundle), `skin.ts` (hover labels replaced by a one-line readout, a trace named "Incomplete" drawn hatched, the Absolute|Percentage and Linear|Log chips,
  a heatmap's scale chosen from the template), `PlotlyChart.tsx`, and a dev gallery at `/charts.html` that draws all 12 charts **before and after** from
  `gallery-figures.json`, generated by `scripts/build_chart_gallery.py` with the real chart classes (it fails if a registered chart has no spec, or the
  file is stale; `tests/assets/test_chart_gallery.py` pins both and that the template applies to every chart type). A multi-series stacked column, the
  OpenRouter-style reference, comes first with its chips. Checked in a real browser: 26 figures drawn, no console messages, axe 0 violations (31 rules),
  the Percentage chip turns the y axis to 0-100 %, the hover readout fills from a real mouse move and no floating label appears.
  **Three core chart defects found by drawing the real charts, all fixed with tests:** `ScatterChart` and `BubbleChart` raised `ValueError` for a text
  `color_column` (the API would answer 422; now one trace per category, via a new `category_groups` helper), and `TreemapChart` drew nothing because it
  passed raw rows (parents that were not nodes, repeated labels without ids; now summed per leaf with every ancestor a node and `branchvalues="remainder"`).
- **Not done in step 6:** the Chart tab in the workbench still shows its hint (a chart builder is the Visualize area); the Tier-1 stacked chart itself and
  a ranked list beside a chart are step 7; Plotly's marks cannot be reached by keyboard, so the readout is a pointer aid and the figure has a short text
  summary, not a data table; the treemap's tiles are the 50 % fills (their labels are readable, the tiles are 1.5-2 : 1 against the well and separated
  by outlines and labels, not by colour alone); the production build does not include `charts.html`, so the lazy Plotly chunk is checked in dev only.
- **Step 7 started: 7.1 golden-screenshot harness done; no new chart yet.** `apps/web/playwright.config.ts`, `e2e/charts.golden.spec.ts` and `e2e/docker.mjs`
  (`pnpm test:golden`, `pnpm test:golden:update`) render the skinned half of each `/charts.html` box in the pinned `mcr.microsoft.com/playwright:v1.64.1-noble`
  image and compare it with the committed `-linux` baselines (`e2e/__golden__/`, 15 PNGs, 352 KB: the 12 registered charts plus the reference stacked column in
  Absolute, Percentage and Log views). Baselines are Linux-only on purpose (a golden image is only comparable to one rendered by the same browser, fonts and
  rasteriser); a run on Windows finds none of its own and fails. The gallery takes `?only=<chart>` so a test draws one figure. **Verified:** an update run then a
  separate compare run, 15 passed both times; `tsc -b` and `oxlint` clean. A new CI job `web` (typecheck, oxlint, `vite build`, the golden tests, diff images kept
  on failure) is written in `.github/workflows/ci.yml` and **has not run on GitHub yet**; its image tag is checked against the pinned Playwright version. Two things
  the first run taught: the cold Vite dev server in the container needs a 30 s expect timeout, and pnpm's store must stay out of the bind mount (`--store-dir`).
  **7.2 stacked columns (V11, V12) done.** Not a new chart type: `BarChart.build` takes an optional `series_column` (registry `optional_fields` gained it, so the API,
  persistence and the UI-contract test pick it up with no other edit), one stacked trace per series, categories in the column's own order (dates as dates, **not**
  capped, because they are time buckets), series capped at 14 + "Other" (the shared `_MAX_CATEGORIES`), ordered by label so colours are stable. 100 % is the
  existing Percentage chip, so V12 needed no code. `scripts/build_chart_gallery.py` gained `VARIANTS` (an option's figure beside the base chart; the registry guard is
  unchanged), so `bar_stacked` got its golden test automatically: 16 baselines. **Verified:** `tests/visualization/test_stacked_bar.py` (10), full suite
  **1033 passed / 0 failed**, goldens 16 of 16 with the other 15 byte-for-byte untouched.
  **7.2b hatched incomplete bucket done (decided 2026-10-27: explicit opt-in, never inferred).** `BarChart(incomplete_from="2025-12-01")`: that bucket and every later one
  becomes a single trace named "Incomplete" (total, no series split) which the skin already draws hatched; off by default, because nothing in the data says which
  bucket is partial and marking a finished last bucket would be a false statement. The value must be a bucket as shown on the axis (an exact match, not a date
  cutoff). It is a value, not a column, so `ChartRegistration` gained `literal_fields` (kept out of `optional_fields`, which a column picker reads); the API's
  `_check_spec` and the persistence `**kwargs` fallback accept both. Gallery variants `bar_stacked` and `bar_stacked_incomplete` give 17 golden baselines.
  **7.3 area with end dot (V02) done.** Not a new chart type: `LineChart.build` takes `variant="area"` (a value, so `line` gained `literal_fields=("variant",)`; a string and
  not a bool because the API's `chart_out` only returns str/list spec values). One trace: `fill="tozeroy"`, `mode="lines+markers"` and a marker-size list that is 0 except on
  the last row that has a value (8 px), so the dot takes its line's colour without the core knowing the palette; plotly-resampler slices the list with the data and keeps the
  last point (tested above 5,000 rows). `cliponaxis=False`, because the last x is the end of the axis range and a clipped dot lost half its disc; zoomed past the last
  value no dot is drawn (checked in a browser). Skin: a filled scatter trace gets its colour at 22 % alpha, flat, no gradient or glow (T9); Plotly's default 50 % hid the
  1 px line. Gallery variant `line_area` gives 18 golden baselines. **Verified:** `tests/visualization/test_area_line.py` (7), full suite **1044 passed / 0 failed**, API chart
  tests 3 passed, goldens 18 of 18 with the other 17 untouched, `tsc -b`, oxlint, black, isort, bandit clean. **Harness weakness found:** Playwright's per-pixel `threshold`
  (default 0.2) let the 50 % to 22 % fill change pass the compare against the old baseline (both dark blues), so `--update-snapshots` did not rewrite it; it was rewritten
  with `--update-snapshots=all`. A lower `threshold` in `playwright.config.ts` would make dark-fill changes visible; not changed here.
  **7.4 candlestick + volume (V04) done.** The first step that adds a registry type (the 13th), because a candle needs four price columns no existing chart takes:
  `CandlestickChart` in `advanced_charts.py`, `x_column` + `open/high/low/close_column` required, `volume_column` optional. With volume it is two panes (candles 75 %, a bar
  trace named "Volume" 25 %, the x axes tied, built with `Figure.set_subplots`); the range slider Plotly adds by default is off. Integration points touched: the registry,
  `ChartType.CANDLESTICK` and migration `0003_chart_type_candlestick` (`makemigrations --check` clean; `openapi.json` lists no chart names, so unchanged), the token
  generator's `data.candlestick` default (**hollow green = up, solid red = down**, so direction is the fill as well as the colour; no new contrast pair, both are region keys
  already checked), the skin (`candlestick` is cartesian, the readout shows open/high/low/close, a "Volume" bar beside candles is the neutral axis grey so the next series
  colour does not collide with the direction colours; the Linear|Log chip acts on the price axis only), the gallery (`prices` table drawn last, `candlestick` and
  `candlestick_price_only`: 20 golden baselines), `docs/manual/charts/candlestick.md` and the counts ("thirteen"). **A review found a gap this checklist did not:**
  `ai/tool_registry.py`'s `build_chart` schema lists its properties by hand, so the assistant could not have been told the candlestick columns, nor 7.2's `series_column` and
  `incomplete_from` or 7.3's `variant`; all are now described, and `test_every_builtin_chart_field_is_described_to_the_assistant` fails the next time a chart field is
  missing there. **Verified:** `tests/visualization/test_candlestick.py` (13), full suite **1057 passed / 0 failed** (then 2 tests added, their files 18 passed), API parity, models,
  OpenAPI, stages and IDOR tests 150 passed, goldens 20 of 20, `tsc -b` and oxlint clean. **Not done:** weekend `rangebreaks` (the chart draws the dates it is given),
  downsampling of large candle tables (the web render reads the first 5,000 rows), overlays and indicator panes (V05, V06: Tier 2), duplicate-x handling.
  **Judgment call still open:** V13 thermal narrow bars (a sequential series palette) is not done.
  **Left for step 7:** the other Tier-1 charts (dual-axis lines, hatched grouped bars, paired horizontal bars, donut with
  centre total, pie grid, numeric matrix heatmap, monochrome square-grid heatmap, scatter with pin and Pareto frontier, KPI mini charts, log pane, ranked
  leaderboard), each added with its golden test. Most are options of an existing chart, as stacking was, not new registry types.
- **Decision 3 refinement (WCAG 2.1.4):** bare digit keys are a character-key shortcut, so View > "Single-key shortcuts (1-5)" turns them
  off (stored in `localStorage`); the menu items carry `aria-keyshortcuts`. F6 and Escape are not character keys.
- **Not done, on purpose or deferred:** no automated web accessibility test yet (the ship plan's D12 Playwright + axe pass is the place; the repo's
  `a11y-rules.json` has no DOM checker); a single-pointer alternative to dragging a gutter (WCAG 2.5.7) and a 24 px gutter hit area (it would cover the
  neighbouring pane's controls; it is 19 px); narrow-screen tabs (decision 10; still open after step 5); Windows high-contrast was reasoned from CSS, not run.
- **Ship plan edited:** D3 and D4 in `plans/two-week-ship-plan.md` now say headless primitives + Instrument tokens, and the C6 workbench with
  View-menu/`1`-`5` navigation.
- **Thin margins worth knowing:** the yellow region fill under `#e5e6e7` text is 4.52 : 1 (limit 4.5) and the focus ring on the focused tab is
  3.04 : 1 (limit 3.0); the generator fails if either regresses.

0. **Prerequisites** — read `assets/ui-contract/workspace-layout.json` in full (I read only its dock section) and `a11y-*.json`
   (thresholds): the dock arrangement there differs from C6's and the a11y rules override mine (decision 8 risk, §9).
1. **Reference manifest** (decision 7) — commit a manifest only: file → label → measured palette → role (base / stepping stone /
   skin). Images stay local. *Output: `assets/design-reference/manifest`.*
2. **Instrument tokens** — JSON source → `tokens.css` + Plotly template + contrast report, from T3/T4: surfaces, the blue state set,
   the 10-colour region palette with a `fill(key, 50 %)` helper, sizes in `rem`/`ch` with **one row-height variable (16 px)**, an
   invisible ≥24 px hit-area helper for small controls, and a **≥3 : 1 focus ring** (C6's border is 1.79 : 1). Replaces the blue
   subset in `apps/web/src/theme/tokens.css`. *Output: a token page (swatches, region fills with contrast, type ramp).*
3. **Shell and dynamic panes** (decisions 1, 3, 11) — K4 chrome band, K3 tab strip (3 states), K1 panes, K7 status strip, K2 layout
   as the fixed C6 arrangement with **resizable gutters, collapse, maximise and tab groups**, built on headless primitives with our
   own flat CSS; View-menu + `1`–`5` shortcuts reveal/focus panes (T7). *Output: an empty workbench matching T2 within a few px,
   fully keyboard-operable, sizes persisted.*
4. **Core components** — K5/K6 fields and radios, K8–K10 table / tree-table / inspector, K14 scrollbar, K15–K19 sheet, quote strip,
   numbered tabs, editable cell, alert bar. *Output: a component gallery.*
5. **Data views wired to the API** — K11 cell grid with column-type regions, inspector, schema tree-table, K12 rule editor, K13
   profile plot, calm first-run pane (decision 10). *Output: upload a CSV → preview → inspect → profile in the workbench.*
6. **Chart skin** (decision 9) — Plotly template from K13, with **OpenRouter** as the multi-series reference: stacked and
   100 % columns with Absolute|Percentage and Linear|Log chips, ranked lists, hatched incomplete bucket; colours from the region
   palette, flat bars, one-line readout. Restyle the 12 registered charts. *Output: the 12 charts before/after.*
7. **Tier 1 charts before launch** (decision 4), each with a golden screenshot test; **Tier 2 and Tier 3 after launch**, including
   the four niche charts kept by decision 6 (skew-T/hodograph, Hilbert map, chord, 3-D terrain).
8. **Design-language skill** — `PRODUCT.md` + `DESIGN.md` written via `/impeccable init` and `document`, a project skill
   (`uadas-design-language`) holding tokens, pins (T8), chart rules and the manifest, with Impeccable's `critique`/`audit`/`polish`
   as reviewers.

**Fit with the ship date (decision 4):** `plans/two-week-ship-plan.md` puts tokens at D3, the app shell at D4, the preview at D6 and
Plotly at D9. Phases 2–6 map onto those days **if the dock stays a fixed arrangement (decision 1)**. Two edits to the ship plan are
implied: D3 should read "tokens from the Instrument system, headless primitives" instead of "Tailwind + shadcn" (decision 11), and D4's
five-area nav becomes the View menu + shortcuts of T7 (decision 3). Phase 7 beyond Tier 1 is post-launch.

## 8. Risks and things I did not or could not do

- Licensing/privacy of the images: Bloomberg, IB, TradingView, Finviz, ImHex and Dribbble shots are third-party; the
  OpenRouter screenshot shows part of a signed-in email address in the footer. Do not commit these to a repo that is or
  may become public. Recommend committing the manifest and measurements only.
- Fonts are guesses; none has been checked for licence. Pixel/LCD display faces in particular need a licence check.
- I did not read Impeccable's playbooks beyond the craft floor, so §5.6 may miss further conflicts.
- No Plotly capability above was tested; names are from memory of the library and must be verified at implementation
  (pattern fills on filled scatter traces and the `indicator` gauge in particular).
- Nothing was rendered. All measurements come from the supplied images; colours in photographs (A8) are unreliable.
- The two GIFs' motion (sparkline scroll, mesh deformation) is described from sampled frames only.

## 9. Decisions (all 11 answered on 2026-10-26)

| # | Question | Decision | Consequence in this plan |
|---|---|---|---|
| 1 | Dock scope for launch | **Fixed layout + resizable gutters + tab groups**; free drag-docking later | §7 phase 3; T10 |
| 2 | B4 vs C6 colours | **Blue only; amber = editable cells; crimson = one alert bar** | T6, K18, K19 |
| 3 | Five areas in the layout | **Use C6's format, palette and layout unchanged, but dynamic: the user can enlarge, minimise or collapse the data tables, lists and every pane to taste.** The five areas are views reached from the View menu and tab groups, not a separate preset switch *(my reading of your answer; correct me if you meant something else)* | T7 |
| 4 | Scope vs ship date | **Base theme + Tier 1 charts before launch**; Tier 2/3 after | §7, §4 |
| 5 | Light mode / Reading skin | **Dark only; no extra skin** | §5.3, T10 |
| 6 | Niche visualisations | **Keep all four** (skew-T/hodograph, Hilbert map, chord diagram, 3-D terrain) on the roadmap, all Tier 3 / post-launch | §4 |
| 7 | Images and licences | **Manifest and measurements only; images stay local** | §7 phase 1, §8 |
| 8 | Type and density | **11 px mono, 16 px rows only, exactly as C6** (this overrides my recommendation of 12 px / 24 px default) | T2, T4, T8 |
| 9 | Chart reference | **OpenRouter rankings** (stacked and 100 % columns, chips, ranked lists), re-coloured and flattened | T9, §7 phase 6 |
| 10 | Small screens / first-run | **Desktop-first; tabs below ≈900 px; calm first-run pane** | T10 |
| 11 | UI building blocks | **Headless primitives with our own flat CSS**; no shadcn defaults | §7, ship-plan D3 |

**Risks the answers leave open**

- **Decision 8 vs accessibility.** 11 px text and 16 px interactive rows fall below WCAG 2.2 SC 2.5.8's 24 px target guidance for
  controls (inline text links and spacing exceptions apply) and may conflict with the repo's `a11y-*.json` rules, which I have
  only partly re-read (see the Progress note in section 7). Mitigations that keep your look: size everything in `rem`/`ch` so browser zoom and text-size settings scale the
  whole layout, give small controls (tab ×, sort arrows, tree arrows) an invisible ≥24 px hit area, and keep a **single
  CSS variable for row height** so a comfortable mode can be added later without a redesign.
- **Decision 3 needs a concrete model** (T7): which panes collapse to a strip, how "maximise" works, what the five areas open.
  I have drafted one; it is not tested.
- **Decision 6 adds four custom charts** that have no web implementation path yet; they stay Tier 3.

## 10. Index of the 29 references

**Role after the final decision:** **Base theme and layout** = C6 (final) and B4 (components), the two images in `theme/`.
**Stepping stones** = all others, including B1 and B8†, which were in the base earlier. **Optional skins** = C1–C5 (Phosphor), D1–D4
(Editorial).

| ID | File (prefix) | One-line label |
|---|---|---|
| A1 | 7057570b | Churn prediction SaaS dashboard |
| A2 | 8de19ce8 | Vaultify DeFi overview |
| A3 | 3a22871c | ORION hex-map analytics |
| A4 | 4c00b802 | E-TechInvest deliverability ops |
| A5 | fd58bb38 | mount climbing metrics + terrain |
| A6 | Screenshot…openrouter.ai | OpenRouter model rankings (16k px) |
| A7 | 860170b9 | SUI mono mobile app, 4 screens |
| A8 | 3d135272 | Habits heat-map app (photo) |
| A9 | 19557e6f | Resource Overview, bracket UI |
| A10 | 6a621ee0 | HydraDB pixel-tree poster |
| B1 | 31454318 | Bloomberg 4-pane |
| B2 | 62a18fd6 | Bloomberg ALLINONE + IMAP |
| B3 | dfa73688 | Bloomberg DRSK default risk |
| B4 | da814a0f | Bloomberg KOM6 spec sheet |
| B5 | 91a00b1e | Bloomberg iPad |
| B6 | fb4eea1b | Interactive Brokers Mosaic |
| B7 | 1303961e | Binance BNB with Fib/Gann/MACD/RSI/KDJ |
| B8† | 657fbc46 | Holy Grail signal matrix (near-base; left `theme/`) |
| B9 | 732aef72 | Finviz S&P heat map |
| C1 | 5b16ad71 | 1977 CRT mesh plot (GIF) |
| C2 | 097565d6 | termui dashboard (GIF) |
| C3 | c9693173 | Cogmind ASCII |
| C4 | 573db33f | IPv4 Hilbert census |
| C5 | ff3680c7 | SHARPpy skew-T sounding |
| C6 | 81d355ee | ImHex hex editor |
| D1 | 7d90ae22 | Felton-style 4-column report |
| D2 | 32ad1d8c | Bournemouth fact-boards (red/grey) |
| D3 | ca6f5fa1 | Driven by Brand infographic |
| D4 | 92bc03ae | Nobel nominees mosaic (light) |
