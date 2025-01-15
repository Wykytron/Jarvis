# agent/orchestrator.py

import json
import os
import logging
import openai

from openai import OpenAI

from .schemas import ALL_FUNCTION_SCHEMAS, PlanTasksArguments
from .blocks import (
    handle_parse_block,
    handle_sql_block,
    handle_output_block,
    handle_batch_insert_block,
    handle_batch_update_block  # <-- NEW: import the new batch_update handler
)
from agent.global_store import TABLE_SCHEMAS, CURRENT_DATETIME_FN

logger = logging.getLogger("agent")

def call_openai_plan(user_request: str, debug_info: list, task_memory: dict) -> PlanTasksArguments:
    """
    Calls GPT with plan instructions to produce a short JSON plan { tasks: [...] }.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plan_path = os.path.join(base_dir, "prompts", "plan_prompt.md")
    with open(plan_path, "r", encoding="utf-8") as f:
        plan_instructions = f.read()

    model_name = task_memory.get("agent_model", "gpt-4-0613")

    messages = [
        {"role": "system", "content": plan_instructions},
        {"role": "user", "content": f"USER REQUEST: {user_request}"}
    ]

    logger.info(f"[call_openai_plan] user_request='{user_request}'")
    debug_info.append(f"[plan] user_request='{user_request}'")

    client = OpenAI(api_key=openai.api_key)
    resp = client.chat.completions.create(
        model=model_name,
        messages=messages,
        functions=[fn for fn in ALL_FUNCTION_SCHEMAS if fn["name"] == "plan_tasks"],
        function_call="auto",
        temperature=0.7
    )

    logger.info(f"[call_openai_plan] raw response => {resp}")
    debug_info.append(f"[plan] raw response => {resp}")

    choice = resp.choices[0]
    fn_call = choice.message.function_call
    if fn_call:
        fn_args_str = fn_call.arguments
        debug_info.append(f"[plan] function_call arguments => {fn_args_str}")
        try:
            data = json.loads(fn_args_str)
            plan_args = PlanTasksArguments(**data)
            logger.info(f"[call_openai_plan] Final plan => {plan_args.tasks}")
            debug_info.append(f"[plan] tasks => {plan_args.tasks}")
            return plan_args
        except Exception as e:
            debug_info.append(f"[plan] parse error => {e}")
            logger.warning(f"[call_openai_plan] parse error => {e}")
            return PlanTasksArguments(tasks=[])
    else:
        # fallback parse if no function_call
        content_str = choice.message.content or ""
        debug_info.append(f"[plan] no function_call, content => {content_str}")
        try:
            candidate = json.loads(content_str)
            if "name" in candidate and "arguments" in candidate:
                plan_args_data = candidate["arguments"]
                plan_args = PlanTasksArguments(**plan_args_data)
                logger.info(f"[call_openai_plan] Final plan => {plan_args.tasks}")
                debug_info.append(f"[plan] tasks => {plan_args.tasks}")
                return plan_args
        except:
            pass
        logger.info("[call_openai_plan] no tasks returned.")
        return PlanTasksArguments(tasks=[])


def build_system_prompt_for_block(block_name: str, block_description: str, task_memory: dict) -> str:
    """
    Provide specialized instructions for each block.
    Now we also handle 'batch_insert_block' and 'batch_update_block' with short schema notes.
    And mention parse_block can parse DB rows if needed.
    """
    from agent.global_store import TABLE_SCHEMAS, CURRENT_DATETIME_FN

    if block_name == "parse_block":
        user_req = task_memory.get("original_user_input", "")
        date_str = ""
        if CURRENT_DATETIME_FN:
            dt_now = CURRENT_DATETIME_FN()
            date_str = f"Current date/time => {dt_now.isoformat()}\n"

        target_table = task_memory.get("target_table", "(none)")
        table_cols = TABLE_SCHEMAS.get(target_table, [])
        col_list_str = ", ".join(table_cols)

        last_rows = task_memory.get("last_sql_rows", [])
        last_rows_str = json.dumps(last_rows, default=str)

        return (
            "You are the 'parse_block'. You can parse or unify user text AND/OR data from the DB.\n"
            "If 'db_rows' is provided, unify or fill columns. If user says '1 liter', parse quantity=1.0, unit='liter'.\n"
            "If user says 'expires next week', convert to a date offset.\n"
            "Return function_call => { raw_text:'...', explanation:'...', db_rows:..., parsed_item:{...} }.\n\n"
            f"{date_str}"
            f"Target table => {target_table}\n"
            f"Columns => {col_list_str}\n"
            f"last_sql_rows => {last_rows_str}\n"
            f"user_input => {user_req}\n"
            f"task_memory => {json.dumps(task_memory, default=str)}"
        )

    elif block_name == "sql_block":
        db_schema_str = (
            "Here is your DB schema:\n"
            "- fridge_items:\n"
            "   columns => [id, name, quantity, unit, expiration_date, category] (ALWAYS_ALLOW)\n"
            "- shopping_items:\n"
            "   columns => [id, name, desired_quantity, unit, purchased] (ALWAYS_ALLOW)\n"
            "- invoices:\n"
            "   columns => [id, date, total_amount, store_name] (REQUIRE_USER)\n"
            "- invoice_items:\n"
            "   columns => [id, invoice_id, name, quantity, price_per_unit] (REQUIRE_USER)\n"
            "- monthly_spendings:\n"
            "   columns => [id, year_month, total_spent] (ALWAYS_DENY)\n"
        )
        return (
            "You are 'sql_block'. You produce JSON => { table_name, columns, values, action_type, explanation, [where_clause] }.\n"
            "If user says 'delete X', do DELETE with a proper where_clause.\n"
            "If user says 'update X', do UPDATE with a proper where_clause.\n"
            "You MUST always provide a where_clause if action_type=DELETE or UPDATE.\n\n"
            + db_schema_str
            + "\n"
            + "task_memory => "
            + json.dumps(task_memory, default=str)
        )

    elif block_name == "output_block":
        last_sql = task_memory.get("last_sql_block_result", {})
        return (
            "You are 'output_block'. Summarize or finalize the answer.\n"
            "Override if rowcount=0 => say 'No items found or changed', or if there's an error.\n"
            f"last_sql_block_result => {json.dumps(last_sql, default=str)}\n"
            f"task_memory => {json.dumps(task_memory, default=str)}"
        )

    elif block_name == "batch_insert_block":
        db_schema_str = (
            "Here is your DB schema:\n"
            "- fridge_items:\n"
            "   columns => [id, name, quantity, unit, expiration_date, category] (ALWAYS_ALLOW)\n"
            "- shopping_items:\n"
            "   columns => [id, name, desired_quantity, unit, purchased] (ALWAYS_ALLOW)\n"
            "- invoices:\n"
            "   columns => [id, date, total_amount, store_name] (REQUIRE_USER)\n"
            "- invoice_items:\n"
            "   columns => [id, invoice_id, name, quantity, price_per_unit] (REQUIRE_USER)\n"
            "- monthly_spendings:\n"
            "   columns => [id, year_month, total_spent] (ALWAYS_DENY)\n"
        )
        return (
            "You are 'batch_insert_block'. You receive { table_name, rows:[{columns, values},...], explanation}.\n"
            "Insert multiple rows into the DB.\n\n"
            + db_schema_str
            + "\n"
            + "task_memory => "
            + json.dumps(task_memory, default=str)
        )

    elif block_name == "batch_update_block":  # <--- NEW
        db_schema_str = (
            "Here is your DB schema:\n"
            "- fridge_items:\n"
            "   columns => [id, name, quantity, unit, expiration_date, category] (ALWAYS_ALLOW)\n"
            "- shopping_items:\n"
            "   columns => [id, name, desired_quantity, unit, purchased] (ALWAYS_ALLOW)\n"
            "- invoices:\n"
            "   columns => [id, date, total_amount, store_name] (REQUIRE_USER)\n"
            "- invoice_items:\n"
            "   columns => [id, invoice_id, name, quantity, price_per_unit] (REQUIRE_USER)\n"
            "- monthly_spendings:\n"
            "   columns => [id, year_month, total_spent] (ALWAYS_DENY)\n"
        )
        return (
            "You are 'batch_update_block'. You receive { table_name, rows:[{where_clause, columns, values},...], explanation}.\n"
            "Update multiple rows in a single call. If user says 'Update these items at once,' produce multiple row objects.\n\n"
            + db_schema_str
            + "\n"
            + "task_memory => "
            + json.dumps(task_memory, default=str)
        )

    else:
        return f"You are block={block_name}, partial memory => {json.dumps(task_memory, default=str)}"


def call_block_llm(block_name: str, block_description: str, task_memory: dict, debug_info: list):
    """
    Calls GPT with the appropriate function schema.
    Then dispatches to the matching handler: parse_block, sql_block, etc.
    """
    logger.info(f"[call_block_llm] block={block_name}, desc={block_description}")
    debug_info.append(f"[block_llm] block={block_name}, desc={block_description}")

    schema = None
    for s in ALL_FUNCTION_SCHEMAS:
        if s["name"] == block_name:
            schema = s
            break

    if not schema:
        msg = f"No schema found for block={block_name}"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}

    system_prompt = build_system_prompt_for_block(block_name, block_description, task_memory)
    model_name = task_memory.get("agent_model", "gpt-4-0613")

    client = OpenAI(api_key=openai.api_key)
    resp = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": block_description}
        ],
        functions=[schema],
        function_call="auto",
        temperature=0.7
    )
    logger.info(f"[call_block_llm] LLM resp => {resp}")
    debug_info.append(f"[block_llm] raw response => {resp}")

    choice = resp.choices[0]
    fn_call = choice.message.function_call
    if not fn_call:
        content_str = choice.message.content or ""
        debug_info.append(f"[block_llm] no function_call => fallback parse content = {content_str}")
        try:
            candidate = json.loads(content_str)
            if "name" in candidate and "arguments" in candidate:
                fallback_args = candidate["arguments"]
                logger.info(f"[call_block_llm] fallback parse => block={block_name}, arguments={fallback_args}")
                return dispatch_block(block_name, fallback_args, task_memory, debug_info)
        except Exception as e:
            msg = f"No function_call returned, fallback parse error => {e}"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        return {"error": "No function_call returned and fallback parse didn't match block."}
    else:
        fn_args_str = fn_call.arguments
        debug_info.append(f"[block_llm] function_call args => {fn_args_str}")
        logger.info(f"[call_block_llm] function_call args => {fn_args_str}")
        try:
            args_data = json.loads(fn_args_str)
        except Exception as e:
            debug_info.append(f"[block_llm] JSON parse error => {e}")
            return {"error": f"JSON parse error => {e}"}
        return dispatch_block(block_name, args_data, task_memory, debug_info)


def dispatch_block(block_name: str, args_data: dict, task_memory: dict, debug_info: list):
    logger.info(f"[dispatch_block] block={block_name}, args={args_data}")
    debug_info.append(f"[dispatch_block] block={block_name}, args={args_data}")

    if ("table_name" in args_data
        and block_name in ["sql_block","batch_insert_block","batch_update_block"]):
        guessed_table = args_data["table_name"]
        debug_info.append(f"[dispatch_block] Setting target_table => {guessed_table}")
        task_memory["target_table"] = guessed_table

    from .blocks import (
        handle_parse_block,
        handle_sql_block,
        handle_output_block,
        handle_batch_insert_block,
        handle_batch_update_block  # <-- NEW
    )

    if block_name == "parse_block":
        return handle_parse_block(args_data, task_memory, debug_info)
    elif block_name == "sql_block":
        return handle_sql_block(args_data, task_memory, debug_info)
    elif block_name == "output_block":
        return handle_output_block(args_data, task_memory, debug_info)
    elif block_name == "batch_insert_block":
        return handle_batch_insert_block(args_data, task_memory, debug_info)
    elif block_name == "batch_update_block":  # <-- NEW
        return handle_batch_update_block(args_data, task_memory, debug_info)
    else:
        msg = f"Unrecognized block => {block_name}"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}


def run_agent(user_input: str, initial_task_memory: dict = None):
    """
    Orchestrates the user request -> plan -> block calls -> final answer.
    """
    debug_info = []
    if not initial_task_memory:
        initial_task_memory = {}
    task_memory = {"original_user_input": user_input, **initial_task_memory}

    plan_result = call_openai_plan(user_input, debug_info, task_memory)
    if not plan_result.tasks:
        return ("Could not plan tasks. Possibly clarify your request.", debug_info)

    final_answer = "(No final answer produced)"
    output_block_triggered = False

    for step in plan_result.tasks:
        block = step.block
        desc = step.description

        # optional heuristic for target_table
        if "fridge_items" in desc.lower():
            task_memory["target_table"] = "fridge_items"
        elif "shopping_list" in desc.lower() or "shopping_items" in desc.lower():
            task_memory["target_table"] = "shopping_items"
        elif "invoice" in desc.lower():
            task_memory["target_table"] = "invoices"

        result = call_block_llm(block, desc, task_memory, debug_info)
        task_memory[f"last_{block}_result"] = result

        if block == "output_block":
            output_block_triggered = True
            if "final_answer" in result:
                final_answer = result["final_answer"]
            else:
                fm = result.get("final_message", "")
                if fm:
                    final_answer = fm
            break

    if not output_block_triggered:
        last_sql_res = task_memory.get("last_sql_block_result", {})
        if "error" in last_sql_res:
            final_answer = "Sorry, an error occurred with your request:\n" + last_sql_res["error"]
        else:
            ra = last_sql_res.get("rows_affected", None)
            rc = last_sql_res.get("rows_count", None)
            rows_inserted = last_sql_res.get("rows_inserted", None)

            if rows_inserted is not None:
                if rows_inserted == 0:
                    final_answer = "No rows were inserted (possible mismatch)."
                else:
                    final_answer = f"Successfully inserted {rows_inserted} rows."
            elif ra is not None:
                if ra == 0:
                    final_answer = "No matching items were found to update/delete."
                else:
                    final_answer = "Success. The DB was updated."
            elif rc is not None:
                if rc == 0:
                    final_answer = "No items found."
                else:
                    final_answer = f"Found {rc} item(s)."
            else:
                final_answer = "Operation completed, but no final output_block was produced."

    return (final_answer, debug_info)
