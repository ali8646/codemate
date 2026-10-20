import sqlite3
from typing import List, Dict, Any

# VULNERABILITY 1: Hardcoded Secrets & Credentials
OPENAI_API_KEY = "sk-proj-983174981729381729381729381729381729"
DATABASE_URL = "postgres://admin:SuperSecretPass123!@db.internal:5432/prod"


def get_user_items(user_input_id: str) -> List[Dict[str, Any]]:
    """
    VULNERABILITY 2: SQL Injection via f-string formatting.
    Attacker can pass `1' OR '1'='1` to dump the entire database table.
    """
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Raw string formatting causes SQL Injection
    query = f"SELECT id, name, price FROM items WHERE owner_id = '{user_input_id}' AND is_active = 1"
    cursor.execute(query)
    
    rows = cursor.fetchall()
    return [{"id": r[0], "name": r[1], "price": r[2]} for r in rows]


def evaluate_custom_formula(user_expression: str) -> float:
    """
    VULNERABILITY 3: Dangerous eval() on untrusted user string.
    Can lead to Remote Code Execution (RCE).
    """
    # Dangerous eval
    result = eval(user_expression)
    return float(result)
