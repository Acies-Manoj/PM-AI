# Table Grapes Guided Drill-down Brief: Product > Origin > Carrier Test

Purpose: check the guided drill-down chain. The app should spot that one product spans many origins, let me confirm a focus, drill to its top origins, then to the top carriers of those origins with % in spec. Each step has its own chart and filters and becomes its own numbered report slide.
Test dataset: `backend/data/raw/edeka_tabular_shipment_data.xlsx` (2,370 rows, 2,277 Trip IDs, all Arrived).

---

## Part A: Brief to paste on the Client Brief page

> We ship fresh produce from suppliers in Italy and elsewhere to Germany for EDEKA. I need a cold-chain performance report covering all shipments in the file.
>
> **Temperature specification.** Each product has its own limits in the data (Limit Low, Limit High). Shipments with no limits cannot be scored: leave them out of every percentage, keep them in the volumes, and tell me how many there are.
>
> **In-spec percentage.** For each shipment, the percentage of transport time that stayed within the temperature specification: 1 minus (Time Below Low Hours plus Time Above High Hours) divided by the segment duration in hours, limited to 0 to 100%. Report the average of the shipment percentages, together with the number of shipments behind it.
>
> **What I want to see:**
> 1. Trips by product and by origin. I expect one product to have many more origins than the others, so point that out.
> 2. For that product, which origins matter most (the top few by trips).
> 3. For those top origins, which carriers move the volume, and how well each stays in spec (% in spec next to trip count).
> 4. Let me change how many I look at (top 3, top 2, or the bottom ones) without re-running everything, and show me clearly if a later chart is out of date after I do.
> 5. A short summary: which origin/carrier combinations are strongest and weakest on % in spec.

---

## Part B: Expected drill-down chain (from the test file)

| Level | Slide | What the app should show | Expected on the test file |
|---|---|---|---|
| 1 | 1 | Trips by product (and origin) | Table Grapes 1,481; Cherries 197; Apricots 159; Nectarines 124; Peach 54; Plum 52 |
| Flag | | Wide-dimension callout | Table Grapes spans **22 origins** (Nectarines 13, Apricots 9, Peach 8), marked "wide" |
| 2 | 2 | Table Grapes: top origins by trips | Default N = 4 (about 70% of volume): Giacovelli Srl 423, Agricola Ci.da 311, Agrimessina 275, Southern Cross Marketing ZA 70. With N = 3 the first three only |
| 3 | 2.1 | Carriers for those origins, trips with % in spec | For the top 3 origins together: Campagnolo 494, GEA 424, FGF 44, PINTO GIOVANNI 32 |
| 3 (alt) | 2.2 | Same drill for a second focus | See Part D |
| Stop | | Level 4 is the maximum | Level 3 offers the next level only if a lower dimension exists |

Carriers per origin (Table Grapes), useful when a single origin is drilled:

| Origin | Top carriers (trips) |
|---|---|
| Giacovelli Srl | Campagnolo 326, GEA 49, PINTO GIOVANNI 32 |
| Agricola Ci.da | GEA 196, Campagnolo 74, FGF 38 |
| Agrimessina | GEA 179, Campagnolo 94, FGF 1 |

Note: counts here are rows in the file, which for Table Grapes equal Trip IDs (1,481 each). Percent-in-spec values depend on the features the app builds, so check those for plausibility (between 0 and 100, GEA and Campagnolo clearly different) rather than to an exact number.

## Part C: Test checklist

| ID | Area | Test | Pass criterion |
|---|---|---|---|
| G01 | Detection | Run "trips by product and origin", open the drill-down | Table Grapes shown with "22 origins" and a wide badge |
| G02 | Confirm | Pick Table Grapes, change nothing, do not click Confirm | No new analysis is created or run |
| G03 | Confirm | Click Confirm | Level 2 appears with the top origins from Part B, own chart and filters |
| G04 | Default N | Read the default Top N | 4 (covers about 70%), user can change it |
| G05 | Rank control | Change Top 4 to Top 3 | Level 2 re-runs with Giacovelli, Ci.da, Agrimessina only, no LLM wait |
| G06 | Bottom | Switch to Bottom 2 by trips | Two smallest origins for Table Grapes |
| G07 | Level 3 | From level 2 (Top 3), confirm Carrier with % in spec | Carriers match Part B (Campagnolo 494, GEA 424, FGF 44, PINTO 32) with a % in spec value each |
| G08 | Small groups | Rank Carrier by % in spec, Bottom 2 | Carriers with fewer than 5 trips are not listed (noise guard) |
| G09 | Stale | With level 3 built, change level 2 to Top 2 | Level 3 shows "Stale - upstream changed" and a Refresh button |
| G10 | Refresh | Click Refresh on level 3 | Level 3 now covers only the two remaining origins, stale badge gone |
| G11 | Filters | On level 2, filter Is Alarmed = Yes | Chart updates with no LLM call, applied filter shown, stored result unchanged |
| G12 | AI proposals | Click "Suggest with AI" | Up to 3 cards, each with a reason, using real columns and real values; "Use this" only pre-fills the controls |
| G13 | Other scenario | Repeat with Cherries (8 origins) | Works the same, top origins Poulis Agia 57, Elita 46, SAT Vidrio 39 |
| G14 | Depth cap | Try to drill below Carrier / past level 4 | Panel shows the reason instead of a Confirm button |
| G15 | Report order | Open the Report page | Slides listed 1, 2, 2.1 (and 2.2 if built), children indented under parent |
| G16 | Report stale | Leave a level stale, download | Stale level is not in the deck and is flagged on the page |
| G17 | Report slides | Open the downloaded deck | Headings numbered ("2.1  ..."), subtitle line such as "Table Grapes - Top 3 Origin by trips", chart not overlapping the subtitle |
| G18 | Report reorder | Drag slide 2.1 above slide 1 | Not possible; a child stays under its parent |

## Part D: Second-branch scenario (siblings 2.1 and 2.2)

To test separate slides for siblings, build two level-3 drills from the same level 2:

1. Focus **Giacovelli Srl** only, Carrier, Top 3 (expect Campagnolo 326, GEA 49, PINTO GIOVANNI 32) as slide 2.1.
2. Focus **Agricola Ci.da** only, Carrier, Top 3 (expect GEA 196, Campagnolo 74, FGF 38) as slide 2.2.

Pass: two separate slides, each with its own chart, filters and subtitle, numbered 2.1 and 2.2.

## Prerequisites

- An OpenRouter key in `backend/.env` (interpretation and AI proposals use it).
- The **% in spec** feature must be computed on the Features page first. If it is missing, `% in spec` is not offered and the drill-down asks you to compute it, which is itself a valid check (G07 then shows trips only).
