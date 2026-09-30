import asyncio
import logging

import httpx

from .config import MAX_TOKENS, PROVIDERS

log = logging.getLogger(__name__)

RETRY_DELAYS = [2, 4]  # free tiers get 429'd/overloaded often; short retries usually fix it
RETRYABLE = {429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


async def complete(client: httpx.AsyncClient, model: dict, messages: list[dict]) -> str:
    provider = PROVIDERS[model["provider"]]
    payload = {"model": model["id"], "messages": messages, "max_tokens": MAX_TOKENS}
    headers = {"Authorization": f"Bearer {provider['api_key']}"}

    for attempt, delay in enumerate([0, *RETRY_DELAYS], start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.post(provider["url"], json=payload, headers=headers, timeout=120)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("%s request failed (attempt %d): %r", model["provider"], attempt, e)
            continue

        # OpenRouter reports errors in the body (sometimes with HTTP 200); NVIDIA uses HTTP status.
        error = data.get("error") if isinstance(data, dict) else None
        if error or resp.is_error:
            code = (error or {}).get("code") if isinstance(error, dict) else None
            code = code if isinstance(code, int) else resp.status_code
            log.warning("%s error %s (attempt %d): %s", model["provider"], code, attempt, str(data)[:300])
            if code in RETRYABLE:
                continue
            raise LLMError("The model returned an error. Please try again or switch models.")

        content = data["choices"][0]["message"].get("content")
        if content:
            return content.strip()
        log.warning("Empty completion (attempt %d)", attempt)

    raise LLMError("The model is busy right now. Please try again in a moment or switch models.")
