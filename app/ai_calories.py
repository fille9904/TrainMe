from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6")

CALORIE_HINTS = {
    "banana": 105,
    "apple": 95,
    "egg": 78,
    "eggs": 156,
    "bread": 90,
    "toast": 90,
    "rice": 260,
    "pasta": 320,
    "chicken": 250,
    "salmon": 300,
    "beef": 350,
    "yogurt": 150,
    "oatmeal": 180,
    "porridge": 180,
    "pizza": 700,
    "burger": 650,
    "salad": 250,
    "avocado": 240,
    "potato": 160,
    "sandwich": 380,
}


def openai_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def extract_calories(text: str) -> int | None:
    match = re.search(r"(\d{2,5})", text)
    if not match:
        return None
    calories = int(match.group(1))
    if 1 <= calories <= 5000:
        return calories
    return None


def local_text_calorie_estimate(description: str) -> tuple[int | None, str]:
    lower = description.lower()
    total = 0
    matched: list[str] = []
    for food, calories in CALORIE_HINTS.items():
        if food in lower:
            total += calories
            matched.append(food)

    if total:
        return total, f"Local estimate based on: {', '.join(matched[:4])}."
    return None, "I could not estimate that locally. Add more detail or connect an OpenAI API key for AI estimates."


def response_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return " ".join(chunks).strip()


def call_openai_calorie_estimator(content: list[dict[str, Any]]) -> tuple[int | None, str]:
    api_key = openai_api_key()
    if not api_key:
        return None, "OpenAI API key is not configured."

    prompt = (
        "Estimate the calories in this food intake. Return one short sentence with an approximate kcal number. "
        "If uncertain, give a reasonable range but include a single best estimate in kcal."
    )
    body = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}, *content],
            }
        ],
    }
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"AI estimate failed: {exc}"

    output = response_output_text(payload)
    calories = extract_calories(output)
    return calories, output or "AI returned no estimate."


def estimate_calories_from_text(description: str) -> tuple[int | None, str]:
    clean = description.strip()
    if not clean:
        return None, "Describe what you ate first."
    if openai_api_key():
        return call_openai_calorie_estimator([{"type": "input_text", "text": clean}])
    return local_text_calorie_estimate(clean)


def estimate_calories_from_image(image_bytes: bytes, content_type: str) -> tuple[int | None, str]:
    if not openai_api_key():
        return None, "Photo calorie estimates need OPENAI_API_KEY because TrainMe does not store or analyze images locally."
    encoded = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{content_type};base64,{encoded}"
    return call_openai_calorie_estimator([{"type": "input_image", "image_url": data_url}])
