"""Code quality score calculator.

Formula
-------
    score = max(0, 100 - sum(SEVERITY_WEIGHT[sev] * FREQUENCY_WEIGHT[count]) for each smell type)

Severity weights (penalty per finding of that severity):
    Critical  →  25
    High      →  15
    Medium    →   8
    Low       →   3

Frequency multiplier (how many findings of the same smell type exist):
    1 occurrence  →  1.0x  (no bonus penalty)
    2 occurrences →  1.3x
    3 occurrences →  1.6x
    4+            →  2.0x  (capped)

The frequency multiplier penalises repeated patterns more harshly than isolated ones.

Public API
----------
compute_score(findings: list[dict]) -> ScoreResult
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


# ── Weights ───────────────────────────────────────────────────────────────────

_SEVERITY_WEIGHT: dict[str, float] = {
    "Critical": 25.0,
    "High":     15.0,
    "Medium":    8.0,
    "Low":       3.0,
}

_FREQUENCY_MULTIPLIER: list[float] = [
    0.0,   # index 0 — unused
    1.0,   # 1 occurrence
    1.3,   # 2 occurrences
    1.6,   # 3 occurrences
]
_FREQUENCY_CAP = 2.0   # applied for 4+ occurrences


@dataclass
class ScoreResult:
    score: int                          # 0–100
    penalty: float                      # total deducted points
    breakdown: list[dict]               # per-severity breakdown
    grade: str                          # A / B / C / D / F
    color: str                          # hex colour for the grade


def _frequency_multiplier(count: int) -> float:
    if count <= 0:
        return 0.0
    if count < len(_FREQUENCY_MULTIPLIER):
        return _FREQUENCY_MULTIPLIER[count]
    return _FREQUENCY_CAP


def compute_score(findings: list[dict]) -> ScoreResult:
    """Compute a quality score from a list of finding dicts.

    Each dict must have at least a ``severity`` key.
    """
    if not findings:
        return ScoreResult(score=100, penalty=0.0, breakdown=[], grade="A", color="#16a34a")

    # Count how many findings per severity level
    sev_counter: Counter[str] = Counter(
        f.get("severity", "Low") for f in findings
    )

    total_penalty = 0.0
    breakdown: list[dict] = []

    for sev in ("Critical", "High", "Medium", "Low"):
        count = sev_counter.get(sev, 0)
        if count == 0:
            continue
        weight = _SEVERITY_WEIGHT.get(sev, 3.0)
        freq   = _frequency_multiplier(count)
        penalty = weight * count * freq
        total_penalty += penalty
        breakdown.append({
            "severity": sev,
            "count":    count,
            "weight":   weight,
            "freq_multiplier": freq,
            "penalty":  round(penalty, 1),
        })

    score = max(0, round(100 - total_penalty))
    grade, color = _grade(score)

    return ScoreResult(
        score=score,
        penalty=round(total_penalty, 1),
        breakdown=breakdown,
        grade=grade,
        color=color,
    )


def _grade(score: int) -> tuple[str, str]:
    if score >= 90:
        return "A", "#16a34a"   # green
    if score >= 75:
        return "B", "#65a30d"   # lime
    if score >= 55:
        return "C", "#ca8a04"   # amber
    if score >= 35:
        return "D", "#d97706"   # orange
    return "F", "#dc2626"       # red
