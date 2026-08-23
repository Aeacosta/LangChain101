"""
Agent setup for the Code Smell Analyzer.

Instantiates the LangChain agent with its tools and system prompt.
Import `agent` from this module wherever you need to invoke the agent.
"""

import os
import urllib.parse

import requests
from . import Agent
from .Rag import RagCore
from Helpers.Logger import AgentLogger
from langchain.tools import tool

log = AgentLogger(name="agent", level="DEBUG")
rag = RagCore(logger=log)

@tool
def find_documents(query: str) -> str:
    """Se utiliza para consultar la documentacion referente a buenas practicas de programacion"""
    return rag.find_documents(query)


@tool
def read_local_file(file_path: str) -> str:
    """
    Reads the content of a local text-based file given its strict system file path.
    Use this tool whenever you need to see what is inside a file.
    """
    normalized_path = os.path.normpath(file_path)
    if normalized_path.startswith("..") or os.path.isabs(normalized_path):
        return "Error: Access denied. You can only read files within the local project directory."
    if not os.path.exists(normalized_path):
        return f"Error: File '{file_path}' not found."
    try:
        with open(normalized_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception as exc:
        return f"Error reading file: {exc}"


@tool
def read_github_url(url: str) -> str:
    """
    Fetches the raw source code of a file hosted on GitHub given its URL.
    Accepts both standard GitHub blob URLs
    (https://github.com/<user>/<repo>/blob/<branch>/<path>)
    and direct raw URLs (https://raw.githubusercontent.com/...).
    Use this tool whenever the file to analyse is a GitHub URL instead of a local path.
    """
    url = url.strip()
    # Convert blob URL to raw URL if needed.
    if "raw.githubusercontent.com" not in url:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc == "github.com":
            path = parsed.path.replace("/blob/", "/", 1)
            url = urllib.parse.urlunparse(
                ("https", "raw.githubusercontent.com", path, "", "", "")
            )
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        return f"Error fetching GitHub URL: {exc}"


_SYSTEM_PROMPT = """
# OUTPUT FORMAT — STRICT REQUIREMENT

You MUST return your entire response as **ONE VALID JSON OBJECT**.

This is a machine-to-machine response. The response will be parsed programmatically.

## ABSOLUTE RULES

1. The first character of your response MUST be `{`.
2. The last character of your response MUST be `}`.
3. The root JSON value MUST be an object.
4. Return JSON ONLY.
5. Do NOT return Markdown.
6. Do NOT use Markdown code fences.
7. Do NOT write ```json.
8. Do NOT write ``` anywhere in the response.
9. Do NOT include explanations before the JSON.
10. Do NOT include explanations after the JSON.
11. Do NOT include comments inside the JSON.
12. Do NOT include headings such as "Analysis", "Findings", or "Result" outside the JSON.
13. Use double quotes for JSON property names.
14. Use double quotes for JSON string values.
15. Escape newline characters inside strings as `\\n`.
16. Escape double quotes inside strings as `\\"`.
17. Escape backslashes inside strings as `\\\\`.
18. Do NOT use trailing commas.
19. Do NOT return pseudocode outside the JSON.
20. Do NOT return multiple JSON objects.
21. Do NOT return a JSON array as the root value.

Your response must be directly parseable by a standard JSON parser.

## REQUIRED JSON STRUCTURE

Return exactly one object with this structure:

{
"fileName": "string",
"summary": {
"overallAssessment": "string",
"smellsDetected": 0,
"highestPriority": null
},
"findings": [],
"refactoringOrder": []
}

The property names above are mandatory.

### fileName
The name of the C# file being analyzed. Type: string.

### summary
Must contain:
* `overallAssessment`: string
* `smellsDetected`: integer
* `highestPriority`: string or null

### findings
An array of detected code smells. Each finding MUST contain:
* `id`: integer
* `smell`: string
* `severity`: one of `"Critical"`, `"High"`, `"Medium"`, `"Low"`
* `location`: object
* `description`: string
* `impact`: array of strings
* `recommendation`: string
* `diff`: string
* `ragReference`: string — the APA-format citation returned by the `find_documents` tool that supports this finding. Call `find_documents` with the smell name or a short description of the bad practice. Copy the returned string **verbatim** into this field. If no relevant document is found, use `""`.

### location
Must contain:
* `fileName`: string
* `className`: string or null
* `methodName`: string or null
* `startLine`: integer or null
* `endLine`: integer or null

Never invent line numbers.

### diff
The `diff` property MUST be a JSON string.
It MUST NOT be a Markdown code block.
It MUST contain the unified diff as plain text with newline characters escaped as `\\n`.

Correct:
"diff": "--- a/Test.cs\\n+++ b/Test.cs\\n@@\\n-public void Test()\\n+public void Test(int value)\\n"

Incorrect:
"diff": "`diff\\n--- a/Test.cs\\n+++ b/Test.cs\\n`"

If no safe refactoring can be proposed, use: "diff": ""

## NO FINDINGS

If no meaningful code smells are detected, return:

{
"fileName": "<actual file name>",
"summary": {
"overallAssessment": "No significant code smells were detected.",
"smellsDetected": 0,
"highestPriority": null
},
"findings": [],
"refactoringOrder": []
}

Do not omit any properties.

## CONSISTENCY RULES

Before returning the response, internally verify:
* `smellsDetected` equals the number of objects in `findings`.
* Every finding has a unique integer `id`.
* Every finding contains the analyzed `fileName`.
* Every finding has one of the allowed severity values.
* Every `findingId` in `refactoringOrder` exists in `findings`.
* `startLine` is less than or equal to `endLine` when both are provided.
* Every `diff` is a JSON string.
* Every finding has a `ragReference` string (may be empty but must be present).
* No Markdown code fences exist anywhere.
* There is exactly one root JSON object.
* The result can be parsed by a standard JSON parser.

DO NOT describe this validation in your response.
Perform the validation internally and then output ONLY the final JSON object.
"""

agent = Agent.Agent(_SYSTEM_PROMPT, [find_documents, read_local_file, read_github_url], logger=log)
