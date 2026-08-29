import os
import re
from operator import itemgetter

import streamlit as st
from langchain.chains import create_sql_query_chain
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    FewShotChatMessagePromptTemplate,
    MessagesPlaceholder,
)
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

from table_details import get_table_details, table_chain as select_table
from examples import get_example_selector
from prompts import answer_prompt, example_prompt

db_user = os.getenv("db_user")
db_password = os.getenv("db_password")
db_host = os.getenv("db_host")
db_name = os.getenv("db_name")
db_port = os.getenv("db_port")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def _clean_sql(query: str) -> str:
    """Strips markdown code fences the LLM sometimes wraps generated SQL in."""
    match = re.search(r"```(?:sql)?\s*(.*?)\s*```", query, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else query.strip()


def _enforce_read_only(query: str) -> str:
    """Blocks any generated query that isn't a read-only SELECT/WITH statement."""
    if not query.strip().upper().startswith(("SELECT", "WITH")):
        raise ValueError(f"Refusing to execute non-read-only SQL query: {query}")
    return query


def build_db():
    """Creates a SQLDatabase connection from environment configuration."""
    db_uri = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    return SQLDatabase.from_uri(db_uri)


def build_query_chain(db):
    """Builds the runnable that turns a question into a generated SQL query.

    Shared by the app (get_chain) and the evaluation harness (evaluate.py)
    so both use the exact same prompting/table-selection logic.
    """
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.6-flash", google_api_key=GEMINI_API_KEY, temperature=0
    )

    example_selector = get_example_selector()

    few_shot_prompt = FewShotChatMessagePromptTemplate(
        example_prompt=example_prompt,
        example_selector=example_selector,
        input_variables=["input", "top_k"],
    )

    final_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a MySQL expert. Given an input question, create a syntactically correct MySQL query to run. Unless otherwise specified.\n\nHere is the relevant table info: {table_info}\n\nBelow are a number of examples of questions and their corresponding SQL queries.",
            ),
            few_shot_prompt,
            MessagesPlaceholder(variable_name="messages"),
            ("human", "{input}"),
        ]
    )

    table_details = get_table_details()
    generate_query = create_sql_query_chain(llm, db, final_prompt) | RunnableLambda(_clean_sql)

    return (
        RunnablePassthrough.assign(table_details=lambda x: table_details)
        | RunnablePassthrough.assign(table_names_to_use=select_table)
        | RunnablePassthrough.assign(query=generate_query)
    )


@st.cache_resource
def get_chain():
    """Creates and caches the main LangChain runnable."""
    print("Creating chain...")
    db = build_db()
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.6-flash", google_api_key=GEMINI_API_KEY, temperature=0
    )

    query_chain = build_query_chain(db)
    execute_query = RunnableLambda(_enforce_read_only) | QuerySQLDataBaseTool(db=db)
    rephrase_answer = answer_prompt | llm | StrOutputParser()

    chain = query_chain | RunnablePassthrough.assign(
        result=itemgetter("query") | execute_query
    ) | rephrase_answer

    print("Chain created successfully!")
    return chain


def create_history(messages):
    """Creates a chat history object from a list of messages."""
    history = ChatMessageHistory()
    for message in messages:
        if message["role"] == "user":
            history.add_user_message(message["content"])
        else:
            history.add_ai_message(message["content"])
    return history


def invoke_chain(question, messages):
    """Invokes the main chain with the user's question and chat history."""
    chain = get_chain()
    history = create_history(messages)
    response = chain.invoke(
        {"question": question, "top_k": 3, "messages": history.messages}
    )
    history.add_user_message(question)
    history.add_ai_message(response)
    return response
