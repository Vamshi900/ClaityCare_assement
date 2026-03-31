"""
LLM client adapter: supports Anthropic and OpenAI providers.
"""

import json
import re
import logging

from app.config import settings

log = logging.getLogger(__name__)

MAX_TOKENS = 8192


def get_llm_metadata() -> dict:
    """Return metadata about the current LLM configuration."""
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        model = settings.llm_model_anthropic
    else:
        model = settings.llm_model_openai
    return {
        "provider": provider,
        "model": model,
        "prompt_version": "v1",
    }


def parse_json_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON from LLM response."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


async def call_llm(system_prompt: str, user_prompt: str) -> str:
    """
    Call the configured LLM provider and return the raw text response.
    """
    provider = settings.llm_provider.lower()

    if provider == "anthropic":
        return await _call_anthropic(system_prompt, user_prompt)
    elif provider == "openai":
        return await _call_openai(system_prompt, user_prompt)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


async def call_llm_with_json_retry(system_prompt: str, user_prompt: str, max_retries: int = 2) -> dict:
    """
    Call LLM and parse JSON response. On JSON parse failure, retry with
    conversational feedback telling the model what went wrong.
    """
    messages_context = user_prompt

    for attempt in range(1, max_retries + 1):
        raw = await call_llm(system_prompt, messages_context)
        try:
            return parse_json_response(raw)
        except json.JSONDecodeError as e:
            log.warning(f"JSON parse failed (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                messages_context = (
                    f"{user_prompt}\n\n"
                    f"Your previous response was not valid JSON. The error was: {e}\n"
                    f"Here was your response (first 500 chars):\n{raw[:500]}\n\n"
                    f"Please try again and return ONLY valid JSON with no markdown fences or commentary."
                )
            else:
                raise


async def _call_anthropic(system_prompt: str, user_prompt: str) -> str:
    """Call Anthropic Claude API."""
    from anthropic import AsyncAnthropic

    import httpx
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=httpx.Timeout(120.0, connect=10.0),
    )
    model = settings.llm_model_anthropic

    log.info(f"Calling Anthropic ({model})...")

    response = await client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.content[0].text.strip()
    log.info(f"Anthropic response: {len(raw)} chars")
    return raw


async def _call_openai(system_prompt: str, user_prompt: str) -> str:
    """Call OpenAI API."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = settings.llm_model_openai

    log.info(f"Calling OpenAI ({model})...")

    response = await client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    log.info(f"OpenAI response: {len(raw)} chars")
    return raw
