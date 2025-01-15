# agent/blocks.py

import re
import json
import logging
from typing import Any, Dict
from database import SessionLocal, table_permissions
from sqlalchemy import text
import datetime

logger = logging.getLogger("agent")

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
    # ...
}

def dictionary_normalize_item_name(raw: str) -> str:
    lowered = raw.strip().lower()
    return NAME_SYNONYMS.get(lowered, lowered)

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

def guess_expiration_date_from_text(text: str, current_dt_fn):
    match = re.search(r"(expires|expiring|expiry)\s+(today|tomorrow|next week)\b", text, re.IGNORECASE)
    if match:
        phrase = match.group(2).lower()
        offset_days = DATE_SYNONYMS.get(phrase, 0)
        now_dt = current_dt_fn() if current_dt_fn else datetime.datetime.utcnow()
        real_dt = now_dt + datetime.timedelta(days=offset_days)
        return real_dt.strftime("%Y-%m-%d")
    else:
        return None


def handle_parse_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    parse_block can parse raw_text from user, but also can unify 'db_rows' if provided.
    We store the result in parsed_item or we can store additional logic.
    """
    raw_text = args.get("raw_text", "")
    explanation = args.get("explanation", "")
    parsed_item = args.get("parsed_item", {}) or {}

    # Optionally, if we have db_rows in the parse_block arguments:
    db_rows = args.get("db_rows", [])  # new field if you let LLM produce it

    debug_info.append(f"[parse_block] raw_text={raw_text}, explanation={explanation}, #db_rows={len(db_rows)}")

    from agent.global_store import TABLE_SCHEMAS, CURRENT_DATETIME_FN

    # Possibly unify synonyms if 'name' in parsed_item
    if "name" in parsed_item:
        old_name = parsed_item["name"]
        new_name = dictionary_normalize_item_name(old_name)
        parsed_item["name"] = new_name
        debug_info.append(f"[parse_block] Normalized name from '{old_name}' => '{new_name}'")

    # If no 'quantity' or 'unit', guess from raw_text
    if "quantity" not in parsed_item or "unit" not in parsed_item:
        (qty_guess, unit_guess) = guess_quantity_and_unit_from_text(raw_text)
        if qty_guess is not None and "quantity" not in parsed_item:
            parsed_item["quantity"] = qty_guess
        if unit_guess is not None and "unit" not in parsed_item:
            parsed_item["unit"] = unit_guess

    # If no expiration_date, guess from raw_text
    if "expiration_date" not in parsed_item:
        dt_guess = guess_expiration_date_from_text(raw_text, CURRENT_DATETIME_FN)
        if dt_guess:
            parsed_item["expiration_date"] = dt_guess

    # If we want to unify partial DB data as well
    # e.g. fill missing columns in each row, or something advanced.
    # For now, we just store the db_rows in memory so the LLM knows it can use them.
    # Or we can do more advanced logic here.
    if db_rows:
        debug_info.append(f"[parse_block] We also have {len(db_rows)} row(s) from the DB to parse/unify.")
        # In a real scenario, you might unify each row with parsed_item
        # or do some advanced merging logic. For now, we just keep them in memory:
        task_memory["last_parsed_db_rows"] = db_rows

    # Also fill missing columns if target_table is known
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
    task_memory["parsed_item"] = parsed_item

    return {
        "success": True,
        "parsed_item": parsed_item,
        "db_rows": db_rows,
        "explanation": explanation
    }


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
    """
    The normal single SQL action: SELECT, INSERT, UPDATE, DELETE.
    Potentially merges parse_block data into columns/values if action_type in [INSERT,UPDATE].
    """
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

    parsed_item = task_memory.get("parsed_item", {})
    if parsed_item and action_type in ["INSERT","UPDATE"]:
        for col, val in parsed_item.items():
            if col not in columns:
                columns.append(col)
                val_str = "NULL" if val is None else str(val)
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

    elif action_type in ["UPDATE","DELETE"]:
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
    # Store the rows in memory so parse_block can read them
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

def handle_batch_insert_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    Insert multiple rows into a table in one go.
    """
    table_name = args.get("table_name","").strip()
    rows_info = args.get("rows", [])
    explanation = args.get("explanation","")

    debug_info.append(f"[batch_insert] table={table_name}, #rows={len(rows_info)}")

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True

    if permission_mode == "ALWAYS_DENY":
        msg = f"[batch_insert_block] INSERT => table '{table_name}' => ALWAYS_DENY"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}

    if permission_mode == "REQUIRE_USER" and not user_permission:
        msg = f"[batch_insert_block] Write to '{table_name}' => not granted"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}

    inserted_count = 0
    error_msg = None
    db = SessionLocal()
    try:
        for row_data in rows_info:
            columns = row_data.get("columns", [])
            values = row_data.get("values", [])

            if len(columns) != len(values):
                raise ValueError(f"Mismatch in columns vs. values => {columns} vs. {values}")

            col_list_str = ", ".join(columns)
            val_list_str = ", ".join(quote_if_needed(v) for v in values)
            sql_query = f"INSERT INTO {table_name} ({col_list_str}) VALUES ({val_list_str});"
            debug_info.append(f"[batch_insert] running => {sql_query}")

            result = db.execute(text(sql_query))
            rowcount = result.rowcount or 0
            inserted_count += rowcount

        db.commit()
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[batch_insert] error => {error_msg}")
        logger.warning(f"[batch_insert_block] error => {error_msg}")
        db.rollback()
    finally:
        db.close()

    if error_msg:
        return {"error": error_msg, "rows_inserted": inserted_count, "explanation": explanation}

    return {
        "success": True,
        "rows_inserted": inserted_count,
        "explanation": explanation
    }

def handle_batch_update_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    """
    Similar to batch_insert_block, but for multiple UPDATE statements in one call.

    {
      "table_name": "fridge_items",
      "rows": [
        {
          "where_clause": "WHERE id=5",
          "columns": ["quantity","expiration_date"],
          "values": ["3","2025-05-10"]
        },
        ...
      ],
      "explanation": "some reason"
    }
    """
    table_name = args.get("table_name","").strip()
    rows_info = args.get("rows", [])
    explanation = args.get("explanation","")

    debug_info.append(f"[batch_update] table={table_name}, #rows={len(rows_info)}")

    permission_mode = table_permissions.get(table_name, "ALWAYS_DENY")
    user_permission = True  # or some real check

    if permission_mode == "ALWAYS_DENY":
        msg = f"[batch_update_block] => table '{table_name}' => ALWAYS_DENY"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}

    if permission_mode == "REQUIRE_USER" and not user_permission:
        msg = f"[batch_update_block] => not granted for '{table_name}'"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}

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
                raise ValueError(f"Mismatch => columns={columns}, values={values}")

            set_clauses = []
            for c, v in zip(columns, values):
                set_clauses.append(f"{c}={quote_if_needed(v)}")
            set_stmt = ", ".join(set_clauses)

            sql_query = f"UPDATE {table_name} SET {set_stmt} {where_clause};"
            debug_info.append(f"[batch_update] running => {sql_query}")

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
        return {"error": error_msg, "rows_affected": updated_count, "explanation": explanation}

    return {
        "success": True,
        "rows_affected": updated_count,
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
    rows_inserted = last_sql_result.get("rows_inserted", None)

    if sql_error:
        final_msg = f"Sorry, an error occurred with your request:\n{sql_error}"
        debug_info.append("[output_block] Overriding LLM message due to SQL error.")
        return {"final_answer": final_msg}

    if rows_inserted is not None:
        if rows_inserted == 0:
            final_msg = "No rows were inserted. Possibly data mismatch or user canceled."
            debug_info.append("[output_block] Overriding LLM => no rows inserted.")
            return {"final_answer": final_msg}
        else:
            debug_info.append(f"[output_block] Inserted {rows_inserted} => letting LLM message stand.")
            return {"final_answer": llm_message}

    if row_affected is not None:
        if row_affected == 0:
            final_msg = (
                "No matching items were found to update/delete. "
                "If you expected a change, please check the name."
            )
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

    debug_info.append("[output_block] letting LLM stand => no row_affected, row_count, or rows_inserted.")
    return {"final_answer": llm_message}
