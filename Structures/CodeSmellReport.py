from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Location:
    fileName: str
    className: Optional[str]
    methodName: Optional[str]
    startLine: Optional[int]
    endLine: Optional[int]


@dataclass
class Finding:
    id: int
    smell: str
    severity: str
    location: Location
    description: str
    impact: list[str]
    recommendation: str
    diff: str


@dataclass
class Summary:
    overallAssessment: str
    smellsDetected: int
    highestPriority: Optional[str]


@dataclass
class RefactoringItem:
    priority: int
    findingId: int
    action: str


@dataclass
class CodeSmellReport:
    fileName: str
    summary: Summary
    findings: list[Finding] = field(default_factory=list)
    refactoringOrder: list[RefactoringItem] = field(default_factory=list)
    prompt_response: str = field(default="")