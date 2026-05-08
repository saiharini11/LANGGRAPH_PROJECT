import streamlit as st
from langgraph_backend_tools import chatbot,retrieve_all_threads, GLOBAL_CONN
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage,ToolMessage
import uuid
from langchain_openai import ChatOpenAI
import time
import sqlite3

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
    state = chatbot.get_state(config=CONFIG)
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
    GLOBAL_CONN.execute("DELETE FROM thread_meta where thread_id = ?",(thread_id,))
    GLOBAL_CONN.execute("DELETE FROM writes WHERE thread_id = ?",(thread_id,))
    GLOBAL_CONN.commit()
    #conn.close()
    

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
    st.session_state['chat_threads'] = retrieve_all_threads()

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
    for msg in messages:
        # Store ToolMessage durations/results temporarily
        # if isinstance(msg,ToolMessage):
        #     continue

        if isinstance(msg,HumanMessage):
            formatted.append({'role':'user', 'content':msg.content })
            
        elif isinstance(msg,AIMessage):
            # Query metrics for THIS SPECIFIC message ID
            cursor = GLOBAL_CONN.execute(
                "SELECT tool_name, execution_time FROM tool_metrics_meta WHERE message_id = ?", (msg.id,))
            rows = cursor.fetchall()
            msg_metrics = [{"Tool": r[0], "Time (s)": r[1]} for r in rows]
            formatted.append({'role':'assistant', 'content':msg.content, 'tool_info': msg_metrics })
        #     if getattr(msg,"tool_calls",None):
        #         continue
        #     role='assistant'
        # else:
        #     continue
        # if not msg.content:
        #     continue
        
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
for message in st.session_state['message_history']:
    with st.chat_message(message['role']):
        st.markdown(message['content'])
        # If there's tool info stored in history, you'd render it here
        if "tool_info" in message:
            with st.expander("🛠️ Tool Details"):
                st.table(message["tool_info"])

user_input=st.chat_input('Type here')

if user_input:
    st.session_state['message_history'].append({'role':'user','content':user_input})
    new_thread_created=False
    if(st.session_state['thread_title']=="New Chat"):
        title=generate_title(user_input)
        st.session_state['thread_title'] =  title
        #st.session_state['chat_threads'][-1][st.session_state['thread_id']]=title
        add_thread(st.session_state['thread_id'],st.session_state['thread_title'] )
        #conn=sqlite3.connect('chatbot.db')
        GLOBAL_CONN.execute(
            "INSERT OR REPLACE INTO thread_meta (thread_id,title) VALUES (?,?)",
            (str(st.session_state['thread_id']),st.session_state['thread_title'])
        )
        GLOBAL_CONN.commit()
        #conn.close()
        new_thread_created=True
    with st.chat_message('user'):
        st.markdown(user_input)
    
    # CONFIG = {'configurable': {'thread_id' : st.session_state['thread_id']}}
    # Also includes langsmith tracing threadwise
    CONFIG = {'configurable': {'thread_id' : st.session_state['thread_id']},
              "metadata": {
                  'thread_id' : st.session_state['thread_id']
              },
              "run_name": "chat_turn"
              }
    
  
    with st.chat_message('assistant'):
        full_response = ""
        tool_metrics = [] # To store {tool_name, time_taken}
        active_tools = {} # To track start times: {tool_call_id: start_time}
        current_ai_msg_id = None # Track the ID of this specific response turn

        # UI placeholder for status and main text
        status_placeholder = st.empty()
        text_placeholder = st.empty()


        # Streaming including tool events. # Initialize a single status container
        with status_placeholder.status("Thinking...",expanded=False) as status_container:
            t_name="tool"
            for message_chunk,metadata in chatbot.stream(
                    {'messages': [HumanMessage(content=user_input)]},
                    config=CONFIG,stream_mode='messages'
                ):

                # FIX: Capture the unique ID of the AI Message
                if isinstance(message_chunk,AIMessage) and not current_ai_msg_id:
                    current_ai_msg_id = message_chunk.id

                # 1. Capture Tool CALL (Start)
                if isinstance(message_chunk,AIMessage) and message_chunk.tool_calls:
                    for tool_call in message_chunk.tool_calls:
                        t_name = tool_call['name']
                        t_id = tool_call['id']
                        active_tools[t_id] = {"name": t_name, "start": time.perf_counter()}
                        #status_placeholder.status(f"Running tool: **{t_name}**...")
                        status_container.update(label = f"🛠️ Running tool: **{t_name}**...", state="running")

                # 2. Capture Tool RESULT (End)
                elif isinstance(message_chunk,ToolMessage):
                    t_id = message_chunk.tool_call_id
                    if t_id in active_tools:
                        end_time = time.perf_counter()
                        duration = end_time - active_tools[t_id]["start"]
                        tool_metrics.append({
                            "Tool": active_tools[t_id]["name"],
                            "Time (s)": round(duration,3)
                        })

                        # FIX: Persistent Save to DB linked to this Message ID
                        GLOBAL_CONN.execute(
                                "INSERT INTO tool_metrics_meta (thread_id, message_id, tool_name, execution_time) VALUES (?, ?, ?, ?)", 
                                (st.session_state['thread_id'], current_ai_msg_id, t_name, duration)
                            )
                        GLOBAL_CONN.commit()
                        status_container.update(label = f"✅ Tool calls - ({t_name}) completed", state = "running")
                        #status_placeholder.empty() # Clear the status once done

                # 3. Capture AI Text content
                elif isinstance(message_chunk,AIMessage) and message_chunk.content:
                    full_response += message_chunk.content
                    text_placeholder.markdown(full_response)

            # Final status cleanup
            status_container.update(label="Response generated", state="complete")

        # Final Tool Summary (The "Small Link" functionality)
        if tool_metrics:
            with st.expander("🛠️ Tool Execution Details"):
                st.table(tool_metrics)

    # Save to history with metrics
    st.session_state['message_history'].append({'role':'assistant','content':full_response, 'tool_info':tool_metrics})
    if 'new_thread_created' in locals() and new_thread_created:
        st.rerun()

    

