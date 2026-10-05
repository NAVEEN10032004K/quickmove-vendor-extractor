"""Local Ollama client with the same interface as claude_client (text only, no vision)."""
import json
import os
from datetime import date

import requests

from app.claude_client import _json
from app.prompts import ACTION_SYSTEM, TEXT_FILL_SYSTEM

MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


def _ask(system: str, content: str, max_tokens: int = 1500) -> str:
    r = requests.post(f"{URL}/api/chat", timeout=300, json={
        "model": MODEL, "stream": False, "options": {"num_predict": max_tokens, "temperature": 0},
        "format": "json" if "Return ONLY a JSON" in system else "",
        "messages": [{"role": "system", "content": f"{system}\nToday's date: {date.today().isoformat()}."},
                     {"role": "user", "content": content}]})
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def fill_text_fields(message: str, hints: dict) -> dict:
    prompt = f"Regex hints: {json.dumps(hints, ensure_ascii=False)}\n\nMessage:\n{message}"
    return _json(_ask(TEXT_FILL_SYSTEM, prompt))


def extract_with_vision(message: str | None, image_bytes: bytes) -> dict:
    raise RuntimeError(f"{MODEL} (Ollama) has no vision support; set LLM_BACKEND=claude for screenshots.")


def write_action_sentence(record_json: str) -> str:
    return _ask(ACTION_SYSTEM, record_json, max_tokens=100)
