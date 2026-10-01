"""The semantic model the drill-down path planner reads.

shipment_semantics.json (next to this file) is authored once: what every column of
this dataset means, which are real business dimensions and which are identifiers,
settings or empty columns, which columns roll up into which, which aggregations
make sense for each measure, typical drill patterns, and known data issues. Column
names of the export do not change, so nothing here is recomputed or asked of a model.

Only what varies per session is merged in at run time: how many values each column
has right now, example values, and the feature columns created in this session
(with their own definitions), so a newly created feature is available as soon as
it exists.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.services.analysis.analysis_columns import as_labels

_FILE = Path(__file__).parent / "semantics" / "shipment_semantics.json"
_NOT_MEASURES = {"setting", "empty", "constant", "unusable", "identifier", "time", "text"}
DEFAULT_AGGS = ["mean", "max", "min", "median"]


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(_FILE.read_text(encoding="utf-8"))


def _is_flag(series: pd.Series) -> bool:
    values = series.dropna().unique()
    return len(values) > 0 and set(values) <= {0, 1, 0.0, 1.0, True, False}


def for_planner(df: pd.DataFrame, usable: list[str], numeric: list[str], features: list[dict]) -> dict:
    """The semantic model for this session's data, ready to put in a prompt."""
    sem = load()
    documented = {**sem["known_features"], **sem["columns"]}
    definition = {f["output_column"]: f.get("definition", "") for f in features}
    present = set(df.columns)

    groupable = []
    for col in usable:
        base = documented.get(col, {})
        if base.get("groupable") is False:
            continue  # documented as an identifier, setting, empty, constant or unusable column
        item = {
            "column": col,
            "meaning": base.get("meaning") or definition.get(col, ""),
            "distinct_values": int(as_labels(df[col]).nunique()),
            "examples": [str(v) for v in df[col].dropna().astype(str).unique()[:4]],
        }
        if col in definition:
            item["engineered_feature"] = True
        groupable.append(item)

    measures = []
    for col in numeric:
        base = documented.get(col, {})
        if base.get("kind") in _NOT_MEASURES:
            continue
        flag = col not in documented and _is_flag(df[col])
        item = {
            "column": col,
            "meaning": base.get("meaning") or definition.get(col, ""),
            "allowed_aggs": base.get("aggs") or (["mean"] if flag else DEFAULT_AGGS),
        }
        if base.get("unit"):
            item["unit"] = base["unit"]
        if flag:
            item["note"] = "0/1 flag: its mean is the share of trips that are flagged"
        if col in definition:
            item["engineered_feature"] = True
        measures.append(item)

    return {
        "dataset": sem["dataset"],
        "grain": sem["grain"],
        "supply_chain": sem["supply_chain"],
        "groupable_columns": groupable,
        "measures": measures,
        "hierarchies": [h for h in sem["hierarchies"] if h["parent"] in present and h["child"] in present],
        "drill_patterns": [p for p in sem["drill_patterns"] if all(c in present for c in p["path"])],
        "measure_guidance": sem["measure_guidance"],
        "data_issues": sem["data_issues"],
    }


def allowed_aggs(model: dict) -> dict[str, list[str]]:
    """{measure column: the aggregations that make sense for it}."""
    return {m["column"]: m["allowed_aggs"] for m in model["measures"]}
