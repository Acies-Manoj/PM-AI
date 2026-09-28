"""Sandboxed execution for AI-generated pandas calculations. Used by the
Feature Agent (feature_agent.py, via run_generated_code -- one value per
row) and the Analysis Agent (analysis_agent.py, via run_generated_table_code
-- an aggregated chart table).

Generated code is never trusted at face value: it's AST-validated against
an allowlist before it's compiled, and executed with no builtins beyond a
short safe list, so a hallucinated `import os`, `open(...)`, or
`df.to_csv(...)` fails closed rather than running. This mirrors the
restricted-grammar precedent already used for user-typed formulas in
feature_engineering.py's `df.eval(engine="python")` -- "restricted, not
general Python" -- just extended to cover a full code snippet instead of a
single expression.

This is a practical sandbox suitable for an internal ops tool where the
"attacker" is an LLM occasionally reaching for a convenient-but-unsafe
API, not a hardened defense against a deliberately adversarial prompt.
"""
import ast
import builtins

import numpy as np
import pandas as pd

_ALLOWED_BUILTIN_NAMES = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "range", "round", "set", "sorted", "str", "sum", "tuple", "zip",
}
_SAFE_BUILTINS = {name: getattr(builtins, name) for name in _ALLOWED_BUILTIN_NAMES if hasattr(builtins, name)}

_BLOCKED_NAMES = {
    "os", "sys", "subprocess", "shutil", "socket", "pathlib", "importlib",
    "builtins", "__import__", "open", "eval", "exec", "compile", "globals",
    "locals", "vars", "input", "exit", "quit", "__builtins__",
    "getattr", "setattr", "delattr", "type",
}

# pandas I/O and eval/query surface -- these aren't dunder attributes so the
# generic dunder check below wouldn't catch them, and letting an LLM call
# them defeats the point of a sandbox (arbitrary file read/write, or
# pd.read_pickle's known arbitrary-code-execution risk).
_BLOCKED_ATTRS = {
    "to_csv", "to_excel", "to_pickle", "to_hdf", "to_sql", "to_feather",
    "to_parquet", "to_stata", "to_gbq", "to_clipboard", "to_markdown",
    "read_csv", "read_excel", "read_pickle", "read_hdf", "read_sql",
    "read_html", "read_json", "read_parquet", "read_feather", "read_gbq",
    "read_clipboard", "read_table", "read_fwf", "read_orc", "read_sas",
    "read_spss", "read_xml", "HDFStore", "ExcelWriter", "eval", "query",
}

_DISALLOWED_NODES = (
    ast.Import, ast.ImportFrom, ast.With, ast.AsyncWith,
    ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
    ast.For, ast.AsyncFor, ast.While, ast.Global, ast.Nonlocal, ast.Delete,
)

def _validate_ast(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, _DISALLOWED_NODES):
            raise ValueError(f"Generated code uses a disallowed construct: {type(node).__name__}.")
        if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise ValueError(f"Generated code references a disallowed name: '{node.id}'.")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("__") or node.attr in _BLOCKED_ATTRS):
            raise ValueError(f"Generated code accesses a disallowed attribute: '{node.attr}'.")


def run_generated_code(code: str, df: pd.DataFrame) -> pd.Series:
    """Executes `code` against a copy of `df` and returns whatever it
    assigns to a variable named `result`. Raises ValueError on anything
    unsafe or malformed -- callers treat that as "this calculation
    couldn't be computed" and show a skip note, never the raw traceback."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Generated code has a syntax error: {exc}") from exc

    _validate_ast(tree)

    compiled = compile(tree, filename="<ai_generated_feature>", mode="exec")
    sandbox_globals = {"__builtins__": _SAFE_BUILTINS, "pd": pd, "np": np}
    sandbox_locals: dict = {"df": df.copy()}

    try:
        exec(compiled, sandbox_globals, sandbox_locals)  # noqa: S102 -- sandboxed above
    except Exception as exc:
        raise ValueError(f"Generated code raised an error while running: {exc}") from exc

    result = sandbox_locals.get("result")
    if not isinstance(result, pd.Series):
        raise ValueError("Generated code did not assign a pandas Series to `result`.")
    if len(result) != len(df):
        raise ValueError("Generated code's `result` doesn't have one value per row.")
    return result.set_axis(df.index)


def run_generated_table_code(code: str, df: pd.DataFrame, max_rows: int = 500) -> list[dict]:
    """Same AST-sandboxed execution as run_generated_code, but for the
    Analysis Agent (see analysis_agent.py): `result` here is expected to be
    an aggregated pd.DataFrame (a groupby/pivot-shaped chart table), not a
    per-row Series, since a chart's underlying table always has fewer rows
    than the source data. Returns the table as a list of row dicts, capped
    at `max_rows` so a runaway group-by can't ship an unbounded payload."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Generated code has a syntax error: {exc}") from exc

    _validate_ast(tree)

    compiled = compile(tree, filename="<ai_generated_analysis>", mode="exec")
    sandbox_globals = {"__builtins__": _SAFE_BUILTINS, "pd": pd, "np": np}
    sandbox_locals: dict = {"df": df.copy()}

    try:
        exec(compiled, sandbox_globals, sandbox_locals)  # noqa: S102 -- sandboxed above
    except Exception as exc:
        raise ValueError(f"Generated code raised an error while running: {exc}") from exc

    result = sandbox_locals.get("result")
    if not isinstance(result, pd.DataFrame):
        raise ValueError("Generated code did not assign a pandas DataFrame to `result`.")
    if result.empty:
        raise ValueError("Generated code's `result` table is empty.")
    return result.head(max_rows).to_dict(orient="records")
