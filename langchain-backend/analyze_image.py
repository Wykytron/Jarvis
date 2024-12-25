import openai
import base64

openai.api_key = 'YOUR_API_KEY'

def analyze_image(image_path):
    # Read the image file
    with open(image_path, 'rb') as image_file:
        image_data = image_file.read()

    # Convert the image to base64
    image_base64 = base64.b64encode(image_data).decode('utf-8')

    # Send the image to OpenAI API for analysis
    response = openai.Completion.create(
        model="gpt-4",  # Replace this with the correct model that supports image inputs
        messages=[
            {"role": "system", "content": "Analyze the following image"},
            {"role": "user", "content": image_base64}
        ]
    )

    # Get the analysis result
    if response['choices']:
        result = response['choices'][0]['message']['content']
        return result
    else:
        return "Error: Unable to analyze the image."

# Test the function
if __name__ == "__main__":
    result = analyze_image("photo.jpg")
    print(result)
