# v0.2/backend/agent/schemas.py

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
# 2) sql_block
#
class SQLBlockArguments(BaseModel):
    table_name: str
    columns: List[str]  # e.g. ["name","quantity","unit","expiration_date","category"]
    values: List[str]   # e.g. ["Joghurt","2","unit","2025-01-25","dairy"]
    action_type: Literal["SELECT", "INSERT", "UPDATE", "DELETE"]
    explanation: str = ""
    where_clause: Optional[str] = None

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
            "table_name": {"type": "string"},
            "columns": {
                "type": "array",
                "items": {"type": "string"}
            },
            "values": {
                "type": "array",
                "items": {"type": "string"}
            },
            "action_type": {
                "type": "string",
                "enum": ["SELECT","INSERT","UPDATE","DELETE"]
            },
            "explanation": {"type": "string"},
            "where_clause": {"type": "string"}
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
                "type": "string"
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
    db_rows: Optional[List[Any]] = None

parse_block_schema = {
    "name": "parse_block",
    "description": (
        "Parse or unify raw user text AND optionally DB data (db_rows) into a 'parsed_item'. "
        "No disclaimers, just JSON with 'raw_text', 'parsed_item', and optionally 'db_rows'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "raw_text": {"type": "string"},
            "explanation": {"type": "string"},
            "parsed_item": {
                "type": "object",
                "description": "structured object if needed"
            },
            "db_rows": {
                "type": "array",
                "items": {"type": "object"}
            }
        },
        "required": ["raw_text"],
        "additionalProperties": False
    }
}


#
# 5) batch_insert_block
#
class BatchInsertRow(BaseModel):
    columns: List[str]
    values: List[str]

class BatchInsertBlockArguments(BaseModel):
    table_name: str
    rows: List[BatchInsertRow]
    explanation: str = ""

batch_insert_block_schema = {
    "name": "batch_insert_block",
    "description": (
        "Insert multiple rows in one table in a single call."
        "No disclaimers, only valid JSON."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "columns": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["columns","values"]
                }
            },
            "explanation": {"type": "string"}
        },
        "required": ["table_name","rows"],
        "additionalProperties": False
    }
}


#
# 6) batch_update_block
#
class BatchUpdateRow(BaseModel):
    where_clause: str
    columns: List[str]
    values: List[str]

class BatchUpdateBlockArguments(BaseModel):
    table_name: str
    rows: List[BatchUpdateRow]
    explanation: str = ""

batch_update_block_schema = {
    "name": "batch_update_block",
    "description": (
        "Update multiple rows in one table in a single call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "where_clause": {"type": "string"},
                        "columns": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["where_clause","columns","values"]
                }
            },
            "explanation": {"type": "string"}
        },
        "required": ["table_name","rows"],
        "additionalProperties": False
    }
}


#
# 7) batch_delete_block
#
class BatchDeleteRow(BaseModel):
    where_clause: str

class BatchDeleteBlockArguments(BaseModel):
    table_name: str
    rows: List[BatchDeleteRow]
    explanation: str = ""

batch_delete_block_schema = {
    "name": "batch_delete_block",
    "description": (
        "Delete multiple rows from one table in a single call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "where_clause": {"type": "string"}
                    },
                    "required": ["where_clause"]
                }
            },
            "explanation": {"type": "string"}
        },
        "required": ["table_name","rows"],
        "additionalProperties": False
    }
}


#
# 8) chat_block
#
class ChatBlockArguments(BaseModel):
    user_prompt: str
    context: Optional[str] = None

chat_block_schema = {
    "name": "chat_block",
    "description": (
        "Perform an open-ended chat or reasoning step. "
        "We supply 'user_prompt' plus optional 'context'. "
        "Return { response_text:'...' }."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_prompt": {"type": "string"},
            "context": {"type": "string"}
        },
        "required": ["user_prompt"],
        "additionalProperties": False
    }
}


#
# 9) reflect_block (NEW)
#
class ReflectBlockArguments(BaseModel):
    reasoning: str
    final_message: Optional[str] = None
    data_output: Optional[Any] = None
    additional_tasks: Optional[List[PlanTaskItem]] = None

reflect_block_schema = {
    "name": "reflect_block",
    "description": (
        "Reflect on the entire task memory. "
        "You can optionally provide final_message to end, data_output if you want to return structured data, "
        "or additional_tasks if more steps are needed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "Your chain-of-thought or reflection"
            },
            "final_message": {
                "type": "string",
                "description": "Optional user-facing text to finalize if done"
            },
            "data_output": {
                "type": "object",
                "description": "Optional structured data to return with final_message"
            },
            "additional_tasks": {
                "type": "array",
                "description": "Optional new tasks to add if more steps are needed",
                "items": {
                    "type": "object",
                    "properties": {
                        "block": {"type": "string"},
                        "description": {"type": "string"},
                        "title": {"type": "string"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["block","description","title","reasoning"]
                }
            }
        },
        "required": ["reasoning"],
        "additionalProperties": False
    }
}


ALL_FUNCTION_SCHEMAS = [
    plan_tasks_schema,
    sql_block_schema,
    output_block_schema,
    parse_block_schema,
    batch_insert_block_schema,
    batch_update_block_schema,
    batch_delete_block_schema,
    chat_block_schema,
    reflect_block_schema  # <-- newly added
]
