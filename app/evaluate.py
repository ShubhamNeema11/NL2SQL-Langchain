"""
Execution-accuracy evaluation harness for the NL2SQL pipeline.

For each (question, expected_sql) pair below, the app's own query-generation
chain (see langchain_utils.build_query_chain) is used to generate SQL from
the question. Both the generated query and the expected query are executed
against the database, and the two result sets are compared (order-insensitive).
A row is scored PASS if the result sets match exactly.

This is deliberately a small, hand-written eval set (not a benchmark import)
so results are easy to inspect and reason about. It targets the "SQL Sample
Database" (classicmodels-style) schema this project ships with.

Usage:
    python app/evaluate.py

Requires the same environment variables as the app: db_user, db_password,
db_host, db_port, db_name, GEMINI_API_KEY.
"""

import ast
import re

from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool

from langchain_utils import build_db, build_query_chain, _enforce_read_only

EVAL_SET = [
    {
        "question": "How many customers are there in total?",
        "expected_sql": "SELECT COUNT(*) FROM customers;",
    },
    {
        "question": "What is the total payment amount received across all customers?",
        "expected_sql": "SELECT SUM(amount) FROM payments;",
    },
    {
        "question": "List the cities of all offices located in the USA.",
        "expected_sql": "SELECT city FROM offices WHERE country = 'USA';",
    },
    {
        "question": "How many distinct product lines are there?",
        "expected_sql": "SELECT COUNT(DISTINCT productLine) FROM products;",
    },
    {
        "question": "What is the average credit limit of customers based in the USA?",
        "expected_sql": "SELECT AVG(creditLimit) FROM customers WHERE country = 'USA';",
    },
    {
        "question": "How many orders have the status 'Shipped'?",
        "expected_sql": "SELECT COUNT(*) FROM orders WHERE status = 'Shipped';",
    },
    {
        "question": "What is the total quantity ordered for product code 'S10_1678'?",
        "expected_sql": "SELECT SUM(quantityOrdered) FROM orderdetails WHERE productCode = 'S10_1678';",
    },
    {
        "question": "How many employees report to employee number 1002?",
        "expected_sql": "SELECT COUNT(*) FROM employees WHERE reportsTo = 1002;",
    },
]


def _normalize(rows):
    """Turns a raw SQLDatabase result string/list into a comparable, order-insensitive set."""
    if isinstance(rows, str):
        if rows.strip().startswith("["):
            # MySQL DECIMAL/date columns come back as e.g. Decimal('1.23') or
            # datetime.date(2003, 1, 6), which ast.literal_eval can't parse
            # directly since they're constructor calls, not literals.
            unwrapped = re.sub(r"Decimal\('([^']+)'\)", r"\1", rows)
            unwrapped = re.sub(r"datetime\.date\(([^)]+)\)", r"(\1)", unwrapped)
            rows = ast.literal_eval(unwrapped)
        else:
            rows = [(rows,)]
    return sorted(str(row) for row in rows)


def run_eval():
    db = build_db()
    query_chain = build_query_chain(db)
    execute = QuerySQLDataBaseTool(db=db)

    passed = 0
    results = []

    for case in EVAL_SET:
        question = case["question"]
        expected_sql = case["expected_sql"]

        try:
            generated = query_chain.invoke(
                {"question": question, "top_k": 3, "messages": []}
            )["query"]
            _enforce_read_only(generated)
            generated_result = _normalize(execute.invoke(generated))
            expected_result = _normalize(execute.invoke(expected_sql))
            ok = generated_result == expected_result
        except Exception as exc:  # noqa: BLE001 - eval harness reports any failure as a fail row
            ok = False
            generated = f"<error: {exc}>"

        passed += ok
        results.append((question, generated, expected_sql, ok))

    print(f"\nExecution accuracy: {passed}/{len(EVAL_SET)} ({100 * passed / len(EVAL_SET):.0f}%)\n")
    for question, generated, expected_sql, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {question}")
        print(f"  generated: {generated}")
        print(f"  expected:  {expected_sql}\n")


if __name__ == "__main__":
    run_eval()
