# main.py

from fastapi import FastAPI, UploadFile, File, Form, Body
import os
import base64
import uuid
import re
from dotenv import load_dotenv
from datetime import datetime

from database import SessionLocal, ChatExchange, Document
from vectorstore import ingest_document, query_docs
from parser_utils import parse_file

# Import the orchestrator "run_agent"
from agent.orchestrator import run_agent

import openai
import logging

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

###############################################################################
# LOGGING SETUP
###############################################################################
logging.basicConfig(
    level=logging.INFO,  # or DEBUG if needed
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("agent")


###############################################################################
# 1) /api/image_recognize
###############################################################################
@app.post("/api/image_recognize")
async def image_recognize_endpoint(
    file: UploadFile = File(...),
    user_prompt: str = Form(""),
    model: str = Form("gpt-4o-mini")
):
    """
    Example route for image recognition. 
    1) Convert image to base64
    2) Possibly pass to an image-based model
    3) Store results
    """
    db = SessionLocal()
    try:
        # (A) Base64-encode the image
        raw_img = await file.read()
        user_image_b64 = base64.b64encode(raw_img).decode("utf-8")

        # (B) Build content parts (prompt + image)
        content_parts = []
        if user_prompt.strip():
            content_parts.append({"type": "text", "text": user_prompt.strip()})
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{user_image_b64}"}
        })

        # (C) The instructions for the image model
        instructions = (
            "You are an expert image recognition AI. The user may provide a prompt + image. "
            "If no additional prompt is provided, put something like 'How can I help you with this image?' "
            "into the <Response> section.\n"
            "Return EXACT:\n<Title>...</Title>\n<Description>...</Description>\n<Response>...</Response>\n"
        )

        # (D) Call the model
        from openai import OpenAI
        client = OpenAI(api_key=openai.api_key)

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": content_parts},
                ],
                max_tokens=400,
                temperature=0.7
            )
            llm_text = resp.choices[0].message.content or ""
        except Exception as e:
            logger.error("Error calling the image model: %s", e)
            return {"error": f"Model call failed: {str(e)}"}

        # (E) Parse <Title>, <Description>, <Response>
        title_match = re.search(r"<Title>(.*?)</Title>", llm_text, re.DOTALL)
        desc_match = re.search(r"<Description>(.*?)</Description>", llm_text, re.DOTALL)
        resp_match = re.search(r"<Response>(.*?)</Response>", llm_text, re.DOTALL)

        image_title = title_match.group(1).strip() if title_match else ""
        image_desc = desc_match.group(1).strip() if desc_match else ""
        final_response = resp_match.group(1).strip() if resp_match else llm_text

        # (F) Save to DB
        new_ex = ChatExchange(
            user_message=user_prompt,
            llm_response=final_response,
            user_image_b64=user_image_b64,
            image_title=image_title,
            image_description=image_desc
        )
        db.add(new_ex)
        db.commit()
        db.refresh(new_ex)

        # (G) Also store + embed the image_desc in documents
        new_doc = Document(
            filename=f"image_{new_ex.id}.jpg",
            file_content=raw_img,
            text_content=image_desc,
            description=image_title
        )
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)

        # optional: vector-store indexing
        if image_desc.strip():
            ingest_document(new_doc.id, image_desc)

        return {
            "title": image_title,
            "description": image_desc,
            "response": final_response,
            "exchange_id": new_ex.id
        }
    finally:
        db.close()


###############################################################################
# 2) /api/chat => text-based short-term memory
###############################################################################
@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    model: str = Form("gpt-3.5-turbo")
):
    """
    If user only sends text => short-term memory approach.
    We'll fetch last N messages from DB, passing any 'image_description' as context.
    The model can see ~5 prior user/assistant messages.
    """
    ROLLING_WINDOW_SIZE = 5
    db = SessionLocal()
    try:
        old_exs = db.query(ChatExchange) \
                    .order_by(ChatExchange.timestamp.desc()) \
                    .limit(ROLLING_WINDOW_SIZE).all()
        old_exs.reverse()

        system_msg = {
            "role": "system",
            "content": "You are a helpful text-based assistant. You recall the last few messages."
        }
        conversation = [system_msg]

        for exch in old_exs:
            user_txt = exch.user_message.strip() if exch.user_message else ""
            if exch.image_description and exch.image_description.strip():
                user_txt += f"\n[Previous Image Description: {exch.image_description.strip()}]"

            if user_txt.strip():
                conversation.append({"role": "user", "content": user_txt})

            if exch.llm_response and exch.llm_response.strip():
                conversation.append({"role": "assistant", "content": exch.llm_response.strip()})

        # add the new user text
        conversation.append({"role": "user", "content": message.strip()})

        from openai import OpenAI
        client = OpenAI(api_key=openai.api_key)

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=conversation,
                max_tokens=400,
                temperature=0.7
            )
            llm_msg = resp.choices[0].message.content
        except Exception as e:
            logger.error("Error calling text model: %s", e)
            llm_msg = "(Error calling text model.)"

        # store the conversation
        new_ex = ChatExchange(user_message=message, llm_response=llm_msg)
        db.add(new_ex)
        db.commit()
        db.refresh(new_ex)

        return {"response": llm_msg}
    finally:
        db.close()


###############################################################################
# 3) /api/history => returns text + optional image
###############################################################################
@app.get("/api/history")
def get_chat_history():
    """
    Simple route to return all ChatExchange rows in ascending timestamp order.
    """
    db = SessionLocal()
    try:
        rows = db.query(ChatExchange).order_by(ChatExchange.timestamp.asc()).all()
        hist = []
        for r in rows:
            item = {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "user_message": r.user_message or "",
                "llm_response": r.llm_response or ""
            }
            if r.user_image_b64:
                item["user_image_b64"] = r.user_image_b64
            if r.image_title:
                item["image_title"] = r.image_title
            if r.image_description:
                item["image_description"] = r.image_description
            hist.append(item)
        return {"history": hist}
    finally:
        db.close()


###############################################################################
# 4) /api/ingest => doc ingestion
###############################################################################
@app.post("/api/ingest")
async def ingest_endpoint(
    file: UploadFile = File(...),
    description: str = Form(None)
):
    """
    Example route for ingesting a file, extracting text, storing in DB, then
    indexing into a vector store for semantic search.
    """
    raw_bytes = await file.read()
    filename = file.filename or f"unknown-{uuid.uuid4()}"
    extension = filename.rsplit(".", 1)[-1].lower()
    text_content = parse_file(raw_bytes, extension)

    if not description or not description.strip():
        base_name = filename.rsplit(".", 1)[0]
        description = base_name

    db = SessionLocal()
    try:
        new_doc = Document(
            filename=filename,
            file_content=raw_bytes,
            text_content=text_content,
            description=description
        )
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)

        doc_id = new_doc.id
        if text_content.strip():
            ingest_document(doc_id, text_content)

        return {
            "status": "ok",
            "doc_id": doc_id,
            "filename": filename,
            "description": description,
            "text_length": len(text_content)
        }
    finally:
        db.close()


###############################################################################
# 5) /api/search_docs => vector search
###############################################################################
@app.post("/api/search_docs")
def search_docs_endpoint(
    query: str = Body(..., embed=True),
    top_k: int = Body(3, embed=True)
):
    """
    Return the top_k similar documents from the vector store.
    """
    results = query_docs(query, top_k=top_k)
    return {"results": results}


###############################################################################
# 6) /api/agent => The new Agent endpoint
###############################################################################
@app.post("/api/agent")
def agent_endpoint(user_input: str = Body(..., embed=True), chosen_model: str = Body("gpt-3.5-turbo", embed=True)):
    logger.info(f"Received user_input for agent: {user_input}")
    # If the frontend sends a model name in the same payload, store it in memory so orchestrator can use it
    task_memory = {}
    if chosen_model and chosen_model.strip():
        task_memory["agent_model"] = chosen_model.strip()

    final_answer, debug_info = run_agent(user_input, task_memory)
    logger.info(f"Final answer from agent: {final_answer}")

    return {
        "final_answer": final_answer,
        "debug_info": debug_info
    }
