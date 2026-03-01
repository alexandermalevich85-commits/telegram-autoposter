"""Publish a photo + text post to a Max messenger channel.

Max Bot API flow:
1. POST /uploads (multipart image) → token
2. POST /messages?chat_id=... with image attachment → message
"""

import requests

from config import MAX_BOT_TOKEN, MAX_CHAT_ID, MAX_FOOTER
from utils import strip_html

_API_BASE = "https://platform-api.max.ru"


def send_post(
    photo_path: str,
    caption: str,
    bot_token: str | None = None,
    chat_id: str | None = None,
    footer_text: str | None = None,
) -> dict:
    """Send a photo with text to a Max channel.

    Args:
        photo_path: Path to the image file.
        caption: HTML-formatted text (will be stripped to plain text).
        bot_token: Max bot token.
        chat_id: Max channel chat ID.

    Returns:
        {"ok": True, "result": {"message_id": "<mid>"}}
    """
    token = bot_token or MAX_BOT_TOKEN
    cid = chat_id or MAX_CHAT_ID

    if not token:
        raise RuntimeError("MAX_BOT_TOKEN не задан")
    if not cid:
        raise RuntimeError("MAX_CHAT_ID не задан")

    # Max Bot API expects "Bearer <token>" in Authorization header
    headers = {"Authorization": f"Bearer {token}"}
    plain_text = strip_html(caption)

    # Append platform-specific footer
    footer = footer_text if footer_text is not None else MAX_FOOTER
    if footer:
        plain_text = plain_text + "\n\n" + footer

    # Step 1: Upload image
    with open(photo_path, "rb") as photo_file:
        upload_resp = requests.post(
            f"{_API_BASE}/uploads",
            params={"type": "image"},
            headers=headers,
            files={"file": photo_file},
            timeout=30,
        )

    if upload_resp.status_code != 200:
        raise RuntimeError(f"Max upload error: HTTP {upload_resp.status_code} {upload_resp.text}")

    upload_data = upload_resp.json()

    # The response contains either a token or a url+token structure
    img_token = upload_data.get("token")
    if not img_token:
        # Try nested structure
        img_token = upload_data.get("payload", {}).get("token")
    if not img_token:
        raise RuntimeError(f"Max upload: no token in response: {upload_data}")

    # Step 2: Send message with image attachment
    message_body = {
        "text": plain_text,
        "attachments": [
            {
                "type": "image",
                "payload": {
                    "token": img_token,
                },
            }
        ],
    }

    msg_resp = requests.post(
        f"{_API_BASE}/messages",
        params={"chat_id": cid},
        headers={**headers, "Content-Type": "application/json"},
        json=message_body,
        timeout=30,
    )

    if msg_resp.status_code != 200:
        raise RuntimeError(f"Max sendMessage error: HTTP {msg_resp.status_code} {msg_resp.text}")

    msg_data = msg_resp.json()

    # Extract message ID
    mid = msg_data.get("message", {}).get("body", {}).get("mid")
    if not mid:
        mid = msg_data.get("message", {}).get("mid", "unknown")

    return {
        "ok": True,
        "result": {"message_id": str(mid)},
    }
