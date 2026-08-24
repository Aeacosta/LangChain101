"""Applies unified diffs from a CodeSmellReport to the source file.

Public API
----------
build_combined_diff(report: dict) -> str
    Concatenate ALL finding diffs (sorted by id) into one unified diff string.

git_apply_patch(report: dict, logger=None) -> PatchResult | None
    Write the combined diff to a temp file, run ``git apply``, read back the
    result.  Returns None when git is unavailable or the apply fails, so
    callers can fall back to preview_patch.

apply_fixes(report: dict, logger=None) -> None
    Apply all diffs (via git_apply_patch with preview_patch fallback) and
    overwrite the source file on disk.

preview_patch(report: dict) -> PatchResult | None
    Python hunk-walker fallback — returns a PatchResult without touching the
    filesystem except to read the source.

PatchResult
    .original    : str        — original file content
    .patched     : str        — patched file content
    .unified_diff: str        — unified diff between original and patched
    .errors      : list[str]  — any hunks that could not be applied
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import tempfile
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

    Each contiguous block of -/+ lines separated by context lines (or a new @@
    marker) becomes its own hunk entry so that _apply_hunks can locate each
    block independently in the source file.

    Handles diffs where the LLM emitted literal ``\\n`` escape sequences instead
    of real newline characters (a common LLM output artefact).
    """
    # Normalise literal \n sequences → real newlines so splitlines() works.
    if "\n" not in diff_text and "\\n" in diff_text:
        diff_text = diff_text.replace("\\n", "\n")

    hunks: list[tuple[list[str], list[str]]] = []
    removed: list[str] = []
    added: list[str] = []
    in_hunk = False

    def _flush() -> None:
        """Save current removed/added pair if non-empty."""
        if removed or added:
            hunks.append((list(removed), list(added)))
        removed.clear()
        added.clear()

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("@@"):
            # New @@ marker: flush whatever was accumulating and start fresh.
            _flush()
            in_hunk = True
        elif in_hunk:
            if raw_line.startswith("-") and not raw_line.startswith("---"):
                removed.append(raw_line[1:])
            elif raw_line.startswith("+") and not raw_line.startswith("+++"):
                added.append(raw_line[1:])
            else:
                # Context line (space-prefixed) or blank line: each interruption
                # ends the current contiguous block — flush it as its own hunk so
                # _apply_hunks can locate the block independently in the source.
                _flush()

    _flush()

    return hunks


# Minimum SequenceMatcher ratio for a line to be considered a fuzzy match.
_FUZZY_THRESHOLD = 0.75


def _block_score(window: list[str], needle: list[str]) -> float:
    """Return a [0, 1] similarity score between two equal-length line lists.

    Each corresponding pair is scored with SequenceMatcher and the scores are
    averaged.  A perfect match scores 1.0.
    """
    if not needle:
        return 1.0
    total = 0.0
    for w, n in zip(window, needle):
        total += difflib.SequenceMatcher(None, w, n).ratio()
    return total / len(needle)


def _apply_hunks(
    source_lines: list[str],
    hunks: list[tuple[list[str], list[str]]],
    eol: str = "\n",
) -> tuple[list[str], list[str]]:
    """Apply hunks to source_lines using a sliding window search.

    Matching strategy (in order):
    1. Exact match after stripping trailing whitespace.
    2. Fuzzy match: the window whose average per-line SequenceMatcher ratio
       with the needle is highest, provided it exceeds ``_FUZZY_THRESHOLD``.

    ``eol`` is appended to every replacement line so the patched file
    preserves the original line endings (``\\n`` or ``\\r\\n``).

    Returns (result_lines, errors).
    """
    result = list(source_lines)
    errors: list[str] = []

    for removed, added in hunks:
        if not removed:
            # Pure insertion — append at end (best effort)
            result.extend(l + eol for l in added)
            continue

        needle = [l.rstrip() for l in removed]
        n = len(removed)
        best_i: int | None = None
        best_score = -1.0

        for i in range(len(result) - n + 1):
            window = [l.rstrip() for l in result[i:i + n]]
            if window == needle:
                # Exact match — apply immediately.
                best_i = i
                best_score = 1.0
                break
            score = _block_score(window, needle)
            if score > best_score:
                best_score = score
                best_i = i

        if best_i is not None and best_score >= _FUZZY_THRESHOLD:
            result[best_i:best_i + n] = [l + eol for l in added]
        else:
            errors.append(f"Could not apply hunk removing: {removed[:1]!r}…")

    return result, errors


def _detect_eol(text: str) -> str:
    """Return ``'\\r\\n'`` if the text uses CRLF, else ``'\\n'``."""
    return "\r\n" if "\r\n" in text else "\n"


def preview_patch(report: dict) -> PatchResult | None:
    """Build a PatchResult for the report without writing anything to disk.

    Applies every finding's diff sequentially to the original source.
    Returns None if the source file cannot be read.
    """
    file_path: str = report.get("fileName", "")
    if not file_path or not os.path.exists(file_path):
        return None

    with open(file_path, encoding="utf-8") as fh:
        original = fh.read()

    eol          = _detect_eol(original)
    source_lines = original.splitlines(keepends=True)
    all_errors: list[str] = []

    for finding in report.get("findings", []):
        diff_text = (finding.get("diff") or "").strip()
        if not diff_text:
            continue
        hunks = _parse_hunks(diff_text)
        source_lines, errs = _apply_hunks(source_lines, hunks, eol=eol)
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


def preview_patch_single_finding(
    original: str,
    finding: dict,
    file_path: str = "",
) -> PatchResult:
    """Apply a single finding's diff to *original* content (no disk I/O).

    Parameters
    ----------
    original  : original file text (already read from disk).
    finding   : a single finding dict with a ``diff`` key.
    file_path : used only for display names in the unified diff header.

    Returns a PatchResult.  ``patched`` equals ``original`` when the diff
    is empty or could not be matched.
    """
    basename  = os.path.basename(file_path) if file_path else "file"
    eol       = _detect_eol(original)
    src_lines = original.splitlines(keepends=True)
    errors: list[str] = []

    diff_text = (finding.get("diff") or "").strip()
    if diff_text:
        hunks      = _parse_hunks(diff_text)
        src_lines, errors = _apply_hunks(src_lines, hunks, eol=eol)

    patched = "".join(src_lines)
    unified = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile=f"a/{basename}",
            tofile=f"b/{basename}",
        )
    )
    return PatchResult(
        file_path=file_path,
        original=original,
        patched=patched,
        unified_diff=unified,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Combined diff builder  (Sub-Task 1)
# ---------------------------------------------------------------------------

def build_combined_diff(report: dict) -> str:
    """Return a single unified diff string combining ALL finding diffs.

    Findings are sorted by ``id`` ascending so hunks are emitted in the same
    order they appear in the file — critical for ``git apply`` offset tracking.

    Each per-finding diff is normalised: any existing ``--- a/`` / ``+++ b/``
    header lines are stripped and a single canonical header pair is prepended
    for the whole file.  The ``@@`` hunk lines and their context/add/remove
    lines are kept verbatim.

    Returns an empty string when no finding carries a non-empty diff.
    """
    file_path: str = report.get("fileName", "")
    basename = os.path.basename(file_path) if file_path else "file"

    findings = sorted(report.get("findings", []), key=lambda f: f.get("id", 0))

    hunk_blocks: list[str] = []
    for finding in findings:
        raw = (finding.get("diff") or "").strip()
        if not raw:
            continue
        # Normalise literal \n escape sequences (common LLM artefact).
        if "\n" not in raw and "\\n" in raw:
            raw = raw.replace("\\n", "\n")
        # Strip any leading --- / +++ header lines already present.
        lines = raw.splitlines()
        body_lines = [
            l for l in lines
            if not (l.startswith("--- ") or l.startswith("+++ "))
        ]
        hunk_blocks.append("\n".join(body_lines))

    if not hunk_blocks:
        return ""

    header = f"--- a/{basename}\n+++ b/{basename}"
    return header + "\n" + "\n".join(hunk_blocks) + "\n"


# ---------------------------------------------------------------------------
# git apply  (Sub-Task 2)
# ---------------------------------------------------------------------------

def _find_git_root(path: str) -> str | None:
    """Walk up from *path* until a ``.git`` directory is found.

    Returns the directory that contains ``.git``, or ``None`` if not found.
    """
    current = os.path.abspath(path)
    if os.path.isfile(current):
        current = os.path.dirname(current)
    while True:
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:          # reached filesystem root
            return None
        current = parent


def git_apply_patch(report: dict, logger=None) -> PatchResult | None:
    """Apply all finding diffs via ``git apply`` and return a PatchResult.

    Workflow
    --------
    1. Build the combined unified diff from ALL findings (sorted by id).
    2. Write it to a temp ``.diff`` file.
    3. Run ``git apply --whitespace=fix <temp.diff>`` in the git root.
    4. Read the now-patched file back from disk.
    5. Return a PatchResult.  Return ``None`` on any failure so callers can
       fall back to :func:`preview_patch`.

    Parameters
    ----------
    report : dict
        The parsed CodeSmellReport dict (must have ``fileName`` and
        ``findings`` keys).
    logger : AgentLogger | None
        Optional logger for diagnostic messages.

    Returns
    -------
    PatchResult | None
        ``None`` when git is not available, the file is not inside a git
        repo, the combined diff is empty, or ``git apply`` exits non-zero.
    """
    def _log(level: str, msg: str, *args) -> None:
        if logger:
            getattr(logger._logger, level)(msg, *args)

    # ── Guard: git must be on PATH ───────────────────────────────────────
    if not shutil.which("git"):
        _log("warning", "git_apply_patch — git not found on PATH; falling back")
        return None

    file_path: str = report.get("fileName", "")
    if not file_path or not os.path.exists(file_path):
        _log("warning", "git_apply_patch — source file not found: %s", file_path)
        return None

    git_root = _find_git_root(file_path)
    if git_root is None:
        _log("warning", "git_apply_patch — %s is not inside a git repo; falling back", file_path)
        return None

    # ── Build combined diff ───────────────────────────────────────────────
    combined = build_combined_diff(report)
    if not combined:
        _log("info", "git_apply_patch — no diffs in report; nothing to apply")
        return None

    # Read original before git touches the file.
    with open(file_path, encoding="utf-8") as fh:
        original = fh.read()

    tmp_path: str | None = None
    try:
        # ── Write temp .diff ──────────────────────────────────────────────
        fd, tmp_path = tempfile.mkstemp(suffix=".diff", prefix="codesmell_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(combined)

        _log("debug", "git_apply_patch — temp diff written to %s (%d bytes)",
             tmp_path, len(combined))
        _log("debug", "git_apply_patch — combined diff:\n%s", combined)

        # ── Run git apply ─────────────────────────────────────────────────
        proc = subprocess.run(
            ["git", "apply", "--whitespace=fix", tmp_path],
            cwd=git_root,
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0:
            _log("warning",
                 "git_apply_patch — git apply failed (rc=%d):\nstdout: %s\nstderr: %s",
                 proc.returncode, proc.stdout.strip(), proc.stderr.strip())
            return None

        _log("info", "git_apply_patch — git apply succeeded ✓")

        # ── Read patched file ─────────────────────────────────────────────
        with open(file_path, encoding="utf-8") as fh:
            patched = fh.read()

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
            errors=[],
        )

    except Exception as exc:  # noqa: BLE001
        _log("error", "git_apply_patch — unexpected error: %s", exc)
        return None

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Public writers
# ---------------------------------------------------------------------------

def apply_fixes(report: dict, logger=None) -> None:
    """Apply all diffs from the report and overwrite the source file.

    Tries ``git apply`` first (all diffs combined, correct offset handling).
    Falls back to the Python hunk-walker via :func:`preview_patch` when git
    is unavailable or the apply fails.
    """
    # Try git apply first.
    result = git_apply_patch(report, logger=logger)

    # Fallback: Python hunk-walker.
    if result is None:
        result = preview_patch(report)

    if result is None:
        msg = f"Source file not found: {report.get('fileName')}"
        if logger:
            logger._logger.error(msg)
        else:
            print(msg)
        return

    # git_apply_patch already wrote the file in place; preview_patch did not.
    # Write only when the result came from preview_patch (patched != original
    # after git apply, but git already flushed it — writing again is harmless
    # and keeps the logic simple).
    with open(result.file_path, "w", encoding="utf-8") as fh:
        fh.write(result.patched)

    if logger:
        logger._logger.info("Patched %s (%d errors)", result.file_path, len(result.errors))
        for err in result.errors:
            logger._logger.warning("Patch warning: %s", err)
