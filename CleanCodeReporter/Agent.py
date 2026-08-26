
import json
import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from . import Rag
from Helpers.Logger import AgentLogger
from Helpers.JsonFormatterAgent import JsonFormatterAgent
from Helpers.ScorerAgent import ScorerAgent
from Helpers.LangfuseCallbackHandler import get_callback, trace_name_context
from Structures.CodeSmellReport import CodeSmellReport

# Load .env if it exists, otherwise fall back to .env.example
load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")


class Agent:

    def __init__(self, prompt: str, tools, logger: AgentLogger | None = None):
        self._log = logger or AgentLogger(name="agente")

        model = ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            openai_api_key=os.getenv("LLM_API_KEY"),
            openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
        )

        self._formatter = JsonFormatterAgent(self._log)
        self._scorer    = ScorerAgent(self._log)

        self.agent = create_agent(
            model=model,
            system_prompt=prompt,
            tools=tools,
            debug=False,
        )

    def call_agent(self, message: str):
        self._log.inicio(message, [])
        _cb = get_callback()
        _callbacks = [_cb] if _cb else []
        with trace_name_context("CleanCodeReviewer"):
            result = self.agent.invoke(
                {"messages": [
                    {"role": "user", "content": message},
                    {
                        "role": "system",
                        "content": (
                            "You are an expert C# software engineer and code-quality reviewer.\n\n"
                            "Analyze the provided C# source file and identify meaningful code smells,\n"
                            "SOLID violations, maintainability problems, and opportunities for refactoring.\n\n"
                            "Be conservative. Do not report theoretical or insignificant issues.\n"
                            "Do not invent line numbers, APIs, classes, or behavior.\n\n"
                            "For every finding provide:\n"
                            "- code smell\n- severity\n- location\n- explanation\n"
                            "- impact\n- recommendation\n- unified diff\n\n"
                            "The response MUST conform to the provided JSON schema."
                        ),
                    },
                ]},
                config={"callbacks": _callbacks},
            )
        prompt_response = result["messages"][-1].content

        # Pass the raw analysis through the formatter agent to get clean JSON.
        answer = self._formatter.format(prompt_response)

        # Score the report and inject both score and original response.
        try:
            parsed = json.loads(answer)
            if isinstance(parsed, dict):
                parsed["prompt_response"] = prompt_response
                score_json = self._scorer.score(parsed)
                score_data = json.loads(score_json)
                parsed["scoreReport"] = score_data
                answer = json.dumps(parsed)
        except Exception:
            pass

        self._log.respuesta_final(answer)
        self._log._logger.debug("%s", answer)
        return answer

    def stream_agent(self, message: str):
        """Yield raw text chunks from the LLM as they arrive.

        Each yielded value is a plain string token.  The final chunk is always
        the complete, post-processed JSON string (same output as call_agent).
        Callers that only care about the finished JSON should use call_agent.
        """
        self._log.inicio(message, [])
        input_payload = {
            "messages": [
                {"role": "user", "content": message},
                {
                    "role": "system",
                    "content": (
                        "You are an expert C# software engineer and code-quality reviewer.\n\n"
                        "Analyze the provided C# source file and identify meaningful code smells,\n"
                        "SOLID violations, maintainability problems, and opportunities for refactoring.\n\n"
                        "Be conservative. Do not report theoretical or insignificant issues.\n"
                        "Do not invent line numbers, APIs, classes, or behavior.\n\n"
                        "For every finding provide:\n"
                        "- code smell\n- severity\n- location\n- explanation\n"
                        "- impact\n- recommendation\n- unified diff\n\n"
                        "The response MUST conform to the provided JSON schema."
                    ),
                },
            ]
        }

        _cb = get_callback()
        _callbacks = [_cb] if _cb else []
        collected: list[str] = []
        stream_config = {
            "configurable": {"streaming": True},
            "callbacks": _callbacks,
        }
        with trace_name_context("CleanCodeReviewer"):
            for event in self.agent.stream(input_payload, stream_mode="messages", config=stream_config):
                # stream_mode="messages" yields (message_chunk, metadata) tuples.
                chunk, _meta = event if isinstance(event, tuple) else (event, {})
                token = getattr(chunk, "content", "") or ""
                if token:
                    collected.append(token)
                    self._log.stream_token(token)
                    yield token

        # Re-assemble and pass through the formatter agent to get clean JSON.
        prompt_response = "".join(collected)

        raw = self._formatter.format(prompt_response)

        # Score the report and inject both score and original response.
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                parsed["prompt_response"] = prompt_response
                score_json = self._scorer.score(parsed)
                score_data = json.loads(score_json)
                parsed["scoreReport"] = score_data
                raw = json.dumps(parsed)
        except Exception:
            pass

        self._log.respuesta_final(raw)
        self._log._logger.info("%s", raw)
    