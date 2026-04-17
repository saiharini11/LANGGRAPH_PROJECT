from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages

class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage],add_messages]

llm = ChatOpenAI()

def chat_node(state:ChatState):
    # Take user query from state
    messages = state['messages']
    # Send to llm
    response = llm.invoke(messages)
    # response store in state
    return {'messages':[response]}

graph = StateGraph(ChatState)

# Add nodes
graph.add_node('chat_node',chat_node)

# Add edges
graph.add_edge(START,'chat_node')
graph.add_edge('chat_node',END)

chatbot = graph.compile()

print(chatbot)

initial_state = {
    'messages' : [HumanMessage(content='What is the capital of India')]
}
chatbot.invoke(initial_state)

