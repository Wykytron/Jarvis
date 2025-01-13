# backend/agent/agent_router.py
from fastapi import APIRouter, Body
from .orchestrator import run_agent

router = APIRouter()

@router.post("/agent")
def agent_endpoint(user_input: str = Body(..., embed=True)):
    """
    The front-end can call POST /api/agent { "user_input": "...some text..." }
    We'll run plan -> blocks -> final answer.
    """
    final_answer = run_agent(user_input)
    return {"final_answer": final_answer}
