import os
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

async def main():
    # Pass connection config directly to the constructor
    client = MultiServerMCPClient(
        {
            "github": {
                "command": "npx",
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-github",
                ],
                "transport": "stdio",
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN"),
                },
            }
        }
    )

    # Load tools mapped from the MCP server into LangChain format
    tools = await client.get_tools()

    # Initialize your LLM and build a LangGraph React agent
    model = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
        openai_api_key=os.getenv("LLM_API_KEY"),
        openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
        temperature=0.5,
    )

    agent = create_agent(model=model, tools=tools)

    # Run a query against your GitHub repositories
    response = await agent.ainvoke({
        "messages": [("user", "Summarize open pull requests in langchain-ai/langchain-mcp-adapters")]
    })

    print(response["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())
