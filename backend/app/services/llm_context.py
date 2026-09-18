"""Shared "here are the columns" block every Groq-calling agent in this app
prepends to its prompt (formula_agent, feature_request_agent,
feature_orchestrator, analysis_orchestrator -- previously four byte-for-byte
identical copies of this same function).

Trimmed deliberately: with a wide dataset (this app's own test file has 59
columns), the old 3-sample-per-column version alone ran to ~1000 tokens
PER CALL, and every agent here makes at least one such call per question/
feature/requirement -- a single Client Brief with 2 analysis asks can
easily spend several thousand tokens just on repeated columns blocks
before Groq answers anything, which is what was chewing through the
8000-tokens-per-minute rate limit so fast in practice. One short sample is
enough for the LLM to tell a string "Serial Number" apart from a numeric
"Trip ID"; it doesn't need three full examples to do that."""
import pandas as pd


def columns_block(df: pd.DataFrame, max_samples: int = 1, max_sample_len: int = 40) -> str:
    lines = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(max_samples).tolist()
        sample = [s if len(s) <= max_sample_len else s[: max_sample_len - 1] + "…" for s in sample]
        preview = ", ".join(sample) if sample else "(all null)"
        lines.append(f"- {col} ({df[col].dtype}): e.g. {preview}")
    return "\n".join(lines)
