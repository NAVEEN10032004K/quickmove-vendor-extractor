"""Anthropic Claude wrapper: free-text fill, vision extraction, action sentence."""
import base64
import io
import json
import re
from datetime import date

import anthropic
from PIL import Image

from app.prompts import ACTION_SYSTEM, TEXT_FILL_SYSTEM, VISION_SYSTEM

MODEL = "claude-sonnet-5-5"
_client = None  # reads ANTHROPIC_API_KEY from env on first use


def _ask(system: str, content, max_tokens: int = 1500) -> str:
    global _client
    _client = _client or anthropic.Anthropic()
    system = f"{system}\nToday's date: {date.today().isoformat()}."
    msg = _client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": content}]
    )
    return msg.content[0].text.strip()


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)  # tolerate ```json fences / stray prose
    if not m:
        raise ValueError(f"Model did not return JSON: {text[:80]!r}")
    return json.loads(m.group(0))


def fill_text_fields(message: str, hints: dict) -> dict:
    prompt = f"Regex hints: {json.dumps(hints, ensure_ascii=False)}\n\nMessage:\n{message}"
    return _json(_ask(TEXT_FILL_SYSTEM, prompt))


def extract_with_claude_vision(message: str | None, image_bytes: bytes) -> dict:
    fmt = (Image.open(io.BytesIO(image_bytes)).format or "PNG").lower()
    media_type = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.b64encode(image_bytes).decode()}},
        {"type": "text", "text": f"Pasted text (may be empty):\n{message or ''}"},
    ]
    return _json(_ask(VISION_SYSTEM, content))


def write_action_sentence(record_json: str) -> str:
    return _ask(ACTION_SYSTEM, record_json, max_tokens=100)
