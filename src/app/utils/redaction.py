"""Conservative redaction for logs and diagnostics."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*[^\r\n]+"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?token|"
    r"plugin[_-]?token|token|secret|password)\s*[:=]\s*"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;}&]+)"
)
_JSON_SECRET = re.compile(
    r"(?i)(\"(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
    r"client[_-]?token|plugin[_-]?token|token|secret|password)\"\s*:\s*)"
    r"(\"(?:\\.|[^\"\\])*\")"
)
_ACTIONS = re.compile(r"(?is)(\"actions\"\s*:\s*\[).*")
_URL = re.compile(r"(?i)\bhttps?://[^\s\"']+")
_TOKEN_LIKE = re.compile(
    r"(?i)\b(?:sk|secret|token|password|passwd)[-_][a-z0-9._~-]{4,}\b"
)


def redact_sensitive_text(text: object) -> str:
    value = str(text or "")
    value = _AUTH_HEADER.sub(lambda match: f"{match.group(1)}: [REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    value = _JSON_SECRET.sub(
        lambda match: f'{match.group(1)}"[REDACTED]"',
        value,
    )
    value = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        value,
    )
    value = _URL.sub(lambda match: redact_url(match.group(0)), value)
    value = _TOKEN_LIKE.sub("[REDACTED]", value)
    value = _ACTIONS.sub(
        lambda match: f"{match.group(1)}[REDACTED]",
        value,
    )
    return value


def redact_url(value: object) -> str:
    text = str(value or "")
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "[REDACTED_URL]"
    if not parsed.scheme or not parsed.netloc:
        return "[REDACTED_URL]"
    host = parsed.hostname or "unknown"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return f"{parsed.scheme}://{netloc}{parsed.path}".rstrip("/")


def safe_exception_message(exc: BaseException, *, limit: int = 500) -> str:
    rendered = redact_sensitive_text(f"{type(exc).__name__}: {exc}")
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 3)] + "..."
