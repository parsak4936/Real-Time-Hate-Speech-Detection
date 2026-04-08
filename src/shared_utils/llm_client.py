import ollama
from openai import OpenAI # Most cloud OSS models use OpenAI-compatible APIs
from .config import MODEL_MODE, LOCAL_MODEL, CLOUD_MODEL, CLOUD_API_KEY, CLOUD_API_URL

def ask_ai(prompt):
    if MODEL_MODE == "cloud":
        client = OpenAI(api_key=CLOUD_API_KEY, base_url=CLOUD_API_URL)
        response = client.chat.completions.create(
            model=CLOUD_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    else:
        # Fallback to local Ollama
        response = ollama.chat(model=LOCAL_MODEL, messages=[
            {'role': 'user', 'content': prompt}
        ])
        return response['message']['content']