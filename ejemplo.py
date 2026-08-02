import sys

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

debug = False

@tool
def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}"

model = ChatOllama(
    model="llama3.1:8b",
    temperature=0,
    base_url="http://localhost:11434"
)

agent = create_agent(
    model=model,
    tools=[get_weather],
    system_prompt="Eres un asistente climatico. Responde en español.",
    debug=debug 
)

try:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "What's the weather in San Francisco?"}]}
    )
    print("Agent Executed via Modern LangChain Pipeline!\n")
    
    print(result["messages"][-1].content)
except Exception as e:
    print(f"Execution Error: {e}")

if not debug:
    sys.exit()    

# Print out the explicit sequence to see what the agent did
for msg in result["messages"]:
    print(f"[{type(msg).__name__}]:")
    
    # Check if the model attempted a tool call
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        print(f" -> 🤖 Model requested tool: {msg.tool_calls}")
    
    # Check if the tool actually executed and passed data back
    elif type(msg).__name__ == "ToolMessage":
        print(f" -> 🔌 Tool Output Received: {msg.content}")
        
    else:
        print(f" -> Content: {msg.content[:100]}...")
