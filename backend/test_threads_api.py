import os
import base64
from openai import OpenAI

def main():
    # 1) Initialize the OpenAI client
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    client = OpenAI(api_key=openai_api_key)

    # 2) Read and encode the local image (photo.jpg in the root folder)
    with open("photo.jpg", "rb") as f:
        image_data = f.read()

    # 3) Convert image bytes to base64
    b64_str = base64.b64encode(image_data).decode("utf-8")

    # 4) Specify the MIME type (assuming JPEG)
    mime_type = "image/jpeg"

    # 5) Create the user message with text + a base64-encoded image
    user_content = [
        {"type": "text", "text": "Analyze this local photo for me."},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{b64_str}",
            },
        },
    ]

    # 6) Call the chat completions endpoint with a vision-capable model
    response = client.chat.completions.create(
        model="gpt-4o-mini",  # Or whichever GPT-4o variant you have
        messages=[
            {
                "role": "user",
                "content": user_content,
            }
        ],
    )

    # 7) Print the entire response (or just the assistant's output)
    print(response)

if __name__ == "__main__":
    main()
