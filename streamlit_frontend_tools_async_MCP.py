import streamlit as st
from langgraph_backend_tools_async_MCP import chatbot,retrieve_all_threads, DB_PATH
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage,ToolMessage
import uuid
from langchain_openai import ChatOpenAI
import time
import sqlite3
import asyncio
import aiosqlite

# ---------------------------- Utility functions -------------------------------
def generate_thread_id():
# To generate a dynamic random thread id
    thread_id = uuid.uuid4()
    return str(thread_id)

def reset_chat():
    thread_id = generate_thread_id()
    st.session_state['thread_id'] = thread_id
    st.session_state['thread_title'] = "New Chat"
    
    st.session_state['message_history'] = []

def add_thread(thread_id,thread_title):
    if thread_id not in st.session_state['chat_threads']:
        st.session_state['chat_threads'].append((thread_id,thread_title))
        
def load_conversation(thread_id):
    # Returns messages of a particular thread_id
    CONFIG = {'configurable': {'thread_id' : thread_id}}
    # Use asyncio.run to call the async aget_state
    async def get_val():
        state = await chatbot.aget_state(config=CONFIG)
        return state
    
    state = asyncio.run(get_val())
    if not state.values or 'messages' not in state.values:
        return []
    return state.values['messages']

def generate_title(user_message):
    model = ChatOpenAI()
    prompt = f"Summarize this user request into a very short 3 to 5 word title. Return only the title text and nothing else : \n {user_message}"

    result = model.invoke(prompt)
    title = result.content.strip()
    title=title.split('\n')[0]
    title=title.replace('"','').replace("'","")
    return title

# def delete_from_checkpointer(thread_id):
#     """
#     Deletes all LangGraph checkpoints (actual conversation history)
#     for a given thread_id from the SqliteSaver backend.
#     """
#     # These are internal tables used by SqliteSaver
#     GLOBAL_CONN.execute("DELETE FROM checkpoints where thread_id = ?",(thread_id,))
#     GLOBAL_CONN.execute("DELETE FROM writes where thread_id = ?",(thread_id,))
#     GLOBAL_CONN.commit()

def clear_conversation(thread_id):
    """
    Safely clears conversation without corrupting DB.
    """
    CONFIG = {"configurable": {"thread_id": thread_id}}
    chatbot.update_state(
        config = CONFIG,
        values = {'messages':[]}
    )


def delete_thread(thread_id):
    # Remove from session
    st.session_state['chat_threads'] = [
        (tid,title) for tid,title in st.session_state['chat_threads'] if tid!=thread_id
    ]
    # Remove from DB
    #conn=sqlite3.connect('chatbot.db')
    async def _async_delete():
        async with aiosqlite.connect(DB_PATH) as db:
            # Delete your custom title metadata
            await db.execute("DELETE FROM thread_meta where thread_id = ?",(thread_id,))
            # Delete LangGraph's internal checkpoint data
            await db.execute("DELETE FROM checkpoints where thread_id = ?",(thread_id,))
            # Delete LangGraph's internal intermediate writes
            await db.execute("DELETE FROM writes where thread_id = ?",(thread_id,))
            await db.commit()
    # Run the cleanup bridge
    asyncio.run(_async_delete())

    # 3. Reset UI if the deleted thread was the one we were looking at
    if st.session_state.get('thread_id') == thread_id:
        reset_chat()
    st.rerun()
    
    
    # Remove from LangGraph checkpoint storage (actual messages)
    clear_conversation(thread_id)

    # Reset if active
    if(st.session_state['thread_id']==thread_id):
        reset_chat()
    
    st.rerun()




# ------------------ Session setup -----------------------------------
if 'message_history' not in st.session_state:
    st.session_state['message_history'] =[]

if 'thread_id' not in st.session_state:
    st.session_state['thread_id'] = generate_thread_id()

if 'thread_title' not in st.session_state:
    st.session_state['thread_title'] = "New Chat"

if 'chat_threads' not in st.session_state:
    st.session_state['chat_threads'] = asyncio.run(retrieve_all_threads())

if 'active_menu_thread' not in st.session_state:
    st.session_state['active_menu_thread'] = None



# ---------------------- Sidebar UI ------------------------------
# ---------------------- Sidebar UI controller utility functions   --------------------
# ---------------------- Load chat ---------------------------------

def format_messages(messages):
    """
    Convert Langchain message objects into UI friendly format.
    Output format:
    [{"role: 'user', content: 'Hi'}, --- ]
    """
    formatted = []
    temp_tool_map = {} # To match ToolMessages back to their names
    accumulated_tool_info = []
    for msg in messages:
        # Store ToolMessage durations/results temporarily
        # if isinstance(msg,ToolMessage):
        #     continue

        if isinstance(msg,HumanMessage):
            formatted.append({'role':'user', 'content':msg.content })
            
        elif isinstance(msg,AIMessage):
            # 1. Query metrics for THIS SPECIFIC message ID
            # Change format_messages metrics query
            async def get_metrics(msg_id):
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT tool_name, execution_time FROM tool_metrics_meta WHERE message_id = ?", (msg_id,)) as cursor:
                        return await cursor.fetchall()

            # Inside format_messages for msg in messages:
            rows = asyncio.run(get_metrics(msg.id))
            msg_metrics = [{"Tool": r[0], "Time (s)": r[1]} for r in rows]

            if msg_metrics:
                accumulated_tool_info.extend(msg_metrics)

            # 2. If this message has tool calls but NO content, store the metrics and wait 
            # if msg.tool_calls and not msg.content:
            #     last_tool_metrics = msg_metrics
            #     continue

            if msg.content.strip():
                formatted.append({
                    'role':'assistant', 
                    'content':msg.content,
                    'tool_info': accumulated_tool_info if accumulated_tool_info else None
                })
                accumulated_tool_info = []

            # 3. If this is a final message (has content), attach the metrics and draw
            # Use metrics from this message OR metrics we "saved" from the previous tool-call message
            # final_metrics = msg_metrics if msg_metrics else last_tool_metrics

            # formatted.append({'role':'assistant', 'content':msg.content, 'tool_info': final_metrics})
            # 4. Clear the bucket for the next turn
            
      
        
    return formatted
    
def render_load_button(col,thread_id,title):
    """ 
    Handles loading a conversation when use clicks on chat title.
    Updates session state with selected thread and messages.
    """
    if col.button(title,key=f"load_{thread_id}"):
        st.session_state['thread_id'] = thread_id
        st.session_state['thread_title'] = title
        messages = load_conversation(thread_id)
        st.session_state['message_history'] = format_messages(messages)


# -------------------- Three dot menu ---------------------------------------
def toggle_active_menu(thread_id):
    """
    Opens or closes dropdown menu for a thread.
    Only one menu is active at a time.
    """
    if st.session_state['active_menu_thread'] == thread_id:
        st.session_state['active_menu_thread'] = None
    else:
        st.session_state['active_menu_thread'] = thread_id

def render_menu_button(col,thread_id):
    """
    Handles ... function.
    Toggles which thread's dropdown menu is currently open.
    """
    if col.button("...",key=f"menu_{thread_id}"):
        toggle_active_menu(thread_id)

# ---------------------- Delete button ---------------------------------------
def render_delete_button(col,thread_id):
    """
    Deletes the thread when clicked on it.
    """
    if col.button("🗑 Delete",key=f"delete_{thread_id}"):
        delete_thread(thread_id)
                  
# ---------------------- Dropdownm menu --------------------------------------
def render_dropdown_menu(thread_id):
    """
    Displays dropdown options (Like delete) only for the currently active thread.
    """
    if st.session_state['active_menu_thread'] == thread_id:
        sub_col1,sub_col2 = st.sidebar.columns([0.1,0.9])
        render_delete_button(sub_col2,thread_id)

# ---------------------- Sidebar UI controller -------------------------------
# ---------------------- Each thread row -------------------------------------

def render_thread_row(thread_id,title):
    """
    Renders a single row in sidebar:
    - Chat title button (to load conversation)
    - Three-dot menu button
    - Conditional dropdown (Delete)
    """
    col1,col2 = st.sidebar.columns([0.85,0.15])
    render_load_button(col1,thread_id,title)
    render_menu_button(col2,thread_id)
    render_dropdown_menu(thread_id)

# ---------------------- Main sidebar controller ------------------------------
def render_sidebar_threads():
    """
    Main function to render all chat threads in the sidebar.
    Iterates through threads and calls smaller UI components.
    """
    st.sidebar.header('My Conversations')
    st.sidebar.title('LangGraph Chatbot')
    if st.sidebar.button('New Chat'):
        reset_chat()
    st.sidebar.header('My Conversations')
    for thread_id,title in st.session_state['chat_threads'][::-1]:
        render_thread_row(thread_id,title)


render_sidebar_threads()


# ------------------------------------  Main UI -------------------------------------

# Loading the conversation history
for idx, message in enumerate(st.session_state['message_history']):
#for message in st.session_state['message_history']:
    if message['role'] == 'user':
        with st.chat_message('user'):
            st.markdown(message['content'])
    else:
        with st.chat_message("assistant"):
            #st.markdown(message['content'])
            # If there's tool info stored in history, you'd render it here
            if message.get("tool_info"):
                with st.expander("🛠️ Tool Execution Details",expanded=False):
                    st.table(message["tool_info"])
            st.markdown(message['content'])
        

user_input=st.chat_input('Type here')



# Print this to your command prompt/terminal to inspect the data
# print("\n--- Current Message History Debug ---")
# for idx, msg in enumerate(st.session_state['message_history']):
#     role = msg.get('role')
#     content = msg.get('content', '')[:50] # Show first 50 chars
#     has_tools = "Yes" if msg.get('tool_info') else "No"
    
#     print(f"Index: {idx} | Role: {role} | Tools Included: {has_tools} | Content: {content}...")
# print("-------------------------------------\n")




if user_input:
    # 1. Append user message to session state
    st.session_state['message_history'].append({'role':'user','content':user_input})
    new_thread_created=False

    # 2. Handle New Chat title generation
    if(st.session_state['thread_title']=="New Chat"):
        title=generate_title(user_input)
        st.session_state['thread_title'] =  title
        add_thread(st.session_state['thread_id'],st.session_state['thread_title'] )
  
        # Async Database call for thread metadata
        async def save_thread_meta():
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO thread_meta (thread_id, title) VALUES (?, ?)",
                    (str(st.session_state['thread_id']), st.session_state['thread_title'])
                )
                await db.commit()
        asyncio.run(save_thread_meta())
        new_thread_created=True
    with st.chat_message('user'):
        st.markdown(user_input)
    
    # 3. Setup LangGraph Config
    # CONFIG = {'configurable': {'thread_id' : st.session_state['thread_id']}}
    # Also includes langsmith tracing threadwise
    CONFIG = {'configurable': {'thread_id' : st.session_state['thread_id']},
              "metadata": {
                  'thread_id' : st.session_state['thread_id']
              },
              "run_name": "chat_turn"
              }
    
    # 4. Assistant Response Logic
    with st.chat_message('assistant'):
        response_data = {
            "full_response": "",
            "current_ai_msg_id": None # Track the ID of this specific response turn
        }
        tool_metrics = [] # To store {tool_name, time_taken}
        active_tools = {} # To track start times: {tool_call_id: start_time}

        # UI placeholder for status and main text
        tool_details_place_holder = st.empty()
        status_placeholder = st.empty()
        text_placeholder = st.empty()


        # Define the async streaming logic
        async def run_chatbot_async():
            # Switch to astream to ensure the event loop stays open for MCP tools
            async for message_chunk in chatbot.astream(
                    {'messages': [HumanMessage(content=user_input)]},
                    config=CONFIG,stream_mode='messages'
                ):
                # LangGraph message chunks can sometimes be tuples
                msg = message_chunk[0] if isinstance(message_chunk, tuple) else message_chunk

                # Capture the message ID for database logging
                if isinstance(message_chunk,AIMessage) and not response_data["current_ai_msg_id"]:
                    response_data["current_ai_msg_id"] = msg.id
                # Tool Call Start (LLM decides to use a tool)
                # 1. Capture Tool CALL (Start)
                if isinstance(msg,AIMessage) and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        t_name = tool_call['name']
                        t_id = tool_call['id']
                        active_tools[t_id] = {"name": t_name, "start": time.perf_counter()}
                        #status_placeholder.status(f"Running tool: **{t_name}**...")
                        status_container.update(label = f"🛠️ Running MCP/Tool: **{t_name}**...", state="running")

                # Tool Result End (The tool has finished executing)
                # 2. Capture Tool RESULT (End)
                elif isinstance(msg,ToolMessage):
                    t_id = msg.tool_call_id
                    if t_id in active_tools:
                        t_name_actual = active_tools[t_id]["name"]
                        end_time = time.perf_counter()
                        duration = end_time - active_tools[t_id]["start"]
                        tool_metrics.append({
                            "Tool": t_name_actual,
                            "Time (s)": round(duration,3)
                        })

                        # Async Save Metrics to DB
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "INSERT INTO tool_metrics_meta (thread_id, message_id, tool_name, execution_time) VALUES (?, ?, ?, ?)",
                                (st.session_state['thread_id'], response_data["current_ai_msg_id"], t_name_actual, duration)
                            )
                            await db.commit()
                        status_container.update(label = f"✅ Tool calls - ({t_name_actual}) completed", state = "running")

                 # 3. Capture AI Text content
                 # Text Generation (Streaming the words)
                elif isinstance(msg,AIMessage) and msg.content:
                    response_data["full_response"] += msg.content
                    text_placeholder.markdown(response_data["full_response"])

        # Initialize the status container and run the async bridge
        # Streaming including tool events. # Initialize a single status container
        with status_placeholder.status("Thinking...", expanded=False) as status_container:
            asyncio.run(run_chatbot_async())

            status_container.update(label="Response generated", state="complete")

        # 5. Final Tool Summary UI
        if tool_metrics:
            with st.expander("🛠️ Tool Details"):
                st.table(tool_metrics)
    
    # Save to history with metrics
    st.session_state['message_history'].append({'role':'assistant','content':response_data["full_response"], 'tool_info':tool_metrics if tool_metrics else None})

    if 'new_thread_created' in locals() and new_thread_created:
        st.rerun()







    

