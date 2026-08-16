"""
XTPTableExtractor — Parses a Markdown table produced by XTPMismatchJustificationAgent
into a pandas DataFrame that can be used programmatically.

No LLM is involved.  The extractor locates the first Markdown pipe-table in the
supplied text, strips formatting characters, normalises column names, and returns
a clean DataFrame.

Expected input table columns (from XTPMismatchJustificationAgent):
    Prog A Bin | Prog B Bin | Count | % of Src | Direction |
    Most Likely Cause (Diff Block / Parameter) | Confidence

Column name normalisation applied:
    "Prog A Bin"                              → prog_a_bin
    "Prog B Bin"                              → prog_b_bin
    "Count"                                   → count          (int)
    "% of Src"                                → pct_of_src     (float)
    "Direction"                               → direction
    "Most Likely Cause (Diff Block / Parameter)" → most_likely_cause
    "Confidence"                              → confidence

Raises
------
ValueError
    If no Markdown table is found in the input text, or if the table has fewer
    than the minimum required columns.
"""

from __future__ import annotations

import re
import io
from typing import List

import pandas as pd


# Minimum columns a valid justification table must have
_MIN_COLUMNS = 5

# Column rename map: canonical header → DataFrame column name
_COLUMN_MAP: dict[str, str] = {
    "prog a bin":                                  "prog_a_bin",
    "prog b bin":                                  "prog_b_bin",
    "count":                                       "count",
    "% of src":                                    "pct_of_src",
    "direction":                                   "direction",
    "most likely cause (diff block / parameter)":  "most_likely_cause",
    "most likely cause":                           "most_likely_cause",
    "confidence":                                  "confidence",
}


class XTPTableExtractor:
    """Extracts the Markdown justification table into a pandas DataFrame.

    Usage
    -----
    ::

        from XTPAnalyser.XTPTableExtractor import XTPTableExtractor

        extractor = XTPTableExtractor()
        df = extractor.extract(justification_table_text)
        print(df)

    The returned DataFrame has typed columns:

    ============  ==================  ===================================================
    Column        dtype               Description
    ============  ==================  ===================================================
    prog_a_bin    object (str)        Soft-bin label in Program A
    prog_b_bin    object (str)        Soft-bin label in Program B
    count         int64               Number of units in this transition
    pct_of_src    float64             Percentage of the Prog-A bin population that shifted
    direction     object (str)        ↑ / ↓ / ↔ / ✗ / ✓ direction symbol + label
    most_likely_cause  object (str)   XTP block / parameter and root-cause description
    confidence    object (str)        HIGH / MEDIUM / LOW
    ============  ==================  ===================================================
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def extract(self, text: str) -> pd.DataFrame:
        """Parse the Markdown table in *text* and return a DataFrame.

        Parameters
        ----------
        text : str
            Full output string from ``XTPMismatchJustificationAgent.justify()``.
            May contain a WARNING block instead of a table — in that case this
            method raises ``ValueError`` with the warning message.

        Returns
        -------
        pd.DataFrame
            One row per off-diagonal mismatch, with normalised column names and
            correctly typed numeric columns.

        Raises
        ------
        ValueError
            If *text* contains a WARNING block (no table to extract), or if no
            valid Markdown table is found.
        """
        # Surface WARNING blocks immediately so callers can handle them clearly
        if "⚠️" in text or "CORRELATION WARNING" in text:
            raise ValueError(
                "XTPMismatchJustificationAgent returned a coherence warning — "
                "no table to extract.\n\n" + text.strip()
            )

        rows = self._parse_markdown_table(text)
        if not rows:
            raise ValueError(
                "No Markdown table found in the provided text.  "
                "Ensure XTPMismatchJustificationAgent produced a table output."
            )

        headers, data_rows = rows[0], rows[1:]

        if len(headers) < _MIN_COLUMNS:
            raise ValueError(
                f"Table has only {len(headers)} column(s); expected at least "
                f"{_MIN_COLUMNS}.  Raw headers: {headers}"
            )

        df = pd.DataFrame(data_rows, columns=headers)
        df = self._normalise_columns(df)
        df = self._cast_types(df)
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_markdown_table(text: str) -> List[List[str]]:
        """Extract rows from the first Markdown pipe-table in *text*.

        Returns a list of lists where index 0 is the header row and
        subsequent entries are data rows.  Separator rows (``|---|``) are
        discarded.  Returns an empty list if no table is found.
        """
        table_rows: List[List[str]] = []
        in_table = False

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("|"):
                # Once we have started collecting and encounter a non-pipe line,
                # stop — we only want the first table.
                if in_table:
                    break
                continue

            # Skip separator rows like |---|---|
            if re.match(r"^\|[\s\-:|]+\|$", line):
                continue

            in_table = True
            # Split on pipe, strip whitespace, drop empty boundary tokens
            cells = [c.strip() for c in line.split("|")]
            cells = [c for c in cells if c != ""]  # remove leading/trailing empties
            table_rows.append(cells)

        return table_rows

    @staticmethod
    def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Rename columns using ``_COLUMN_MAP`` (case-insensitive, strip spaces)."""
        rename: dict[str, str] = {}
        for col in df.columns:
            key = col.strip().lower()
            if key in _COLUMN_MAP:
                rename[col] = _COLUMN_MAP[key]
        return df.rename(columns=rename)

    @staticmethod
    def _cast_types(df: pd.DataFrame) -> pd.DataFrame:
        """Cast *count* to int and *pct_of_src* to float where present."""
        if "count" in df.columns:
            df["count"] = pd.to_numeric(df["count"], errors="coerce").astype("Int64")

        if "pct_of_src" in df.columns:
            # Strip trailing % signs before casting
            df["pct_of_src"] = (
                df["pct_of_src"]
                .astype(str)
                .str.replace("%", "", regex=False)
                .str.strip()
            )
            df["pct_of_src"] = pd.to_numeric(df["pct_of_src"], errors="coerce")

        return df


# ---------------------------------------------------------------------------
# Script entry-point — self-test with a synthetic table string
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _SAMPLE = """
| Prog A Bin | Prog B Bin | Count | % of Src | Direction | Most Likely Cause (Diff Block / Parameter) | Confidence |
|---|---|---|---|---|---|---|
| SB_1001_PassPrime | SB_1003_EcoPass | 103 | 12.9% | ↓ down-bin | LEVELS / V_DD_CORE: 1.20V→0.95V reduces noise margin → Eco-Pass threshold crossed | HIGH |
| SB_1001_PassPrime | SB_4001_TimingFail | 58 | 7.3% | ✗ pass→fail | LEVELS / V_DD_CORE: 1.20V→0.95V increases gate propagation delay → setup-time violation | HIGH |
"""

    extractor = XTPTableExtractor()
    df = extractor.extract(_SAMPLE)

    print("=== Extracted DataFrame ===")
    print(df.to_string(index=False))
    print()
    print("=== dtypes ===")
    print(df.dtypes)
