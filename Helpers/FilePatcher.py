"""Applies unified diffs from a CodeSmellReport to the source file.

Public API
----------
apply_fixes(report: dict, logger=None) -> None
    Write the patched file to disk (overwrites original).

preview_patch(report: dict) -> PatchResult
    Return a PatchResult without touching the filesystem.

PatchResult
    .original   : str   — original file content
    .patched    : str   — patched file content
    .unified_diff: str  — unified diff between original and patched
    .errors     : list[str] — any hunks that could not be applied
"""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field


@dataclass
class PatchResult:
    file_path: str
    original: str
    patched: str
    unified_diff: str
    errors: list[str] = field(default_factory=list)


def _parse_hunks(diff_text: str) -> list[tuple[list[str], list[str]]]:
    """Parse a unified diff string into (removed_lines, added_lines) hunk pairs.

    Each element is one @@ hunk.  Lines are kept without trailing newline.
    """
    hunks: list[tuple[list[str], list[str]]] = []
    removed: list[str] = []
    added: list[str] = []
    in_hunk = False

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("@@"):
            if in_hunk:
                hunks.append((removed, added))
            removed, added, in_hunk = [], [], True
        elif in_hunk:
            if raw_line.startswith("-") and not raw_line.startswith("---"):
                removed.append(raw_line[1:])
            elif raw_line.startswith("+") and not raw_line.startswith("+++"):
                added.append(raw_line[1:])
            # context lines (space prefix) are ignored — we match by content

    if in_hunk:
        hunks.append((removed, added))

    return hunks


def _apply_hunks(
    source_lines: list[str],
    hunks: list[tuple[list[str], list[str]]],
) -> tuple[list[str], list[str]]:
    """Apply hunks to source_lines using a sliding window search.

    Returns (result_lines, errors).
    """
    result = list(source_lines)
    errors: list[str] = []

    for removed, added in hunks:
        if not removed:
            # Pure insertion — append at end (best effort)
            result.extend(added)
            continue

        # Search for the removed block inside result (sliding window)
        found = False
        for i in range(len(result) - len(removed) + 1):
            window = [l.rstrip("\n") for l in result[i:i + len(removed)]]
            needle = [l.rstrip("\n") for l in removed]
            if window == needle:
                result[i:i + len(removed)] = [l + "\n" for l in added]
                found = True
                break

        if not found:
            errors.append(f"Could not apply hunk removing: {removed[:1]!r}…")

    return result, errors


def preview_patch(report: dict) -> PatchResult | None:
    """Build a PatchResult for the report without writing anything to disk.

    Returns None if the source file cannot be read.
    """
    file_path: str = report.get("fileName", "")
    if not file_path or not os.path.exists(file_path):
        return None

    with open(file_path, encoding="utf-8") as fh:
        original = fh.read()

    source_lines = original.splitlines(keepends=True)
    all_errors: list[str] = []

    for finding in report.get("findings", []):
        diff_text = (finding.get("diff") or "").strip()
        if not diff_text:
            continue
        hunks = _parse_hunks(diff_text)
        source_lines, errs = _apply_hunks(source_lines, hunks)
        all_errors.extend(errs)

    patched = "".join(source_lines)

    unified = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(file_path)}",
            tofile=f"b/{os.path.basename(file_path)}",
        )
    )

    return PatchResult(
        file_path=file_path,
        original=original,
        patched=patched,
        unified_diff=unified,
        errors=all_errors,
    )


def apply_fixes(report: dict, logger=None) -> None:
    """Apply all diffs from the report and overwrite the source file."""
    result = preview_patch(report)
    if result is None:
        msg = f"Source file not found: {report.get('fileName')}"
        if logger:
            logger._logger.error(msg)
        else:
            print(msg)
        return

    with open(result.file_path, "w", encoding="utf-8") as fh:
        fh.write(result.patched)

    if logger:
        logger._logger.info("Patched %s (%d errors)", result.file_path, len(result.errors))
        for err in result.errors:
            logger._logger.warning("Patch warning: %s", err)
