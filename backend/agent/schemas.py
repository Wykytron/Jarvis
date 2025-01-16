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
# 2) sql_block
#
class SQLBlockArguments(BaseModel):
    table_name: str
    columns: List[str]  # e.g. ["name","quantity","unit","expiration_date","category"]
    values: List[str]   # e.g. ["'Joghurt'","2","'unit'","'2025-01-25'","'dairy'"]
    action_type: Literal["SELECT", "INSERT", "UPDATE", "DELETE"]
    explanation: str = ""
    where_clause: Optional[str] = None  # for updates/deletes

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
            "where_clause": {
                "type": "string",
                "description": "e.g. WHERE name='tomatoes'"
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
    # NEW: allow the LLM to pass db_rows if it wants
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
                "items": {"type": "object"},
                "description": "If we need to parse/fill data from a prior SELECT query"
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
        "Insert multiple rows into one table in a single call. "
        "No disclaimers, only valid JSON. "
        "If user says 'Add multiple items at once', produce an array of {columns, values}."
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

class BatchUpdateRow(BaseModel):
    where_clause: str            # e.g. "WHERE id=6"
    columns: List[str]
    values: List[str]

class BatchUpdateBlockArguments(BaseModel):
    table_name: str
    rows: List[BatchUpdateRow]
    explanation: str = ""

batch_update_block_schema = {
    "name": "batch_update_block",
    "description": (
        "Update multiple rows in one table in a single call. "
        "If user says 'Update multiple fridge items at once', produce an array of row updates."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "e.g. 'fridge_items'"
            },
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "where_clause": {
                            "type": "string",
                            "description": "WHERE clause, e.g. 'WHERE id=7'"
                        },
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
                },
                "description": "List of row-level updates"
            },
            "explanation": {
                "type": "string",
                "description": "Reasoning or comment about these updates"
            }
        },
        "required": ["table_name","rows"],
        "additionalProperties": False
    }
}

class BatchDeleteRow(BaseModel):
    where_clause: str  # e.g. "WHERE id=5" or "WHERE name='spinach'"

class BatchDeleteBlockArguments(BaseModel):
    table_name: str
    rows: List[BatchDeleteRow]  # each row just has a where_clause
    explanation: str = ""

batch_delete_block_schema = {
    "name": "batch_delete_block",
    "description": (
        "Delete multiple rows from one table in a single call. "
        "If user says 'Remove these 5 items at once,' produce something like:\n"
        "{\n"
        '  "table_name": "fridge_items",\n'
        '  "rows": [\n'
        '     {"where_clause":"WHERE id=7"},\n'
        '     {"where_clause":"WHERE name=\'spinach\'"}\n'
        '   ],\n'
        '  "explanation":"Deleting multiple items at once."\n'
        '}'
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "The DB table to delete from, e.g. 'fridge_items'"
            },
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "where_clause": {
                            "type": "string",
                            "description": "WHERE clause, e.g. 'WHERE name=\\'spinach\\''"
                        }
                    },
                    "required": ["where_clause"]
                },
                "description": "List of row-level deletes"
            },
            "explanation": {
                "type": "string",
                "description": "Reason or comment about these deletions"
            }
        },
        "required": ["table_name","rows"],
        "additionalProperties": False
    }
}

class ChatBlockArguments(BaseModel):
    user_prompt: str                 # The question or text the user (or system) wants to feed into chat
    context: Optional[str] = None    # If we have an optional large context

chat_block_schema = {
    "name": "chat_block",
    "description": (
        "Perform an open-ended chat or reasoning step. "
        "We supply 'user_prompt' plus optional 'context'. "
        "In response, produce text in 'response_text' if needed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_prompt": {
                "type": "string",
                "description": "The user or system query we want to chat or reason about"
            },
            "context": {
                "type": "string",
                "description": "Optional large context or relevant background we want to feed the model"
            }
        },
        "required": ["user_prompt"],
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
    chat_block_schema
]
