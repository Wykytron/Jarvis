# backend/main.py

import os
import base64
import uuid
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, Body
from sqlalchemy import desc

from database import SessionLocal, ChatExchange, Document
from parser_utils import parse_file
from vectorstore import ingest_document, query_docs

# NEW: from openai import OpenAI for v1.x usage
from openai import OpenAI

# Create a global client using the new approach
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()


@app.post("/api/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    whisper_model: str = Form("base")
):
    """
    Local Whisper usage example.
    """
    try:
        import whisper
        import tempfile

        audio_bytes = await file.read()
        temp_dir = tempfile.gettempdir()
        temp_id = str(uuid.uuid4())
        temp_path = os.path.join(temp_dir, f"{temp_id}.wav")

        with open(temp_path, "wb") as f:
            f.write(audio_bytes)

        model_w = whisper.load_model(whisper_model)
        result = model_w.transcribe(temp_path)
        os.remove(temp_path)

        return {"transcript": result["text"]}
    except Exception as e:
        print("Transcribe error:", e)
        return {"transcript": ""}


@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    model: str = Form("gpt-4o-mini"),
    file: UploadFile = File(None)
):
    content_parts = [
        {"type": "text", "text": message.strip()}
    ]
    if file is not None:
        image_bytes = await file.read()
        b64_str = base64.b64encode(image_bytes).decode("utf-8")
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64_str}"
            }
        })

    #client = OpenAI(api_key=openai.api_key)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": content_parts
                }
            ],
        )
        llm_message = response.choices[0].message.content
    except Exception as e:
        print("Error calling GPT model:", e)
        llm_message = "(Error calling model.)"

    db = SessionLocal()
    try:
        new_exchange = ChatExchange(
            user_message=message,
            llm_response=llm_message
        )
        db.add(new_exchange)
        db.commit()
        db.refresh(new_exchange)
    finally:
        db.close()

    return {"response": llm_message}

@app.get("/api/history")
def get_chat_history(limit: int = 20):
    """
    Return last 'limit' chat logs, including base64 images.
    The front-end can re-display them.
    """
    db = SessionLocal()
    try:
        rows = db.query(ChatExchange).order_by(ChatExchange.timestamp.desc()).limit(limit).all()
        rows.reverse()

        out = []
        for r in rows:
            item = {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "user_message": r.user_message or "",
                "llm_response": r.llm_response or ""
            }
            if r.user_image_b64:
                item["user_image_b64"] = r.user_image_b64
            out.append(item)

        return {"history": out}
    finally:
        db.close()


@app.post("/api/ingest")
async def ingest_endpoint(
    file: UploadFile = File(None),
    url: str = Form(None),
    description: str = Form(None)   # user-provided
):
    """
    Accept either a file or a url, plus optional 'description'.
    parse + store in DB + chunk+embed.
    """
    if url:
        text_content = parse_url(url)
        raw_bytes = text_content.encode("utf-8", errors="ignore")
        filename = f"webpage-{uuid.uuid4()}.html"
    elif file:
        raw_bytes = await file.read()
        extension = file.filename.split(".")[-1].lower() if file.filename else "txt"
        text_content = parse_file(raw_bytes, extension)
        filename = file.filename or f"unknown-{uuid.uuid4()}"
    else:
        return {"error": "Must provide either 'file' or 'url'."}

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
            "text_length": len(text_content),
            "description": description
        }
    finally:
        db.close()


@app.post("/api/search_docs")
def search_docs_endpoint(
    query: str = Body(..., embed=True),
    top_k: int = Body(3, embed=True)
):
    results = query_docs(query, top_k=top_k)
    return {"results": results}