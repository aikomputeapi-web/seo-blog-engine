"""LLM client: OpenAI-compatible chat completions against zen router (free, no key)."""

import time
import requests

from engine import config

_last_call = 0.0
MIN_INTERVAL = 2.0  # be polite to the shared free router


def generate(prompt, max_tokens=2048, retries=3):
    global _last_call
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    wait = MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(retries):
        try:
            r = requests.post(
                config.LLM_URL,
                json=payload,
                timeout=120,
                headers={"Content-Type": "application/json"},
            )
            _last_call = time.time()
            if r.status_code == 200:
                data = r.json()
                choices = data.get("choices") or []
                if choices and choices[0].get("message", {}).get("content"):
                    return choices[0]["message"]["content"]
                # empty/odd choice (router hiccup): retry once after short pause
                time.sleep(3)
                continue
            if r.status_code in (429, 500, 502, 503):
                time.sleep(8 * (attempt + 1))  # backoff on quota / transient
                continue
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:300]}")
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(6 * (attempt + 1))
    raise RuntimeError("LLM generate failed after retries")
