from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import LLMConfigurationError, LLMRequestError


_BASE_URL_ENV = "REGULATED_WORKFLOW_OPENAI_BASE_URL"
_API_KEY_ENV = "REGULATED_WORKFLOW_OPENAI_API_KEY"
_MODEL_ENV = "REGULATED_WORKFLOW_OPENAI_MODEL"


class _RejectRedirectHandler(HTTPRedirectHandler):
    """Make redirects fail before a request (and its bearer token) is forwarded."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


@dataclass(frozen=True)
class OpenAICompatibleAdapter:
    """Explicit, optional adapter for an OpenAI-compatible chat endpoint.

    The CLI never constructs this adapter unless ``--llm-summary`` is supplied.
    Configuration is read only from environment variables, and callers should
    pass counts-only context rather than source text.
    """

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(
        cls, environ: Optional[Mapping[str, str]] = None
    ) -> "OpenAICompatibleAdapter":
        values = os.environ if environ is None else environ
        missing = [
            name
            for name in (_BASE_URL_ENV, _API_KEY_ENV, _MODEL_ENV)
            if not values.get(name, "").strip()
        ]
        if missing:
            raise LLMConfigurationError(
                "--llm-summary requires environment variables: %s"
                % ", ".join(missing)
            )

        base_url = values[_BASE_URL_ENV].strip().rstrip("/")
        parsed = urlparse(base_url)
        is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_local):
            raise LLMConfigurationError(
                "%s must use HTTPS (HTTP is allowed only for localhost)" % _BASE_URL_ENV
            )
        return cls(
            base_url=base_url,
            api_key=values[_API_KEY_ENV].strip(),
            model=values[_MODEL_ENV].strip(),
        )

    def draft_summary(self, counts_only_context: str) -> str:
        endpoint = "%s/chat/completions" % self.base_url
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Draft a concise workflow review note from aggregate counts only. "
                        "Do not make legal, medical, financial, regulatory, or approval decisions."
                    ),
                },
                {"role": "user", "content": counts_only_context},
            ],
        }
        request = Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": "Bearer %s" % self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            opener = build_opener(_RejectRedirectHandler())
            with opener.open(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            exc.close()
            raise LLMRequestError("OpenAI-compatible summary request failed: %s" % exc) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LLMRequestError("OpenAI-compatible summary request failed: %s" % exc) from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError("OpenAI-compatible response has no message content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMRequestError("OpenAI-compatible response returned empty message content")
        return content.strip()
