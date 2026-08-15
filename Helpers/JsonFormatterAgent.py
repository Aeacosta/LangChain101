import os
import re

from langchain_openai import ChatOpenAI

from Helpers.Logger import AgentLogger
from Helpers.JsonUtils import fix_json_string_control_chars

_JSON_FORMATTER_PROMPT = """You are a JSON converter.

You will receive a code-smell analysis in any format (prose, bullet points, mixed text, partial JSON, markdown).
Your ONLY job is to reformat that content into a single valid JSON object that matches the schema below.

RULES:
1. Output ONLY the JSON object. No prose, no markdown fences, no comments.
2. First character MUST be `{`. Last character MUST be `}`.
3. Escape all newlines inside string values as \\n.
4. Do NOT invent findings. Only include what was described in the input.
5. If a field is missing from the input, use a sensible default (empty array, null, 0).

SCHEMA:
{
  "fileName": "string",
  "summary": {
    "overallAssessment": "string",
    "smellsDetected": 0,
    "highestPriority": null
  },
  "findings": [
    {
      "id": 1,
      "smell": "string",
      "severity": "Critical|High|Medium|Low",
      "location": {
        "fileName": "string",
        "className": "string or null",
        "methodName": "string or null",
        "startLine": null,
        "endLine": null
      },
      "description": "string",
      "impact": ["string"],
      "recommendation": "string",
      "diff": "string",
      "ragReference": "string"
    }
  ],
  "refactoringOrder": [
    { "priority": 1, "findingId": 1, "action": "string" }
  ]
}
"""


class JsonFormatterAgent:
    """Thin single-call LLM that converts any free-text analysis into the
    CodeSmellReport JSON schema. No tools, no RAG — just a focused reformat.

    Usage
    -----
    from Helpers.JsonFormatterAgent import JsonFormatterAgent

    formatter = JsonFormatterAgent(logger)
    json_str = formatter.format(raw_analysis_text)
    """

    def __init__(self, logger: AgentLogger) -> None:
        self._log = logger
        self._model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
        )

    def format(self, raw_analysis: str) -> str:
        """Take free-text analysis and return a clean JSON string."""
        self._log._logger.debug(
            "JsonFormatterAgent: reformatting %d chars", len(raw_analysis)
        )
        messages = [
            {"role": "system", "content": _JSON_FORMATTER_PROMPT},
            {"role": "user", "content": raw_analysis},
        ]
        response = self._model.invoke(messages)
        answer = response.content.strip()

        if answer.lower().startswith("assistant"):
            answer = answer[len("assistant"):].lstrip()

        # Strip markdown fences the model may have added anyway
        answer = re.sub(r'^```(?:json)?\s*', '', answer, flags=re.IGNORECASE)
        answer = re.sub(r'\s*```$', '', answer)

        answer = fix_json_string_control_chars(answer)
        self._log._logger.debug("JsonFormatterAgent: done")
        return answer.strip()
