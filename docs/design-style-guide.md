# Program Manager AI — Design Style Guide

> Audit of the existing `frontend/` application, written from the code (42 CSS files, 47 TSX files) and from the screenshots shared during development.
> **Method note:** the app could not be run in the review browser (it could not load local pages), so nothing here comes from a live visual pass. Every number was produced by scanning the source with scripts; counts are exact for what the scripts matched. Anything that must be seen on screen is marked **(verify visually)**.
> **Scope note:** the brief mentioned an attached sample style guide. None was received, so the section order follows the list in the brief.

---

## 0. Revision history

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-10-06 | Claude (audit) | First complete audit and standard. No application code was changed. |

---

## 1. Introduction

Program Manager AI is a six-step wizard (Upload → Planner → Audit → Features → Analysis → Report) that turns SensiWatch / ColdStream cold-chain exports into an audited dataset, engineered features, analyses with charts, and a downloadable PowerPoint report. It is used by Carrier program managers.

The UI grew screen by screen with no design system. It has a small, well-chosen token file (`src/styles/theme.css`, 27 tokens) but most components bypass it: **286 hard-coded colour values (73 distinct) sit outside the token file**, there are **45 button class families**, **30 distinct font sizes**, and charts use **a different palette from both the UI and the exported deck**. This guide fixes one standard for each of those, and gives an ordered migration plan.

## 2. Purpose

1. A reference precise enough to rebuild any screen of the UI.
2. A rulebook another AI (or developer) can follow to refactor the codebase to match, without asking questions.
3. A checklist for reviewing new work.

## 3. Design principles

| Principle | What it means here |
|---|---|
| **Human decides, AI suggests** | AI output is shown as a suggestion with a reason; the reviewer confirms. No bulk "apply AI recommendations". (Already decided in this project.) |
| **One job per screen** | Each wizard step has one primary action, placed bottom-right. |
| **Evidence before action** | Show the numbers (rows, findings, counts) before asking for a decision. |
| **Quiet, corporate, dense** | Navy on white, one accent, no decoration. The data is the colour. |
| **Same meaning, same colour** | A colour means one thing everywhere (see §8.8). |
| **Accessible by default** | Text ≥ 4.5:1, controls visible to keyboard, colour never the only signal. |

---

## 4. Inventory (Step 0)

### 4.1 Technology

| Area | Finding |
|---|---|
| Framework | React 19.2, TypeScript 6, Vite 8, react-router-dom 7. Single-page app, `BrowserRouter`. |
| Styling | **Plain CSS**, one `.css` file per page/component, BEM-style names (`block__element--modifier`). No Tailwind, SCSS, CSS-in-JS or component library. |
| Tokens | CSS custom properties in `src/styles/theme.css` (colors, 3 radii, 2 shadows, 1 font stack). No spacing, type, z-index, duration or breakpoint tokens. |
| Charts | **Plotly** (`plotly.js-dist-min` via `react-plotly.js`) on screen; **python-pptx native charts** in the exported deck (`backend/app/services/report/report_style.py`). |
| Icons | 31 inline-SVG React components in `components/icons.tsx` (24×24 viewBox, `currentColor`). No icon library. |
| Fonts | **No web fonts loaded.** System stack `"Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif`. The deck uses Arial. |
| Theming | **Light only.** No `prefers-color-scheme` rules; no theme switch. |
| i18n | UI strings are English only (`<html lang="en">`). Only the *report content* (slide titles, explanations, summary) can be translated (DeepL), selected on the Report page. |
| State | Shared in-memory store (`src/state/sessionStore.ts`) + React state; not persisted across reload. |

### 4.2 Screens

| # | Route | Screen | Main parts |
|---|---|---|---|
| 1 | `/` | Welcome | Hero, flow explainer, start button |
| 2 | `/upload` | Upload Source Data | Client brief input, 4 file cards (SensiWatch required; ColdStream, Customer KPI Profile, Analysis Profile optional), actions |
| 3 | `/planner` | Planner | Recommendation cards (analysis / feature / configuration), tabs, bulk accept/reject, nav buttons |
| 4 | `/audit` | Data Audit | Per-file card; SensiWatch has 3 tabs (Outliers Check / Standard Check / Summary); stat tiles; issue cards; issue detail modal; affected-rows modal; Segment Length and Temperature outlier tabs with lane/product modals |
| 5 | `/features` | Feature Engineering | Stat tiles, feature cards, AI-suggestion and custom-KPI panels, feature detail modal, data preview |
| 6 | `/analysis` | Analysis | Stat tiles, toolbar (search/sort/filter), analysis cards + pagination, overall summary, AI/custom panels, analysis detail modal (Analysis / Selected Drill-downs tabs, drill-down panel, drill paths) |
| 7 | `/report` | Report | Language picker, slide list, final summary, preview-and-edit modal (rail, stage, inspector), export buttons |
| — | `*` | Redirect to `/` | — |

### 4.3 Shared components

`Header`, `StepIndicator`, `PageHeader`, `StatTile`, `Modal`, `ThinkingLoader` (+`Spinner`), `FileUploadCard`, `SourceSelect`, `ClientBriefInput`, `DataPreviewTable`, `ExcelTable` (new), `EditableNumberCell`, `AnalysisCard`, `AnalysisToolbar`, `AnalysisFilterBar`, `AnalysisChart`, `AnalysisDetailModal`, `AnalysisSuggestionCard`, `AddAnalysisForm`, `OverallAnalysisCard`, `DrilldownPanel`, `DrilldownPaths`, `FeatureCard`, `FeatureDetailModal`, `FeatureSuggestionCard`, `AddKpiForm`, `AuditReport`, `AuditIssueCard`, `AuditSummaryPanel`, `IssueRowsModal`, `OutlierCorrectionStep`, `SegmentOutlierTab`, `TemperatureOutlierTab`, `OutlierBoxPlot`, `PlanText`, `SlidePreview`, `ReportEditorModal`.

---

## 5. Brand identity

| Item | Current state | Standard |
|---|---|---|
| Logo | `public/carrier-logo.svg` (header, favicon, slide preview), `backend/app/assets/carrier-logo.png` (deck). Header height 32px, left, followed by a 1px divider and the product name "Program Manager AI" 15px/700 navy + page name 12.5px muted. | Keep. Logo min height 28px, clear space ≥ logo height / 2. Never recolour. |
| Product name | "Program Manager AI" (header), "Program Manager AI — Cold Chain Analysis" (deck footer), HTML `<title>` still says **"Carrier Global \| Cold Chain Data Upload"** (stale). | Product name: **Program Manager AI**. Set `<title>` to "Program Manager AI". *(Low)* |
| Primary brand colour | **UI `#152c73`** (214 token uses) vs **deck `#010198`** (client-specified "Carrier blue" in `report_style.py`) vs deck cover blue `#0a2ef5`. | **DECISION NEEDED** — see §6.2. |
| Tagline | None. | Not present in the app. |

---

## 6. Colour

### 6.1 What exists today

**Tokens defined (`theme.css`)**: 5 brand blues, 8 neutral/semantic, 6 accent (purple/teal/amber ± bg), 3 radii, 2 shadows, 1 font.

**Drift found**

| Problem | Evidence |
|---|---|
| Hard-coded colours outside tokens | 286 uses, 73 distinct hex in 34 files, 20 distinct `rgba()`. Heaviest files: `OutlierTabs.css` 64, `ClientBriefInput.css` 37, `PlannerPage.css` 37, `ExcelTable.css` 36 (mostly `var(--x, #fallback)`). Top values: `#ffffff` ×72 (should be `--color-surface`/white), `#64748b` ×15, `#dde3ed` ×10, `#e2e8f0` ×10, `#152c73` ×10 (a token typed by hand). |
| Undefined variables used with a fallback | `--color-bg-subtle` (5), `--color-bg-alt` (2), `--color-surface-raised` (2), `--color-success-text` (1), `--font-mono` (1). They silently use the fallback hex. |
| ≥ 15 near-duplicate neutrals | `#64748b #dde3ed #e2e8f0 #f8f9fa #f4f6f8 #f7f9fc #f1f5f9 #94a3b8 #cbd5e1 #334155 #6b7a99 #5b6285 #8a90ad #b0bec5 #1a2340` next to tokens `#dde3ef #5b6478 #f4f6fb`. |
| Two purples | token `#6f42c1` vs `#6d3fc0` (7 uses, 3 files) vs `#6b2fb3` (Planner). |
| Three reds | token `#c62828` vs `#c0392b` (7) vs `#dc2626` (4). |
| Five greens | token `#1a8f5e` vs `#2a7a3b`, `#15803d`, `#2e7d32`, `#10b981`. |
| Five ambers | token `#8a5a10` vs `#f59e0b`, `#92400e`, `#c98a1b`, `#f57f17`. |
| A second palette | `ClientBriefInput.css` uses its own legacy navy `#002e6e`, `#1a2340`, `#6b7a99`, `#dde3ed` (the Upload screen). |
| Dark mode | Not present in the app. |

### 6.2 DECISION NEEDED — one brand blue

| Option | Result | Recommendation |
|---|---|---|
| A. UI navy `#152c73` everywhere (deck changes to it) | One blue; contrast on white 12.81:1 | **Recommended for the screen UI.** |
| B. Deck/client blue `#010198` everywhere | Matches the client's stated Carrier blue; 14.39:1 | Choose this if the client brand team mandates it. |
| C. Keep both (UI `#152c73`, deck `#010198`) | Zero work, visible mismatch between preview and download | Not recommended. |

This guide uses **`#152c73`** (option A) and lists the deck constant as a follow-up (§16, Phase 6).

### 6.3 Standard palette

All ratios are WCAG 2.x, computed for the exact pairs.

**Brand and surfaces**

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `--color-brand-primary` | `#152c73` | Primary buttons, headings, active tab, links to action | 12.81 on white |
| `--color-brand-primary-dark` | `#0d1c4d` | Hover/pressed on primary; overlays | 17.6 on white |
| `--color-brand-accent` | `#1891f6` | **Fills, focus ring, selection only — not text** | 3.27 on white (fails for text) |
| `--color-brand-tint` | `#eaf1fb` | Selected/hover background, info banner | navy text 11.27 |
| `--color-brand-tint-strong` | `#dce7fa` | Pressed tint, table highlight header | navy text 10.28 |
| `--color-bg-page` | `#f4f6fb` | Page background | text 14.55 |
| `--color-surface-card` | `#ffffff` | Cards, modals, inputs | text 15.73 |
| `--color-surface-subtle` | `#f4f6f8` | Table header, hint boxes, disabled fill | replaces 5 greys |
| `--color-border-default` | `#dde3ef` | Card and divider borders (decorative) | 1.29 (OK: decorative only) |
| `--color-border-strong` | `#7b8599` | **Input, checkbox and button borders** (a control boundary must be ≥ 3:1) | 3.71 on white, 3.43 on page |
| `--color-overlay` | `rgba(11,20,51,0.5)` | Modal backdrop | — |

**Text**

| Token | Hex | Use | Contrast on white |
|---|---|---|---|
| `--color-text-primary` | `#1b2333` | Body, table cells | 15.73 |
| `--color-text-secondary` | `#5b6478` | Hints, labels, secondary buttons' icons | 5.93 (5.49 on page bg) |
| `--color-text-disabled` | `#8b93a5` | Disabled text only (exempt from contrast) | 3.08 |
| `--color-text-on-brand` | `#ffffff` | Text on navy / purple / error fills | 12.81 / 6.51 / 5.62 |
| `--color-link` | `#0b63c5` | Text links (replaces `#1891f6` which fails) | 5.82 on white, 5.39 on page |

**Status (semantic) — one hue per meaning**

| Meaning | Text/icon | Background | Contrast | Note |
|---|---|---|---|---|
| Success / ready / reviewed / template | `#137a4f` | `#e8f7f0` | 4.84 | Existing `#1a8f5e` is only 4.09 on white and 3.70 on its tint: **fails small text**. Keep `#1a8f5e` for fills/icons only. |
| Error / required / critical | `#c62828` | `#fdecec` | 4.92 | Existing token passes. |
| Warning / pending / stale | `#8a5a10` | `#fbf0dc` | 5.24 | Existing token passes. |
| Info / planned / existing | `#1a6fb3` | `#e8f0ff` | 4.62 | Use instead of ad-hoc blues. |
| AI-generated / generated code | `#6f42c1` | `#f1ebfa` | 5.58 | **Purple = AI only** (see §8.8). |
| Data / teal accent | `#0b6f71` | `#e3f4f4` | 5.25 | Existing `#0f8b8d` is 3.63 as text: use only as a fill under white *icons*. |
| Neutral / new / default | `#5b6478` | `#f4f6fb` | 5.49 | — |

**Failing pairs found in code today**

| Pair | Where | Ratio | Fix |
|---|---|---|---|
| `#94a3b8` on white | ExcelTable menu button, count labels | 2.56 | → `--color-text-secondary` |
| `#f57f17` on `#fff8e1` | `ClientBriefInput` warning badge | 2.49 | → warning pair |
| `#10b981` on white | Temperature "ideal" pill | 2.54 | → success pair |
| `#8a90ad` on white | Step indicator labels (inactive) | 3.15 | → `--color-text-secondary` |
| `#1891f6` on white / page | Default `<a>` colour, several hover colours | 3.27 / 3.03 | → `--color-link` |
| `#1a8f5e` text on white / tint | 11px status pills (`features-page__status-pill`, `audit-page__status--reviewed`) | 4.09 / 3.70 | → success pair |
| `#0f8b8d` text on `#e3f4f4` | teal pills | 3.63 | → teal pair |
| `#dc2626` on `#fef2f2` | Outlier retry | 4.41 | → error pair |
| Control borders `#dde3ef` | Inputs, selects, secondary buttons | 1.29 / 1.19 | → `--color-border-strong` |

### 6.4 Old colour → new token mapping (complete for hex ≥ 2 uses; the rest map by rule below)

| Old value(s) | → New token |
|---|---|
| `#fff`, `#ffffff` (as a surface) | `--color-surface-card` |
| `#fff`/`#ffffff` (as text on a fill) | `--color-text-on-brand` |
| `#152c73` typed by hand | `--color-brand-primary` |
| `#0d1c4d`, `#002e6e`, `#1a2340`, `#1a2b6b` | `--color-brand-primary-dark` |
| `#eaf1fb`, `#e8f0ff` (as selected bg) | `--color-brand-tint` |
| `#dce7fa` | `--color-brand-tint-strong` |
| `#1891f6` (fill, ring, border-on-hover) | `--color-brand-accent` |
| `#1891f6` (text/link) | `--color-link` |
| `#1b2333` | `--color-text-primary` |
| `#5b6478`, `#64748b`, `#6b7a99`, `#5b6285`, `#8a90ad`, `#334155` (secondary), `#94a3b8` | `--color-text-secondary` (`#334155` → `--color-text-primary`) |
| `#dde3ef`, `#dde3ed`, `#e2e8f0`, `#f1f5f9` (borders) | `--color-border-default` |
| `#cbd5e1`, `#b0bec5` (control borders) | `--color-border-strong` |
| `#f4f6fb` | `--color-bg-page` |
| `#f4f6f8`, `#f8f9fa`, `#f7f9fc` | `--color-surface-subtle` |
| `#1a8f5e`, `#2a7a3b`, `#15803d`, `#2e7d32`, `#10b981` (text) | `--color-status-success-text` |
| `#1a8f5e`, `#10b981` (fill/icon) | `--color-status-success` |
| `#e8f7f0`, `#e8f7ee`, `#e8f5e9`, `#f0fdf4`, `#bbf7d0` | `--color-status-success-bg` |
| `#c62828`, `#c0392b`, `#dc2626`, `#a13c2a` | `--color-status-error` |
| `#fdecec`, `#fbe9e7`, `#ffebee`, `#fef2f2`, `#fff0f0`, `#fecaca`, `#f5c2c2` | `--color-status-error-bg` (borders → `--color-status-error`) |
| `#8a5a10`, `#92400e`, `#8a5a00`, `#c98a1b`, `#f57f17` | `--color-status-warning` |
| `#f59e0b` | `--color-selection` (amber selected-row marker; keep as a fill) |
| `#fbf0dc`, `#fff4e0`, `#fff4dd`, `#fff3d6`, `#fef3c7`, `#fff8e1` | `--color-status-warning-bg` |
| `#6f42c1`, `#6d3fc0`, `#6b2fb3` | `--color-status-ai` |
| `#f1ebfa`, `#f0ecff`, `rgba(109,63,192,0.06–0.1)` | `--color-status-ai-bg` |
| `#1a6fb3` | `--color-status-info` (`#e8f0ff` → `--color-status-info-bg`) |
| `#0f8b8d` | `--color-status-data` (text `#0b6f71` = `--color-status-data-text`) |
| `rgba(13,28,77,0.45)`, `rgba(11,20,51,0.5)` | `--color-overlay` |
| `rgba(15,23,42,0.18–0.22)`, `rgba(0,0,0,0.08–0.25)` | `--shadow-*` (see §7.4) |

Rule for any value not listed: pick the token with the same hue family and role; never add a new hex without adding a token.

---
## 7. Design tokens

### 7.1 Typography

**Current state.** One family (system `Segoe UI` stack) for everything; monospace stack for code (6 uses, written three different ways: a literal stack ×6, `monospace` ×2, `var(--font-mono, …)` ×2 with `--font-mono` undefined). **30 distinct font sizes** (top: 12.5px ×94, 12px ×71, 13px ×46, 11.5px ×41, 11px ×35, 10.5px ×34, 13.5px ×21, 14px ×15, 10px ×12); weights 700 ×113, 800 ×80, 600 ×44, 500 ×9, 400 ×2; line-heights 12 values (1.5 ×29 dominant); letter-spacing 0.03em ×17, 0.04em ×12, 0.02em ×11; `text-transform: uppercase` ×28 (labels, pills, table headers). **48 declarations are below 11px** (10.5px ×34, 10px ×12, 9.5px ×2: pills, badges, step numbers, icons).

**Standard.** A 7-step scale, half-pixel sizes removed. Weights 400 / 600 / 700 / 800 only (500 removed).

| Token | Size / line / weight | Role (replaces) |
|---|---|---|
| `--font-display` | 32 / 1.2 / 800 | Welcome title (32) |
| `--font-h1` | 24 / 1.25 / 800 | Page title: `PageHeader` (23), Upload heading (24) |
| `--font-h2` | 18 / 1.3 / 800 | Card / source title (17, 18, 19) |
| `--font-h3` | 15 / 1.35 / 800 | Section title, card name, modal title 16→15 (15, 16, 17) |
| `--font-body` | 13 / 1.5 / 400 | Body, inputs, table cells (12.5, 13, 13.5) |
| `--font-small` | 12 / 1.45 / 400–600 | Hints, secondary text, dense table text (11.5, 12, 12.5) |
| `--font-caption` | 11 / 1.4 / 700 + uppercase + 0.04em | Table headers, pills, labels, chart axis (9.5, 10, 10.5, 11, 11.5) |
| Button text | 13 / 1 / 700 (md); 12 / 1 / 700 (sm); 14 / 1 / 700 (lg) | Buttons (11.5, 12.5, 13.5, 14) |
| Stat value | 28 / 1.1 / 800 (tile), 19 (compact tile) | `StatTile` |

Rules: minimum text size **11px** (raises the 48 sub-11px declarations); uppercase only for caption-role text; numbers in tables and tiles use `font-variant-numeric: tabular-nums`. Monospace: `--font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace`.

### 7.2 Spacing

**Current state.** Padding/margin/gap use 21 distinct pixel values. Gap: 8px ×57, 6px ×53, 10px ×47, 12px ×41, 4px ×19, 14px ×18, 16px ×12. Padding: 10px ×68, 8px ×54, 12px ×41, 6px ×36, 14px ×32, 20px ×31, 16px ×29, 4px ×20, 18px ×19. Off-grid values 3, 5, 7, 9, 11, 14, 18, 22, 28 appear ≈ 90 times.

**Standard.** 4px base with the half-step `6` and `10` kept because they dominate dense UI.

| Token | px | Typical use |
|---|---|---|
| `--space-1` | 4 | Icon gap, chip inner gap |
| `--space-2` | 6 | Tight control gap |
| `--space-3` | 8 | Default control gap, button group gap (dense) |
| `--space-4` | 10 | Input padding vertical, card inner gap |
| `--space-5` | 12 | Default gap between controls, modal sections |
| `--space-6` | 16 | Card padding (compact), section gap |
| `--space-7` | 20 | Card padding, between cards |
| `--space-8` | 24 | Page side padding, large gaps |
| `--space-9` | 32 | Between page sections |
| `--space-10` | 40 | Empty-state vertical padding |
| `--space-page-bottom` | 60 | Space below last page element |

Snap rule: 3→4, 5→4 or 6, 7→6 or 8, 9→8 or 10, 11→12, 14→12 or 16, 18→16 or 20, 22→24, 28→24 or 32 (choose the nearer; prefer the larger when ties).

### 7.3 Radius and borders

**Current state.** `--radius-sm/md/lg` (6/10/14) are used 86 / 41 / 11 times, but literals 4px ×7, 5px ×3, 6px ×10, 8px ×9, 10px ×6, 12/14/20px ×3 also appear; pills `999px` ×44; circles `50%` ×22. Borders: `1px solid var(--color-border)` ×83 dominant; `1.5px` ×6 (Planner, step indicator); dashed ×4.

**Standard.** `--radius-xs` 4 (inline code, tiny tags, edit input), `--radius-sm` 6 (buttons, inputs, small controls), `--radius-md` 10 (cards inside cards, popovers, tiles), `--radius-lg` 14 (cards, modals), `--radius-pill` 999, `--radius-circle` 50%. Border width 1px everywhere (1.5px → 1px); focus uses a ring, not a thicker border.

### 7.4 Elevation

**Current state.** `--shadow-sm` ×13, `--shadow-md` ×7, plus 11 one-off shadows (modal `0 12px 40px rgba(0,0,0,.25)`, popover `0 10px 28px rgba(15,23,42,.22)`, frozen-column edge, focus rings).

| Token | Value | Use |
|---|---|---|
| `--shadow-sm` | `0 1px 2px rgba(21,44,115,0.06)` | Cards, header |
| `--shadow-md` | `0 4px 16px rgba(21,44,115,0.08)` | Raised badges, hovered cards |
| `--shadow-lg` | `0 12px 40px rgba(11,20,51,0.25)` | Modals |
| `--shadow-popover` | `0 10px 28px rgba(15,23,42,0.22)` | Dropdowns, column menus |
| `--shadow-pinned` | `2px 0 4px -1px rgba(15,23,42,0.18)` | Edge of frozen table columns |
| `--ring-focus` | `0 0 0 2px #fff, 0 0 0 4px #1891f6` | Keyboard focus (§11) |

### 7.5 z-index

Current: 0, 1 ×6, 2, 3, 20 ×3, 100 (`Modal`), 1000 ×2 (audit modals), 1100 (table menu). `Modal` (100) is lower than the audit modals (1000) — a modal opened from another modal can render behind it.

| Token | Value |
|---|---|
| `--z-base` / `--z-raised` | 0 / 1 |
| `--z-sticky` / `--z-sticky-corner` | 2 / 3 (table header / pinned header cell) |
| `--z-dropdown` | 20 |
| `--z-modal` | 1000 (**also set `Modal.css` to this**) |
| `--z-popover` | 1100 (menus opened inside a modal) |

### 7.6 Motion

Current: `0.15s ease` ×~22 (dominant), `0.12s` ×6, `0.1s` ×1; loaders `0.7s–2.4s`; `prefers-reduced-motion` handled in **1** file only.

| Token | Value |
|---|---|
| `--duration-fast` | 120ms (small hover, icon) |
| `--duration-base` | 150ms ease (default: hover, colour, border) |
| `--duration-slow` | 250ms ease (panel open/close) |
| Spinner | 700ms linear infinite |
| Rule | Under `prefers-reduced-motion: reduce`, set all transitions and animations to `none` globally (§10). |

### 7.7 Breakpoints and containers

Current breakpoints: 560, 640, 680, 720, 900, 960, 961, 1000 (8 values, 11 queries). Containers: header 1080, Welcome 1140, Upload 1080, Audit/Features/Analysis/Report 960, Planner 860 — so the header edge and the page content edge **do not align** on four screens.

| Token | Value |
|---|---|
| `--bp-sm` | 640px (phone → stack) |
| `--bp-md` | 960px (tablet → desktop) |
| `--container-page` | 1080px (header and all page content; replaces 860/960/1140) |
| `--container-modal-sm / md / lg / xl` | 640 / 900 / 1080 / 1320 |
| `--page-padding` | 28px 24px 60px |

**DECISION NEEDED — content width.** Options: (a) 1080 for everything (recommended: aligns with the header, fits wide tables and charts); (b) keep 960 for reading-heavy pages (Audit, Features, Report) and 1080 for the rest (header would still misalign); (c) widen the header to 960. Recommendation: (a).

### 7.8 Ready-to-use tokens (CSS)

```css
/* src/styles/tokens.css — import once, before any component CSS */
:root {
  /* Brand */
  --color-brand-primary: #152c73;
  --color-brand-primary-dark: #0d1c4d;
  --color-brand-accent: #1891f6;          /* fills, focus ring. NOT text */
  --color-brand-tint: #eaf1fb;
  --color-brand-tint-strong: #dce7fa;

  /* Surfaces, borders, text */
  --color-bg-page: #f4f6fb;
  --color-surface-card: #ffffff;
  --color-surface-subtle: #f4f6f8;
  --color-border-default: #dde3ef;
  --color-border-strong: #7b8599;         /* control borders (>= 3:1) */
  --color-overlay: rgba(11, 20, 51, 0.5);
  --color-text-primary: #1b2333;
  --color-text-secondary: #5b6478;
  --color-text-disabled: #8b93a5;
  --color-text-on-brand: #ffffff;
  --color-link: #0b63c5;
  --color-selection: #f59e0b;             /* selected-row marker */

  /* Status */
  --color-status-success: #1a8f5e;        /* fills / icons */
  --color-status-success-text: #137a4f;
  --color-status-success-bg: #e8f7f0;
  --color-status-error: #c62828;
  --color-status-error-bg: #fdecec;
  --color-status-warning: #8a5a10;
  --color-status-warning-bg: #fbf0dc;
  --color-status-info: #1a6fb3;
  --color-status-info-bg: #e8f0ff;
  --color-status-ai: #6f42c1;
  --color-status-ai-bg: #f1ebfa;
  --color-status-data: #0f8b8d;           /* fills / icons */
  --color-status-data-text: #0b6f71;
  --color-status-data-bg: #e3f4f4;
  --color-status-neutral-bg: #f4f6fb;

  /* Chart (see §9) */
  --chart-1: #152c73; --chart-2: #1891f6; --chart-3: #617080;
  --chart-4: #61b549; --chart-5: #f6d009; --chart-6: #bac0d0;

  /* Type */
  --font-sans: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
  --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  --text-display: 32px; --text-h1: 24px; --text-h2: 18px; --text-h3: 15px;
  --text-body: 13px; --text-small: 12px; --text-caption: 11px;
  --weight-regular: 400; --weight-semibold: 600; --weight-bold: 700; --weight-heavy: 800;
  --leading-tight: 1.25; --leading-body: 1.5;

  /* Space */
  --space-1: 4px; --space-2: 6px; --space-3: 8px; --space-4: 10px; --space-5: 12px;
  --space-6: 16px; --space-7: 20px; --space-8: 24px; --space-9: 32px; --space-10: 40px;

  /* Shape */
  --radius-xs: 4px; --radius-sm: 6px; --radius-md: 10px; --radius-lg: 14px;
  --radius-pill: 999px; --radius-circle: 50%;
  --shadow-sm: 0 1px 2px rgba(21, 44, 115, 0.06);
  --shadow-md: 0 4px 16px rgba(21, 44, 115, 0.08);
  --shadow-lg: 0 12px 40px rgba(11, 20, 51, 0.25);
  --shadow-popover: 0 10px 28px rgba(15, 23, 42, 0.22);
  --shadow-pinned: 2px 0 4px -1px rgba(15, 23, 42, 0.18);
  --ring-focus: 0 0 0 2px #ffffff, 0 0 0 4px #1891f6;

  /* Layering, motion, layout */
  --z-sticky: 2; --z-sticky-corner: 3; --z-dropdown: 20; --z-modal: 1000; --z-popover: 1100;
  --duration-fast: 120ms; --duration-base: 150ms; --duration-slow: 250ms;
  --container-page: 1080px;
}

/* Legacy aliases — delete each alias when its last use is migrated (Phase 1). */
:root {
  --carrier-blue: var(--color-brand-primary);
  --carrier-blue-dark: var(--color-brand-primary-dark);
  --carrier-light-blue: var(--color-brand-accent);
  --carrier-blue-tint: var(--color-brand-tint);
  --carrier-blue-tint-2: var(--color-brand-tint-strong);
  --color-bg: var(--color-bg-page);
  --color-surface: var(--color-surface-card);
  --color-border: var(--color-border-default);
  --color-text: var(--color-text-primary);
  --color-text-muted: var(--color-text-secondary);
  --color-success: var(--color-status-success);
  --color-success-bg: var(--color-status-success-bg);
  --color-error: var(--color-status-error);
  --color-error-bg: var(--color-status-error-bg);
  --color-required: var(--color-status-error);
  --accent-purple: var(--color-status-ai);
  --accent-purple-bg: var(--color-status-ai-bg);
  --accent-teal: var(--color-status-data);
  --accent-teal-bg: var(--color-status-data-bg);
  --accent-amber: var(--color-status-warning);
  --accent-amber-bg: var(--color-status-warning-bg);
  --color-bg-subtle: var(--color-surface-subtle);   /* was undefined */
  --color-bg-alt: var(--color-surface-subtle);      /* was undefined */
  --color-surface-raised: var(--color-surface-subtle); /* was undefined */
  --color-success-text: var(--color-status-success-text); /* was undefined */
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
}
```

---

## 8. Component specifications

### 8.1 Buttons

**Current state.** **45 button class families**, each page re-declaring the same button: `upload-page__btn`, `audit-page__btn`, `features-page__btn`, `analysis-page__btn`, `report-page__btn`, `planner-page__btn--*`, `outlier-step__btn`, `add-kpi-form__btn`, `add-analysis-form__btn`, `audit-issue__btn`, `drilldown-btn`, plus ad-hoc ones.

| Variant | Found | Differences |
|---|---|---|
| Primary (navy) | all pages | padding 6×14, 7×16, 8×16, 8×18, 9×20, 10×20, 11×24; font 11.5 / 12.5 / 13.5 / 14; radius 6 (Planner 8) |
| Primary (purple, "AI") | `analysis-suggestion__btn`, `feature-suggestion__btn` | same shape, purple fill |
| Secondary | footers: transparent + 1px `--color-border` + **muted** text; editor/preview/toolbar: surface + border + **navy** text | two looks for one role |
| Pill outline | `drilldown-btn`, `analysis-detail__suggest-more-btn` (radius 999) | third shape |
| Link / tertiary | `features-page__link-btn`, "Revert", "Reset", "Clear filters" | text-only, navy/light-blue |
| Destructive | **No destructive button exists.** Delete/Revert are text links or red icon buttons (trash). | — |
| Icon-only | modal ✕ (24px glyph), `excel-table__menu-btn` (13px icon, ≈ 21px target), `report-editor__icon-btn`, step arrows | targets 21–36px |
| Toggle | tabs, `aria-expanded` toggles (code view, drill paths), checkbox rows | — |

| State | Current | Gap |
|---|---|---|
| Hover | 96 `:hover` rules, mostly colour/border change | ok |
| Focus | **1** `:focus-visible` rule in the whole app; 14 `outline: none` | **High**: keyboard focus is invisible on almost every control |
| Active/pressed | none | add |
| Disabled | `opacity .6` (pages) vs `.35` / `.4` / `.5` (components); 53 rules | unify to one |
| Loading | label swap ("Building report…", "Opening…") on some; `<Spinner/>` + "Thinking…" on others | unify |

**Standard — one `Button` pattern** (class `.btn` + modifiers; replaces all 45 families).

| | sm | **md (default)** | lg |
|---|---|---|---|
| Height / padding | 28px / 0 12px | 36px / 0 16px | 40px / 0 20px |
| Font | 12 / 700 | 13 / 700 | 14 / 700 |
| Where | in cards, toolbars, modals | forms, panels | page footers, page header actions |
| Radius | `--radius-sm` everywhere (pill shape removed) | | |

| Variant | Default | Hover | Active | Disabled |
|---|---|---|---|---|
| `btn--primary` | bg `brand-primary`, text `on-brand`, border same | bg `brand-primary-dark` | same as hover + `translateY(1px)` | opacity .45, `cursor: not-allowed` |
| `btn--secondary` | bg `surface-card`, border `border-strong`, text `text-primary` | bg `brand-tint`, border `brand-primary` | bg `brand-tint-strong` | opacity .45 |
| `btn--ai` | bg `status-ai`, text white | darken 8% | — | opacity .45 |
| `btn--tertiary` | no bg/border, text `color-link` (underlined on hover) | underline | — | text-disabled |
| `btn--danger` | bg `surface-card`, border + text `status-error` (solid red only inside a confirm dialog) | bg `status-error-bg` | — | opacity .45 |
| `btn--icon` | 32×32 (min 24×24), radius sm, text `text-secondary` | bg `brand-tint` | — | opacity .45 |

All variants: `:focus-visible { outline: none; box-shadow: var(--ring-focus); }`, `transition: background, color, border-color var(--duration-base) ease`. Loading: keep width, replace label with the verb-ing form and show the 14px spinner before it, set `aria-busy="true"` and disable.

Do: one primary per view region. Don't: pill-shaped buttons, a coloured border on a disabled button, icon-only buttons without `aria-label`.
Accessibility: contrast of every label ≥ 4.5:1 (primary 12.81, AI 6.51, danger 5.62); target ≥ 28px high (24px minimum for icon-only).

### 8.2 Button placement

**Current patterns**

| Context | Dominant pattern | Deviations |
|---|---|---|
| Wizard page footer (Audit, Features, Analysis) | `[‹ Back to X (secondary)] ………… [Continue to Y › (primary)]`, `justify-content: space-between`, gap 12 | **Report**: Back only; export buttons now live in the top bar *and* bottom bar (`report-page__export-host`). **Upload**: count text left ("N of 4 files selected"); `[Add all samples]` `[Clear All]` (both secondary) and `[Upload & Continue]` (primary) grouped right. **Planner**: nav buttons grouped in `planner-page__nav-btns`. |
| Page header | Title left, one secondary action right (`PageHeader action`, e.g. "Back to Analysis") | Back appears both in the header and the footer on Analysis/Report. |
| Forms inside modals (Add Analysis, Add KPI) | `[Primary (Add)] [Cancel (secondary)]`, left-aligned, gap 10 | **Opposite order** from the wizard footer (primary rightmost). |
| Modals | Close ✕ top-right; no footer | Report editor has a toolbar row instead of a footer. |
| Cards | Primary action bottom-right or full width (`panel-btn`: `width:100%`) in the Features/Analysis AI panels; `Run`/`Retry` bottom of a card | — |
| Table toolbars | Search left; bulk button(s) right | — |
| Destructive | Inline text link ("Revert") beside the resolved item | No confirm dialog anywhere. |

**Standard**

```
WIZARD PAGE FOOTER                                      (btn--lg)
┌───────────────────────────────────────────────────────────────┐
│ [‹ Back to Audit]                       [Continue to Analysis ›]│
│  secondary, left                              primary, right   │
└───────────────────────────────────────────────────────────────┘

PAGE HEADER
┌───────────────────────────────────────────────────────────────┐
│ [icon] Title                                  [secondary action]│
│        subtitle                                                 │
└───────────────────────────────────────────────────────────────┘

FORM / DIALOG FOOTER                                    (btn--md)
┌───────────────────────────────────────────────────────────────┐
│                                         [Cancel]  [Add analysis]│
│                                       secondary    primary      │
└───────────────────────────────────────────────────────────────┘

TABLE / LIST TOOLBAR                                    (btn--sm)
┌───────────────────────────────────────────────────────────────┐
│ [🔍 Search…]  [Filter ▾]                  [Bulk action] [Export]│
└───────────────────────────────────────────────────────────────┘

DESTRUCTIVE: btn--danger, never adjacent to the primary; always asks "Delete X?" with [Cancel] [Delete].
```

Rules: primary is always rightmost; cancel/back is secondary to its left; gap `--space-3` (8) in toolbars, `--space-5` (12) in footers; at ≤ 640px the footer stacks, primary on top, full width. On the Report page the export pair appears **once** in the footer (the duplicate in the top bar is a deliberate user request — keep both only if the user confirms; see §15).

### 8.3 Form controls

**Current state.** Inputs `8px 10px`, 12.5–13px, `1px solid --color-border`, radius sm (consistent); selects the same; textareas 14×16 (Upload brief) vs 8×10; native checkboxes with `accent-color` only in some places; **no custom switch, slider, radio or date picker exists**; the analysis filter bar has a numeric range pair; labels are uppercase 11px muted (field labels) in forms, plain 12.5px in others; required marked by a red "Required" pill on upload cards, not by an asterisk; helper text 11.5–12px muted; errors red text on `--color-error-bg` 12.5px.

**Standard**

| Part | Spec |
|---|---|
| Label | `--font-small` 12 / 700, `text-primary`, above the field, `margin-bottom 4`; optional → "(optional)" muted; required → red "Required" pill is allowed on file cards only, elsewhere "*" in `status-error` |
| Input / select | height 36, padding `0 10px` (textarea `8px 10px`), 13px, bg surface, border `1px solid border-strong`, radius sm, placeholder `text-secondary` |
| Focus | border `brand-primary` + `--ring-focus` (never `outline: none` alone) |
| Error | border `status-error`, message below 12px `status-error`, `aria-invalid` + `aria-describedby` |
| Helper | 12px `text-secondary` below, `margin-top 4` |
| Disabled | bg `surface-subtle`, text `text-disabled` |
| Checkbox / radio | native, 16×16, `accent-color: var(--color-brand-primary)`, label to the right, whole label clickable |
| Field width | form column max 560px; two-column grid gap 16; vertical rhythm 14px between fields |
| Search box | icon 14px left (inside), clear ✕ right when non-empty, same height/border as input |

Not present in the app: switch, slider, date picker, multi-select (the Excel-style menu with checkboxes is the multi-select pattern).

### 8.4 Filters

**Current state.** Four separate filter patterns: (1) `AnalysisToolbar`: search + sort + filter popover with a count of active filters; (2) `AnalysisFilterBar`: pill filters, active pill `--carrier-blue-tint`, close ✕ glyph 18px; (3) audit `col-search` with a type-ahead dropdown; (4) the new `ExcelTable` header menu (sort + value checklist + "Clear filter"). Outlier tabs add a fifth: a lane/product text search. Clear/reset wording differs: "Clear filters", "Clear filter", "Clear filters and sorting", "✕".

**Standard**

| Rule | Spec |
|---|---|
| Placement | Search left, filters next to it, sort at the far right of the same toolbar row, above the list/table. Column-level filters sit in the column header (ExcelTable pattern). |
| Applied indicator | Filter button shows a solid `brand-primary` fill (ExcelTable funnel) or a count badge (toolbar); a "N of M rows" line is shown next to the table. |
| Clear | One text link "Clear filters" (and "Clear sorting" when a sort is active) next to the count; ✕ only inside a search box. |
| Reset on navigation | Filters stay with the screen state in `sessionStore`; they reset when the data changes. |
| Multi-select | Checkbox list with search, "(Select all)", counts per value. |

### 8.5 Cards and containers

| Component | Current | Standard |
|---|---|---|
| Page card (source card) | surface, `1px border`, radius lg (14), `--shadow-sm`, padding 18×20, margin-bottom 18 — repeated in 5 page CSS files | one `.card`: padding `--space-7` (20), radius lg, border default, `shadow-sm` |
| Inner panel | border default, radius md (10), padding 14–18 | `.panel` radius md, padding 16 |
| Stat tile | 20×22 padding / 48px icon (default); **overridden to 10×12 / 38px in 5 places** (Features, Analysis and Report pages, `AuditReport`, `OutlierCorrectionStep`) by copy-pasted CSS | Two sizes as variants: `stat-tile` (default) and `stat-tile--compact`; delete the 5 overrides |
| AI panel | purple tint bg + purple title | `.panel--ai`: bg `status-ai-bg`, title `status-ai` |
| Banner / hint | grey `#f4f6f8` hint, red-tint error, amber notice; each re-styled per page | `.notice--info / --warning / --error`: tint bg, 1px border of the status colour, 12.5px text, radius sm, padding 8×12 |
| Toast | Not present in the app | — |
| Drawer | Not present in the app | — |
| Tooltip | Only native `title` attributes (37) — no component | Keep `title` for short hints; add visible text for anything essential (touch has no hover) |
| Empty state | Left-aligned muted text + one primary button (`__empty`, padding 40) | Keep; centre-align inside cards; always offer the next action |
| Loading | `ThinkingLoader` (cycling messages, elapsed timer, `inline` variant) | Keep; it is the one consistent loading pattern |

### 8.6 Modals

Current: three implementations — `Modal` (900px, overlay `rgba(11,20,51,.5)`, z 100), `audit-issue__modal` (640px, overlay `rgba(13,28,77,.45)`, z 1000), `issue-rows-modal` (1080px) — plus `report-editor__panel` (1320px × 92vh, via `Modal`).

Standard: one `Modal` component; header 16×20 with `--font-h3` title and a 32px icon-button ✕; body padding 18×20, scrolls; sizes sm 640 / md 900 / lg 1080 / xl 1320; overlay `--color-overlay`; `role="dialog"`, `aria-modal`, `aria-labelledby`; Escape closes; focus moves in and returns on close. **Today `Modal.tsx` has Escape-to-close and an aria-labelled ✕ only: no `role="dialog"`, no `aria-modal`, no focus trap or focus return (the audit-issue and rows modals are the same)**; footer for forms per §8.2.

### 8.7 Tables and lists

**Current state.** Five table implementations: `DataPreviewTable`, the fallback table in `AnalysisChart`, the preview table in `AddKpiForm`, `IssueRowsModal`, and the new `ExcelTable` (now also used by the Segment Length and Temperature outlier views, which leaves the `.outlier-lane-card__table` CSS in `OutlierTabs.css` unused). Header 11px uppercase 600–700 muted on a grey fill; cell padding 5–6×14; no zebra; hover tint `--carrier-blue-tint`; selected row amber (`#fdf1dc`, marker `#f59e0b`); numeric columns are left-aligned (right-align appears only in tile/label contexts); pagination = 30px square prev/next + "1 / 3" (Analysis only); sorting/filtering only in `ExcelTable`.

**Standard (`ExcelTable` is the reference)**

| Part | Spec |
|---|---|
| Header | 11px / 700 / uppercase / `0.04em` / `text-secondary` on `surface-subtle`, sticky top (`z-sticky`) |
| Row | min height 32px (padding `6px 14px`), 12–13px text, 1px top border default |
| States | hover `brand-tint`; selected `#fdf1dc` with a 3px `--color-selection` left marker; highlighted column header `brand-tint-strong`, cells `brand-tint` + bold |
| Alignment | text left; **numbers right-aligned with `tabular-nums`**; status text left with a pill |
| Frozen columns | `position: sticky`, `--shadow-pinned` on the last pinned column; pin identifiers + the value being corrected |
| Sort / filter | Header menu (§8.4); "N of M rows" + "Clear filters and sorting" above the table |
| Pagination | prev/next 32px `btn--icon` + "page / total" (`--font-small`); count text "13–24 of 40 analyses" left |
| Row actions | inline editable cell (dashed border on hover) or a trailing `btn--tertiary` |
| Empty | one full-width cell, centred muted text |

### 8.8 Tags, chips, badges and status pills

**Current state.** About 55 pill/badge/tag classes in 18 files, in 4 sizes (10px/2×8, 10.5px/3×10, 11px/4×10, 11.5px/3×10), both fill-tint and solid variants; colours chosen per file, so **one colour carries several meanings**: purple = AI-suggested **and** Generated Code **and** Planner **and** Feature type; green = Template **and** Reviewed **and** Ready **and** Analysis type **and** Predefined; amber = Pending **and** Stale **and** Configuration; navy tint = Optional, Report ready, source label, chart type.

**Standard — one `Pill`** (11px / 700, padding `3px 10px`, radius pill, no border, uppercase only for fixed-vocabulary labels).

| Meaning | Colour | Examples |
|---|---|---|
| Neutral / informational | brand-tint + navy | source label ("FEATURE REPORT"), chart type, Optional |
| Success / done | success pair | Ready, Reviewed, Computed, Template, Accepted |
| Warning / needs attention | warning pair | Pending, Stale, N decisions needed, Configuration |
| Error / blocking | error pair | Required, Critical, Failed |
| AI-generated | AI pair | AI Suggested, Generated Code, AI-written summary |
| Info / existing | info pair | Existing, Planned |
| Data | data pair | Analyses, Rows (stat tiles only) |
| Muted | neutral bg + secondary text | New, Default |

Rule: purple is reserved for **AI-generated** content. Planner-approved and predefined items use neutral/info, not purple/green. Never rely on colour alone: every pill carries its text label.

### 8.9 Navigation

| Part | Current | Standard |
|---|---|---|
| Header | white, bottom border 3px navy, `--shadow-sm`, inner max 1080, logo 32px, divider, product + page name | Keep; align inner width with page content (§7.7). |
| Step indicator | 6 circular badges 22px, connectors, labels 12px; done = green ✓, current = navy; inactive labels `#8a90ad` (3.15:1) | Keep; label colour → `text-secondary`; each step a real `<a>`/button with `aria-current="step"` |
| Tabs | **6 tab styles** (audit report, audit wizard, outlier sub-tabs, analysis-modal sub-tabs and modal tabs, planner): underline tabs 12.5–13.5px, modal-level tabs as segmented pills | One underline-tab style: 13px / 700, padding `8px 4px 9px`, 2px bottom border `brand-primary` when active, count badge as a pill; segmented style only inside modals' secondary level |
| Breadcrumbs | Drill-down chain crumbs (`drilldown-crumbs`) | Keep; link colour `--color-link` |
| Pagination | see §8.7 | — |
| Sidebar | Not present in the app | — |

### 8.10 Iconography

31 inline-SVG icons, 24×24 viewBox, `currentColor`, outline style; stroke widths 1.4 ×1, 1.5 ×4, **1.6 ×40 (dominant)**, 1.7 ×2, 1.8 ×5; sizes set per container (13–22px). Some glyph characters are used instead of icons (✕, ✓, ↻, ▾, ▸, ↑, ↓, ×, +, ⤢, ·).

Standard: outline icons, stroke **1.6**, sizes 14 (inline with 12–13px text), 16 (buttons), 20 (page header badge 22 → 20), 22 (stat tile); colour inherits text; decorative icons `aria-hidden="true"`; icon-only controls need `aria-label`. Replace glyph characters (✕ → close icon, ✓ → check icon, ▾/▸ → chevron icon) in Phase 2.

### 8.11 Feedback and states

| Situation | Standard |
|---|---|
| Loading a section | `ThinkingLoader` with 3–5 plain-language messages and elapsed time (only for > 3s work) |
| Loading a button | spinner + verb-ing label, `aria-busy` |
| Error | inline `.notice--error` next to the action that failed, with **Retry**; message says what happened and what to do |
| Success | the UI state changes (pill turns green, item moves to "Resolved"); no toasts |
| Confirmation | Needed for destructive/irreversible actions (delete, overwrite, re-run that discards edits) — **missing today** |
| Undo | Report editor supports Undo/Redo (Ctrl/Cmd+Z); no other screen does |

---
## 9. Data visualization

### 9.1 What exists

| Surface | Library | Colours today |
|---|---|---|
| Analysis charts (bar, grouped bar, line, scatter, pie, heatmap, combo = bar + line on a second axis, plus a table fallback) | Plotly. Figures are built on the backend (`analysis_charts.py`) and rendered by `AnalysisChart.tsx` | **No colours are set anywhere**, so Plotly's built-in 10-colour palette is used (`#1f77b4` blue, `#ff7f0e` orange, `#2ca02c`, `#d62728`, …). This is why charts show blue and orange bars that appear nowhere else in the app. |
| Temperature outlier chart | Plotly (`TemperatureOutlierTab`) | Custom: in-spec `#152C73`, breach `#C0392B`, low `#1891F6`, ideal `#10B981`, high `#C0392B`, selected `#F59E0B` |
| Outlier box plot | Plotly (`OutlierBoxPlot`) | Own colours (not mapped to tokens) |
| Report slide preview | Plotly again (`AnalysisChart fill`) | Same as analysis charts |
| Exported deck | python-pptx native charts (`report_style.py`) | `BAR_PALETTE_HEX = 010198, 1891F6, 617080, 61B549, F6D009, BAC0D0`; line `1891F6`; text `1B2333`; muted `5B6478`; gridline `D9DCE3`; reference line `C62828`; chart font Arial 11pt, data labels 10pt |

Findings:

1. **Three palettes for the same data** (Plotly default on screen, a custom set in the temperature chart, the deck palette in the download). The preview in the report editor therefore does not match the exported chart colours.
2. **A category does not keep its colour.** Colour follows series order, so "MSC" can be blue on one chart and orange on another, and differs again in the deck.
3. **Colour-blind safety.** Smallest perceptual distance between any two palette colours (CIE76 ΔE, simulated, higher is better):

| Palette | Normal | Deuteranopia | Protanopia | Tritanopia |
|---|---|---|---|---|
| Plotly default (used on screen today) | 38.2 | 7.3 | **4.6** | 17.9 |
| Deck palette (`BAR_PALETTE_HEX`) | 31.3 | 31.5 | 30.8 | 18.9 |
| Proposed (below) | 31.3 | 31.5 | 30.8 | 18.9 |

4. Axis text is 10.5px `#5B6478` (screen) / 9px Arial (fill mode) / 11pt (deck): three sizes.
5. Plotly's modebar shows on hover on full charts, hidden in preview ("fill") mode.

### 9.2 Standard

**Ordered categorical palette** (use in this order; the deck palette with the UI brand navy):

| # | Token | Hex | Contrast on white | Note |
|---|---|---|---|---|
| 1 | `--chart-1` | `#152c73` | 12.81 | Primary series |
| 2 | `--chart-2` | `#1891f6` | 3.27 | |
| 3 | `--chart-3` | `#617080` | 5.08 | |
| 4 | `--chart-4` | `#61b549` | 2.56 | needs data labels or a 1px darker outline |
| 5 | `--chart-5` | `#f6d009` | 1.51 | needs data labels or outline |
| 6 | `--chart-6` | `#bac0d0` | 1.82 | "Other" / remainder |

Rules: more than 6 series → group the rest into "Other" (`--chart-6`) rather than inventing colours; bars/lines for series 4–6 get a 1px outline in a 30%-darker shade or direct value labels, because they are below the 3:1 non-text contrast.

**Sequential** (one metric, low → high): `#eaf1fb → #b9cdee → #6f93d4 → #3a5fa8 → #152c73`.
**Diverging** (above / below a reference such as the overall average): `#c2410c ← #f4f6fb → #1a6fb3` (orange–blue, safe for red-green colour blindness).
**Semantic** (only when the colour *is* the message): in spec / ok `--color-status-success` `#1a8f5e`; out of spec / breach `--color-status-error` `#c62828`; warning `#8a5a10`; selected `--color-selection` `#f59e0b`. The temperature chart keeps navy for in-range bars and red for breaches; add a text label or pattern so colour is not the only signal.

**Identity rule.** A category value (a carrier, a product) gets one colour from the palette the first time it appears in a session and keeps it on every chart, preview and in the deck. Store the map in `sessionStore` (`chart.colorByValue`) and send it to the deck builder.

**Plotly template** (apply to every figure, overriding backend defaults):

```ts
export const CHART_LAYOUT = {
  colorway: ["#152c73", "#1891f6", "#617080", "#61b549", "#f6d009", "#bac0d0"],
  font: { family: 'Segoe UI, -apple-system, "Helvetica Neue", Arial, sans-serif', size: 11, color: "#5b6478" },
  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  margin: { l: 48, r: 24, t: 16, b: 72 },
  xaxis: { gridcolor: "#e2e6ee", showgrid: false, linecolor: "#7b8599", ticks: "outside", tickcolor: "#7b8599", automargin: true },
  yaxis: { gridcolor: "#e2e6ee", zeroline: true, zerolinecolor: "#7b8599", automargin: true },
  legend: { orientation: "h", x: 0, y: -0.25, yanchor: "top", font: { size: 11 } },
  hoverlabel: { bgcolor: "#ffffff", bordercolor: "#dde3ef", font: { size: 12, color: "#1b2333" } },
  hovermode: "x unified",
} as const;
```

| Element | Rule |
|---|---|
| Axis and tick text | 11px, `text-secondary`; long category labels follow the existing axis plan in `AnalysisChart` (flat if they fit, else −45°, truncated with "…") |
| Gridlines | horizontal only, 1px `#e2e6ee`; no vertical gridlines; zero line `border-strong` |
| Legend | horizontal below the plot, left-aligned; hidden for a single series |
| Tooltip | white card, 1px border default, 12px text, shows the full (untruncated) label |
| Data labels | on for ≤ 12 bars; off otherwise |
| Numbers | counts: thousands separator, 0 dp (`12,430`); percentages: 1 dp with `%` (`77.3%`); measurements: 2 dp (the backend already rounds to 2 dp) |
| Dates / periods | `2026-03`, `2026-Q1`, `2026` (as the backend labels them); day: `2026-03-04` |
| Empty | "No data for the selected filters." (existing wording) |
| Loading | `ThinkingLoader` |
| Modebar | hide on all in-page charts except the main analysis chart; keep `displaylogo: false` |
| Deck | `BAR_PALETTE_HEX` replaced by the proposed palette (Phase 6); axis text 11pt; footer text colour `5C8AA5` → `5B6478` (3.73 → 5.93) |

---

## 10. Interaction design

| Interaction | Standard |
|---|---|
| Hover | colour/border/background change over `--duration-base`; clickable rows and cards use `brand-tint`; never move layout |
| Focus | `--ring-focus` on every interactive element, via `:focus-visible` |
| Active/pressed | primary buttons darken and move 1px down |
| Disabled | one opacity (.45), `cursor: not-allowed`, no hover effect |
| Transitions | 150ms ease for colour/border/background; 250ms for panel open/close; none for layout shifts |
| Drag and drop | the dragged item drops to 40% opacity; a 3px `--color-brand-accent` line shows the drop position; keyboard alternative provided where reordering exists |
| Selection | selected row `#fdf1dc` + 3px amber marker; selected tab underline 2px navy |
| Keyboard | Escape closes modals and menus; Enter commits an edited cell, Escape cancels; in the report editor: ←/→/↑/↓ move between slides, Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z or Ctrl+Y redo |
| Loading | `ThinkingLoader` for > 3s work; spinner + verb-ing label on buttons; no skeleton screens in the app (**Not present in the app**) |
| Errors | inline notice + Retry (§8.11); raw browser errors ("Failed to fetch") must be translated: "Can't reach the server. Check that the backend is running, then try again." |
| Confirmation | destructive or discarding actions open a small confirm dialog with [Cancel] [Delete]; **none exist today** |
| Success | state change in place (pill/colour/count); no toast component |
| Reduced motion | all transitions/animations disabled under `prefers-reduced-motion: reduce` (global rule in §7.8; today only one file handles it) |

### Component states (summary)

| Component | default | hover | focus-visible | active | disabled | loading | error |
|---|---|---|---|---|---|---|---|
| Button | per variant | tint/darken | ring | −1px | .45 | spinner + label | n/a |
| Input | border-strong | border-primary 50% | border-primary + ring | — | subtle bg | n/a | red border + message |
| Tab | text-secondary | text-primary | ring | — | .45 | n/a | n/a |
| Row | white | brand-tint | ring (clickable) | — | .6 | n/a | n/a |
| Pill | static | static (non-interactive) | — | — | — | — | — |
| Card (clickable) | border default | border brand-primary | ring | — | .6 | loader inside | notice inside |

---

## 11. Accessibility

| Check | Finding | Severity |
|---|---|---|
| Focus visibility | 1 `:focus-visible` rule; 14 `outline: none`; no focus ring on buttons, tabs, cards, rows. A keyboard user cannot see where they are. | **High** |
| Text contrast | 9 failing pairs in §6.3 (`#94a3b8` 2.56, `#f57f17` 2.49, `#10b981` 2.54, `#8a90ad` 3.15, light-blue links 3.27, green/teal 11px pills 3.6–4.1) | **High** |
| Control borders | `#dde3ef` on white/page = 1.29 / 1.19:1, below the 3:1 needed to see an input or button edge | **High** |
| Modal semantics | No `role="dialog"`, `aria-modal`, focus trap or focus return on any modal (`Modal`, the audit-issue/lane/product modals, `IssueRowsModal`) | **High** |
| Tabs | `role="tab"` / `aria-selected` used (44 `role=` attributes total) but no `role="tabpanel"`, `aria-controls` (0) or arrow-key navigation | Medium |
| Target size | Icon-only controls 21–32px (`excel-table__menu-btn` ≈ 21px, below the 24px WCAG 2.2 minimum); most buttons 28–40px high | Medium |
| Labels | 39 `aria-label`s; the 4 `alt` attributes cover logos only; native `title` used 37× for hints (not announced reliably, not visible on touch) | Medium |
| Colour as the only signal | Chart in-spec vs breach (navy vs red); outlier bars; stat tile icons. Pills, step indicator and table statuses also carry text. | Medium |
| Headings | 25 `h1–h3` elements; page title is `h1`-equivalent only by class — **(verify)** one `h1` per page | Low |
| Motion | Reduced-motion handled in 1 file | Medium |
| Language | `lang="en"`; translated report content is inside slides only (not in the UI) | Low |

---

## 12. Responsive behaviour

Breakpoints in use: 560, 640, 680, 720, 900, 960, 961, 1000 (standardise to 640 and 960, §7.7). Most layouts adapt through `flex-wrap` and `grid-template-columns: repeat(auto-fit / auto-fill, minmax(260–320px, 1fr))`, not through media queries.

| Screen | Behaviour today | Standard |
|---|---|---|
| All pages | `max-width` container, side padding 24 | 1080 container; padding 16 below 640px |
| Header | single row, no collapse | wrap the page name under the product name below 640px |
| Cards / stat tiles / panels | auto-fit grids, wrap | keep |
| Tables | horizontal scroll inside a bordered wrapper; frozen columns keep identifiers visible | keep; pinned width total ≤ 390px; below 640px pin only the first column |
| Report editor | 3 columns (rail 188 / stage / inspector 290); stacks and turns the rail into a horizontal strip ≤ 1000px | keep |
| Footers | `flex-wrap` | stack, primary first and full width ≤ 640px |
| Charts | `responsive: true`, fixed height 360 | height 280 below 640px |

Mobile is not a target use case (analyst desktop workflow) but nothing should overflow horizontally.

---

## 13. Voice and tone

Tone: plain, professional, second person where needed, no jargon about "agents" in user-facing text (already removed on the Audit page; **Features and Analysis subtitles still say "the Feature Agent…" / "The Analysis Agent…"**).

| Rule | Standard | Deviations found |
|---|---|---|
| Capitalisation | **Sentence case** for buttons, labels, tabs, menu items, messages. **Title Case** only for page titles and product/proper names (SensiWatch, ColdStream, Carrier). | Title Case buttons: "Continue to Features", "Back to Audit", "Download Report", "Clear All", "Upload & Continue", "Suggest Analyses", "Suggest More"; sentence case in the same screens: "Add all samples", "Suggest more", "Show 5 more", "View agent generated code", "Plan a drill-down path". `Upload` actions mix both in one button group ("Add all samples" next to "Clear All"). |
| Button text | Verb first, names the outcome: "Continue to Features", "Add analysis", "Download report". In-progress: verb-ing + ellipsis ("Uploading…"). | "Drill down" vs "Drilldown" vs "drill-down"; "AI" as a bare button label |
| Terminology | Use **drill-down** (noun and adjective), **analysis / analyses**, **feature**, **source** (not "slot"), **trip**, **segment length (days)**. Avoid "agent", "pipeline", "repository" in UI text. | "Drilldown(s)" in code identifiers and some UI strings; "Analysis Repository" pill removed, but "repository" remains in messages; "Analysis tables" → "Analyses" (done) |
| Dashes | Use "—" (em dash) with spaces, or rewrite. | 24 UI strings use a double hyphen " -- " as a dash (e.g. "…predefined -- planner-approved -- custom…") |
| Error messages | What happened + what to do. No raw exception text. | "Failed to fetch" shown as-is on the Upload page |
| Empty states | State the fact, then the next step. | "No analyses have been run yet -- go run some on the Analysis page first, since…" (long, double hyphen) |
| Numbers | thousands separator, `toLocaleString()` (used 21×, so output depends on the browser locale — set an explicit `"en-US"`); percentages 1 dp | `toFixed(1/2)` mixed with `toLocaleString()` |
| Dates | Display `2026-03-04 07:34` (ISO date + 24h time, no `T`, no milliseconds) | Tables show raw `2025-12-12T07:34:50.633` **DECISION NEEDED**: options (a) ISO-like `2026-03-04 07:34` (recommended: unambiguous, sortable), (b) `4 Mar 2026, 07:34`, (c) leave raw. |
| Currency | Not present in the app | — |
| Placeholders / hints | End without a full stop for fragments; full sentences get a full stop | mixed |

---

## 14. Cross-platform adaptation

| Surface | Standard |
|---|---|
| Browser UI | Desktop-first, evergreen browsers. System font stack (no font loading). |
| Exported PowerPoint | 16:9 (13.333 × 7.5 in), Arial throughout, title 28–18pt step by length, explanation 18pt (up to 4 lines; chart moves down), chart area from 2.0 in, footer 10pt. Carrier template cover. Logo top right on content slides. |
| Report slide preview | Must render the same layout as the file (it does: `SlidePreview.tsx` mirrors `report_style.py` in container units). Keep the two files in step. |
| Print / PDF | Not present in the app |
| Dark mode | Not present in the app (light only) |
| Mobile app | Not present in the app |

---

## 15. Screen-by-screen compliance

| Screen | Deviations from this standard | Sev. |
|---|---|---|
| **Global (Header, Modal, base CSS)** | Header inner 1080 vs page content 860–1140; `Modal` z-index 100 vs other modals 1000; no `role="dialog"`/focus handling; no focus rings anywhere; `<title>` stale; `a` colour `#1891f6` (3.27:1); 5 undefined CSS variables | High |
| **Welcome (`/`)** | Container 1140; own badge/step number sizes (9.5px); hard-coded colours; Title Case CTA | Low |
| **Upload (`/upload`)** | `ClientBriefInput.css` is a second design language (`#002e6e`, `#dde3ed`, `#6b7a99`, `#f7f9fc`, own greens/ambers; 37 hard-coded hex); warning badge `#f57f17` on `#fff8e1` = 2.49; footer buttons 14px / 11×24 (lg differs from other pages' 13.5px / 10×20); "Clear All" vs "Add all samples" casing; raw "Failed to fetch" | High |
| **Planner (`/planner`)** | Own button style (radius 8, border 1.5px, weight 600, padding 9×20, no shared class); 37 hard-coded hex including its own badge palette (6 type/status pairs); container 860; tabs 10×20 / 13.5px unlike others; step layout nav buttons grouped differently | Medium |
| **Audit (`/audit`)** | Footer buttons 14px / 11×24; wizard tabs 13.5px vs 12.5px elsewhere; status pills hard-coded; stat-tile overrides ×2; `OutlierTabs.css` has 64 hard-coded hex values (mostly `var(--x, #fallback)`, plus `#15803d`, `#dc2626`, `#c0392b`, `#e2e8f0`); `ExcelTable.css` (new) carries 36 more fallbacks and should be migrated first; modal overlays `rgba(13,28,77,.45)` ≠ `Modal`; `outlier-lane-card__table` CSS now dead; chart colours (temperature) custom | High |
| **Features (`/features`)** | Page buttons 13.5px (matches standard lg except font); stat-tile override; green 11px status pill 4.09:1; subtitle mentions "Feature Agent"; AI panel and custom panel duplicate Analysis panel CSS | Medium |
| **Analysis (`/analysis`)** | **Charts in Plotly default colours (High)**; pill-shaped buttons (`drilldown-btn`, suggest-more) and purple buttons; two tab styles in one modal; 5 `analysis-card__pill` colours (blue/teal/purple/amber/error) chosen per card; icon-only controls < 24px; "Suggest More" casing; panel/panel CSS duplicated from Features; subtitle mentions "Analysis Agent" | High |
| **Report (`/report`)** | Export buttons duplicated top and bottom (portal) — confirm intent; `--` dashes in copy; preview palette (Plotly) ≠ deck palette; deck brand blue `#010198` ≠ UI; editor modal 1320 with its own toolbar buttons (`report-editor__tool`) instead of `btn--tertiary`; slide footer text 3.73:1 | High |

---

## 16. Migration plan

| Phase | Work | Files | Risk | Verify |
|---|---|---|---|---|
| **0. Baseline** | Capture a screenshot of every screen/state; record `tsc -b`, `npm run build`, `oxlint` results | none | Low | Screenshots saved; all three commands pass |
| **1. Tokens** | Add `src/styles/tokens.css` (§7.8), import in `main.tsx` before all CSS; keep the legacy aliases; define the 5 missing variables | `styles/theme.css`, `main.tsx` (+ new `tokens.css`) | Low (no visual change) | Build passes; screenshots identical; script finds 0 undefined `var(--…)` |
| **2. Base components** | Create `components/ui/`: `Button` (§8.1), `Pill` (§8.8), `Notice` (§8.5), `Card`, `FieldLabel`, `Icon` set additions (close, check, chevron); upgrade `Modal` (z-index 1000, `role="dialog"`, `aria-modal`, focus trap/return); add `:focus-visible` rings globally | `components/Modal.*`, new `components/ui/*`, `index.css` | Medium | Keyboard-tab through each screen: ring visible; modals trap focus; Escape closes |
| **3. Colour** | Replace every hard-coded hex/rgba per §6.4, one file at a time; fix the 9 failing contrast pairs | all 42 CSS files (largest: `ClientBriefInput`, `OutlierTabs`, `PlannerPage`, `AnalysisDetailModal`, `ExcelTable`) | Medium–High (purples/greens/ambers shift slightly) | `grep -E "#[0-9a-fA-F]{3,8}\b"` outside `tokens.css` returns only chart/deck files; contrast script passes; side-by-side screenshots |
| **4. Type, spacing, radius** | Snap font sizes to §7.1, spacing to §7.2, radii to §7.3; raise sub-11px text; unify border widths | all CSS | Medium | Count distinct `font-size` ≤ 8; no value off the scale; screenshots |
| **5. Buttons and placement** | Replace the 45 button families with `Button`; apply §8.2 footers (Upload, Planner, forms: primary rightmost) | pages + forms | Medium | Each screen matches the §8.2 diagram; no `*__btn` classes remain |
| **6. Charts and deck** | Plotly template (§9.2) in `AnalysisChart`, `TemperatureOutlierTab`, `OutlierBoxPlot`; category colour map in `sessionStore`; backend `analysis_charts.py` stops emitting colours; `report_style.py` palette and brand blue per the §6.2 decision; footer colour | `components/AnalysisChart.tsx`, `TemperatureOutlierTab.tsx`, `OutlierBoxPlot.tsx`, `state/sessionStore.ts`, `backend/app/services/analysis/analysis_charts.py`, `backend/app/services/report/report_style.py`, `SlidePreview.css` | Medium–High | Same category = same colour across 3 charts and the downloaded deck; CVD simulation min ΔE ≥ 18 |
| **7. Screens** | Container 1080 for header and pages; copy/voice fixes (§13); accessibility items (§11); delete dead CSS | `pages/*`, `Header.css`, copy in `*.tsx` | Medium | §15 table: every row re-checked and cleared |
| **8. Lock-in** | Delete legacy aliases; add a lint/CI check that rejects hex colours, off-scale `font-size`/`px` spacing and new `*__btn` classes outside `tokens.css` | `tokens.css`, lint config | Low | CI fails on a deliberate violation |

---

## 17. Instructions for the AI developer

Follow these rules exactly when refactoring or adding UI. If a rule and the existing code disagree, the rule wins.

1. **Do not change behaviour.** This is a visual/structural refactor: no logic, API, or data-flow changes. One phase per change set; run `npm run build` and `npx oxlint` after each.
2. **Read this document's tokens first.** Create `src/styles/tokens.css` exactly as in §7.8. Never delete a legacy alias until `grep` shows zero uses.
3. **Colours:** never write a hex, `rgb()` or `rgba()` outside `tokens.css` (chart/deck files excepted, §9). Use the token from §6.4. If no token fits, stop and add a token with a semantic name — do not use a near colour.
4. **Text colours on tints:** use the `-text` / status token, never the fill token (e.g. success text is `--color-status-success-text`, not `--color-status-success`). `--color-brand-accent` is never a text colour.
5. **Typography:** only the sizes in §7.1; never below 11px; weights 400/600/700/800; no half-pixel sizes.
6. **Spacing / radius / shadow / z-index / motion:** only the tokens in §7.2–§7.6. Snap off-scale values using the rule in §7.2.
7. **Buttons:** use the single `Button` component (variants `primary`, `secondary`, `ai`, `tertiary`, `danger`, `icon`; sizes `sm`, `md`, `lg`). Do not create `*__btn` classes. Radius is always `--radius-sm`. Every icon-only button has `aria-label`.
8. **Placement:** primary rightmost; Cancel/Back to its left; page footers `[Back] … [Continue]`; forms `[Cancel] [Primary]`; destructive actions ask for confirmation. Follow the diagrams in §8.2.
9. **Pills:** use the one `Pill` with the meaning-to-colour table in §8.8. Purple means AI-generated only.
10. **Focus:** every interactive element gets `:focus-visible { box-shadow: var(--ring-focus); outline: none }`. Never leave `outline: none` without a replacement ring.
11. **Inputs and control borders:** `--color-border-strong`. Decorative dividers and card borders: `--color-border-default`.
12. **Modals:** use the shared `Modal` (z-index `--z-modal`, dialog semantics, focus trap and return). Do not add a new overlay implementation.
13. **Tables:** use `ExcelTable` for any data table with more than ~8 rows or more than 4 columns; numbers right-aligned with `tabular-nums`.
14. **Charts:** every Plotly figure is passed through `CHART_LAYOUT` (§9.2); categories keep their colour via `chart.colorByValue`; never rely on colour alone (labels or outline for series 4–6).
15. **Copy:** sentence case for buttons, labels, tabs, messages; Title Case only for page titles and proper names; "drill-down", "analysis/analyses", "source"; no "agent" in UI text; no `--` as a dash; no raw error text.
16. **Layout:** header and page content use `--container-page`; page padding `28px 24px 60px` (16px side padding ≤ 640px).
17. **Do not touch** the backend deck layout geometry (`report_style.py` margins, positions) — only its colours/fonts as listed in Phase 6.
18. **Verification before finishing a phase:** (a) `npx tsc -b`, `npm run build`, `npx oxlint` pass; (b) screenshots of every changed screen match the intended result; (c) the contrast script reports no pair below 4.5:1 for text or 3:1 for control borders; (d) report what you changed per file and anything you could not verify.
19. **When unsure, stop and ask.** Items marked **DECISION NEEDED** (§6.2 brand blue, §7.7 container width, §13 date format) must not be decided by the implementer.

### Open decisions (summary)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | One brand blue (§6.2) | `#152c73` / `#010198` / keep both | `#152c73` for UI; deck follows unless the client mandates `#010198` |
| 2 | Page content width (§7.7) | 1080 everywhere / keep 960 + 1080 / widen header | 1080 everywhere |
| 3 | Date display (§13) | `2026-03-04 07:34` / `4 Mar 2026, 07:34` / raw | `2026-03-04 07:34` |
| 4 | Export buttons on the Report page (§8.2) | top + bottom (current) / bottom only | bottom only, unless the duplicate is intentional |
| 5 | Chart colour source of truth (§9) | UI tokens drive the deck / deck palette drives the UI | one shared list; implement in `tokens.css` and mirror in `report_style.py` |
