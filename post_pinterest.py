"""Publish a pin (image + text) to a Pinterest board.

Pinterest API v5 flow:
1. Read image → base64 encode
2. POST /v5/pins with media_source type=image_base64 → pin
"""

import base64
import re

import requests

from config import PINTEREST_ACCESS_TOKEN, PINTEREST_BOARD_ID

_API_BASE = "https://api.pinterest.com/v5"


def _strip_html(text: str) -> str:
    """Convert HTML-formatted text to plain text for Pinterest."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return text.strip()


def send_post(
    photo_path: str,
    caption: str,
    access_token: str | None = None,
    board_id: str | None = None,
) -> dict:
    """Create a pin on a Pinterest board.

    Args:
        photo_path: Path to the image file.
        caption: HTML-formatted text. First line becomes the title (max 100 chars),
                 rest becomes description (max 500 chars).
        access_token: Pinterest OAuth2 access token.
        board_id: Pinterest board ID.

    Returns:
        {"ok": True, "result": {"message_id": "<pin_id>"}}
    """
    token = access_token or PINTEREST_ACCESS_TOKEN
    bid = board_id or PINTEREST_BOARD_ID

    if not token:
        raise RuntimeError("PINTEREST_ACCESS_TOKEN не задан")
    if not bid:
        raise RuntimeError("PINTEREST_BOARD_ID не задан")

    plain_text = _strip_html(caption)

    # Split into title + description
    lines = plain_text.split("\n", 1)
    title = lines[0][:100]
    description = lines[1][:500] if len(lines) > 1 else ""

    # Read and encode image
    with open(photo_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")

    # Create pin
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "board_id": bid,
        "title": title,
        "description": description,
        "media_source": {
            "source_type": "image_base64",
            "content_type": "image/jpeg",
            "data": image_b64,
        },
    }

    resp = requests.post(
        f"{_API_BASE}/pins",
        headers=headers,
        json=payload,
        timeout=60,
    )

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Pinterest API error: HTTP {resp.status_code} {resp.text}")

    pin_data = resp.json()
    pin_id = pin_data.get("id", "unknown")

    return {
        "ok": True,
        "result": {"message_id": str(pin_id)},
    }
