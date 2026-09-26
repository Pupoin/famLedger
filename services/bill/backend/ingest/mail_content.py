import re

from backend.ingest.parser import html_to_text


def message_body_and_parse_text(msg: dict) -> tuple[str, str]:
    """Return readable body text for Sure notes and parser text with preview fallback."""
    raw_body = (msg.get("body") or {}).get("content") or ""
    readable_html = re.sub(r"<br\s*/?>", "\n", raw_body, flags=re.IGNORECASE)
    body_text = html_to_text(readable_html) if raw_body else ""
    return body_text, body_text or msg.get("bodyPreview", "")
