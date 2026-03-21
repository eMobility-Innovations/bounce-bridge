import re
from typing import Optional, Tuple


def extract_conv_id_from_header(headers: dict) -> Optional[Tuple[str, str]]:
    """
    Extract conversation ID from email headers.

    Looks for: X-Chatwoot-Conv-ID: {account_id}:{conv_id}

    Returns: (account_id, conv_id) or None
    """
    # Try various header formats
    header_names = [
        "X-Chatwoot-Conv-ID",
        "x-chatwoot-conv-id",
        "X-Chatwoot-Conv-Id",
    ]

    for header in header_names:
        if header in headers:
            value = headers[header]
            return parse_conv_id(value)

    # Also check nested headers dict
    if isinstance(headers, dict):
        for key, value in headers.items():
            if key.lower() == "x-chatwoot-conv-id":
                return parse_conv_id(value)

    return None


def extract_conv_id_from_body(html_body: str) -> Optional[Tuple[str, str]]:
    """
    Extract conversation ID from HTML body comment.

    Looks for: <!-- cw:{account_id}:{conv_id} -->

    Returns: (account_id, conv_id) or None
    """
    if not html_body:
        return None

    # Match <!-- cw:123:456 --> pattern
    pattern = r'<!--\s*cw:(\d+):(\d+)\s*-->'
    match = re.search(pattern, html_body)

    if match:
        return (match.group(1), match.group(2))

    return None


def parse_conv_id(value: str) -> Optional[Tuple[str, str]]:
    """
    Parse account_id:conv_id format.

    Returns: (account_id, conv_id) or None
    """
    if not value:
        return None

    value = value.strip()

    if ":" in value:
        parts = value.split(":", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])

    return None


def extract_conv_id(
    headers: Optional[dict] = None,
    html_body: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    Extract conversation ID from headers or body.

    Prefers header over body.

    Returns: (account_id, conv_id) or None
    """
    # Try header first
    if headers:
        result = extract_conv_id_from_header(headers)
        if result:
            return result

    # Fall back to body
    if html_body:
        result = extract_conv_id_from_body(html_body)
        if result:
            return result

    return None
