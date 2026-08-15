
import json

from agent_setup import agent, log
from Helpers.Reporter import print_report
from Helpers.FilePatcher import apply_fixes

file = r"Ejemplos/CodeSmell2.cs"
user_prompt = f"Que Code Smells detectas en este archivo? {file}"
raw_answer = agent.call_agent(user_prompt)

try:
    result = json.loads(raw_answer)
    print_report(result)
    apply_fixes(result, logger=log)
except json.JSONDecodeError as e:
    log._logger.error("La respuesta no es JSON válido: %s", e)
    print(raw_answer)