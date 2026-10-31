"""
A tiny client for the NVIDIA API catalog (https://build.nvidia.com).

NVIDIA's hosted models speak the same "chat completions" format as OpenAI,
so a plain HTTP POST is all we need - only the Python standard library is used,
nothing extra to install.

What it handles for you:
  * Rate limits (HTTP 429)   -> wait (respecting the Retry-After header) and retry
  * Server errors (5xx)      -> wait and retry with exponential backoff (2s, 4s, 8s ...)
  * Timeouts / network blips -> wait and retry
  * Bad JSON from the model  -> retry (models occasionally return invalid JSON)
  * Other errors (401, 404)  -> stop immediately; retrying will not help
If all attempts fail it raises LLMError, and the caller decides what to do
(our pipeline falls back to template messages instead of crashing).
"""

import json
import logging
import re
import time
import urllib.error
import urllib.request

from . import settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when the LLM could not give us a usable answer."""


def is_configured():
    return bool(settings.LLM_API_KEY)


def parse_json_reply(text):
    """Pull the JSON object out of the model's reply.

    Models sometimes add extras around the JSON: ```json fences, a sentence of
    explanation, or <think>...</think> blocks (reasoning models). We drop the
    thinking part and parse from the first '{' to the last '}'.
    """
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise json.JSONDecodeError("no JSON object found in reply", text, 0)
    return json.loads(text[start:end + 1])


def chat_json(system_prompt, user_prompt):
    """Send one chat request and return the model's reply parsed as a JSON object."""
    if not is_configured():
        raise LLMError("NVIDIA_API_KEY is not set")

    url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": settings.LLM_MODEL,
        "temperature": 0.4,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "User-Agent": "lead-qualifier/1.0",
    }

    for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
        wait_seconds = 2 ** attempt  # exponential backoff: 2, 4, 8, 16 ...
        try:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=settings.LLM_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            return parse_json_reply(content)

        except urllib.error.HTTPError as error:
            if error.code == 429:
                retry_after = error.headers.get("Retry-After")
                if retry_after and retry_after.replace(".", "", 1).isdigit():
                    wait_seconds = float(retry_after)
                problem = "rate limited (429)"
            elif error.code >= 500:
                problem = f"server error ({error.code})"
            else:
                details = error.read().decode("utf-8", errors="replace")[:300]
                hints = {401: "check NVIDIA_API_KEY", 403: "check NVIDIA_API_KEY",
                         404: f"model '{settings.LLM_MODEL}' not found - check NVIDIA_MODEL"}
                hint = hints.get(error.code, "not retrying")
                raise LLMError(f"HTTP {error.code} ({hint}): {details}") from error

        except (urllib.error.URLError, TimeoutError) as error:
            problem = f"network problem ({error})"
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            problem = f"unusable reply ({error})"

        if attempt == settings.LLM_MAX_RETRIES:
            raise LLMError(f"Gave up after {attempt} attempts: {problem}")
        log.warning("LLM attempt %d/%d failed: %s. Retrying in %.0fs",
                    attempt, settings.LLM_MAX_RETRIES, problem, wait_seconds)
        time.sleep(wait_seconds)

    raise LLMError("unreachable")  # keeps linters happy


def in_batches(items, size):
    """Split a list into chunks: in_batches([1,2,3,4,5], 2) -> [1,2], [3,4], [5]"""
    for start in range(0, len(items), size):
        yield items[start:start + size]
