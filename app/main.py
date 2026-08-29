import os

import streamlit as st

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("🔴 ERROR: GEMINI_API_KEY not found!")
    st.info("Please make sure you have a .env file in the same directory as main.py with the line: GEMINI_API_KEY='your_api_key'")
    st.stop()

from langchain_utils import invoke_chain

st.title("Langchain NL2SQL Chatbot")

# Initialize chat history
if "messages" not in st.session_state:
    # print("Creating session state")
    st.session_state.messages = []

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("What is up?"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)

    # Display assistant response in chat message container
    with st.spinner("Generating response..."):
        with st.chat_message("assistant"):
            # Directly use invoke_chain which is now Gemini-configured
            response = invoke_chain(prompt,st.session_state.messages)
            st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
