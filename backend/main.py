# main.py
from fastapi import FastAPI, UploadFile, File, Form, Body
import os
import openai
import base64
import uuid
import re
from dotenv import load_dotenv
from datetime import datetime

from database import SessionLocal, ChatExchange, Document
from vectorstore import ingest_document, query_docs
from parser_utils import parse_file

from openai import OpenAI

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()


# -------------------------------------------------------------
# 1) /api/image_recognize
#    Provide the image via "content_parts" + system message
#    => always produce <Title>, <Description>, <Response>.
# -------------------------------------------------------------
@app.post("/api/image_recognize")
async def image_recognize_endpoint(
    file: UploadFile = File(...),
    user_prompt: str = Form(""),
    model: str = Form("gpt-4o-mini")
):
    """
    1) We pass content_parts to the model so it can 'see' the image (like your old snippet).
    2) We also add a system instruction requiring <Title>, <Description>, <Response>.
    3) The model returns them, which we parse & store in DB.
    4) We always return them in the response so the frontend can display each.
    """
    db = SessionLocal()
    try:
        # (A) Base64-encode the image
        raw_img = await file.read()
        user_image_b64 = base64.b64encode(raw_img).decode("utf-8")

        # (B) Build content_parts (like old approach)
        content_parts = []
        if user_prompt.strip():
            content_parts.append({
                "type": "text",
                "text": user_prompt.strip()
            })
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{user_image_b64}"
            }
        })

        # (C) System message: demand Title, Description, Response
        instructions = (
            "You are an expert image recognition AI. The user may provide a prompt + image. If no additional prompt is provided, put something like 'How can i help you with this image?' into the <Response> section. \n"
            "You MUST return the results in this EXACT format:\n"
            "<Title>...</Title>\n"
            "<Description>...</Description>\n"
            "<Response>...</Response>\n"
            "Where:\n"
            "- <Title> is a short name for the image.\n"
            "- <Description> is a factual description of the image.\n"
            "- <Response> addresses the user's prompt or question about the image.\n"
        )

        # (D) Call your custom model
        client = OpenAI(api_key=openai.api_key)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": content_parts}
                ],
                max_tokens=400,
                temperature=0.7
            )
            llm_text = response.choices[0].message.content or ""
        except Exception as e:
            print("Error calling the image model:", e)
            return {"error": f"Model call failed: {str(e)}"}

        # (E) Parse <Title>, <Description>, <Response>
        title_match = re.search(r"<Title>(.*?)</Title>", llm_text, re.DOTALL)
        desc_match = re.search(r"<Description>(.*?)</Description>", llm_text, re.DOTALL)
        resp_match = re.search(r"<Response>(.*?)</Response>", llm_text, re.DOTALL)

        image_title = title_match.group(1).strip() if title_match else ""
        image_desc = desc_match.group(1).strip() if desc_match else ""
        final_response = resp_match.group(1).strip() if resp_match else llm_text

        # (F) Save to DB (ChatExchange)
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

        # (G) Also store + embed the image_desc as doc
        new_doc = Document(
            filename=f"image_{new_ex.id}.jpg",
            file_content=raw_img,
            text_content=image_desc,
            description=image_title
        )
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)

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


# -------------------------------------------------------------
# 2) /api/chat => text-only short-term memory
# -------------------------------------------------------------
@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    model: str = Form("gpt-3.5-turbo")
):
    """
    If user only sends text => short-term memory approach.
    We'll fetch last N from DB, passing any 'image_description'
    from previous images as additional user text, so the LLM knows context.
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

        # new user text
        conversation.append({"role": "user", "content": message.strip()})

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
            print("Error calling text model:", e)
            llm_msg = "(Error calling text model.)"

        # store
        new_ex = ChatExchange(
            user_message=message,
            llm_response=llm_msg
        )
        db.add(new_ex)
        db.commit()
        db.refresh(new_ex)

        return {"response": llm_msg}
    finally:
        db.close()


# -------------------------------------------------------------
# 3) /api/history => returns text + optional image
# -------------------------------------------------------------
@app.get("/api/history")
def get_chat_history():
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


# -------------------------------------------------------------
# 4) /api/ingest => doc ingestion
# -------------------------------------------------------------
@app.post("/api/ingest")
async def ingest_endpoint(
    file: UploadFile = File(...),
    description: str = Form(None)
):
    raw_bytes = await file.read()
    filename = file.filename or f"unknown-{uuid.uuid4()}"
    extension = filename.rsplit(".",1)[-1].lower()
    text_content = parse_file(raw_bytes, extension)

    if not description or not description.strip():
        base_name = filename.rsplit(".",1)[0]
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


# -------------------------------------------------------------
# 5) /api/search_docs => vector search
# -------------------------------------------------------------
@app.post("/api/search_docs")
def search_docs_endpoint(
    query: str = Body(..., embed=True),
    top_k: int = Body(3, embed=True)
):
    results = query_docs(query, top_k=top_k)
    return {"results": results}
