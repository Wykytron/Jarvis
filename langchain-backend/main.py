from fastapi import FastAPI, UploadFile, File, Form
from typing import Optional
import os
from dotenv import load_dotenv
import openai
import uuid
import tempfile
import whisper

from openai import OpenAI  # If using the new v1 Python library
import base64

from database import SessionLocal, ChatExchange  # <-- Make sure you have these

# If you're using LangChain's ChatOpenAI:
from langchain.chat_models import ChatOpenAI

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

# Transcription endpoint (local Whisper as example)
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


@app.post("/api/chat")
async def chat_endpoint(
    message: str = Form(...),
    model: str = Form("gpt-4o-mini"),   # default to a vision-capable model
    file: UploadFile = File(None)       # optional image file
):
    """
    - If `file` is present, treat it as an image to be sent to GPT for analysis.
    - Otherwise, just send text.
    - Return the GPT response.
    """
    # 1) Build content array with the user text
    content_parts = [
        {"type": "text", "text": message.strip()}
    ]

    # 2) If there's an uploaded image, base64-encode it
    if file is not None:
        image_bytes = await file.read()
        b64_str = base64.b64encode(image_bytes).decode("utf-8")
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{b64_str}"
            }
        })

    # 3) Call GPT using the new v1 Python client
    #    (If you prefer the older approach w/ ChatOpenAI + LangChain, adapt similarly.)
    client = OpenAI(api_key=openai.api_key)

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
        # Extract the text from the assistant
        llm_message = response.choices[0].message.content
    except Exception as e:
        print("Error calling GPT model:", e)
        llm_message = "(Error calling model.)"

    # 4) Optionally store in your DB
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

