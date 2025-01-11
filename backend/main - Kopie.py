import os
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from langchain.llms import OpenAI  # Or use langchain_openai if you'd like
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

load_dotenv()
openai_api_key = os.getenv("OPENAI_API_KEY", "")

app = FastAPI()

class PromptRequest(BaseModel):
    prompt: str
    image: Optional[str] = None  # Base64 string if provided

# Simple prompt
template = PromptTemplate(
    input_variables=["user_input"],
    template="You are a helpful AI. User says: {user_input}"
)

llm = OpenAI(
    openai_api_key=openai_api_key,
    temperature=0.7
)
chain = LLMChain(llm=llm, prompt=template)

@app.post("/ask")
async def ask_llm(request: PromptRequest):
    """
    1) If an image is provided, we can either store or do something with it.
    2) Use LangChain to generate a response from the user's prompt.
    """
    user_input = request.prompt
    base64_image = request.image  # This might be None if user didn't send an image

    # For now, just print if we got an image
    if base64_image:
        print("Received an image (base64) of length:", len(base64_image))
        # If you want to store it, decode and save to a file or pass it to an image-processing API.

    # Process the prompt with LangChain
    response = chain.run(user_input)

    return {"answer": response}
