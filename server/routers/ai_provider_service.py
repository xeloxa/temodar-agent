import json
import logging
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import HTTPException, status

logger = logging.getLogger("temodar_agent.ai.provider")

# Maximum length of provider error detail reflected to the client.
_MAX_ERROR_DETAIL_LENGTH = 200

TEST_PROMPT = "Reply with exactly OK."
TEST_TIMEOUT_SECONDS = 20
DEFAULT_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "copilot": "https://api.githubcopilot.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "grok": "https://api.x.ai/v1",
}
OPENAI_COMPATIBLE_PROVIDERS = {"openai", "grok", "gemini"}


def normalize_provider_base_url(provider: str, base_url: str | None) -> str:
    explicit_base_url = str(base_url or "").strip().rstrip("/")
    if explicit_base_url:
        return explicit_base_url
    return DEFAULT_PROVIDER_BASE_URLS.get(provider, DEFAULT_PROVIDER_BASE_URLS["anthropic"])


def post_json(url: str, *, headers: dict[str, str], body: dict, timeout: int = TEST_TIMEOUT_SECONDS) -> dict:
    request = urllib_request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode("utf-8")
            return json.loads(raw_response) if raw_response else {}
    except urllib_error.HTTPError as exc:
        raw_detail = exc.read().decode("utf-8", errors="ignore").strip()
        # Log the full error server-side for debugging.
        logger.warning(
            "Provider HTTP %d error: %s", exc.code, raw_detail[:500]
        )
        # Sanitize: truncate and strip potentially sensitive info before
        # reflecting to the client.
        safe_detail = raw_detail[:_MAX_ERROR_DETAIL_LENGTH] if raw_detail else ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=safe_detail or f"Provider returned HTTP {exc.code}.",
        ) from exc
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        logger.warning("Provider connection failed: %s", reason)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection to AI provider failed.",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection timed out.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider returned invalid JSON.",
        ) from exc


def test_openai_connection(*, api_key: str, model: str, base_url: str | None) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": TEST_PROMPT},
            {"role": "user", "content": TEST_PROMPT},
        ],
        "max_tokens": 5,
        "temperature": 0,
    }
    response = post_json(
        f"{normalize_provider_base_url('openai', base_url)}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        body=payload,
    )
    choices = response.get("choices") or []
    if not choices:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider did not return a test reply.",
        )

    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider did not return a test reply.",
        )
    return content


def test_anthropic_connection(*, api_key: str, model: str, base_url: str | None) -> str:
    payload = {
        "model": model,
        "max_tokens": 5,
        "temperature": 0,
        "messages": [
            {"role": "user", "content": TEST_PROMPT},
        ],
        "system": TEST_PROMPT,
    }
    response = post_json(
        f"{normalize_provider_base_url('anthropic', base_url)}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        body=payload,
    )
    content_blocks = response.get("content") or []
    content = " ".join(
        str(block.get("text") or "").strip()
        for block in content_blocks
        if isinstance(block, dict) and str(block.get("text") or "").strip()
    ).strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider did not return a test reply.",
        )
    return content


def run_provider_connection_test(*, provider: str, api_key: str, model: str, base_url: str | None) -> str:
    if provider == "anthropic":
        return test_anthropic_connection(api_key=api_key, model=model, base_url=base_url)
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return test_openai_connection(api_key=api_key, model=model, base_url=base_url)
    if provider == "copilot":
        return "Copilot connectivity is handled by the Open Multi-Agent provider adapter at runtime."
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported provider: {provider}",
    )
