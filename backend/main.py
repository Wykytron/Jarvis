# main.py
from fastapi import FastAPI, UploadFile, File, Form, Body
import os
from dotenv import load_dotenv
import openai
import uuid
import tempfile
import whisper
import base64
from io import BytesIO
import re  # for removing file extension

from database import SessionLocal, ChatExchange, Document
from vectorstore import ingest_document, query_docs
from parser_utils import parse_file, parse_url

from openai import OpenAI

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
print("DEBUG KEY:", openai.api_key)

app = FastAPI()

# --------------------
# TRANSCRIBE
# --------------------
@app.post("/api/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    whisper_model: str = Form("base")
):
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


# --------------------
# CHAT (unchanged logic for images)
# --------------------
@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    model: str = Form("gpt-4o-mini"),
    file: UploadFile = File(None)
):
    """
    EXACT old snippet with content_parts for images
    but using the new library call (client.chat.completions.create).
    """
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

    client = OpenAI(api_key=openai.api_key)  # same new library approach
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


# --------------------
# HISTORY
# --------------------
@app.get("/api/history")
def get_chat_history():
    db = SessionLocal()
    try:
        exchanges = db.query(ChatExchange).order_by(ChatExchange.timestamp.asc()).all()
        history = [
            {
                "id": exch.id,
                "user_message": exch.user_message,
                "llm_response": exch.llm_response,
                "timestamp": exch.timestamp.isoformat()
            }
            for exch in exchanges
        ]
        return {"history": history}
    finally:
        db.close()


# --------------------
# INGEST
# --------------------
@app.post("/api/ingest")
async def ingest_endpoint(
    file: UploadFile = File(None),
    url: str = Form(None),
    description: str = Form(None)
):
    """
    Accept either a file or a url, plus an optional description.
    If user doesn't provide a description, we auto-set it to the filename (minus extension).
    """
    if url:
        # parse url text
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

    # If no description or user typed nothing,
    # let's set description = filename minus extension
    if (not description) or (not description.strip()):
        # remove extension with a regex or rsplit
        # e.g. "file.pdf" => "file"
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
            "text_length": len(text_content),
            "description": description
        }
    finally:
        db.close()


# --------------------
# SEARCH DOCS
# --------------------
@app.post("/api/search_docs")
def search_docs_endpoint(
    query: str = Body(..., embed=True),
    top_k: int = Body(3, embed=True)
):
    results = query_docs(query, top_k=top_k)
    return {"results": results}
