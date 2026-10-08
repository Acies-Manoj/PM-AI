# PM-AI DynamoDB redesign: plan

Goal: 3 tables (`pmai-docs`, `pmai-profiles`, `pmai-audit-log`), one item per record, and an event
schema that says *what happened, in which wizard step, to which record*.

## 1. Tables

| Table | Partition key | Sort key | Notes |
|---|---|---|---|
| `pmai-docs` | `session_id` (S) | `doc` (S) | Everything about one session, one item per record. Also holds the session header (`SESSIONS`). TTL `ttl`. |
| `pmai-profiles` | `user_id` (S) | `profile` (S) | `KPI` and `ANALYSIS` JSON a PM uploaded. TTL 365 days. Unchanged. |
| `pmai-audit-log` | `session_id` (S) | `ts_event` (S) | One item per event. TTL 365 days. GSIs: `by-user`, `by-target`. |

`pmai-sessions` is removed: its header moves into `pmai-docs` as the `SESSIONS` item.
`DDB_SESSIONS` is removed from config, task definition, IAM and `.env.example`.
`USE_AWS_STORAGE` becomes `S3_BUCKET and DDB_DOCS`.

## 2. Docs: one item per record (`pmai-docs`)

| `doc` (sort key) | Record | Holds | Replaces today |
|---|---|---|---|
| `SESSIONS` | session header | owner, filename, source, frame refs, created/updated, selections snapshot | `pmai-sessions` item |
| `BRIEF` | client brief | raw brief, final text, translation, file list | `BRIEF_META` |
| `COLUMN#<name>` | one column | full column profile (type, stats, samples...) | `COLUMN_META` (one big doc) |
| `PLAN#<n>` | one planner recommendation | AI proposal, PM decision and notes | `PLANNER_SUGGEST` + `PLANNER_OUTPUT` |
| `ISSUE#<id>` | one audit finding | title, options, AI recommendation, status, resolution, applied step | `issues` list inside the header |
| `OUTLIER` | outlier flags | segment and mean-temperature outliers flagged, edits, reviews | `OUTLIER_AUDIT` |
| `FEATURE#<id>` | one feature (any source/status) | definition, formula, plan, final code, status | `FEATURE_REPO` list + `FCACHE#` |
| `ANALYSIS#<id>` | one analysis or drill-down level | definition, plan, final code, chart, filters, chain | `ANALYSIS_REPO` list + `ACACHE#` |
| `PROPOSAL#<analysis id>#<n>` | one drill-down suggestion | columns, measure, ranking, focus values, status | `guided_proposals` inside `RESULT#` |
| `DRILL#<analysis id>#<path id>` | one drill-down path | levels, accepted/rejected | `PATHS` list |
| `OVERALL` | session summary | row count, KPI highlights, executive summary | unchanged |

Not in your list, kept on purpose:

- `RESULT#<analysis id>`: the computed table/chart/interpretation of a run. It is large and rewritten
  on every run; keeping it apart stops a re-run from rewriting the analysis definition.
- `DRAFT#<token>`: a custom-feature draft under review (2-day TTL).

Removed: `STEP#<n>`. Each issue carries its own applied step, and any one can be undone on its own.

Sort-key rule: every doc name is `TYPE` or `TYPE#id[#id2]`. `begins_with(doc, "FEATURE#")` lists
all features of a session in one query.

## 3. Events (`pmai-audit-log`)

Append-only. One item per event.

| Attribute | Type | Meaning |
|---|---|---|
| `session_id` | S, partition key | Session the event belongs to (`_global` if none) |
| `ts_event` | S, sort key | `<ISO time>#<8-hex id>`, unique and time-ordered |
| `event_id` | S | The 8-hex id from `ts_event` |
| `user_id` | S | Who did it (GSI `by-user`) |
| `event_type` | S | What happened (catalog below) |
| `category` | S | Area: `session`, `planner`, `audit`, `outlier`, `feature`, `analysis`, `report`, `ai` |
| `step` | N | Wizard step 1-6 (below); `0` = not tied to a step |
| `step_name` | S | Name of that step |
| `target` | S | The record the event is about, written exactly as its `pmai-docs` sort key, e.g. `FEATURE#coo` |
| `target_key` | S | `<session_id>#<target>`: GSI `by-target` partition key = history of one record |
| `result` | S | `ok` or `failed` |
| `summary` | S | One readable line |
| `payload` | S | JSON text with the details (kept as text so floats never hit DynamoDB number rules) |
| `ttl` | N | Expiry (365 days) |

Wizard steps (from the app's step indicator):

| step | step_name | Pages |
|---|---|---|
| 1 | Upload | upload, client brief |
| 2 | Planner | planner |
| 3 | Audit | audit issues, outlier review |
| 4 | Features | features |
| 5 | Analysis | analysis and drill-downs |
| 6 | Report | report |

Input rule: callers pass `session_id`, `user_id`, `event_type`, `payload` (the details), and optionally
`target` (to override) and `result`. `category`, `step`, `step_name`, `target` and `summary` come from
one catalog (`audit_log.EVENT_CATALOG`), so existing call sites keep working unchanged and every event
is classified the same way.

Catalog:

| event_type | category | step | target |
|---|---|---|---|
| `upload` | session | 1 | `SESSIONS` |
| `brief_finalize` | session | 1 | `BRIEF` |
| `planner_suggest` | planner | 2 | none |
| `planner_save` | planner | 2 | none |
| `audit_run` | audit | 3 | `SESSIONS` |
| `decision` | audit | 3 | `ISSUE#{issue_id}` |
| `revert` | audit | 3 | `ISSUE#{issue_id}` |
| `download` | audit | 3 | `SESSIONS` |
| `edit` | outlier | 3 | `OUTLIER` |
| `outlier_detected` / `outlier_edit` / `outlier_review` | outlier | 3 | `OUTLIER` |
| `feature_suggested` / `feature_draft` / `apply_features` | feature | 4 | none |
| `feature_custom_added` / `feature_accepted` / `feature_rejected` | feature | 4 | `FEATURE#{entry_id}` |
| `analysis_suggested` | analysis | 5 | none |
| `analysis_custom_added` / `analysis_accepted` / `analysis_rejected` / `analysis_run` | analysis | 5 | `ANALYSIS#{entry_id}` |
| `drilldown_suggested` / `drilldown_proposed` / `drilldown_run` | analysis | 5 | `ANALYSIS#{entry_id}` |
| `drilldown_path_accepted` / `drilldown_path_rejected` | analysis | 5 | `DRILL#{entry_id}#{path_id}` |
| `report_downloaded` | report | 6 | `OVERALL` |
| `llm_call` | ai | by call name | the record the call wrote (`output_ref`) |
| `code_attempt` / `code_run` / `code_fallback` | ai | 4 (feature) or 5 (analysis) | `FEATURE#` / `ANALYSIS#{entry_id}` |

Indexes: `by-user` (`user_id`, `ts_event`) and `by-target` (`target_key`, `ts_event`, sparse: events with
no target are not indexed).

## 4. Phases and status

Each phase leaves the app working in local-file mode (no AWS) and in AWS mode.

| Phase | What | Status |
|---|---|---|
| 1 | Event schema + catalog, `by-target` index, history of one record. `pmai-sessions` removed (header is the `SESSIONS` doc). `BRIEF_META`→`BRIEF`, `OUTLIER_AUDIT`→`OUTLIER`. Config, task definition, README. | Done |
| 2 | One doc per record: `FEATURE#`, `ANALYSIS#` (code cache lives inside), `PLAN#`, `DRILL#`, `COLUMN#`. | Done |
| 3 | `ISSUE#` (issues leave the header) and `PROPOSAL#` (leave `RESULT#`). | Done |
| 4 | Undo from stored before-values instead of replaying from a baseline frame. | Not started, needs your decision |

Phase 4 note: today a revert drops the issue's change and replays the rest from `audit_baseline`, so it
already undoes any one issue in any order. Storing before-values per issue needs the removed rows and
columns saved with each issue (large, so in S3), and a rule for two issues that touched the same cell.
It is a behaviour change, so it was left out. Until then `ISSUE#<id>.applied` holds the decision that was
applied (`decision_id`, `selected_items`); the replay still reads `audit_events` in the `SESSIONS` item.

## 5. Behaviour changes to know about

- **Planner "generate more suggestions" now appends.** Before, the second call overwrote the stored
  suggestions with only the new batch, while the page kept the merged list, so saved decisions could land on
  the wrong recommendation. Now the first call replaces the list (a decision already made on a recommendation
  with the same name is kept) and a "more" request appends, so the list index always matches.
- **Persisted features/analyses keep insertion order** through a `created_at` field, as the old list did.
- **A predefined or planner feature/analysis gets a `FEATURE#`/`ANALYSIS#` item** the first time its code is
  cached (a snapshot of its definition plus the code, `persisted: false`). They are still re-derived on every
  read; the snapshot is not used as the definition.
- **Event `step` is a Number, `payload` stays a JSON string** (so floats never hit DynamoDB number rules).
  `event_id` is the 8-hex id inside `ts_event`, not a per-session counter.
- **Drill-down proposals have no status field.** The app has no accept/reject on a proposal (confirming one
  creates a drill-down analysis), so there is no state to store yet.
- **TTL is per item**: each item expires 30 days after its own last write, so a long-lived session can lose an
  item that was written once and never touched again (for example `COLUMN#`). Same as before the change.
- Existing local `data/sessions` folders written before the change are not read by the new code (new
  environment: nothing to migrate in AWS).

## 6. Testing

Two throwaway scripts (not in the repo) exercised the change: a local-mode walk of the wizard through the real
API with the LLM stubbed (upload, brief, planner, features, analysis, drill-downs, audit run/resolve/revert,
events) and an AWS-mode run against a mocked DynamoDB + S3 (moto): item keys, parallel writes, only-changed
writes, S3 overflow, both event indexes. All checks passed. Not exercised: real Bedrock calls, a real
DynamoDB table, the frontend.

## 7. Request to the cloud team

3 tables (`pmai-docs`, `pmai-profiles`, `pmai-audit-log`), on-demand, TTL on `ttl`, point-in-time recovery.
`pmai-audit-log` needs two global secondary indexes, both projecting all attributes:
`by-user` (`user_id`, `ts_event`) and `by-target` (`target_key`, `ts_event`).
