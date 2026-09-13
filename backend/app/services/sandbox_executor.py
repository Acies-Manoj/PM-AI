"""Sandboxed Python code executor for AI-generated feature and formula code.

The sandbox:
  - Permits only pandas, numpy, and stdlib math/re/statistics imports
  - Blocks exec / eval / open / __import__ and similar
  - Enforces a wall-clock time limit via a daemon thread
  - Expects generated code to assign its result to a variable named `result`
"""
from __future__ import annotations

import ast
import json
import threading

import numpy as np
import pandas as pd

_TIME_LIMIT_SECS = 10
_ALLOWED_IMPORTS = {"pandas", "numpy", "math", "statistics", "datetime", "re", "functools"}
_BLOCKED_NAMES = {"exec", "eval", "open", "__import__", "compile", "globals", "locals", "vars"}


class SandboxSecurityError(Exception):
    pass


def _check_ast(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxSecurityError(f"Syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split(".")[0] for a in getattr(node, "names", [])]
            for name in names:
                if name not in _ALLOWED_IMPORTS:
                    raise SandboxSecurityError(f"Import '{name}' is not allowed in the sandbox.")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BLOCKED_NAMES:
                raise SandboxSecurityError(f"Calling '{node.func.id}' is not allowed in the sandbox.")


def run_feature_code(code: str, df: pd.DataFrame) -> tuple[pd.Series | None, str | None]:
    """Execute `code` against `df` and return (result_series, error).

    The code must assign a pd.Series (or array-like coercible to one) to `result`.
    """
    try:
        _check_ast(code)
    except SandboxSecurityError as exc:
        return None, str(exc)

    env: dict = {"df": df.copy(), "pd": pd, "np": np, "result": None}
    error_holder: list[Exception | None] = [None]

    def _run() -> None:
        try:
            exec(code, env)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            error_holder[0] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(_TIME_LIMIT_SECS)

    if thread.is_alive():
        return None, f"Execution exceeded the {_TIME_LIMIT_SECS}s time limit."
    if error_holder[0]:
        return None, f"Runtime error: {error_holder[0]}"

    result = env.get("result")
    if result is None:
        return None, "Code did not assign to 'result'."
    if not isinstance(result, pd.Series):
        try:
            result = pd.Series(result, index=df.index)
        except Exception as exc:  # noqa: BLE001
            return None, f"Could not convert result to Series: {exc}"

    return result, None


def _jsonify(obj):
    """Recursively convert numpy/pandas scalars inside a plain dict/list tree
    into native Python types so it survives json.dumps and Pydantic alike."""
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _jsonify(obj.tolist())
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


_FORMULA_RESULT_TYPES = {"metric", "table", "chart_data"}


def run_formula_code(code: str, df: pd.DataFrame) -> tuple[dict | None, str | None]:
    """Execute Formula Agent code and return (result_dict, error).

    Unlike run_feature_code, `result` here must already be the JSON-shaped
    dict the Formula Agent contract expects -- {"type": "metric"|"table"|
    "chart_data", ...} -- so it's returned as-is rather than coerced into a
    Series.
    """
    try:
        _check_ast(code)
    except SandboxSecurityError as exc:
        return None, str(exc)

    env: dict = {"df": df.copy(), "pd": pd, "np": np, "result": None}
    error_holder: list[Exception | None] = [None]

    def _run() -> None:
        try:
            exec(code, env)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            error_holder[0] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(_TIME_LIMIT_SECS)

    if thread.is_alive():
        return None, f"Execution exceeded the {_TIME_LIMIT_SECS}s time limit."
    if error_holder[0]:
        return None, f"Runtime error: {error_holder[0]}"

    result = env.get("result")
    if not isinstance(result, dict) or "type" not in result:
        return None, "Code did not assign a {'type': ...} dict to 'result'."
    if result["type"] not in _FORMULA_RESULT_TYPES:
        return None, f"Unknown result type '{result.get('type')}'."

    result = _jsonify(result)
    try:
        json.dumps(result)
    except TypeError as exc:
        return None, f"Result is not JSON-serializable: {exc}"

    return result, None
