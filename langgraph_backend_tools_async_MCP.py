from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages
#from langchain_huggingface import ChatHuggingFace,HuggingFaceEndpoint
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
from langgraph.prebuilt import ToolNode,tools_condition
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool
import asyncio
import requests
import random
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from Basic_Rag import RAGPDF
import httpx
from langchain_core.tools import StructuredTool
import uuid

# Tools
# Tool-1
search_tool = DuckDuckGoSearchRun(region="us-en")
# Define the logic as a standard function
# async def run_search_async(query: str) -> str:
#     """Run a DuckDuckGo search asynchronously."""
#     return await asyncio.to_thread(search_tool.run, query)

# # Create the tool
# search_tool_async = StructuredTool.from_function(
#     func=search_tool.run,
#     coroutine=run_search_async, # Pass the named function here
#     name=search_tool.name,
#     description=search_tool.description
# )


@tool
async def search_tool_async(query: str) -> str:
    """
    Search the web for information using DuckDuckGo. 
    Useful for answering questions about current events or finding general information.
    """
    # This keeps the graph from freezing while waiting for the web response
    return await asyncio.to_thread(search_tool.run, query)

# Inject metadata to match the original tool exactly
search_tool_async.name = search_tool.name
search_tool_async.description = search_tool.description

# Tool-2
@tool
async def calculator(first_num: float,second_num: float,operation: str)->dict:
    """
    Perform a basic arithmetic operation on two numbers.
    Supported operations: add, sub, mul, div
    """
    try:
        if operation == "add":
            result=first_num + second_num
        elif operation == "sub":
            result=first_num - second_num
        elif operation == "mul":
            result=first_num * second_num
        elif operation == "div":
            if second_num == 0:
                return {"error": "Division by zero is not allowed"}
            result=first_num / second_num
        else:
            return {"error": f"Unsupported operation '{operation}'"}
        return {"first_num": first_num, "second_num": second_num, "operation": operation, "result": result}
    except Exception as e:
        return {"error": str(e)}

# Tool-3
@tool
async def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest stock price for a given symbol (e.g. 'AAPL', 'TSLA')
    using Alpha Vantage with API key in the URL.
    """
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey=FHHVTI78I9PRGT3"
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        return r.json()

# Tool-4
# RAG tool
# Initialize with your specific PDF path here
pdf_manager = RAGPDF("Introduction to Machine Learning with Python.pdf")
sync_rag_tool = pdf_manager.get_tool()

# @tool
# async def rag_tool_async(query:str) ->str:
#     return await asyncio.to_thread(sync_rag_tool.invoke,query)

rag_tool_async = StructuredTool.from_function(
    func = sync_rag_tool.invoke,  # The original logic
    coroutine=lambda q:asyncio.to_thread(sync_rag_tool.invoke,q),  # The async logic
    name = sync_rag_tool.name, # Inherent name
    description=sync_rag_tool.description # inherent docstring
)

load_dotenv()

model = ChatOpenAI(model = "gpt-4o-mini")

# Make tools list
tools = [search_tool_async, calculator, get_stock_price, rag_tool_async]

# Make the LLM tool-aware
llm_with_tools = model.bind_tools(tools)

# Creates database in same folder as code
#GLOBAL_CONN = sqlite3.connect(database='chatbot.db', check_same_thread=False, isolation_level=None)

DB_PATH = "chatbot.db"

# Initialize database
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS thread_meta (
                thread_id TEXT PRIMARY KEY,
                title TEXT
            )"""
        )
        await db.execute("""
        CREATE TABLE IF NOT EXISTS tool_metrics_meta (
            thread_id TEXT,
            message_id TEXT,
            tool_name TEXT,
            execution_time REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP            
                        
        )""")
        await db.commit()
    

# State creation
class ChatState(TypedDict):
    # Reducer function add - To append
    messages: Annotated[list[BaseMessage],add_messages]


def build_graph(checkpointer):
    

    # Nodes
    async def chat_node(state:ChatState):
        # Take user query from state
        messages = state['messages']
        # Send to llm
        response = await llm_with_tools.ainvoke(messages)
        # response store in state
        return {'messages':[response]}

    # Executes tool calls
    tool_node = ToolNode(tools)


    # Checkpointer
    #checkpointer = AsyncSqliteSaver.from_conn_string("chatbot.db")

    # Define graph
    graph = StateGraph(ChatState)

    # Add nodes
    graph.add_node('chat_node',chat_node)
    graph.add_node("tools", tool_node)

    # Add edges
    graph.add_edge(START,'chat_node')
    # Conditional edge : If the LLM asks for a tool, go to ToolNode; else finish
    graph.add_conditional_edges("chat_node", tools_condition)
    graph.add_edge("tools","chat_node")
    #graph.add_edge('chat_node',END)

    chatbot = graph.compile(checkpointer=checkpointer)


    return chatbot

async def main():
    await init_db()
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        chatbot = build_graph(checkpointer)


if __name__=='__main__':
    asyncio.run(main())


async def retrieve_all_threads():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT thread_id,title FROM thread_meta") as cursor:
            rows = await cursor.fetchall()
            return [(str(row[0]),row[1]) for row in rows]
    

chatbot = build_graph(None)
