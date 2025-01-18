# v0.2/backend/agent/blocks.py

import re
import json
import logging
from typing import Any, Dict
from database import SessionLocal, table_permissions
from sqlalchemy import text
import datetime
import openai

logger = logging.getLogger("agent")

###############################################################################
# Synonyms for item names
###############################################################################
NAME_SYNONYMS = {
    "tomato": "tomatoes",
    "tomatoe": "tomatoes",
    "tomatoes": "tomatoes",
    # ...
}

###############################################################################
# Synonyms for date offsets
###############################################################################
DATE_SYNONYMS = {
    "today": 0,
    "tomorrow": 1,
    "next week": 7,
    # Add more as needed...
}

###############################################################################
# Additional patterns for "in X days/weeks"
###############################################################################
DAYS_REGEX = re.compile(r"(?i)\bin\s+(\d+)\s+day(s)?\b")
WEEKS_REGEX = re.compile(r"(?i)\bin\s+(\d+)\s+week(s)?\b")

###############################################################################
# Utility to unify item names
###############################################################################
def dictionary_normalize_item_name(raw: str) -> str:
    lowered = raw.strip().lower()
    return NAME_SYNONYMS.get(lowered, lowered)

###############################################################################
# Attempt to extract quantity + unit from text
###############################################################################
def guess_quantity_and_unit_from_text(text: str) -> (float, str):
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(liter|liters|unit|units|bag|bags|piece|pieces)\b",
        text,
        re.IGNORECASE
    )
    if match:
        qty_str = match.group(1)
        unit_str = match.group(2)
        try:
            qty_val = float(qty_str)
        except:
            qty_val = 1.0
        return (qty_val, unit_str.lower())
    else:
        return (None, None)

###############################################################################
# Main date-guessing function
###############################################################################
def guess_expiration_date_from_text(text: str, current_dt_fn):
    """
    Looks for phrases like:
      - "expires next week"
      - "expiring tomorrow"
      - "expiry today"
      - "in 3 days"
      - "in 2 weeks"
    etc.
    Returns an ISO date string or None.
    """
    # 1) known synonyms "expires tomorrow", etc.
    pat_syn = re.search(r"(expires|expiring|expiry)\s+(today|tomorrow|next week)\b", text, re.IGNORECASE)
    if pat_syn:
        phrase = pat_syn.group(2).lower()
        offset_days = DATE_SYNONYMS.get(phrase, 0)
        now_dt = current_dt_fn() if current_dt_fn else datetime.datetime.utcnow()
        real_dt = now_dt + datetime.timedelta(days=offset_days)
        return real_dt.strftime("%Y-%m-%d")

    # 2) "in X days"
    pat_days = DAYS_REGEX.search(text)
    if pat_days:
        offset_days = int(pat_days.group(1))
        now_dt = current_dt_fn() if current_dt_fn else datetime.datetime.utcnow()
        real_dt = now_dt + datetime.timedelta(days=offset_days)
        return real_dt.strftime("%Y-%m-%d")

    # 3) "in X weeks"
    pat_weeks = WEEKS_REGEX.search(text)
    if pat_weeks:
        offset_weeks = int(pat_weeks.group(1))
        now_dt = current_dt_fn() if current_dt_fn else datetime.datetime.utcnow()
        real_dt = now_dt + datetime.timedelta(days=7 * offset_weeks)
        return real_dt.strftime("%Y-%m-%d")

    return None

###############################################################################
# handle_parse_block
###############################################################################
def handle_parse_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    parse_block: parse or unify user text + optional db_rows => produce a structured parsed_item.
    No DB changes here.
    """
    raw_text = args.get("raw_text", "")
    explanation = args.get("explanation", "")
    parsed_item = args.get("parsed_item", {}) or {}

    debug_info.append(f"[parse_block] raw_text={raw_text}, explanation={explanation}")

    from agent.global_store import TABLE_SCHEMAS, CURRENT_DATETIME_FN

    # unify synonyms if 'name' is present
    if "name" in parsed_item:
        old_name = parsed_item["name"]
        new_name = dictionary_normalize_item_name(old_name)
        parsed_item["name"] = new_name
        debug_info.append(f"[parse_block] Normalized name '{old_name}' => '{new_name}'")

    # guess quantity, unit from raw_text if not present
    if "quantity" not in parsed_item or "unit" not in parsed_item:
        (qty_guess, unit_guess) = guess_quantity_and_unit_from_text(raw_text)
        if qty_guess is not None and "quantity" not in parsed_item:
            parsed_item["quantity"] = qty_guess
        if unit_guess is not None and "unit" not in parsed_item:
            parsed_item["unit"] = unit_guess

    # guess expiration date
    if "expiration_date" not in parsed_item or not parsed_item.get("expiration_date"):
        dt_guess = guess_expiration_date_from_text(raw_text, CURRENT_DATETIME_FN)
        if dt_guess:
            parsed_item["expiration_date"] = dt_guess

    # fill missing columns if known
    target_table = task_memory.get("target_table", "")
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

    debug_info.append(f"[parse_block] final parsed_item => {parsed_item}")

    return {
        "success": True,
        "parsed_item": parsed_item,
        "explanation": explanation
    }

###############################################################################
# Case-insensitive WHERE
###############################################################################
def build_case_insensitive_where(where_str: str) -> str:
    pattern = r"(?i)WHERE\s+name\s*=\s*([\"'])(.*?)\1"
    replacement = r"WHERE LOWER(name)=LOWER(\1\2\1)"
    out = re.sub(pattern, replacement, where_str)
    return out

###############################################################################
# Quoting logic for SQL
###############################################################################
def quote_if_needed(val: str) -> str:
    if val is None:
        return "NULL"
    trimmed = val.strip()
    if (trimmed.startswith("'") and trimmed.endswith("'")) or trimmed.replace(".", "", 1).isdigit():
        return trimmed
    return f"'{trimmed}'"

###############################################################################
# handle_sql_block
###############################################################################
def handle_sql_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    table_name = args.get("table_name", "").strip()
    columns = args.get("columns", [])
    values = args.get("values", [])
    action_type = args.get("action_type", "").upper()
    explanation = args.get("explanation", "")
    where_clause = args.get("where_clause", "").strip()

    debug_info.append(f"[sql_block] table={table_name}, cols={columns}, vals={values}, action={action_type}, where={where_clause}")

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True  # or do some real check

    if action_type == "SELECT":
        if permission_mode == "ALWAYS_DENY":
            msg = f"[sql_block] SELECT on '{table_name}' => ALWAYS_DENY"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg, "success": False}

        col_list_str = "*"
        if columns:
            col_list_str = ", ".join(columns)
        sql_query = f"SELECT {col_list_str} FROM {table_name};"
        return run_select_query(sql_query, explanation, debug_info, task_memory)

    elif action_type == "INSERT":
        if permission_mode == "ALWAYS_DENY":
            msg = f"[sql_block] INSERT => table '{table_name}' => ALWAYS_DENY"
            debug_info.append(msg)
            return {"error": msg, "success": False}

        if len(columns) != len(values):
            msg = f"[sql_block] Mismatch => columns={columns}, values={values}"
            debug_info.append(msg)
            return {"error": msg, "success": False}

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
            return {"error": msg, "success": False}

        if not where_clause.upper().startswith("WHERE"):
            msg = f"[sql_block] {action_type} requested but no where_clause => not allowed!"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg, "success": False}

        ci_where = build_case_insensitive_where(where_clause)
        debug_info.append(f"[sql_block] where => {ci_where}")
        where_clause = ci_where

        if action_type == "UPDATE":
            if len(columns) != len(values):
                msg = f"[sql_block] mismatch col vs val => {columns} vs {values}"
                debug_info.append(msg)
                return {"error": msg, "success": False}
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
        return {"error": msg, "success": False}

###############################################################################
# SELECT / WRITE queries
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
        debug_info.append(f"[sql_block] got {len(rows_data)} row(s)")
        logger.info(f"[sql_block] success => SELECT '{sql_query}', rows={len(rows_data)}")
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[sql_block] select error => {error_msg}")
        logger.warning(f"[sql_block] SELECT error => {error_msg}")
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "success": False, "sql_query": sql_query}

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
        debug_info.append(f"[sql_block] rowcount={rowcount}")
        logger.info(f"[sql_block] success => WRITE '{sql_query}', rowcount={rowcount}")
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[sql_block] write error => {error_msg}")
        logger.warning(f"[sql_block] WRITE error => {error_msg}")
        db.rollback()
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "success": False, "sql_query": sql_query}

    return {
        "success": True,
        "rows_affected": rowcount,
        "explanation": explanation
    }

###############################################################################
# BATCH blocks
###############################################################################
def handle_batch_insert_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    table_name = args.get("table_name","").strip()
    rows_info = args.get("rows", [])
    explanation = args.get("explanation","")

    debug_info.append(f"[batch_insert] table={table_name}, #rows={len(rows_info)}")

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True

    if permission_mode == "ALWAYS_DENY":
        msg = f"[batch_insert_block] => table '{table_name}' => ALWAYS_DENY"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg, "success": False}

    inserted_count = 0
    error_msg = None
    db = SessionLocal()
    try:
        for row_data in rows_info:
            columns = row_data.get("columns", [])
            values = row_data.get("values", [])
            if len(columns) != len(values):
                raise ValueError(f"Mismatch => {columns} vs {values}")

            col_list_str = ", ".join(columns)
            val_list_str = ", ".join(quote_if_needed(v) for v in values)
            sql_query = f"INSERT INTO {table_name}({col_list_str}) VALUES({val_list_str});"
            debug_info.append(f"[batch_insert] => {sql_query}")
            result = db.execute(text(sql_query))
            rowcount = result.rowcount or 0
            inserted_count += rowcount

        db.commit()
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[batch_insert_block] error => {error_msg}")
        logger.warning(f"[batch_insert_block] error => {error_msg}")
        db.rollback()
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "success": False, "rows_inserted": inserted_count, "explanation": explanation}

    return {
        "success": True,
        "rows_inserted": inserted_count,
        "explanation": explanation
    }

def handle_batch_update_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    table_name = args.get("table_name","").strip()
    rows_info = args.get("rows", [])
    explanation = args.get("explanation","")

    debug_info.append(f"[batch_update] table={table_name}, #rows={len(rows_info)}")

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True

    if permission_mode == "ALWAYS_DENY":
        msg = f"[batch_update_block] => table '{table_name}' => ALWAYS_DENY"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg, "success": False}

    updated_count = 0
    error_msg = None
    db = SessionLocal()
    try:
        for row_data in rows_info:
            where_clause = row_data.get("where_clause","").strip()
            columns = row_data.get("columns", [])
            values = row_data.get("values", [])

            if not where_clause.upper().startswith("WHERE"):
                raise ValueError(f"Missing or invalid where_clause => {where_clause}")

            if len(columns) != len(values):
                raise ValueError(f"Mismatch => {columns} vs {values}")

            set_clauses = []
            for c, v in zip(columns, values):
                set_clauses.append(f"{c}={quote_if_needed(v)}")
            set_stmt = ", ".join(set_clauses)
            sql_query = f"UPDATE {table_name} SET {set_stmt} {where_clause};"
            debug_info.append(f"[batch_update] => {sql_query}")
            result = db.execute(text(sql_query))
            rowcount = result.rowcount or 0
            updated_count += rowcount

        db.commit()
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[batch_update_block] error => {error_msg}")
        logger.warning(f"[batch_update_block] error => {error_msg}")
        db.rollback()
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "success": False, "rows_affected": updated_count, "explanation": explanation}

    return {
        "success": True,
        "rows_affected": updated_count,
        "explanation": explanation
    }

def handle_batch_delete_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    table_name = args.get("table_name", "").strip()
    rows_info = args.get("rows", [])
    explanation = args.get("explanation", "")

    debug_info.append(f"[batch_delete_block] table={table_name}, #rows={len(rows_info)}")

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True

    if permission_mode == "ALWAYS_DENY":
        msg = f"[batch_delete_block] => table '{table_name}' => ALWAYS_DENY"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg, "success": False}

    deleted_count = 0
    error_msg = None
    db = SessionLocal()
    try:
        for row_data in rows_info:
            where_clause = row_data.get("where_clause", "").strip()
            if not where_clause.upper().startswith("WHERE"):
                raise ValueError(f"Invalid where_clause => {where_clause}")

            final_where = build_case_insensitive_where(where_clause)
            sql_query = f"DELETE FROM {table_name} {final_where};"
            debug_info.append(f"[batch_delete_block] => {sql_query}")
            result = db.execute(text(sql_query))
            rowcount = result.rowcount or 0
            deleted_count += rowcount

        db.commit()
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[batch_delete_block] error => {error_msg}")
        logger.warning(f"[batch_delete_block] error => {error_msg}")
        db.rollback()
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "success": False, "rows_affected": deleted_count, "explanation": explanation}

    return {
        "success": True,
        "rows_affected": deleted_count,
        "explanation": explanation
    }

###############################################################################
# handle_output_block
###############################################################################
def handle_output_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    The output_block is an older final step approach.
    Now we typically rely on reflect_block, but if used:
     - produce a final_answer from recent_sql_result or user-provided final_message
    """
    llm_message = args.get("final_message", "").strip()
    if not llm_message:
        llm_message = "(No final_message provided)"

    recent_sql = task_memory.get("recent_sql_result") or {}
    sql_error = recent_sql.get("error", "")
    row_affected = recent_sql.get("rows_affected", None)
    row_count = recent_sql.get("rows_count", None)
    rows_inserted = recent_sql.get("rows_inserted", None)

    if sql_error:
        final_msg = f"Sorry, an error occurred:\n{sql_error}"
        debug_info.append("[output_block] Overriding due to SQL error.")
        return {"final_answer": final_msg}

    if rows_inserted is not None:
        if rows_inserted == 0:
            final_msg = "No rows inserted. Possibly mismatch."
            return {"final_answer": final_msg}
        else:
            return {"final_answer": llm_message}

    if row_affected is not None:
        if row_affected == 0:
            final_msg = "No matching items to update/delete."
            return {"final_answer": final_msg}
        else:
            return {"final_answer": llm_message}

    if row_count is not None:
        if row_count == 0:
            final_msg = "No matching items found."
            return {"final_answer": final_msg}
        else:
            return {"final_answer": llm_message}

    return {"final_answer": llm_message}

###############################################################################
# handle_chat_block
###############################################################################
def handle_chat_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    chat_block: open-ended conversation or reasoning.
    Return => {"response_text":"some text"}.
    """
    user_prompt = args.get("user_prompt", "")
    context = args.get("context", "")
    explanation = "Chat-based reasoning"

    debug_info.append(f"[chat_block] user_prompt={user_prompt}, context={context}")

    model_name = task_memory.get("agent_model", "gpt-4-0613")
    client = openai.OpenAI(api_key=openai.api_key)

    chat_query = f"User Prompt: {user_prompt}\nContext: {context}\nRespond helpfully."

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": chat_query}],
            temperature=0.7
        )
        choice = resp.choices[0]
        final_text = choice.message.content.strip()
        debug_info.append(f"[chat_block] LLM response => {final_text}")

        return {
            "success": True,
            "response_text": final_text,
            "explanation": explanation
        }
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[chat_block] error => {error_msg}")
        return {
            "error": error_msg,
            "success": False,
            "response_text": "",
            "explanation": explanation
        }

###############################################################################
# handle_reflect_block
###############################################################################
def handle_reflect_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    reflect_block:
     - sees entire task_memory
     - can produce final_message, data_output, or additional_tasks
       for more steps.
    Example JSON:
      {
        "reasoning": "...some reflection...",
        "final_message": "User facing text if done",
        "data_output": {
          "rows":[...],
          "any_other_data":"..."
        },
        "additional_tasks":[
          {"block":"sql_block","description":"...",...}, ...
        ]
      }
    """
    reasoning = args.get("reasoning", "")
    final_message = args.get("final_message", None)
    data_output = args.get("data_output", None)
    additional_tasks = args.get("additional_tasks", None)

    debug_info.append(f"[reflect_block] reasoning => {reasoning}")
    if final_message:
        debug_info.append(f"[reflect_block] final_message => {final_message}")

    # Return structure so orchestrator can interpret
    return_dict = {
        "success": True,
        "reasoning": reasoning
    }
    if final_message:
        return_dict["final_message"] = final_message
    if data_output:
        return_dict["data_output"] = data_output
    if additional_tasks:
        return_dict["additional_tasks"] = additional_tasks

    return return_dict
