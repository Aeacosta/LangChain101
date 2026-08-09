
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama


import Rag


class Agent:
    
    def __init__(self, prompt: str, tools):
        model = ChatOllama(
        model="llama3.1:8b",
        temperature=0,
        base_url="http://localhost:11434")
        

        
        self.agent = create_agent(
        model=model,
        system_prompt=prompt,
        tools=tools,
        debug=True
        )
    
    def call_agent(self, message: str):
        result = self.agent.invoke(
        {"messages": [{"role": "user", "content": message}]}
    )
        print(result["messages"][-1].content)
    