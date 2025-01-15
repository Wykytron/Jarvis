# agent/blocks.py

import re
import json
import logging
from typing import Any, Dict
from database import SessionLocal, table_permissions
from sqlalchemy import text
import datetime

logger = logging.getLogger("agent")

###############################################################################
# Some synonyms or simple lookups
###############################################################################
NAME_SYNONYMS = {
    "tomato": "tomatoes",
    "tomatoe": "tomatoes",
    "tomatoes": "tomatoes",
    # ...
}

DATE_SYNONYMS = {
    "today": 0,
    "tomorrow": 1,
    "next week": 7,
    # etc.
}

###############################################################################
# Simple normalizers
###############################################################################
def dictionary_normalize_item_name(raw: str) -> str:
    lowered = raw.strip().lower()
    return NAME_SYNONYMS.get(lowered, lowered)

def guess_quantity_and_unit_from_text(text: str) -> (float, str):
    """
    Very naive approach:
    1) Look for pattern like: "(\d+(\.\d+)?)\s*(liter|liters|unit|units|bag|bags|piece|pieces?)"
    2) If found, return that quantity + unit
    3) else default to (None, None)
    """
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(liter|liters|unit|units|bag|bags|piece|pieces)\b",
        text,
        re.IGNORECASE
    )
    if match:
        qty_str = match.group(1)  # e.g. "1" or "1.0"
        unit_str = match.group(2) # e.g. "liter"
        try:
            qty_val = float(qty_str)
        except:
            qty_val = 1.0
        return (qty_val, unit_str.lower())
    else:
        return (None, None)

def guess_expiration_date_from_text(text: str, current_dt_fn):
    """
    If we find "expires next week", "expires tomorrow", etc.
    Then do a date offset. If none found, return None.
    """
    match = re.search(r"(expires|expiring|expiry)\s+(today|tomorrow|next week)\b", text, re.IGNORECASE)
    if match:
        phrase = match.group(2).lower()  # e.g. "next week"
        offset_days = DATE_SYNONYMS.get(phrase, 0)
        if current_dt_fn:
            now_dt = current_dt_fn()  # <--- this was throwing
        else:
            now_dt = datetime.datetime.utcnow()  # fallback
        real_dt = now_dt + datetime.timedelta(days=offset_days)
        return real_dt.strftime("%Y-%m-%d")
    else:
        return None

###############################################################################
# handle_parse_block
###############################################################################
def handle_parse_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    raw_text = args.get("raw_text", "")
    explanation = args.get("explanation", "")
    parsed_item = args.get("parsed_item", {}) or {}

    debug_info.append(f"[parse_block] raw_text={raw_text}, explanation={explanation}")

    # 1) Possibly handle synonyms for 'name'
    if "name" in parsed_item:
        old_name = parsed_item["name"]
        new_name = dictionary_normalize_item_name(old_name)
        parsed_item["name"] = new_name
        debug_info.append(f"[parse_block] Normalized name from '{old_name}' => '{new_name}'")

    from agent.global_store import TABLE_SCHEMAS, CURRENT_DATETIME_FN

    # 2) Attempt to guess quantity / unit if missing
    if "quantity" not in parsed_item or "unit" not in parsed_item:
        (qty_guess, unit_guess) = guess_quantity_and_unit_from_text(raw_text)
        if qty_guess is not None and "quantity" not in parsed_item:
            parsed_item["quantity"] = qty_guess
        if unit_guess is not None and "unit" not in parsed_item:
            parsed_item["unit"] = unit_guess

    # 3) Attempt to guess expiration_date if missing
    if "expiration_date" not in parsed_item:
        dt_guess = guess_expiration_date_from_text(raw_text, CURRENT_DATETIME_FN)
        if dt_guess:
            parsed_item["expiration_date"] = dt_guess

    # 4) If we want to fill missing columns automatically for target_table
    target_table = task_memory.get("target_table", "")  # might be empty
    col_list = TABLE_SCHEMAS.get(target_table, [])
    debug_info.append(f"[parse_block] target_table => {target_table}, col_list => {col_list}")

    for c in col_list:
        if c not in parsed_item:
            if c == "quantity":
                parsed_item[c] = 1.0
            elif c == "unit":
                parsed_item[c] = "unit"
            elif c == "expiration_date":
                parsed_item[c] = None
            elif c == "category":
                parsed_item[c] = "misc"
            # etc.

    debug_info.append(f"[parse_block] final parsed_item => {parsed_item}")

    # store in task_memory
    task_memory["parsed_item"] = parsed_item
    return {
        "success": True,
        "parsed_item": parsed_item,
        "explanation": explanation
    }

###############################################################################
# SQL logic, unchanged
###############################################################################
def build_case_insensitive_where(where_str: str) -> str:
    pattern = r"(?i)WHERE\s+name\s*=\s*([\"'])(.*?)\1"
    replacement = r"WHERE LOWER(name)=LOWER(\1\2\1)"
    out = re.sub(pattern, replacement, where_str)
    return out

def quote_if_needed(val: str) -> str:
    trimmed = val.strip()
    if (trimmed.startswith("'") and trimmed.endswith("'")) or trimmed.replace(".", "", 1).isdigit():
        return trimmed
    return f"'{trimmed}'"

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

    # Merge parse_block data if present
    parsed_item = task_memory.get("parsed_item", {})
    if parsed_item and action_type in ["INSERT", "UPDATE"]:
        for col, val in parsed_item.items():
            val_str = "NULL" if val is None else str(val)
            if col not in columns:
                columns.append(col)
                values.append(val_str)
        debug_info.append(f"[sql_block] after merging parse_item => columns={columns}, values={values}")

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True

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

def handle_output_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    llm_message = args.get("final_message", "").strip()
    if not llm_message:
        llm_message = "(No final_message provided by LLM)"

    last_sql_result = task_memory.get("last_sql_block_result", {})
    sql_error = last_sql_result.get("error", "")
    row_affected = last_sql_result.get("rows_affected", None)
    row_count = last_sql_result.get("rows_count", None)

    if sql_error:
        final_msg = f"Sorry, an error occurred with your request:\n{sql_error}"
        debug_info.append("[output_block] Overriding LLM message due to SQL error.")
        return {"final_answer": final_msg}

    if row_affected is not None:
        if row_affected == 0:
            final_msg = "No matching items were found to update/delete. If you expected a change, please check the name."
            debug_info.append("[output_block] Overriding LLM => no row changed.")
            return {"final_answer": final_msg}
        else:
            debug_info.append("[output_block] row_affected>0 => letting LLM message stand.")
            return {"final_answer": llm_message}

    if row_count is not None:
        if row_count == 0:
            final_msg = "No matching items found."
            debug_info.append("[output_block] SELECT => 0 => overriding.")
            return {"final_answer": final_msg}
        else:
            debug_info.append("[output_block] SELECT => letting LLM stand.")
            return {"final_answer": llm_message}

    debug_info.append("[output_block] letting LLM stand => no row_affected or row_count.")
    return {"final_answer": llm_message}
