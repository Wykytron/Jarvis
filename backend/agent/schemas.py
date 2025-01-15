# backend/agent/schemas.py

from typing import List, Optional, Literal, Any
from pydantic import BaseModel


#
# 1) plan_tasks
#
class PlanTaskItem(BaseModel):
    block: str
    description: str
    title: str
    reasoning: str = ""


class PlanTasksArguments(BaseModel):
    tasks: List[PlanTaskItem]


plan_tasks_schema = {
    "name": "plan_tasks",
    "description": (
        "Produce a short plan (a list of tasks) to solve the user request. "
        "Each item has a block name, description, title, and reasoning."
    ),
    "parameters": PlanTasksArguments.schema()
}


#
# 2) sql_block (Method A)
#
class SQLBlockArguments(BaseModel):
    table_name: str
    columns: List[str]    # e.g. ["name","quantity","unit","expiration_date","category"]
    values: List[str]     # e.g. ["'Joghurt'","2","'unit'","'2025-01-25'","'dairy'"]
    action_type: Literal["SELECT", "INSERT", "UPDATE", "DELETE"]
    explanation: str = ""


sql_block_schema = {
    "name": "sql_block",
    "description": (
        "Use this to run a SQL query on the local DB. "
        "No single big sql string—use 'table_name','columns','values','action_type','explanation'. "
        "No disclaimers or code blocks—only valid JSON."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Target DB table, e.g. fridge_items or shopping_items"
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Which columns to read/write, e.g. ['name','quantity','unit','expiration_date','category']"
            },
            "values": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Matching values, e.g. ['Joghurt','2','Units','2025-01-25','Dairy']"
            },
            "action_type": {
                "type": "string",
                "enum": ["SELECT","INSERT","UPDATE","DELETE"]
            },
            "explanation": {
                "type": "string",
                "description": "Short explanation or reasoning behind the query"
            },
            "where_clause": {
                "type": "string",
                "description": "Optional WHERE clause if we do an UPDATE or DELETE, e.g. \"WHERE name='tomatoes'\""
            }
        },
        "required": ["table_name","columns","values","action_type"],
        "additionalProperties": False
    }
}


#
# 3) output_block
#
class OutputBlockArguments(BaseModel):
    final_message: str


output_block_schema = {
    "name": "output_block",
    "description": "Produces the final user-facing answer as JSON with 'final_message'.",
    "parameters": {
        "type": "object",
        "properties": {
            "final_message": {
                "type": "string",
                "description": "User-facing text or summary"
            }
        },
        "required": ["final_message"],
        "additionalProperties": False
    }
}


#
# 4) parse_block
#
class ParseBlockArguments(BaseModel):
    raw_text: str
    explanation: Optional[str] = ""
    parsed_item: Optional[Any] = None


parse_block_schema = {
    "name": "parse_block",
    "description": (
        "Parse or unify raw user text into a structured 'parsed_item'. "
        "No disclaimers, just JSON with 'raw_text' and optionally 'parsed_item'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "raw_text": {
                "type": "string",
                "description": "The raw text we want to parse"
            },
            "explanation": {
                "type": "string",
                "description": "Short reasoning or explanation"
            },
            "parsed_item": {
                "type": "object",
                "description": "Structured object if needed, e.g. {'name':'Joghurt', 'quantity':2, ...}",
                "additionalProperties": True
            }
        },
        "required": ["raw_text"],
        "additionalProperties": False
    }
}


#
# Gather them all
#
ALL_FUNCTION_SCHEMAS = [
    plan_tasks_schema,
    sql_block_schema,
    output_block_schema,
    parse_block_schema
]
