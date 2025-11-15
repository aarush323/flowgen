import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME")
API_URL = os.getenv("OPENROUTER_API_URL")

def track_usage(response):
    """Track token usage from OpenRouter response"""
    usage = response.get("usage", {})
    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0)
    }

class OpenRouterClient:
    def __init__(self):
        if not API_KEY:
            raise ValueError("Missing OPENROUTER_API_KEY in .env")
        if not MODEL_NAME:
            raise ValueError("Missing MODEL_NAME in .env")
        if not API_URL:
            raise ValueError("Missing OPENROUTER_API_URL in .env")

    def generate(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "FlowGen",
        }

        body = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        response = requests.post(API_URL, json=body, headers=headers)

        # explicit error exposure
        try:
            response.raise_for_status()
        except Exception:
            print("❌ Error from OpenRouter:", response.text)
            raise

        data = response.json()

        # normalize all output cases
        choices = data.get("choices")
        if not choices:
            raise ValueError("OpenRouter returned no choices")

        msg = choices[0].get("message")
        if not msg:
            raise ValueError("OpenRouter returned no message in choices[0]")

        content = msg.get("content")
        if not content:
            raise ValueError("OpenRouter returned empty message content")

        return content
