# Italy 2025 Cold-Chain Brief: Feature / Analysis / Drill-down Test

Purpose: check that the app generates the features, analyses and drill-downs needed to reproduce the Italy 2025 report (`Italien 2025.pptx`). Slide count and layout are not tested.
Test dataset: `backend/data/raw/edeka_tabular_shipment_data.xlsx` (2,370 rows).

---

## Part A: Brief to paste on the Client Brief page

> We ship fresh produce from Italian suppliers to Germany for EDEKA. I need the cold-chain performance report for shipments that departed between 01.01.2025 and 31.12.2025.
>
> Italian suppliers are shipments whose Origin is Giacovelli Srl, Agrimessina, Agricola Ci.da, Agricola Dino, Mazzoni, Unacoa Salvi, Frudis SRL Noicattaro, AZ. AGR. LILLA E GIULIANI SRL, Di Palma, Coniglio, Grasso srl, Biohortus, APOFRUIT ITALIA, Frutta IN or Vita Emanuele. One shipment is one Trip ID.
>
> **Temperature specification.** Each product has its own limits in the data (Limit Low, Limit High): Table Grapes 0 to 5.96 °C, Apricots 0 to 5.98 °C. Shipments with no product, and therefore no limits, cannot be scored. Leave them out of every percentage, keep them in the volumes, and tell me how many there are.
>
> **In-spec percentage.** For each shipment, calculate the percentage of transport time that stayed within the temperature specification: 1 minus (Time Below Low Hours plus Time Above High Hours) divided by the segment duration in hours, limited to 0 to 100%. Some shipments carry several products. For those, use the best product, meaning the product with the highest in-spec percentage, so each shipment counts once. Report the average of the shipment percentages.
>
> **What I want to see:**
> 1. Shipment volumes by product and by supplier.
> 2. In-spec percentage by carrier for Italy overall, with the number of shipments behind each carrier.
> 3. The same in-spec percentage by carrier for each of my three largest suppliers.
> 4. For my main carriers, GEA and Campagnolo, the in-spec percentage by month of departure within each supplier. Data starts on 29.07.2025, so do not invent months before then.
> 5. If a month stands out with a low in-spec percentage, drill into it and show the temperature curve of every shipment in that month (hours from departure against °C, with the 0 °C and 5.96 °C limit lines). A month stands out if it is at least 10 percentage points below that supplier–carrier pair's own average and the pair has at least 10 shipments in it.
> 6. Two or three findings, including whether temperatures run too warm and whether any transports show start/stop cycling.

---

## Part B: Features the app should create

| ID | Feature | Definition | Check on the test file |
|---|---|---|---|
| F1 | Shipment key | One row per Trip ID, mixed loads collapsed | 1,309 shipments in scope (Italian origin, 2025 departure) |
| F2 | Spec limits | Limit Low and Limit High from the product row | Table Grapes 0 / 5.96, Apricots 0 / 5.98, blank = none |
| F3 | Transport hours | Segment End − Segment Start, in hours | Mean about 47 h |
| F4 | Out-of-spec hours | Time Below Low Hours + Time Above High Hours | Blanks treated as 0 |
| F5 | % time in spec | 1 − F4 / F3, clamped to 0–100% | Min 0%, max 100% |
| F6 | Best-product % | Highest F5 among a shipment's product rows | Verify on mixed loads, e.g. serial PDA1W02N90 |
| F7 | Scored flag | Shipment has limits | 1,201 scored, 108 excluded |
| F8 | Departure month | Month of Actual Departure Time CET | Jul (8 shipments), Aug to Dec |

## Part C: Analyses the app should create

Tolerance: ±0.5 pt for carrier and supplier percentages, ±4 pts for monthly percentages (the reference deck was built from a slightly different cleaned file). Counts are shipments (n).

| ID | Analysis | Expected result |
|---|---|---|
| A1 | Shipments by supplier | Giacovelli 401, Agrimessina 325, Ci.da 295, Dino 69, Unacoa Salvi 50, Frudis 37, Lilla & Giuliani 34, Di Palma 27, Coniglio 26, Grasso 20, Mazzoni 16, Biohortus 3, Apofruit 2, Frutta IN 2, Vita Emanuele 2 |
| A2 | Shipments by product | Table Grapes 1,185, Apricots 16, blank 108 |
| A3 | % in spec by carrier, Italy overall | Overall 50.3% (1,201). Campagnolo 66.1% (558), GEA 33.1% (551), FGF 59.5% (46), PINTO GIOVANNI 61.2% (31) |
| A4 | Carrier % in spec, Giacovelli | Campagnolo 67.7% (310), GEA 21.3% (44), PINTO GIOVANNI 61.2% (31), FGF 32.5% (5) |
| A5 | Carrier % in spec, Agricola Ci.da | GEA 40.3% (182), Campagnolo 69.3% (72), FGF 63.8% (38) |
| A6 | Carrier % in spec, Agrimessina | GEA 29.4% (164), Campagnolo 60.6% (72) |
| A7 | Giacovelli × Campagnolo by month | Aug 54.5% (68), Sep 66.8% (79), Oct 71.2% (82), Nov 77.6% (65), Dec 71.1% (16) |
| A8 | Giacovelli × GEA by month | Aug 24.2% (17), Sep 22.0% (12), Oct 17.5% (13), Nov 16.5% (2) |
| A9 | Ci.da × GEA by month | Aug 43.2% (45), Sep 43.8% (65), Oct 31.7% (51), Nov 46.4% (20) |
| A10 | Ci.da × Campagnolo by month | Aug 67.2% (19), Sep 68.8% (22), Oct 65.0% (21), Nov 83.7% (10) |
| A11 | Agrimessina × GEA by month | Sep 20.0% (43), Oct 23.8% (71), Nov 45.9% (49) |
| A12 | Agrimessina × Campagnolo by month | Sep 48.0% (25), Oct 61.7% (23), Nov 71.4% (23) |

The monthly analyses (A7 to A12) use the user's "main carriers" (GEA and Campagnolo) and each supplier that the brief names.

## Part D: Drill-downs the app should create

| ID | Trigger | Expected drill-down |
|---|---|---|
| D1 | Giacovelli × Campagnolo, August: 54.5% against a pair average of 67.7% (−13.2 pts, n = 68) | Temperature curves for all 68 August shipments, 0 and 5.96 °C limit lines, title "68 Serial Numbers Found" |
| D2 | Agrimessina × Campagnolo, September: 48.0% against 60.6% (−12.6 pts, n = 25) | Curves for all 25 September shipments |
| D3 | Every other pair and month | No drill-down. Examples: Ci.da × GEA October (−8.6 pts) and Agrimessina × GEA September (−9.4 pts) are below the threshold, and Giacovelli × GEA November has only 2 shipments |

Under this rule exactly two drill-downs are expected. The reference deck drilled into more pairs (for example a November multigraph), so if the app generates more, review them against the threshold rather than the deck.

## Part E: Test checklist

| ID | Area | Test | Pass criterion |
|---|---|---|---|
| T01 | Features | The app proposes F1 to F8, or equivalent features | Each definition in Part B is present and the formula text matches |
| T02 | Features | Spec limits are read from the data, not from a single fixed threshold | Two different limit pairs shown (5.96 and 5.98) |
| T03 | Features | Blank-product shipments are excluded from % and counted separately | 108 excluded, 1,201 scored, message shown |
| T04 | Features | Best-product rule | A mixed-load serial takes its highest product % |
| T05 | Features | Clamp | No shipment below 0% or above 100% |
| T06 | Analysis | A1 and A2 are generated | Values match Part C |
| T07 | Analysis | A3 to A6 are generated with n per carrier | Values match Part C |
| T08 | Analysis | A7 to A12 are generated, GEA and Campagnolo only | Values match Part C, no months before August (Jul has 8 shipments in total) |
| T09 | Analysis | Percentages are means of shipment %, not pooled hours | Overall 50.3% |
| T10 | Analysis | Chart types are suitable | Volumes as columns, % with shipment-count line, months as columns |
| T11 | Drill-down | D1 and D2 are offered, and nothing else | Exact set of two |
| T12 | Drill-down | Curve counts | 68 and 25 |
| T13 | Drill-down | Curve chart has limit lines at 0 and 5.96 and x-axis in hours from departure | Visible and correct |
| T14 | Drill-down | Sensor readings are missing (tabular file only) | Clear message that curves need a temperature-reading export, with no crash |
| T15 | Summary | Findings match the numbers | GEA below 40%, Campagnolo above 60%, too-warm finding |

Prerequisite for T11 to T13: the temperature curves need the sensor-reading export (temperature matrix or ColdStream), which the tabular file does not contain.
