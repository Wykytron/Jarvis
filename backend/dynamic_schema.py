# dynamic_schema.py

from database import SessionLocal
from sqlalchemy import text

def build_table_schemas() -> dict:
    """
    Programmatically queries the DB to get table -> list of columns.
    Returns something like:
    {
      "fridge_items": ["id","name","quantity","unit","expiration_date","category"],
      "shopping_items": ["id","name","desired_quantity","unit","purchased"],
      ...
    }
    """
    db = SessionLocal()
    table_schemas = {}

    # Query all table names from sqlite_master, using text() for explicit text SQL
    table_rows = db.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).fetchall()
    all_tables = [r[0] for r in table_rows]

    for tbl in all_tables:
        if tbl.startswith("sqlite_"):
            continue

        # 'PRAGMA table_info(<table>)' returns tuples in the format:
        # (cid, name, type, notnull, dflt_value, pk)
        # index 1 => the column's name
        col_info = db.execute(text(f"PRAGMA table_info({tbl})")).fetchall()
        col_names = [row[1] for row in col_info]  # row[1] is the column name

        table_schemas[tbl] = col_names

    db.close()
    return table_schemas
