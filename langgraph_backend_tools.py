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

import requests
import random
from Basic_Rag import RAGPDF

# Tools
search_tool = DuckDuckGoSearchRun(region="us-en")

@tool
def calculator(first_num: float,second_num: float,operation: str)->dict:
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

@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fectch latest stock price for a given symbol (e.g. 'AAPL', 'TSLA')
    using Alpha Vantage with API key in the URL.
    """
    url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey=FHHVTI78I9PRGT3"
    r = requests.get(url)
    return r.json()

# RAG tool
# Initialize with your specific PDF path here
pdf_manager = RAGPDF("Introduction to Machine Learning with Python.pdf")
rag_tool = pdf_manager.get_tool()

load_dotenv()

model = ChatOpenAI(model = "gpt-4o-mini")

# Make tools list
tools = [search_tool, calculator, get_stock_price, rag_tool]

# Make the LLM tool-aware
llm_with_tools = model.bind_tools(tools)


# State creation
class ChatState(TypedDict):
    # Reducer function add - To append
    messages: Annotated[list[BaseMessage],add_messages]

# Nodes
def chat_node(state:ChatState):
    # Take user query from state
    messages = state['messages']
    # Send to llm
    response = llm_with_tools.invoke(messages)
    # response store in state
    return {'messages':[response]}

# Executes tool calls
tool_node = ToolNode(tools)

# Creates database in same folder as code
GLOBAL_CONN = sqlite3.connect(database='chatbot.db', check_same_thread=False, isolation_level=None)

# SQL configuration
GLOBAL_CONN.execute("PRAGMA journal_mode=WAL;")

# Create table to map thread_id and thread_title
GLOBAL_CONN.execute("""
    CREATE TABLE IF NOT EXISTS thread_meta (
             thread_id TEXT PRIMARY KEY,
             title TEXT
)
""")
GLOBAL_CONN.commit()

# reate table to map message_id and tools
GLOBAL_CONN.execute("""
    CREATE TABLE IF NOT EXISTS tool_metrics_meta (
        thread_id TEXT,
        message_id TEXT,
        tool_name TEXT,
        execution_time REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP            
                    
    )"""
)
GLOBAL_CONN.commit()

# Checkpointer
checkpointer = SqliteSaver(conn=GLOBAL_CONN)

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

# # Gives all checkpoints - generator object
# checkpointer.list(None)
# def retrieve_all_threads():
# # Get unique threads in database
#     all_threads=set()
#     for checkpoint in checkpointer.list(None):
#         all_threads.add(checkpoint.config['configurable']['thread_id'])
#     return list(all_threads)

def retrieve_all_threads():
    rows = GLOBAL_CONN.execute("SELECT thread_id,title FROM thread_meta").fetchall()
    return [(str(thread_id),title) for thread_id,title in rows]

