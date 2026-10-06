from app.services.analysis import analysis_agent, analysis_templates

TEMPLATE_SYSTEM = f"""You are the template-matching step of an analytics tool for cold-chain \
shipment data. You are given an analysis request, the computation logic already \
written for it, and the dataset's column catalog. Decide whether the logic can be \
computed EXACTLY by one of the deterministic templates below.

Only choose a template when it computes the same result as the logic -- never an \
approximation. Answer "none" when the logic needs something no template expresses: \
a derived or calculated column, a ratio between two different aggregates, \
period-over-period comparison, joins, ranking within groups, multi-step logic, or \
anything else the parameters can't state.

TEMPLATES:
{analysis_templates.catalog_prompt()}

If the computation logic and the request disagree (e.g. the logic filters rows \
before computing a rate, which would make every rate 100%), match what the request \
asks for. Use column names exactly as they appear in the catalog; omit optional \
parameters you don't need.

Example: request is "% in spec by carrier" but the logic's steps say to filter to \
rows where Status = "In Spec" BEFORE computing the rate -- that would make every \
carrier show 100%. Match the REQUEST instead: a rate_by_group template with no \
pre-filter, computing the true % in spec per carrier from all rows.

Respond with ONLY a JSON object, no markdown:
{{"template_id": "<template id, or none>", "params": {{<the complete template spec including "template_id", or {{}} when none>}}, "reason": "one short sentence"}}"""


CHART_SYSTEM = """You are the chart-recommendation step of an analytics tool for cold-chain \
shipment data. You are given an analysis request and the computation logic that \
defines the result table -- the table has NOT been computed yet. Recommend how to \
visualise that table, and which source columns a program manager would want as \
interactive filters on the chart.

""" + analysis_agent.CHART_TYPE_GUIDANCE + """

Filters: up to 4 columns from the catalog that are useful to slice this analysis \
by -- key business dimensions (carrier, lane, origin, product, customer, status) and \
the main date column. Never propose the metric being measured, IDs, or free-text \
columns.

Example: analysis is "% in spec by Carrier". Good filters: Product, Origin, Month \
(other dimensions to slice the same rate by). Bad filters to reject: "% in spec" \
itself (the metric being measured, not a slicer), "Shipment ID" (a free-text/ID \
column with one value per row, useless as a filter).

Respond with ONLY a JSON object, no markdown:
{"chart_type": "<type>", "reason": "one short sentence",
 "alternatives": [{"chart_type": "<type>", "reason": "one short sentence"}],
 "filters": [{"column": "exact column name", "reason": "one short sentence"}]}"""
