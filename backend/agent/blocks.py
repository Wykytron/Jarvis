# blocks.py

import json
import logging
from typing import Any, Dict

from database import SessionLocal, table_permissions
from sqlalchemy import text

logger = logging.getLogger("agent")

def handle_parse_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    raw_text = args.get("raw_text", "")
    explanation = args.get("explanation", "")
    parsed_item = args.get("parsed_item", {})

    debug_info.append(f"[parse_block] raw_text={raw_text}, explanation={explanation}")

    task_memory["parsed_item"] = parsed_item
    return {
        "success": True,
        "parsed_item": parsed_item,
        "explanation": explanation
    }

def handle_sql_block(args: Dict[str, Any], task_memory: dict, debug_info: list) -> dict:
    table_name = args.get("table_name", "").strip()
    columns = args.get("columns", [])
    values = args.get("values", [])
    action_type = args.get("action_type", "").upper()
    explanation = args.get("explanation", "")

    debug_info.append(f"[sql_block] user gave => table={table_name}, cols={columns}, vals={values}, action={action_type}")
    debug_info.append(f"[sql_block] explanation={explanation}")

    if table_name == "fridge_items":
        columns, values = fix_fridge_columns_and_values(columns, values, debug_info)

    # auto-quote
    quoted_vals = []
    for v in values:
        v_str = str(v).strip()
        if v_str.startswith("'") and v_str.endswith("'"):
            quoted_vals.append(v_str)
        elif v_str.replace(".", "", 1).isdigit():
            quoted_vals.append(v_str)
        else:
            quoted_vals.append(f"'{v_str}'")
    values = quoted_vals

    if not table_name:
        msg = "[sql_block] No table_name provided"
        debug_info.append(msg)
        return {"error": msg}

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

    elif action_type in ["INSERT", "UPDATE", "DELETE"]:
        if permission_mode == "ALWAYS_DENY":
            msg = f"[sql_block] Writes to '{table_name}' => ALWAYS_DENY"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}
        if permission_mode == "REQUIRE_USER" and not user_permission:
            msg = f"[sql_block] Write to '{table_name}' => require user permission not granted"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        if action_type == "INSERT":
            if len(columns) != len(values):
                msg = f"[sql_block] Mismatch col vs. val => {columns} vs. {values}"
                debug_info.append(msg)
                logger.warning(msg)
                return {"error": msg}

            col_list_str = ", ".join(columns)
            val_list_str = ", ".join(values)
            sql_query = f"INSERT INTO {table_name}({col_list_str}) VALUES({val_list_str});"
            debug_info.append(f"[sql_block] final insert => {sql_query}")
            return run_write_query(sql_query, explanation, debug_info)

        elif action_type == "UPDATE":
            return {"error":"UPDATE not implemented yet"}

        elif action_type == "DELETE":
            return {"error":"DELETE not implemented yet"}

    else:
        msg = f"[sql_block] unknown action_type={action_type}"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}

def fix_fridge_columns_and_values(cols, vals, debug_info):
    required = ["name","quantity","unit","expiration_date","category"]
    new_cols = []
    for c in cols:
        c_lower = c.lower().strip()
        if c_lower in ("item_name","food_name"):
            new_cols.append("name")
        else:
            new_cols.append(c.strip())

    col_val_map = {}
    for c, v in zip(new_cols, vals):
        col_val_map[c.lower()] = v

    final_cols = []
    final_vals = []
    for r in required:
        if r in col_val_map:
            final_cols.append(r)
            final_vals.append(col_val_map[r])
        else:
            final_cols.append(r)
            if r == "quantity":
                final_vals.append("1")
            elif r == "unit":
                final_vals.append("'unit'")
            elif r == "expiration_date":
                final_vals.append("'2025-12-31'")
            elif r == "category":
                final_vals.append("'misc'")
            else:
                final_vals.append("'unknown'")

    debug_info.append(f"[fix_fridge] final cols={final_cols}, vals={final_vals}")
    return (final_cols, final_vals)

def run_select_query(sql_query: str, explanation: str, debug_info: list, task_memory: dict) -> dict:
    db = SessionLocal()
    rows_data = []
    error_msg = None
    try:
        debug_info.append(f"[sql_block] Running SELECT => {sql_query}")
        logger.info(f"[sql_block] Running SELECT => {sql_query}")
        result = db.execute(text(sql_query))
        all_rows = result.fetchall()
        for r in all_rows:
            row_dict = dict(r._mapping)
            rows_data.append(row_dict)
        debug_info.append(f"[sql_block] SELECT => got {len(rows_data)} rows")
        logger.info(f"[sql_block] success => SELECT '{sql_query}', rows={len(rows_data)}")
    except Exception as e:
        error_msg = str(e)
        debug_info.append(f"[sql_block] error => {error_msg}")
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
        logger.info(f"[sql_block] Running WRITE => {sql_query}")
        result = db.execute(text(sql_query))
        rowcount = result.rowcount if result.rowcount else 0
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
    final_message = args.get("final_message","").strip()
    if not final_message:
        final_message = "(No final_message in output_block)"

    last_result = task_memory.get("last_sql_block_result", {})
    # if SELECT success => we can override error disclaimers
    if last_result.get("rows_data") and len(last_result["rows_data"])>0:
        if last_result.get("error") is None:
            if "error" in final_message.lower():
                row_data = last_result["rows_data"]
                final_message = "Here are your fridge items:\n"
                for i,r in enumerate(row_data,1):
                    final_message += f"{i}. {r}\n"

    # if INSERT success => override negative disclaimers
    if "rows_affected" in last_result and last_result["rows_affected"]>0:
        if "error" in final_message.lower():
            final_message = "Your item was successfully inserted into the fridge!"

    debug_info.append(f"[output_block] final_message => {final_message}")
    logger.info(f"[output_block] final_message => {final_message}")
    return {"final_answer": final_message}
