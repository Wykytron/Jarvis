# agent/orchestrator.py

import json
import os
import logging

from .schemas import ALL_FUNCTION_SCHEMAS, PlanTasksArguments
from .blocks import handle_sql_block, handle_output_block

import openai
from openai import OpenAI

logger = logging.getLogger("agent")


def call_openai_plan(user_request: str, debug_info: list) -> PlanTasksArguments:
    """
    Asks GPT to plan tasks. If GPT returns function_call plan_tasks, parse it.
    If no function_call, attempt to parse fallback JSON from content.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    plan_path = os.path.join(base_dir, "prompts", "plan_prompt.md")

    with open(plan_path, "r", encoding="utf-8") as f:
        plan_instructions = f.read()

    messages = [
        {
            "role": "system",
            "content": plan_instructions
        },
        {
            "role": "user",
            "content": f"USER REQUEST: {user_request}"
        }
    ]

    logger.info(f"[call_openai_plan] user_request='{user_request}'")
    debug_info.append(f"[plan] user_request='{user_request}'")

    client = OpenAI(api_key=openai.api_key)
    resp = client.chat.completions.create(
        model="gpt-4-0613",
        messages=messages,
        functions=[
            fn for fn in ALL_FUNCTION_SCHEMAS if fn["name"] == "plan_tasks"
        ],
        function_call="auto",
        temperature=0.7
    )
    logger.info(f"[call_openai_plan] raw response: {resp}")
    debug_info.append(f"[plan] raw response: {resp}")

    choice = resp.choices[0]
    fn_call = choice.message.function_call

    if fn_call:
        # The GPT gave us a function_call for plan_tasks
        fn_args_str = fn_call.arguments
        debug_info.append(f"[plan] function_call arguments: {fn_args_str}")
        data = json.loads(fn_args_str)
        plan_args = PlanTasksArguments(**data)
        return plan_args
    else:
        # Possibly GPT returned JSON in .content
        content_str = choice.message.content or ""
        debug_info.append(f"[plan] No function_call, content={content_str}")

        try:
            candidate = json.loads(content_str)
            if "name" in candidate and "arguments" in candidate:
                # The same structure
                plan_args_data = candidate["arguments"]
                plan_args = PlanTasksArguments(**plan_args_data)
                return plan_args
        except Exception as e:
            debug_info.append(f"[plan] JSON parse error fallback: {e}")

        logger.info("[call_openai_plan] No function call returned, no tasks.")
        debug_info.append("[plan] No tasks returned.")
        return PlanTasksArguments(tasks=[])


def call_block_llm(block_name: str, block_description: str, task_memory: dict, debug_info: list):
    """
    Calls GPT with a function schema to produce arguments for the block,
    then we dispatch to the block's python code.
    """
    logger.info(f"[call_block_llm] block_name={block_name}, desc={block_description}")
    debug_info.append(f"[block_llm] block={block_name}, desc={block_description}")

    # Find schema for the block
    block_schema = None
    for s in ALL_FUNCTION_SCHEMAS:
        if s["name"] == block_name:
            block_schema = s
            break

    if not block_schema:
        msg = f"No schema found for block={block_name}"
        logger.warning(msg)
        debug_info.append(msg)
        return {"error": msg}

    # Different system prompts for each block:
    if block_name == "sql_block":
        system_content = (
            "You are the 'sql_block' function. Only SELECT queries.\n"
            "Tables: fridge_items(id, name, quantity, unit, expiration_date, category),\n"
            "        shopping_items(id, name, desired_quantity, unit, purchased),\n"
            "        invoices(id, date, total_amount, store_name),\n"
            "        invoice_items(id, invoice_id, name, quantity, price_per_unit),\n"
            "        monthly_spendings(id, year_month, total_spent),\n"
            "        documents(id, filename, description, text_content, upload_time),\n"
            "        chat_exchanges(id, user_message, llm_response, timestamp).\n\n"
            f"Partial memory (JSON): {json.dumps(task_memory, default=str)}"
        )
    elif block_name == "output_block":
        last_sql_res = task_memory.get("last_sql_block_result", {})
        system_content = (
        "You are the 'output_block'. Summarize final result for the user.\n"
        "IMPORTANT:\n"
        "- If you see 'rows_data' from the prior sql_block, you MUST display them.\n"
        "- Provide a concise but accurate representation of that data.\n\n"
        "No disclaimers unless there's an error.\n\n"
        f"Partial memory => {json.dumps(task_memory, default=str)}\n\n"
        f"last_sql_block_result => {json.dumps(last_sql_res, default=str)}\n\n"

        # ------------ NEW, stronger instructions ------------
        "CRITICAL:\n"
        "You MUST produce a **function call** in JSON format with:\n"
        "{\n"
        "  \"name\": \"output_block\",\n"
        "  \"arguments\": {\n"
        "    \"final_message\": \"(the final text)\"\n"
        "  }\n"
        "}\n"
        "No other fields. No normal text outside of 'arguments'.\n"
        "Exactly that structure, do not add disclaimers.\n"
        )
    else:
        system_content = (
            f"You are block {block_name}. Use function calling.\n"
            f"Partial memory => {json.dumps(task_memory, default=str)}"
        )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": block_description}
    ]

    client = OpenAI(api_key=openai.api_key)
    resp = client.chat.completions.create(
        model="gpt-4-0613",
        messages=messages,
        functions=[block_schema],
        function_call="auto",
        temperature=0.7
    )
    logger.info(f"[call_block_llm] LLM response: {resp}")
    debug_info.append(f"[block_llm] raw response: {resp}")

    choice = resp.choices[0]
    fn_call = choice.message.function_call
    if not fn_call:
        # fallback parse from content
        content_str = choice.message.content or ""
        debug_info.append(f"[block_llm] No function_call. content={content_str}")
        try:
            # Attempt JSON
            candidate = json.loads(content_str)
            if "name" in candidate and "arguments" in candidate:
                fn_call = type("FakeCall", (object,), {})()
                fn_call.arguments = json.dumps(candidate["arguments"])
            else:
                return {"error": "No function_call returned in block."}
        except Exception:
            return {"error": "No function_call returned in block, fallback parse error."}

    fn_args_str = fn_call.arguments
    logger.info(f"[call_block_llm] function_call args: {fn_args_str}")
    debug_info.append(f"[block_llm] function_call args: {fn_args_str}")

    args_data = json.loads(fn_args_str)
    return dispatch_block(block_name, args_data, task_memory, debug_info)


def dispatch_block(block_name: str, args_data: dict, task_memory: dict, debug_info: list):
    logger.info(f"[dispatch_block] block={block_name}, args={args_data}")
    debug_info.append(f"[dispatch_block] block={block_name}, args={args_data}")

    if block_name == "sql_block":
        from .blocks import handle_sql_block
        return handle_sql_block(args_data, task_memory, debug_info)

    elif block_name == "output_block":
        from .blocks import handle_output_block
        return handle_output_block(args_data, task_memory, debug_info)

    else:
        msg = f"Unrecognized block: {block_name}"
        logger.warning(msg)
        debug_info.append(msg)
        return {"error": msg}


def run_agent(user_input: str):
    debug_info = []
    plan_result = call_openai_plan(user_input, debug_info)

    if not plan_result.tasks:
        return ("Could not plan any tasks. Possibly clarify your request.", debug_info)

    task_memory = {}
    final_answer = "(No final answer produced)"

    for step in plan_result.tasks:
        block = step.block
        desc = step.description
        result = call_block_llm(block, desc, task_memory, debug_info)

        # store block's result if needed
        task_memory[f"last_{block}_result"] = result

        # If it is the output_block, we check if "final_answer" is in the result
        if block == "output_block" and "final_answer" in result:
            final_answer = result["final_answer"]
            break

    return (final_answer, debug_info)
