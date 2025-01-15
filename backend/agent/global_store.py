# agent/global_store.py

import datetime

# The dictionary or data structure for table schemas:
TABLE_SCHEMAS = {}

# We'll store a function reference that returns the current datetime
#CURRENT_DATETIME_FN = None

def get_now():
    """Default function that returns current datetime."""
    return datetime.datetime.now()

CURRENT_DATETIME_FN = get_now
