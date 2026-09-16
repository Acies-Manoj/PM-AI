"""Sandboxed execution for AI-generated pandas calculations. Used only by
the "ai_generated" feature type (see feature_engineering.py), when no
existing template -- lookup, extract_month, ratio, duration_hours,
custom_formula -- can express the requested calculation.

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


def _compile_and_run(code: str, df: pd.DataFrame, *, label: str):
    """Shared compile-and-execute step for both sandboxed entry points below:
    parse, AST-validate against the same allowlist, execute against a copy
    of `df` with the same restricted builtins, and hand back whatever the
    snippet assigned to `result` (unvalidated -- callers apply their own
    shape check, since a per-row feature and a whole-dataset analysis
    answer expect different shapes)."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Generated code has a syntax error: {exc}") from exc

    _validate_ast(tree)

    compiled = compile(tree, filename=f"<{label}>", mode="exec")
    sandbox_globals = {"__builtins__": _SAFE_BUILTINS, "pd": pd}
    sandbox_locals: dict = {"df": df.copy()}

    try:
        exec(compiled, sandbox_globals, sandbox_locals)  # noqa: S102 -- sandboxed above
    except Exception as exc:
        raise ValueError(f"Generated code raised an error while running: {exc}") from exc

    if "result" not in sandbox_locals:
        raise ValueError("Generated code did not assign anything to a variable named `result`.")
    return sandbox_locals["result"]


def run_generated_code(code: str, df: pd.DataFrame) -> pd.Series:
    """Executes `code` against a copy of `df` and returns whatever it
    assigns to a variable named `result`. Raises ValueError on anything
    unsafe or malformed -- callers treat that as "this calculation
    couldn't be computed" and show a skip note, never the raw traceback."""
    result = _compile_and_run(code, df, label="ai_generated_feature")
    if not isinstance(result, pd.Series):
        raise ValueError("Generated code did not assign a pandas Series to `result`.")
    if len(result) != len(df):
        raise ValueError("Generated code's `result` doesn't have one value per row.")
    return result.set_axis(df.index)


def run_generated_analysis_code(code: str, df: pd.DataFrame):
    """Sibling to `run_generated_code` for the Formula Agent's "novel ask"
    path (see formula_agent.py): a plain-language analysis question that
    doesn't fit the pivot-table template shape (group_by/metrics), so Groq
    is asked to compute the answer directly instead of one value per row.
    Same AST allowlist and restricted builtins -- only the accepted shape of
    `result` differs: a DataFrame (a small table), a dict/scalar/str/number
    (a single computed answer), rather than a strict per-row Series."""
    result = _compile_and_run(code, df, label="ai_generated_analysis")
    if isinstance(result, pd.Series):
        return result.to_dict()
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
        return result
    raise ValueError(
        "Generated code's `result` must be a DataFrame, Series, dict, string, or number -- "
        f"got {type(result).__name__}."
    )
