# v0.2/backend/agent/orchestrator.py

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
    handle_batch_update_block,
    handle_batch_delete_block,
    handle_chat_block
)
from agent.global_store import TABLE_SCHEMAS, CURRENT_DATETIME_FN

logger = logging.getLogger("agent")


def call_openai_plan(user_request: str, debug_info: list, task_memory: dict) -> PlanTasksArguments:
    """
    Calls GPT with plan instructions to produce a short JSON plan { tasks: [...] }.
    We read from plan_prompt.md for instructions, then let the LLM produce a plan
    calling "name":"plan_tasks" with tasks[].
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


def _assemble_dynamic_schema_note() -> str:
    """
    Builds a text snippet enumerating all tables/columns
    from TABLE_SCHEMAS. This is used inside each block's system prompt
    so GPT sees the actual DB schema at runtime.
    """
    lines = ["Here is your DB schema:"]
    for tbl, cols in TABLE_SCHEMAS.items():
        col_str = ", ".join(cols)
        lines.append(f"- {tbl}: [{col_str}]")
    return "\n".join(lines)


def build_system_prompt_for_block(block_name: str, block_description: str, task_memory: dict) -> str:
    """
    Provide specialized instructions for each block with some minimal context,
    plus the dynamic DB schema. 
    """
    def minimal_parse_data():
        """
        For parse_block, we may include last_sql_rows so the LLM can unify or fill columns.
        """
        subset = {}
        subset["original_user_input"] = task_memory.get("original_user_input", "")
        if "last_sql_rows" in task_memory:
            subset["db_rows"] = task_memory["last_sql_rows"]
        subset["target_table"] = task_memory.get("target_table", "")
        return subset

    def minimal_sql_data():
        """
        For sql-based blocks, we might let the LLM see the parsed_item from parse_block.
        Avoid NoneType by defaulting to an empty dict if recent_parse_result is None.
        """
        recent_parse = task_memory.get("recent_parse_result") or {}
        subset = {}
        if "parsed_item" in recent_parse:
            subset["parsed_item"] = recent_parse["parsed_item"]
        return subset

    # Build the dynamic DB schema snippet
    dynamic_schema_str = _assemble_dynamic_schema_note()

    if block_name == "parse_block":
        subset = minimal_parse_data()
        return (
            "You are 'parse_block'. You parse user text for item info, date phrases, etc.\n"
            "You can consider 'original_user_input' if no raw_text or db_rows is provided.\n"
            "Your goal is to fill potential missing info from the user request or db_rows and fill the parsed_item with all the info you can, see the database schema for reference.\n"
            "User might say "Add Milk to fridge", then you should look into the db schema and fill all missing columns with reasonable informations and format everything nicely into parsed_item.\n"
            "Then return JSON => {parsed_item, explanation}.\n"
            f"{dynamic_schema_str}\n"
            "Minimal parse inputs => " + json.dumps(subset, default=str)
        )

    elif block_name == "sql_block":
        subset = minimal_sql_data()
        return (
            "You are 'sql_block'. Produce JSON => "
            "{ table_name, columns, values, action_type, explanation, [where_clause] }.\n"
            "Allowed action_type: SELECT, INSERT, UPDATE, DELETE.\n\n"
            + dynamic_schema_str
            + "\nMinimal SQL inputs => " + json.dumps(subset, default=str)
        )

    elif block_name == "batch_insert_block":
        subset = minimal_sql_data()
        return (
            "You are 'batch_insert_block'. Insert multiple rows in one call.\n\n"
            + dynamic_schema_str
            + "\nMinimal batch_insert inputs => " + json.dumps(subset, default=str)
        )

    elif block_name == "batch_update_block":
        subset = minimal_sql_data()
        return (
            "You are 'batch_update_block'. Update multiple rows in one call.\n"
            "Provide {where_clause, columns, values} for each row.\n\n"
            + dynamic_schema_str
            + "\nMinimal batch_update inputs => " + json.dumps(subset, default=str)
        )

    elif block_name == "batch_delete_block":
        return (
            "You are 'batch_delete_block'. Delete multiple rows in one call.\n"
            "For each row => a 'where_clause'.\n\n"
            + dynamic_schema_str
        )

    elif block_name == "chat_block":
        # Possibly user wants open-ended reasoning about the data
        return (
            "You are 'chat_block'. Perform open-ended conversation or reasoning.\n"
            "Return JSON => {response_text}.\n\n"
            + "\nYou receive full task_memory => " + json.dumps(task_memory, default=str)
        )

    elif block_name == "output_block":
        return (
            "You are 'output_block'. Summarize or finalize the user-facing answer.\n"
            "If row_affected=0 => might say 'No matching items found'.\n\n"
            + "\nYou receive full task_memory => " + json.dumps(task_memory, default=str)
        )

    else:
        return f"You are block={block_name}, minimal info => {json.dumps(task_memory, default=str)}"


def call_block_llm(block_name: str, block_description: str, task_memory: dict, debug_info: list):
    """
    This function calls GPT with the appropriate function schema, building a small system_prompt
    from the method above. If GPT returns a function_call => we parse its arguments & dispatch the block.
    If no function_call => fallback parse or return error.
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

    # If there's no function_call => fallback
    if not fn_call:
        content_str = choice.message.content or ""
        debug_info.append(f"[block_llm] no function_call => fallback parse = {content_str}")
        try:
            candidate = json.loads(content_str)
            if "name" in candidate and "arguments" in candidate:
                fallback_args = candidate["arguments"]
                logger.info(f"[call_block_llm] fallback parse => {fallback_args}")
                return dispatch_block(block_name, fallback_args, task_memory, debug_info)
        except Exception as e:
            msg = f"No function_call returned, fallback parse error => {e}"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        return {"error": "No function_call returned and fallback parse didn't match block."}
    else:
        # We do have a function_call => parse its arguments
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
    """
    Dispatch the block to the corresponding handler function.
    We also track block steps in task_memory["block_steps"] for possible debugging or reflection later.
    """
    logger.info(f"[dispatch_block] block={block_name}, args={args_data}")
    debug_info.append(f"[dispatch_block] block={block_name}, args={args_data}")

    step_index = len(task_memory.get("block_steps", []))
    step_entry = {
        "block_name": block_name,
        "description": args_data.get("explanation", ""),
        "inputs": args_data,
        "outputs": {},
        "step_index": step_index
    }

    # If we have a DB-related block, set the target_table from the arguments.
    if ("table_name" in args_data
        and block_name in ["sql_block", "batch_insert_block", "batch_update_block", "batch_delete_block"]):
        guessed_table = args_data["table_name"]
        debug_info.append(f"[dispatch_block] Setting target_table => {guessed_table}")
        task_memory["target_table"] = guessed_table

    from .blocks import (
        handle_parse_block,
        handle_sql_block,
        handle_output_block,
        handle_batch_insert_block,
        handle_batch_update_block,
        handle_batch_delete_block,
        handle_chat_block
    )

    if block_name == "parse_block":
        result = handle_parse_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result
        task_memory["recent_parse_result"] = result

    elif block_name == "sql_block":
        result = handle_sql_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result
        task_memory["recent_sql_result"] = result

    elif block_name == "batch_insert_block":
        result = handle_batch_insert_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result
        task_memory["recent_sql_result"] = result

    elif block_name == "batch_update_block":
        result = handle_batch_update_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result
        task_memory["recent_sql_result"] = result

    elif block_name == "batch_delete_block":
        result = handle_batch_delete_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result
        task_memory["recent_sql_result"] = result

    elif block_name == "chat_block":
        result = handle_chat_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result
        task_memory["recent_chat_result"] = result

    elif block_name == "output_block":
        result = handle_output_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result

    else:
        msg = f"Unrecognized block => {block_name}"
        debug_info.append(msg)
        logger.warning(msg)
        step_entry["outputs"] = {"error": msg}
        if "block_steps" not in task_memory:
            task_memory["block_steps"] = []
        task_memory["block_steps"].append(step_entry)
        return {"error": msg}

    if "block_steps" not in task_memory:
        task_memory["block_steps"] = []
    task_memory["block_steps"].append(step_entry)
    return step_entry["outputs"]


def run_agent(user_input: str, initial_task_memory: dict = None):
    """
    Orchestrates the user request -> plan -> block calls -> final answer.
    If the plan does not produce an output_block, we do fallback logic after all tasks.
    """
    debug_info = []
    if not initial_task_memory:
        initial_task_memory = {}

    task_memory = {
        "original_user_input": user_input,
        "block_steps": [],
        "recent_parse_result": None,
        "recent_sql_result": None,
        "recent_chat_result": None,
        **initial_task_memory
    }

    # 1) Plan
    plan_result = call_openai_plan(user_input, debug_info, task_memory)
    if not plan_result.tasks:
        return ("Could not plan tasks. Possibly clarify your request.", debug_info)

    final_answer = "(No final answer produced)"
    output_block_triggered = False

    # 2) Execute tasks in order
    for step in plan_result.tasks:
        block = step.block
        desc = step.description

        # optional heuristic for table guess
        if "fridge_items" in desc.lower():
            task_memory["target_table"] = "fridge_items"
        elif "shopping_list" in desc.lower() or "shopping_items" in desc.lower():
            task_memory["target_table"] = "shopping_items"
        elif "invoice" in desc.lower():
            task_memory["target_table"] = "invoices"

        result = call_block_llm(block, desc, task_memory, debug_info)

        if block == "output_block":
            output_block_triggered = True
            if "final_answer" in result:
                final_answer = result["final_answer"]
            else:
                fm = result.get("final_message", "")
                if fm:
                    final_answer = fm
            break

    # 3) Fallback if no output_block
    if not output_block_triggered:
        last_sql_res = task_memory.get("recent_sql_result") or {}
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
