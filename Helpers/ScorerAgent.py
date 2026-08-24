"""ScorerAgent — evaluates a CodeSmellReport and returns a quality score.

The agent receives the full report JSON (findings + severities) and reasons
about the overall code quality, producing a structured ScoreReport JSON.

Unlike a pure formula, the LLM accounts for:
- Severity distribution and clustering
- Whether the same class/method has multiple issues
- Architectural vs cosmetic concerns
- Presence of Critical findings (hard cap on grade)

Public API
----------
from Helpers.ScorerAgent import ScorerAgent

scorer = ScorerAgent(logger)
score_json: str = scorer.score(report_dict)
"""

from __future__ import annotations

import json
import os
import re

from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger
from Helpers.JsonUtils import fix_json_string_control_chars
from Helpers.LangfuseCallbackHandler import get_callback

_SCORER_SYSTEM_PROMPT = """You are a code quality scoring engine.

You will receive a CodeSmellReport JSON produced by a static analysis agent.
Your job is to evaluate the overall quality of the analyzed file and return a
structured ScoreReport JSON.

## SCORING FORMULA

Start at 100 points. Deduct penalties per finding based on severity:
  Critical  → 25 points each
  High      → 15 points each
  Medium    →  8 points each
  Low       →  3 points each

Apply a frequency multiplier when the same severity appears more than once:
  1 finding  → ×1.0
  2 findings → ×1.3
  3 findings → ×1.6
  4+ findings → ×2.0 (capped)

Final score = max(0, 100 − total_penalty). Round to the nearest integer.

## GRADE THRESHOLDS
  90–100 → A (Excellent)
  75–89  → B (Good)
  55–74  → C (Acceptable)
  35–54  → D (Poor)
  0–34   → F (Critical)

Any report with at least one Critical finding is capped at grade D regardless of score.

## JUSTIFICATION

Write 2–3 sentences explaining the score. Reference the most impactful finding
types. Be concise and specific — no generic phrases like "the code has issues".

## OUTPUT FORMAT — STRICT

Output ONLY a single valid JSON object. No prose. No markdown. No code fences.

{
  "score": 72,
  "grade": "C",
  "justification": "string",
  "breakdown": [
    { "severity": "Critical", "count": 0, "penalty": 0.0 },
    { "severity": "High",     "count": 1, "penalty": 15.0 },
    { "severity": "Medium",   "count": 2, "penalty": 20.8 },
    { "severity": "Low",      "count": 1, "penalty": 3.0 }
  ]
}

Include all four severity levels in breakdown even if count is 0.
"""


class ScorerAgent:
    """Single-call LLM that scores a CodeSmellReport and returns ScoreReport JSON.

    Usage
    -----
    from Helpers.ScorerAgent import ScorerAgent

    scorer = ScorerAgent(logger)
    score_json = scorer.score(report_dict)
    parsed = json.loads(score_json)
    """

    def __init__(self, logger: AgentLogger) -> None:
        self._log = logger
        _cb = get_callback(trace_name="ScorerAgent")
        _callbacks = [_cb] if _cb else []
        self._model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
            callbacks=_callbacks,
        )

    def score(self, report: dict) -> str:
        """Score a report dict and return a ScoreReport JSON string."""
        # Strip prompt_response from the payload — not relevant to scoring
        payload = {k: v for k, v in report.items() if k != "prompt_response"}

        self._log._logger.debug(
            "ScorerAgent: scoring %d findings", len(payload.get("findings", []))
        )

        messages = [
            {"role": "system", "content": _SCORER_SYSTEM_PROMPT},
            {"role": "user",   "content": json.dumps(payload)},
        ]

        response = self._model.invoke(messages)
        answer = response.content.strip()

        if answer.lower().startswith("assistant"):
            answer = answer[len("assistant"):].lstrip()

        # Strip any accidental markdown fences
        answer = re.sub(r'^```(?:json)?\s*', '', answer, flags=re.IGNORECASE)
        answer = re.sub(r'\s*```$', '', answer)

        answer = fix_json_string_control_chars(answer)
        self._log._logger.debug("ScorerAgent: done — %s", answer[:120])
        return answer.strip()
