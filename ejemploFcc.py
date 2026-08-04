from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

@tool
def get_weather(location: str) -> str:
    """Get the current weather for a given location."""
    return f"The weather in {location} is sunny and 22°C."

# Initialize Claude and bind the tool
model = ChatAnthropic(model="claude-3-5-sonnet-20241022",
                      temperature=0,
                      base_url="http://localhost:8082",
                      api_key="freecc",
                      betas=[])
model_with_tools = model.bind_tools([get_weather])

# Invoke the model with a query that triggers the tool
response = model_with_tools.invoke("What is the weather like in Heredia?")
print(response.tool_calls)
