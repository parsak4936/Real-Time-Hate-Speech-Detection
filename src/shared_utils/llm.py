"""
Thin Ollama wrapper used by every Tier-2 agent.

Centralises three concerns that were previously duplicated across modules
and silently inconsistent:

1. temperature is pinned to 0.0 — the report (§4.4) cites deterministic
   inference; ollama's default of 0.8 contradicted that.
2. format="json" — guarantees Ollama returns syntactically valid JSON,
   eliminating the brittle markdown-fence stripping that used to live
   in every agent.
3. One automatic retry on json.JSONDecodeError, re-prompting the model
   with the parser error. Failures past the retry surface as None.

The synthesis-style "free text" leader response uses ollama_chat_text
which keeps temperature=0 but does NOT force JSON.
"""

import json
import ollama

from shared_utils.config import ACTIVE_MODEL


def ollama_chat_json(prompt: str, model: str = ACTIVE_MODEL):
    """
    Send a single user-turn prompt to Ollama and parse the response as JSON.

    Retries once with the parse error embedded if the first response is
    not valid JSON. Returns the parsed dict on success, or None on
    repeated failure.
    """
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(2):
        response = ollama.chat(
            model=model,
            messages=messages,
            options={"temperature": 0.0},
            format="json",
        )
        raw = response["message"]["content"].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if attempt == 0:
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous response was not valid JSON ({exc}). "
                        "Output ONLY the JSON object with no surrounding text, "
                        "markdown, or commentary."
                    ),
                })
                continue
            return None


def ollama_chat_text(prompt: str, model: str = ACTIVE_MODEL) -> str:
    """Free-text Ollama call with temperature=0. Used for analyst-facing synthesis."""
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.0},
    )
    return response["message"]["content"]
