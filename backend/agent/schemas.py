# backend/agent/schemas.py

from typing import List, Optional, Literal
from pydantic import BaseModel

#
# 1) plan_tasks
#
class PlanTaskItem(BaseModel):
    block: str
    description: str
    title: str
    reasoning: Optional[str] = ""

class PlanTasksArguments(BaseModel):
    tasks: List[PlanTaskItem]

plan_tasks_schema = {
    "name": "plan_tasks",
    "description": "Produce a short list of tasks (blocks) to solve the user request. Each item has a block name and a short description.",
    "parameters": PlanTasksArguments.schema()
}

#
# 2) sql_block
#
class SQLBlockArguments(BaseModel):
    sql_query: str
    action_type: Literal["SELECT"] = "SELECT"
    explanation: Optional[str] = ""

sql_block_schema = {
    "name": "sql_block",
    "description": "Execute a SELECT query on the local DB. Only 'SELECT' is allowed.",
    "parameters": SQLBlockArguments.schema()
}

#
# 3) output_block
#
class OutputBlockArguments(BaseModel):
    final_message: str

output_block_schema = {
    "name": "output_block",
    "description": "Produce final user-facing answer, then we are done.",
    "parameters": {
       "type": "object",
       "properties": {
          "final_message": {
             "type": "string",
             "description": "The final user-facing text to present."
          }
       },
       "required": ["final_message"]
    }
}

#
# Gather them for OpenAI function calling
#
ALL_FUNCTION_SCHEMAS = [
    plan_tasks_schema,
    sql_block_schema,
    output_block_schema
]
