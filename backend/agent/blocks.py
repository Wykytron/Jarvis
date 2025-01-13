# backend/agent/blocks.py

import json
import logging
from typing import Any, Dict

from database import SessionLocal
from sqlalchemy import text

logger = logging.getLogger("agent")


def handle_sql_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    Actually run the SELECT query on our SQLite DB using SessionLocal.
    """
    sql_query = args.get("sql_query", "")
    explanation = args.get("explanation", "")

    # Only SELECT in this baby-step
    if not sql_query.strip().lower().startswith("select"):
        msg = f"Only SELECT queries allowed. Blocked => {sql_query}"
        logger.warning(f"[sql_block] {msg}")
        debug_info.append(f"[sql_block] blocked => {sql_query}")
        return {
            "error": msg,
            "sql_query": sql_query
        }

    db = SessionLocal()
    rows_data = []
    error_msg = None
    try:
        result = db.execute(text(sql_query))
        rows = result.fetchall()
        for row in rows:
            row_dict = dict(row._mapping)  # row._mapping in SQLAlchemy 1.4+
            rows_data.append(row_dict)

        debug_info.append(f"[sql_block] query='{sql_query}', #rows={len(rows_data)}")
        logger.info(f"[sql_block] success => query='{sql_query}', rows={len(rows_data)}")
    except Exception as e:
        error_msg = str(e)
        logger.warning(f"[sql_block] error={error_msg}")
        debug_info.append(f"[sql_block] error={error_msg}")
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "sql_query": sql_query}

    # Store in memory for other blocks to reference
    task_memory["last_sql_rows"] = rows_data

    return {
        "success": True,
        "rows_count": len(rows_data),
        "rows_data": rows_data,
        "explanation": explanation
    }


def handle_output_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    Summarize final result or produce final user-facing message.
    MUST return 'final_answer' in the dictionary so the orchestrator sets it.
    """
    # The LLM might pass an argument, e.g. final_message
    final_message = args.get("final_message", "").strip()

    # If the model didn't produce that argument, let's fallback
    if not final_message:
        final_message = "Here is the final answer:\n"

    # Check if we have rows from a prior SQL block
    last_sql_data = task_memory.get("last_sql_rows", [])
    if isinstance(last_sql_data, list) and len(last_sql_data) > 0:
        # format them
        debug_info.append(f"[output_block] We have {len(last_sql_data)} rows.")
        rows_json = json.dumps(last_sql_data, indent=2, default=str)
        final_message += f"\n\nFridge Items:\n{rows_json}"
    else:
        debug_info.append("[output_block] No rows_data found or empty.")
        # Possibly let final_message stand

    logger.info(f"[output_block] final_message={final_message[:50]}...")
    return {
        "final_answer": final_message
    }
