"""Loads an uploaded spreadsheet into a DataFrame without assuming the real
header sits on row 0 -- real exports (confirmed on the Edeka demo file) can
have a title row and/or a blank row before the actual column headers."""
import io
import re

import pandas as pd

HEADER_SCAN_ROWS = 5


def _detect_header_row(preview: pd.DataFrame) -> int:
    """Picks the row with the most distinct string-valued cells -- a real
    header row is mostly unique column-name strings, while a title row has
    one or two cells and a blank spacer row has none."""
    best_idx = 0
    best_score = -1
    for i in range(min(HEADER_SCAN_ROWS, len(preview))):
        row = preview.iloc[i]
        str_cells = {v for v in row.dropna() if isinstance(v, str) and v.strip()}
        if len(str_cells) > best_score:
            best_score = len(str_cells)
            best_idx = i
    return best_idx


def load_spreadsheet(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, list[str]]:
    """Returns (dataframe, warnings). Raises ValueError on an unreadable file."""
    warnings: list[str] = []
    is_csv = filename.lower().endswith(".csv")

    try:
        if is_csv:
            preview = pd.read_csv(io.BytesIO(file_bytes), header=None, nrows=HEADER_SCAN_ROWS)
        else:
            preview = pd.read_excel(io.BytesIO(file_bytes), header=None, nrows=HEADER_SCAN_ROWS)
    except Exception as exc:
        raise ValueError(f"Could not read '{filename}' as a spreadsheet: {exc}") from exc

    header_row = _detect_header_row(preview)
    if header_row != 0:
        warnings.append(
            f"Detected the real column headers on row {header_row + 1} of the file; "
            f"the row(s) above were treated as a title block and skipped."
        )

    if is_csv:
        df = pd.read_csv(io.BytesIO(file_bytes), header=header_row)
    else:
        df = pd.read_excel(io.BytesIO(file_bytes), header=header_row)

    # Collapse embedded newlines/repeated whitespace from wrapped Excel header
    # cells (e.g. "Segment Length \n(Days)") into a single space.
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]

    # Drop fully-unnamed trailing columns that come from stray formatting
    # past the real data range (openpyxl sometimes reports these) -- but
    # only when they're also entirely empty, so we never silently drop real data.
    unnamed_and_empty = [
        c for c in df.columns if str(c).startswith("Unnamed:") and df[c].isna().all()
    ]
    if unnamed_and_empty:
        df = df.drop(columns=unnamed_and_empty)

    if df.empty:
        raise ValueError(f"'{filename}' parsed to zero data rows.")

    return df, warnings
