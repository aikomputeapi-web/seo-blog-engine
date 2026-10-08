"""LLM client: OpenAI-compatible chat completions against zen router (free, no key)."""

import os
import time
from urllib.parse import urlparse
import requests

from engine import config

_last_call = 0.0
MIN_INTERVAL = 2.0  # be polite to the shared free router

# Free models exposed by the configured OpenCode Zen account. Keep this list free-only.
FREE_MODELS = (
    "longcat-2.5-preview-free",
    "ling-3.1-flash-free",
    "mimo-v2.6-flash-free",
)
FALLBACK_MODELS = list(dict.fromkeys(
    [model for model in (config.LLM_MODEL, *FREE_MODELS) if model in FREE_MODELS]
)) or list(FREE_MODELS)


def _post(model, prompt, max_tokens, timeout):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if urlparse(config.LLM_URL).hostname == "zen.nowrouter.store":
        token = os.environ.get("OPENCODE_ZEN_API_KEY")
        if not token:
            raise RuntimeError("OPENCODE_ZEN_API_KEY is required for the Zen router")
        headers["Authorization"] = f"Bearer {token}"
        headers["User-Agent"] = "opencode"
    r = requests.post(
        config.LLM_URL,
        json=payload,
        timeout=timeout,
        headers=headers,
    )
    if r.status_code == 200:
        data = r.json()
        choices = data.get("choices") or []
        if choices and choices[0].get("message", {}).get("content"):
            return choices[0]["message"]["content"]
    return None


def generate(prompt, max_tokens=2048, retries=2, timeout=120, models=None):
    global _last_call
    wait = MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    errors = []
    model_chain = list(models or FALLBACK_MODELS)
    for attempt in range(retries):
        for model in model_chain:
            try:
                result = _post(model, prompt, max_tokens, timeout)
                _last_call = time.time()
                if result is not None:
                    return result
                errors.append(f"{model}: empty choice")
            except requests.RequestException as e:
                _last_call = time.time()
                errors.append(f"{model}: {str(e)[:80]}")
        time.sleep(6 * (attempt + 1))  # cooldown before full-chain retry
    raise RuntimeError("LLM generate failed: " + "; ".join(errors[:4]))
