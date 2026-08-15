from dataclasses import dataclass, field


@dataclass
class SeverityBreakdown:
    severity: str
    count: int
    penalty: float


@dataclass
class ScoreReport:
    score: int                              # 0–100
    grade: str                             # A / B / C / D / F
    justification: str                     # LLM written explanation
    breakdown: list[SeverityBreakdown] = field(default_factory=list)
