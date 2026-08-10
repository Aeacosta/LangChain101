
import re

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

import Rag
from Helpers.Logger import AgentLogger


# Control-character escape table for JSON strings (everything below 0x20).
_CTRL_ESCAPE = {
    '\n': '\\n',
    '\r': '\\r',
    '\t': '\\t',
    '\b': '\\b',
    '\f': '\\f',
}


def _fix_json_string_control_chars(text: str) -> str:
    """Replace literal control characters inside JSON string literals with
    their valid JSON escape sequences.

    The regex matches a JSON string token (starting with an unescaped ``"``),
    capturing everything up to the closing ``"``.  Inside that span any raw
    control character is replaced with its ``\\x`` counterpart so that the
    resulting text is parseable by a standard JSON parser.
    """

    def _escape_controls_in_match(m: re.Match) -> str:
        content = m.group(1)
        result = []
        for ch in content:
            if ch in _CTRL_ESCAPE:
                result.append(_CTRL_ESCAPE[ch])
            elif ord(ch) < 0x20:
                result.append(f'\\u{ord(ch):04x}')
            else:
                result.append(ch)
        return '"' + ''.join(result) + '"'

    # Match a JSON string: opening ", then any chars (non-greedy, with
    # backslash-escape awareness), then closing ".
    return re.sub(r'"((?:[^"\\]|\\.)*)\"', _escape_controls_in_match, text,
                  flags=re.DOTALL)


class Agent:

    def __init__(self, prompt: str, tools, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="agente")

        model = ChatOllama(
            model="llama3.1:8b",
            temperature=0,
            base_url="http://localhost:11434",
        )

        self.agent = create_agent(
            model=model,
            system_prompt=prompt,
            tools=tools,
            debug=False,
        )

    def call_agent(self, message: str):
        self._log.inicio(message, [])
        result = self.agent.invoke(
            {"messages": [{"role": "user", "content": message},
                             {
            "role": "system",
            "content": """
You are an expert C# software engineer and code-quality reviewer.

Analyze the provided C# source file and identify meaningful code smells,
SOLID violations, maintainability problems, and opportunities for refactoring.

Be conservative. Do not report theoretical or insignificant issues.
Do not invent line numbers, APIs, classes, or behavior.

For every finding provide:
- code smell
- severity
- location
- explanation
- impact
- recommendation
- unified diff

The response MUST conform to the provided JSON schema.
"""
        },]}
        )
        raw = result["messages"][-1].content

        # Some LangChain/Ollama versions prepend "assistant\n\n" to the content.
        # Strip any leading role label and whitespace before returning.
        answer = raw.strip()
        if answer.lower().startswith("assistant"):
            answer = answer[len("assistant"):].lstrip()

        # The LLM sometimes emits literal newlines/tabs inside JSON string values
        # instead of the required \n / \t escape sequences, making the JSON
        # unparseable.  Fix every unescaped control character that appears
        # between the enclosing double-quotes of a JSON string token.
        answer = _fix_json_string_control_chars(answer)

        self._log.respuesta_final(answer)
        self._log._logger.debug("%s", answer)
        return answer
    