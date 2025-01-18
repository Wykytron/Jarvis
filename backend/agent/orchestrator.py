import json
import os
import logging
import openai

from openai import OpenAI

from .schemas import ALL_FUNCTION_SCHEMAS, PlanTasksArguments, PlanTaskItem
from .blocks import (
    handle_parse_block,
    handle_sql_block,
    handle_output_block,
    handle_batch_insert_block,
    handle_batch_update_block,
    handle_batch_delete_block,
    handle_chat_block,
    handle_reflect_block
)
from agent.global_store import TABLE_SCHEMAS, CURRENT_DATETIME_FN

logger = logging.getLogger("agent")


def call_openai_plan(user_request: str, debug_info: list, task_memory: dict) -> PlanTasksArguments:
    """
    Calls GPT with plan instructions (plan_prompt.md) to produce a short JSON plan { tasks: [...] }.
    Expects an output calling the function 'plan_tasks'.
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
    Builds a text snippet enumerating all tables/columns from TABLE_SCHEMAS
    so the LLM sees the actual DB schema at runtime.
    """
    lines = ["Here is your DB schema:"]
    for tbl, cols in TABLE_SCHEMAS.items():
        col_str = ", ".join(cols)
        lines.append(f"- {tbl}: [{col_str}]")
    return "\n".join(lines)


def build_system_prompt_for_block(block_name: str, block_description: str, task_memory: dict) -> str:
    """
    Provide specialized instructions for each block with minimal context,
    plus dynamic DB schema. We read the .md file for the block from prompts/
    and then add the minimal (subset) data from the agent's memory.
    """
    # We read the block-specific .md prompt from the prompts folder if present
    # (like parse_block_prompt.md, sql_block_prompt.md, etc.).
    # Then we embed dynamic DB info + minimal memory (like parse_data or sql_data) below.

    base_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(base_dir, "prompts", f"{block_name}_prompt.md")

    # Fallback if there's no .md file for this block name
    block_instructions = ""
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            block_instructions = f.read()

    def minimal_parse_data():
        subset = {}
        # Possibly user input, or last_sql_rows
        subset["original_user_input"] = task_memory.get("original_user_input", "")
        if "last_sql_rows" in task_memory:
            subset["db_rows"] = task_memory["last_sql_rows"]
        subset["target_table"] = task_memory.get("target_table", "")
        return subset

    def minimal_sql_data():
        recent_parse = task_memory.get("recent_parse_result") or {}
        subset = {}
        if "parsed_item" in recent_parse:
            subset["parsed_item"] = recent_parse["parsed_item"]
        return subset

    dynamic_schema_str = _assemble_dynamic_schema_note()

    # For brevity, we handle block_name-specific additions:
    if block_name == "parse_block":
        subset = minimal_parse_data()
        appended_data = "Minimal parse inputs => " + json.dumps(subset, default=str)
        return block_instructions + "\n\n" + dynamic_schema_str + "\n\n" + appended_data

    elif block_name == "sql_block":
        subset = minimal_sql_data()
        appended_data = "Minimal SQL inputs => " + json.dumps(subset, default=str)
        return block_instructions + "\n\n" + dynamic_schema_str + "\n\n" + appended_data

    elif block_name == "batch_insert_block":
        subset = minimal_sql_data()
        appended_data = "Minimal batch_insert => " + json.dumps(subset, default=str)
        return block_instructions + "\n\n" + dynamic_schema_str + "\n\n" + appended_data

    elif block_name == "batch_update_block":
        subset = minimal_sql_data()
        appended_data = "Minimal batch_update => " + json.dumps(subset, default=str)
        return block_instructions + "\n\n" + dynamic_schema_str + "\n\n" + appended_data

    elif block_name == "batch_delete_block":
        appended_data = "(No minimal input needed besides table_name, rows=...)\n"
        return block_instructions + "\n\n" + dynamic_schema_str + "\n\n" + appended_data

    elif block_name == "chat_block":
        memory_dump = "You receive full task_memory => " + json.dumps(task_memory, default=str)
        return block_instructions + "\n\n" + memory_dump

    elif block_name == "output_block":
        memory_dump = "You receive full task_memory => " + json.dumps(task_memory, default=str)
        return block_instructions + "\n\n" + memory_dump

    elif block_name == "reflect_block":
        memory_dump = "Here is your entire memory => " + json.dumps(task_memory, default=str)
        return block_instructions + "\n\n"  + dynamic_schema_str + "\n\n" + memory_dump

    else:
        # If there's no .md file or we didn't handle it above, just return the fallback
        return block_instructions + f"\n\n(Unknown block='{block_name}', minimal memory => {json.dumps(task_memory, default=str)})"


def call_block_llm(block_name: str, block_description: str, task_memory: dict, debug_info: list):
    """
    Calls GPT with the appropriate block schema, merging the block's .md prompt
    plus dynamic DB schema, plus minimal memory context. 
    If GPT returns a function_call => parse arguments and dispatch.
    """
    logger.info(f"[call_block_llm] block={block_name}, desc={block_description}")
    debug_info.append(f"[block_llm] block={block_name}, desc={block_description}")

    # Identify which schema to use from ALL_FUNCTION_SCHEMAS
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

    # If no function_call => fallback parse
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
        # We do have a function_call => parse arguments
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
    Dispatch to the correct block handler function. Tracks steps in block_steps[].
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

    # If this is a DB-related block => we store target_table in memory
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
        handle_chat_block,
        handle_reflect_block
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

    elif block_name == "reflect_block":
        result = handle_reflect_block(args_data, task_memory, debug_info)
        step_entry["outputs"] = result
        task_memory["recent_reflect_result"] = result

    else:
        msg = f"Unrecognized block => {block_name}"
        debug_info.append(msg)
        logger.warning(msg)
        step_entry["outputs"] = {"error": msg}
        if "block_steps" not in task_memory:
            task_memory["block_steps"] = []
        task_memory["block_steps"].append(step_entry)
        return {"error": msg}

    # Log the step
    if "block_steps" not in task_memory:
        task_memory["block_steps"] = []
    task_memory["block_steps"].append(step_entry)
    return step_entry["outputs"]


def run_agent(user_input: str, initial_task_memory: dict = None):
    """
    Orchestrates user request -> plan -> block calls -> final answer.

    If the final step is not reflect_block, we forcibly append reflect_block.
    The reflect_block can produce:
      - final_message (the user-facing conclusion),
      - data_output (structured data),
      - additional_tasks (if more steps are needed).
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
        "recent_reflect_result": None,
        **initial_task_memory
    }

    # Step 1) Plan
    plan_result = call_openai_plan(user_input, debug_info, task_memory)
    if not plan_result.tasks:
        return ("Could not plan tasks. Possibly clarify your request.", debug_info)

    # Ensure reflect_block is last if not present
    if not plan_result.tasks or plan_result.tasks[-1].block != "reflect_block":
        debug_info.append("[run_agent] forcibly adding reflect_block as final step")
        plan_result.tasks.append(
            PlanTaskItem(
                block="reflect_block",
                description="Auto-injected reflect step",
                title="Reflection",
                reasoning="Ensure final reflection"
            )
        )

    final_answer = "(No final answer yet)"
    tasks_list = plan_result.tasks
    task_index = 0

    # Step 2) Execute tasks in a loop
    while task_index < len(tasks_list):
        step = tasks_list[task_index]
        block = step.block
        desc = step.description

        # Quick guess for target_table
        if "fridge_items" in desc.lower():
            task_memory["target_table"] = "fridge_items"
        elif "shopping_items" in desc.lower():
            task_memory["target_table"] = "shopping_items"
        elif "invoice" in desc.lower():
            task_memory["target_table"] = "invoices"

        # Call the block
        result = call_block_llm(block, desc, task_memory, debug_info)

        if block == "reflect_block":
            # reflect_block may produce final_message / additional_tasks
            reflect_res = task_memory.get("recent_reflect_result") or {}
            if "final_message" in reflect_res:
                final_answer = reflect_res["final_message"]
                # If there's data_output => append to final answer
                if "data_output" in reflect_res:
                    final_answer += "\n\nAdditional Data:\n"
                    final_answer += json.dumps(reflect_res["data_output"], indent=2)
                debug_info.append(f"[run_agent] reflect_block produced final_message => {final_answer}")
                break
            elif "additional_tasks" in reflect_res:
                new_tasks = reflect_res["additional_tasks"]
                debug_info.append(f"[run_agent] reflect_block produced {len(new_tasks)} new tasks => {new_tasks}")
                # Insert them into tasks_list after the current step
                for t in new_tasks:
                    if not isinstance(t, dict):
                        continue
                    block_name = t.get("block", "")
                    desc_str = t.get("description", "(no description)")
                    tasks_list.insert(
                        task_index + 1,
                        PlanTaskItem(
                            block=block_name,
                            description=desc_str,
                            title=t.get("title", "(auto)"),
                            reasoning=t.get("reasoning", "(auto)")
                        )
                    )
                # do not break => continue
        task_index += 1

    # Step 3) If we finish w/o final_message from reflect_block, fallback
    if final_answer == "(No final answer yet)" and task_index >= len(tasks_list):
        debug_info.append("[run_agent] reflect_block ended with no final_message => fallback logic")
        last_sql_res = task_memory.get("recent_sql_result") or {}
        if "error" in last_sql_res:
            final_answer = "Sorry, an error occurred:\n" + last_sql_res["error"]
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
                final_answer = "Operation completed, but reflect_block gave no final_message."

    return (final_answer, debug_info)
