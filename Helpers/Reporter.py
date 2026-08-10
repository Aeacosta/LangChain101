"""Console reporter for code-smell analysis results.

Renders the JSON payload returned by the agent as a human-readable,
color-coded summary using only the standard library (no rich/tabulate).
"""

from __future__ import annotations

_RESET   = "\033[0m"
_BOLD    = "\033[1m"
_DIM     = "\033[2m"
_RED     = "\033[31m"
_YELLOW  = "\033[33m"
_GREEN   = "\033[32m"
_CYAN    = "\033[36m"
_MAGENTA = "\033[35m"
_WHITE   = "\033[37m"
_BG_RED  = "\033[41m"

_SEVERITY_COLOR: dict[str, str] = {
    "Critical": _BOLD + _RED,
    "High":     _BOLD + _YELLOW,
    "Medium":   _YELLOW,
    "Low":      _DIM + _WHITE,
}

_SEVERITY_ICON: dict[str, str] = {
    "Critical": "🔴",
    "High":     "🟠",
    "Medium":   "🟡",
    "Low":      "🟢",
}

_LINE_THICK = "═" * 62
_LINE_THIN  = "─" * 62


def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}"


def print_report(data: dict) -> None:
    """Print a formatted code-smell report to stdout."""
    summary  = data.get("summary", {})
    findings = data.get("findings", [])
    order    = data.get("refactoringOrder", [])

    # ── Header ────────────────────────────────────────────────────────────
    print()
    print(_c(_BOLD + _CYAN, _LINE_THICK))
    print(_c(_BOLD + _CYAN, f"  CODE SMELL REPORT  —  {data.get('fileName', 'unknown')}"))
    print(_c(_BOLD + _CYAN, _LINE_THICK))

    # ── Summary ───────────────────────────────────────────────────────────
    detected  = summary.get("smellsDetected", 0)
    priority  = summary.get("highestPriority") or "—"
    p_color   = _SEVERITY_COLOR.get(priority, _RED) if detected else _GREEN
    assessment = summary.get("overallAssessment", "")

    print()
    print(_c(_BOLD, "  SUMMARY"))
    print(_c(_DIM, f"  {_LINE_THIN}"))
    print(f"  Smells detected : {_c(_BOLD, str(detected))}")
    print(f"  Highest priority: {_c(p_color, priority)}")
    print(f"  Assessment      : {assessment}")

    if not findings:
        print()
        print(_c(_GREEN, "  ✓ No significant issues found."))
        print()
        return

    # ── Findings ──────────────────────────────────────────────────────────
    print()
    print(_c(_BOLD, "  FINDINGS"))

    for f in findings:
        fid      = f.get("id", "?")
        smell    = f.get("smell", "")
        severity = f.get("severity", "")
        icon     = _SEVERITY_ICON.get(severity, "•")
        color    = _SEVERITY_COLOR.get(severity, "")
        loc      = f.get("location", {})

        loc_parts = [loc.get("fileName", "")]
        if loc.get("className"):
            loc_parts.append(loc["className"])
        if loc.get("methodName"):
            loc_parts.append(loc["methodName"])
        start = loc.get("startLine")
        end   = loc.get("endLine")
        if start and end:
            loc_parts.append(f"L{start}–{end}")
        elif start:
            loc_parts.append(f"L{start}")
        loc_str = " › ".join(loc_parts)

        print()
        print(_c(_DIM, f"  {_LINE_THIN}"))
        print(f"  {icon}  [{_c(color, severity)}]  #{fid} — {_c(_BOLD, smell)}")
        print(f"  {_c(_DIM, '📍')} {loc_str}")
        print()
        print(f"  {_c(_BOLD, 'Description')}")
        print(f"  {f.get('description', '')}")

        impacts = f.get("impact", [])
        if impacts:
            print()
            print(f"  {_c(_BOLD, 'Impact')}")
            for imp in impacts:
                print(f"    • {imp}")

        rec = f.get("recommendation", "")
        if rec:
            print()
            print(f"  {_c(_BOLD, 'Recommendation')}")
            print(f"  {rec}")

        diff = f.get("diff", "").strip()
        if diff:
            print()
            print(f"  {_c(_BOLD, 'Diff')}")
            for line in diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    print(_c(_GREEN, f"  {line}"))
                elif line.startswith("-") and not line.startswith("---"):
                    print(_c(_RED, f"  {line}"))
                else:
                    print(_c(_DIM, f"  {line}"))

    # ── Refactoring order ─────────────────────────────────────────────────
    if order:
        print()
        print(_c(_DIM, f"  {_LINE_THIN}"))
        id_map = {f["id"]: f["smell"] for f in findings if "id" in f}
        order_str = " → ".join(
            f"#{oid} {id_map.get(oid, '')}" for oid in order
        )
        print(f"  {_c(_BOLD, 'Suggested refactoring order')}")
        print(f"  {order_str}")

    print()
    print(_c(_BOLD + _CYAN, _LINE_THICK))
    print()
