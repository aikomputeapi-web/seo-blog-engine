"""LLM client: OpenAI-compatible chat completions against zen router (free, no key)."""

import time
import requests

from engine import config

_last_call = 0.0
MIN_INTERVAL = 2.0  # be polite to the shared free router

# fallback chain: primary first, then alternates on free-tier gating / model errors
FALLBACK_MODELS = [
    config.LLM_MODEL,
    "longcat-2.5-preview-free",
    "ling-3.1-flash-free",
    "mimo-v2.6-flash-free",
]


def _post(model, prompt, max_tokens, timeout):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    r = requests.post(
        config.LLM_URL,
        json=payload,
        timeout=timeout,
        headers={"Content-Type": "application/json"},
    )
    if r.status_code == 200:
        data = r.json()
        choices = data.get("choices") or []
        if choices and choices[0].get("message", {}).get("content"):
            return choices[0]["message"]["content"]
    return None


def generate(prompt, max_tokens=2048, retries=2):
    global _last_call
    wait = MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    errors = []
    for attempt in range(retries):
        for model in FALLBACK_MODELS:
            try:
                result = _post(model, prompt, max_tokens, 120)
                _last_call = time.time()
                if result is not None:
                    return result
                errors.append(f"{model}: empty choice")
            except requests.RequestException as e:
                _last_call = time.time()
                errors.append(f"{model}: {str(e)[:80]}")
        time.sleep(6 * (attempt + 1))  # cooldown before full-chain retry
    raise RuntimeError("LLM generate failed: " + "; ".join(errors[:4]))
