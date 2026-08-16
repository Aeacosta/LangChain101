import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL", "deepseek-chat"),
    openai_api_key=os.getenv("LLM_API_KEY"),
    openai_api_base=os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1"),
)

response = llm.invoke("What are three core features of the LangChain framework?")
print(response.content)
