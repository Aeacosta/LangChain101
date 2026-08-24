from dataclasses import dataclass, field
from typing import Annotated, Any, Optional

from typing_extensions import TypedDict

from Structures.ScoreReport import ScoreReport


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
    ragReference: str = ""


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
    scoreReport: ScoreReport | None = field(default=None)


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class GraphState(TypedDict):
    """Shared state passed between LangGraph nodes.

    Fields
    ------
    file_path        : absolute or relative path of the C# file to analyze.
    raw_response     : free-text LLM analysis produced by the analyzer node.
    report_json      : raw JSON string produced by the formatter node.
    report           : parsed report as a plain dict (post-formatter).
    score_json       : raw JSON string produced by the scorer node.
    patched          : True once the corrected file has been written to disk.
    patch_content    : full text of the combined-patched file (all findings).
    patch_diff       : unified diff for the combined patch.
    patch_original   : original file content before any patches were applied.
    finding_patches  : list of per-finding patch results
                       [{"finding_id", "patched", "unified_diff", "errors"}, ...].
    valid_json       : True when report_json parses successfully.
    error            : last error message, if any node failed.
    pr_urls          : list of PR result dicts created by create_pr_node
                       [{"finding_id", "smell", "branch", "url"}, ...].
    """
    file_path:       str
    raw_response:    str
    report_json:     str
    report:          dict[str, Any]
    score_json:      str
    patched:         bool
    patch_content:   str
    patch_diff:      str
    patch_original:  str
    finding_patches: list
    valid_json:      bool
    error:           str
    pr_urls:         list