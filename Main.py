
import Agent
import Rag
from Rag import RagCore
from langchain.tools import tool


@tool
def find_documents(query):
    """ Se utiliza para consultar la documentacion referente a buenas practicas de programacion """
    return RagCore().find_documents(query)

agent = Agent.Agent("Tu tarea es dar recomendaciones de codigo limpio en desarrollo de Software.", [find_documents])

user_prompt = "Que es un COde Smell?"
agent.call_agent(user_prompt)