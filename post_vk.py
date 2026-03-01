"""Publish a photo + text post to a VKontakte community wall.

VK API flow:
1. photos.getWallUploadServer → upload URL
2. Upload photo to that URL → server, photo, hash
3. photos.saveWallPhoto → attachment ID
4. wall.post with attachment → post_id
"""

import re

import requests

from config import VK_ACCESS_TOKEN, VK_GROUP_ID

_API_VERSION = "5.199"
_API_BASE = "https://api.vk.com/method"


def _strip_html(text: str) -> str:
    """Convert HTML-formatted text to plain text for VK."""
    # Replace <br> with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Remove all HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return text.strip()


def send_post(
    photo_path: str,
    caption: str,
    access_token: str | None = None,
    group_id: str | None = None,
) -> dict:
    """Send a photo with text to a VK community wall.

    Args:
        photo_path: Path to the image file.
        caption: HTML-formatted text (will be stripped to plain text).
        access_token: VK access token (community or user token with wall,photos scope).
        group_id: VK community ID (without minus sign).

    Returns:
        {"ok": True, "result": {"message_id": "wall-GID_PID"}}
    """
    token = access_token or VK_ACCESS_TOKEN
    gid = group_id or VK_GROUP_ID

    if not token:
        raise RuntimeError("VK_ACCESS_TOKEN не задан")
    if not gid:
        raise RuntimeError("VK_GROUP_ID не задан")

    # Strip minus sign if provided
    gid = gid.lstrip("-")

    plain_text = _strip_html(caption)

    # Step 1: Get upload server
    resp = requests.get(
        f"{_API_BASE}/photos.getWallUploadServer",
        params={
            "group_id": gid,
            "access_token": token,
            "v": _API_VERSION,
        },
        timeout=15,
    ).json()

    if "error" in resp:
        raise RuntimeError(f"VK getWallUploadServer error: {resp['error']}")

    upload_url = resp["response"]["upload_url"]

    # Step 2: Upload photo
    with open(photo_path, "rb") as photo_file:
        upload_resp = requests.post(
            upload_url,
            files={"photo": photo_file},
            timeout=30,
        ).json()

    if not upload_resp.get("photo") or upload_resp["photo"] == "[]":
        raise RuntimeError(f"VK photo upload failed: {upload_resp}")

    # Step 3: Save photo
    save_resp = requests.get(
        f"{_API_BASE}/photos.saveWallPhoto",
        params={
            "group_id": gid,
            "photo": upload_resp["photo"],
            "server": upload_resp["server"],
            "hash": upload_resp["hash"],
            "access_token": token,
            "v": _API_VERSION,
        },
        timeout=15,
    ).json()

    if "error" in save_resp:
        raise RuntimeError(f"VK saveWallPhoto error: {save_resp['error']}")

    photo_info = save_resp["response"][0]
    attachment = f"photo{photo_info['owner_id']}_{photo_info['id']}"

    # Step 4: Create wall post
    post_resp = requests.get(
        f"{_API_BASE}/wall.post",
        params={
            "owner_id": f"-{gid}",
            "from_group": 1,
            "message": plain_text,
            "attachments": attachment,
            "access_token": token,
            "v": _API_VERSION,
        },
        timeout=15,
    ).json()

    if "error" in post_resp:
        raise RuntimeError(f"VK wall.post error: {post_resp['error']}")

    post_id = post_resp["response"]["post_id"]

    return {
        "ok": True,
        "result": {"message_id": f"wall-{gid}_{post_id}"},
    }
