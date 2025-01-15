# agent/orchestrator.py

import json
import os
import logging

from .schemas import ALL_FUNCTION_SCHEMAS, PlanTasksArguments
from .blocks import handle_parse_block, handle_sql_block, handle_output_block

import openai
from openai import OpenAI

logger = logging.getLogger("agent")

def call_openai_plan(user_request: str, debug_info: list, task_memory: dict) -> PlanTasksArguments:
    """
    Asks GPT to produce a short plan of tasks. If GPT returns function_call=plan_tasks, parse it.
    Otherwise fallback parse from content.
    """

    # 1) Load plan instructions from file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plan_path = os.path.join(base_dir, "prompts", "plan_prompt.md")
    with open(plan_path, "r", encoding="utf-8") as f:
        plan_instructions = f.read()

    # 2) We'll look up the model from task_memory (default gpt-4-0613 if not present)
    model_name = task_memory.get("agent_model", "gpt-4-0613")

    # 3) Build messages
    messages = [
        {"role": "system", "content": plan_instructions},
        {"role": "user", "content": f"USER REQUEST: {user_request}"}
    ]

    # 4) Log
    logger.info(f"[call_openai_plan] user_request='{user_request}'")
    debug_info.append(f"[plan] user_request='{user_request}'")

    # 5) Call GPT with "plan_tasks" schema
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

    # 6) Parse function_call
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
        # fallback parse from .content
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
        logger.info("[call_openai_plan] no tasks returned")
        return PlanTasksArguments(tasks=[])


def call_block_llm(block_name: str, block_description: str, task_memory: dict, debug_info: list):
    """
    Calls GPT with the appropriate function schema for the block_name.
    If GPT returns no function_call, fallback parse from content. 
    If still no success => error.
    """

    logger.info(f"[call_block_llm] block={block_name}, desc={block_description}")
    debug_info.append(f"[block_llm] block={block_name}, desc={block_description}")

    # 1) Find function schema
    block_schema = None
    for s in ALL_FUNCTION_SCHEMAS:
        if s["name"] == block_name:
            block_schema = s
            break

    if not block_schema:
        msg = f"No schema found for block={block_name}"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}

    # 2) Build system prompt
    system_prompt = build_system_prompt_for_block(block_name, block_description, task_memory)

    # 3) The agent model
    model_name = task_memory.get("agent_model", "gpt-4-0613")

    # 4) Send to GPT
    client = OpenAI(api_key=openai.api_key)
    resp = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": block_description}
        ],
        functions=[block_schema],
        function_call="auto",
        temperature=0.7
    )

    logger.info(f"[call_block_llm] LLM resp => {resp}")
    debug_info.append(f"[block_llm] raw response => {resp}")

    choice = resp.choices[0]
    fn_call = choice.message.function_call
    if not fn_call:
        # fallback parse from .content
        content_str = choice.message.content or ""
        debug_info.append(f"[block_llm] no function_call => fallback parse content = {content_str}")
        try:
            candidate = json.loads(content_str)
            if "name" in candidate and "arguments" in candidate:
                # we can fake a function_call object
                fallback_args = candidate["arguments"]
                logger.info(f"[call_block_llm] fallback parse => block={block_name}, arguments={fallback_args}")
                return dispatch_block(block_name, fallback_args, task_memory, debug_info)
        except Exception as e:
            msg = f"No function_call returned, fallback parse error => {e}"
            debug_info.append(msg)
            logger.warning(msg)
            return {"error": msg}

        # if no parse
        return {"error": "No function_call returned and fallback parse didn't match block=" + block_name}
    else:
        # normal path
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

    if block_name == "parse_block":
        return handle_parse_block(args_data, task_memory, debug_info)
    elif block_name == "sql_block":
        return handle_sql_block(args_data, task_memory, debug_info)
    elif block_name == "output_block":
        return handle_output_block(args_data, task_memory, debug_info)
    else:
        msg = f"Unrecognized block => {block_name}"
        debug_info.append(msg)
        logger.warning(msg)
        return {"error": msg}


def build_system_prompt_for_block(block_name: str, block_description: str, task_memory: dict) -> str:
    """
    Provide specialized instructions for each block. 
    E.g. show DB schema for sql_block, etc.
    """
    if block_name == "parse_block":
        user_req = task_memory.get("original_user_input", "")
        return (
            "You are the 'parse_block'. You parse raw text into structured data { raw_text, parsed_item }.\n"
            "No disclaimers. Return function_call => { raw_text:'...', explanation:'...', parsed_item:{...}} if needed.\n"
            f"user_input => {user_req}\n"
            f"task_memory => {json.dumps(task_memory, default=str)}"
        )

    elif block_name == "sql_block":           # Here’s a more complete schema block to help the LLM:
        db_schema_str = (
            "Here is your DB schema:\n"
            "- fridge_items:\n"
            "   columns => [id, name, quantity, unit, expiration_date, category]\n"
            "   ALWAYS_ALLOW for writes.\n"
            "- shopping_items:\n"
            "   columns => [id, name, desired_quantity, unit, purchased]\n"
            "   ALWAYS_ALLOW for writes.\n"
            "- invoices:\n"
            "   columns => [id, date, total_amount, store_name]\n"
            "   REQUIRE_USER for writes.\n"
            "- invoice_items:\n"
            "   columns => [id, invoice_id, name, quantity, price_per_unit]\n"
            "   REQUIRE_USER for writes.\n"
            "- monthly_spendings:\n"
            "   columns => [id, year_month, total_spent]\n"
            "   ALWAYS_DENY for writes.\n"
            "\n"
            # If you have more tables or disclaimers, add them here
        )
        return (
            "You are 'sql_block'. You produce { table_name, columns, values, action_type, explanation }.\n"
            "If you do an INSERT, please supply all needed columns. If user didn't specify, use 'misc' or default.\n"
            "For UPDATE or DELETE, you MUST provide where_clause, e.g. \"WHERE name='tomatoes'\".\n\n"
            "If action_type=DELETE, you must provide a where_clause. If the user only says “Delete X,” produce where_clause: \"WHERE name='X'\". No disclaimers.\n"
            "Use EXACT existing table names from the schema below. If you do an INSERT, supply all needed columns.\n"
            + db_schema_str
            + "\n"  # separate line
            + "Example: If user says 'What's on my shopping list?', you select from 'shopping_items'.\n"
            "No disclaimers. You MUST produce a function call object exactly like:\n"
            "{\n"
            '  "name": "sql_block",\n'
            '  "arguments": {\n'
            '     "table_name": "...",\n'
            '     "columns": [...],\n'
            '     "values": [...],\n'
            '     "action_type": "...",\n'
            '     "explanation": "..." \n'
            '     "where_clause": "..." \n'
            '  }\n'
            "}\n\n"
            f"task_memory => {json.dumps(task_memory, default=str)}"
        )

    elif block_name == "output_block":
        last_sql = task_memory.get("last_sql_block_result", {})
        return (
            "You are 'output_block'. Summarize final results. If there's data in last_sql_block_result, show it.\n"
            "Output { 'final_message':'...' } in function_call. No disclaimers.\n"
            f"last_sql_block_result => {json.dumps(last_sql, default=str)}\n"
            f"task_memory => {json.dumps(task_memory, default=str)}"
        )

    else:
        return f"You are block={block_name}, partial memory => {json.dumps(task_memory, default=str)}"


def run_agent(user_input: str, initial_task_memory: dict = None):
    debug_info = []
    if not initial_task_memory:
        initial_task_memory = {}

    task_memory = {"original_user_input": user_input, **initial_task_memory}

    # 1) Plan
    plan_result = call_openai_plan(user_input, debug_info, task_memory)
    if not plan_result.tasks:
        return ("Could not plan tasks. Possibly clarify your request.", debug_info)

    final_answer = "(No final answer produced)"
    output_block_triggered = False

    # 2) Execute steps
    for step in plan_result.tasks:
        block = step.block
        desc = step.description
        res = call_block_llm(block, desc, task_memory, debug_info)

        task_memory[f"last_{block}_result"] = res

        # If it's the output_block, record final_answer
        if block == "output_block":
            output_block_triggered = True
            if "final_answer" in res:
                final_answer = res["final_answer"]
            else:
                # fallback check for "final_message"
                fm = res.get("final_message","")
                if fm:
                    final_answer = fm
            break  # usually we stop after output_block

    # 3) If no output_block was triggered, do a fallback
    if not output_block_triggered:
        # Possibly check last_sql_block_result for success/failure, rowcount, etc.
        # then produce a minimal fallback:
        last_sql_res = task_memory.get("last_sql_block_result", {})
        if "error" in last_sql_res:
            final_answer = (
                "Sorry, an error occurred with your request:\n"
                f"{last_sql_res['error']}"
            )
        else:
            # either row_affected, row_count, or no DB call
            if "rows_affected" in last_sql_res:
                # if row_affected=0 => partial success or no row changed
                ra = last_sql_res["rows_affected"]
                if ra == 0:
                    final_answer = "No rows changed. Possibly the item wasn't found."
                else:
                    final_answer = "Success. The item was changed in the DB."
            elif "rows_count" in last_sql_res:
                # e.g. SELECT
                rc = last_sql_res["rows_count"]
                if rc == 0:
                    final_answer = "No items found."
                else:
                    final_answer = f"Found {rc} item(s)."
            else:
                # no DB call => fallback
                final_answer = "Operation completed, but no final message was produced."

    return (final_answer, debug_info)