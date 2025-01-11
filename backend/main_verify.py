# main.py

import os
import uuid
import base64
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional

from dotenv import load_dotenv
import openai
import whisper

# Use async SQLAlchemy session (example)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from database import ChatExchange  # <-- Adjust your import for the async model
# from langchain.chat_models import ChatOpenAI   # If using LangChain

load_dotenv()

# --------------- CHECK ENV VARS AT STARTUP ---------------
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

openai.api_key = os.getenv("OPENAI_API_KEY")

# --------------- SETUP ASYNC DB SESSION ---------------
DATABASE_URL = "sqlite+aiosqlite:///./test.db"  # Example: switch to your DB URL
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# --------------- PRE-LOAD / CACHE WHISPER MODELS ---------------
transcribe_models = {}

def load_whisper_model(model_name: str = "base"):
    """
    Caches and returns a whisper model instance to avoid repeated loading.
    """
    if model_name not in transcribe_models:
        try:
            transcribe_models[model_name] = whisper.load_model(model_name)
        except Exception as e:
            raise RuntimeError(f"Error loading Whisper model '{model_name}': {e}")
    return transcribe_models[model_name]

# Optionally load a default model at startup
# (If you expect frequent requests with "base" model)
try:
    load_whisper_model("base")
except RuntimeError as e:
    raise RuntimeError(str(e))

app = FastAPI()

# ----------------- HELPER FOR FILE VALIDATION -----------------
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3"}

async def validate_audio_file(file: UploadFile):
    # Check file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {MAX_FILE_SIZE} bytes limit."
        )
    # Check file type (MIME)
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Please upload WAV or MP3."
        )
    # Reset file read pointer so we can use content again
    return content

# --------------- TRANSCRIBE ENDPOINT ---------------
@app.post("/api/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    whisper_model: str = Form("base")
):
    """
    Transcribe the uploaded audio using a preloaded/cached Whisper model.
    """
    # Validate file size and MIME type
    audio_bytes = await validate_audio_file(file)

    # Write temp file for Whisper
    temp_dir = tempfile.gettempdir()
    temp_id = str(uuid.uuid4())
    temp_path = os.path.join(temp_dir, f"{temp_id}.wav")

    with open(temp_path, "wb") as f:
        f.write(audio_bytes)

    # Use cached Whisper model
    try:
        model_w = load_whisper_model(whisper_model)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Perform transcription
    try:
        result = model_w.transcribe(temp_path)
    except Exception as e:
        os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"Transcription error: {str(e)}")

    os.remove(temp_path)
    return {"transcript": result.get("text", "")}

# --------------- CHAT ENDPOINT ---------------
@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    model: str = Form("gpt-4o-mini"),  # default model name
    file: UploadFile = File(None)
):
    """
    - If `file` is present, treat it as an image to be sent to GPT for analysis.
    - Otherwise, just send text.
    - Return the GPT response.
    """
    content_parts = [{"type": "text", "text": message.strip()}]

    # If an image is uploaded, convert to base64 for GPT
    if file is not None:
        image_bytes = await file.read()
        b64_str = base64.b64encode(image_bytes).decode("utf-8")
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_str}"}
        })

    # Using the new "OpenAI" class as shown in the snippet:
    # If your OpenAI library doesn't have this, adapt to the official usage.
    from openai import OpenAI
    client = OpenAI(api_key=openai.api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content_parts}],
        )
        llm_message = response.choices[0].message.content
    except Exception as e:
        return JSONResponse({"error": f"Error calling GPT model: {str(e)}"}, status_code=500)

    # Store exchange in async DB
    async with async_session() as db:
        async with db.begin():
            new_exchange = ChatExchange(
                user_message=message,
                llm_response=llm_message
            )
            db.add(new_exchange)

    return {"response": llm_message}

# --------------- HISTORY ENDPOINT ---------------
@app.get("/api/history")
async def get_chat_history():
    """
    Retrieve all chat exchanges, sorted by timestamp ascending.
    """
    async with async_session() as db:
        result = await db.execute(
            """
            SELECT id, user_message, llm_response, timestamp
            FROM chat_exchange
            ORDER BY timestamp ASC
            """
        )
        exchanges = result.fetchall()

    history = [
        {
            "id": exch[0],
            "user_message": exch[1],
            "llm_response": exch[2],
            "timestamp": exch[3].isoformat() if exch[3] else None
        }
        for exch in exchanges
    ]
    return {"history": history}
