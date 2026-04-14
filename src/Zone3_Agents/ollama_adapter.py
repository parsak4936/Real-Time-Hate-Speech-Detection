# src/agents/ollama_adapter.py
import json, ollama
from .base_adapters import ModelAdapter
from shared_utils.config import OLLAMA_MODEL

class OllamaAdapter(ModelAdapter):
    def __init__(self, model_name: str = OLLAMA_MODEL):
        self.model = model_name

    def _chat(self, system: str, user: str) -> str:
        resp = ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
        )
        return resp["message"]["content"].strip()

    def predict(self, text: str) -> dict:
        system = ("You are a binary hate‑speech classifier. "
                  "Respond ONLY with JSON of the form "
                  '{"label": "HATE" | "NOT_HATE", "score": <float 0‑1>}.')
        user = f'Classify this text: """{text}"""'
        raw = self._chat(system, user)

        # Very tolerant parsing – if the model forgets braces we try again
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # fallback: ask the model to re‑output clean JSON
            payload = json.loads(self._chat(system, f"Please re‑output valid JSON for: {raw}"))
        return {
            "label": payload.get("label", "UNKNOWN"),
            "score": float(payload.get("score", 0.0)),
            "raw_output": raw
        }

    def explain(self, text: str) -> str:
        system = ("You are an XAI assistant. "
                  "Give a short token‑level heat‑map that justifies the classification you just made. "
                  "Use the format **word**(+0.23) or **word**(-0.12).")
        user = f'Text: """{text}"""'
        return self._chat(system, user)
