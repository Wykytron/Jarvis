# blocks.py

import re
import json
import logging
from typing import Any, Dict

from database import SessionLocal, table_permissions
from sqlalchemy import text

logger = logging.getLogger("agent")

###############################################################################
# Optional synonyms / dictionary
###############################################################################
NAME_SYNONYMS = {
    "tomato": "tomatoes",
    "tomatoe": "tomatoes",
    "tomatoes": "tomatoes",
    # ...
}


def dictionary_normalize_item_name(raw: str) -> str:
    """Example dictionary-based normalization."""
    lowered = raw.strip().lower()
    return NAME_SYNONYMS.get(lowered, lowered)


###############################################################################
# 1) parse_block
###############################################################################
def handle_parse_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    raw_text = args.get("raw_text", "")
    explanation = args.get("explanation", "")
    parsed_item = args.get("parsed_item", {}) or {}

    debug_info.append(f"[parse_block] raw_text={raw_text}, explanation={explanation}")

    # Example: unify name if provided
    if "name" in parsed_item:
        old_name = parsed_item["name"]
        new_name = dictionary_normalize_item_name(old_name)
        parsed_item["name"] = new_name
        debug_info.append(f"[parse_block] Normalized name from '{old_name}' => '{new_name}'")

    task_memory["parsed_item"] = parsed_item
    return {
        "success": True,
        "parsed_item": parsed_item,
        "explanation": explanation
    }


###############################################################################
# 2) build_case_insensitive_where
###############################################################################
def build_case_insensitive_where(where_str: str) -> str:
    """
    Convert "WHERE name='XYZ'" to "WHERE LOWER(name)=LOWER('XYZ')"
    with correct parenthesis. 
    We'll also handle the user possibly using double quotes, e.g. WHERE name="Oranges".
    """

    # Regex approach: look for: WHERE name= 'something' (with optional spaces, single or double quotes)
    # Then rewrite to: WHERE LOWER(name)=LOWER('something')
    pattern = r"(?i)WHERE\s+name\s*=\s*([\"'])(.*?)\1"
    # Explanation:
    #  - (?i) for case-insensitive
    #  - WHERE\s+name\s*=: basic pattern for "WHERE name="
    #  - ([\"']): group 1 is the capturing quote, single or double
    #  - (.*?): group 2 is the actual item name inside the quotes
    #  - \1 is a backreference to the same quote symbol
    replacement = r"WHERE LOWER(name)=LOWER(\1\2\1)"

    # e.g. "WHERE name='tomatoes'" => "WHERE LOWER(name)=LOWER('tomatoes')"
    out = re.sub(pattern, replacement, where_str)
    return out


###############################################################################
# 3) quote_if_needed
###############################################################################
def quote_if_needed(val: str) -> str:
    trimmed = val.strip()
    # if numeric or already single-quoted => return as-is
    if (trimmed.startswith("'") and trimmed.endswith("'")) or trimmed.replace(".", "", 1).isdigit():
        return trimmed
    # else => wrap in single quotes
    return f"'{trimmed}'"


###############################################################################
# 4) handle_sql_block
###############################################################################
def handle_sql_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    table_name = args.get("table_name", "").strip()
    columns = args.get("columns", [])
    values = args.get("values", [])
    action_type = args.get("action_type", "").upper()
    explanation = args.get("explanation", "")
    where_clause = args.get("where_clause", "").strip()

    debug_info.append(
        f"[sql_block] user gave => table={table_name}, cols={columns}, vals={values}, "
        f"action={action_type}, where={where_clause}"
    )

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True  # For a simple step, assume user is okay with writes

    # SELECT
    if action_type == "SELECT":
        if permission_mode == "ALWAYS_DENY":
            msg = f"[sql_block] SELECT on '{table_name}' => ALWAYS_DENY"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        col_list_str = "*"
        if columns:
            col_list_str = ", ".join(columns)
        sql_query = f"SELECT {col_list_str} FROM {table_name};"
        return run_select_query(sql_query, explanation, debug_info, task_memory)

    # INSERT
    elif action_type == "INSERT":
        if permission_mode == "ALWAYS_DENY":
            msg = f"[sql_block] INSERT => table '{table_name}' => ALWAYS_DENY"
            debug_info.append(msg)
            return {"error": msg}

        if len(columns) != len(values):
            msg = f"[sql_block] Mismatch => columns={columns}, values={values}"
            debug_info.append(msg)
            return {"error": msg}

        col_list_str = ", ".join(columns)
        val_list_str = ", ".join(quote_if_needed(v) for v in values)
        sql_query = f"INSERT INTO {table_name}({col_list_str}) VALUES({val_list_str});"

        debug_info.append(f"[sql_block] final INSERT => {sql_query}")
        return run_write_query(sql_query, explanation, debug_info)

    # UPDATE / DELETE
    elif action_type in ["UPDATE", "DELETE"]:
        if permission_mode == "ALWAYS_DENY":
            msg = f"[sql_block] Writes to '{table_name}' => ALWAYS_DENY"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        if permission_mode == "REQUIRE_USER" and not user_permission:
            msg = f"[sql_block] Write to '{table_name}' => not granted"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        if not where_clause.upper().startswith("WHERE"):
            msg = f"[sql_block] {action_type} requested but no where_clause => not allowed!"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        # Transform => case-insensitive
        ci_where = build_case_insensitive_where(where_clause)
        debug_info.append(f"[sql_block] transformed where => {ci_where}")
        where_clause = ci_where

        if action_type == "UPDATE":
            if len(columns) != len(values):
                msg = f"[sql_block] mismatch col vs val => {columns} vs {values}"
                debug_info.append(msg)
                return {"error": msg}

            set_clauses = []
            for c, v in zip(columns, values):
                set_clauses.append(f"{c}={quote_if_needed(v)}")

            set_stmt = ", ".join(set_clauses)
            sql_query = f"UPDATE {table_name} SET {set_stmt} {where_clause};"
            debug_info.append(f"[sql_block] final UPDATE => {sql_query}")
            return run_write_query(sql_query, explanation, debug_info)

        elif action_type == "DELETE":
            sql_query = f"DELETE FROM {table_name} {where_clause};"
            debug_info.append(f"[sql_block] final DELETE => {sql_query}")
            return run_write_query(sql_query, explanation, debug_info)

    else:
        msg = f"[sql_block] unrecognized action_type={action_type}"
        debug_info.append(msg)
        return {"error": msg}


###############################################################################
# 5) run_select_query
###############################################################################
def run_select_query(sql_query: str, explanation: str, debug_info: list, task_memory: dict) -> dict:
    db = SessionLocal()
    rows_data = []
    error_msg = None
    try:
        debug_info.append(f"[sql_block] Running SELECT => {sql_query}")
        result = db.execute(text(sql_query))
        all_rows = result.fetchall()
        for row in all_rows:
            row_dict = dict(row._mapping)
            rows_data.append(row_dict)

        debug_info.append(f"[sql_block] SELECT => got {len(rows_data)} row(s)")
        logger.info(f"[sql_block] success => SELECT '{sql_query}', rows={len(rows_data)}")

    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[sql_block] select error => {error_msg}")
        logger.warning(f"[sql_block] SELECT error => {error_msg}")
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "sql_query": sql_query}
    task_memory["last_sql_rows"] = rows_data
    return {
        "success": True,
        "rows_data": rows_data,
        "explanation": explanation,
        "rows_count": len(rows_data)
    }


###############################################################################
# 6) run_write_query
###############################################################################
def run_write_query(sql_query: str, explanation: str, debug_info: list) -> dict:
    db = SessionLocal()
    error_msg = None
    rowcount = 0
    try:
        debug_info.append(f"[sql_block] Running WRITE => {sql_query}")
        result = db.execute(text(sql_query))
        rowcount = result.rowcount or 0
        db.commit()

        debug_info.append(f"[sql_block] WRITE => rowcount={rowcount}")
        logger.info(f"[sql_block] success => WRITE '{sql_query}', rowcount={rowcount}")

    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[sql_block] write error => {error_msg}")
        logger.warning(f"[sql_block] WRITE error => {error_msg}")
        db.rollback()
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "sql_query": sql_query}
    return {
        "success": True,
        "rows_affected": rowcount,
        "explanation": explanation
    }


###############################################################################
# 7) handle_output_block
###############################################################################
def handle_output_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    Summarize final result or produce user-facing text.
    If the LLM says "Success" but rowcount=0 or error, we override message.
    """
    llm_message = args.get("final_message", "").strip()
    if not llm_message:
        llm_message = "(No final_message provided by LLM)"

    last_sql_result = task_memory.get("last_sql_block_result", {})
    sql_error = last_sql_result.get("error", "")
    row_affected = last_sql_result.get("rows_affected", None)
    row_count = last_sql_result.get("rows_count", None)

    # 1) error?
    if sql_error:
        # override with actual error message
        final_msg = f"Sorry, an error occurred with your request:\n{sql_error}"
        debug_info.append("[output_block] Overriding LLM message due to SQL error.")
        return {"final_answer": final_msg}

    # 2) If row_affected=0 => override
    if row_affected is not None:
        if row_affected == 0:
            final_msg = (
                "No matching items were found to update/delete. If you expected a change, please check the name."
            )
            debug_info.append("[output_block] Overriding LLM message => no row affected.")
            return {"final_answer": final_msg}
        else:
            debug_info.append("[output_block] Write success => letting LLM message stand.")
            return {"final_answer": llm_message}

    # 3) If row_count for SELECT
    if row_count is not None:
        if row_count == 0:
            final_msg = "No matching items found."
            debug_info.append("[output_block] SELECT => 0 rows => overriding message.")
            return {"final_answer": final_msg}
        else:
            debug_info.append("[output_block] SELECT => letting LLM message stand.")
            return {"final_answer": llm_message}

    # 4) Otherwise let LLM message stand
    debug_info.append("[output_block] letting LLM message stand.")
    return {"final_answer": llm_message}
