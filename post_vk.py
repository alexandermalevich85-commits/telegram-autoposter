"""Publish a photo + text post to a VKontakte community wall.

Supports both community (group) tokens and user tokens.

Community token flow:
1. photos.getMessagesUploadServer → upload URL
2. Upload photo → server, photo, hash
3. photos.saveMessagesPhoto → attachment ID
4. wall.post with attachment → post_id

User token flow:
1. photos.getWallUploadServer → upload URL
2. Upload photo → server, photo, hash
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


def _upload_photo_wall(token: str, gid: str, photo_path: str) -> str:
    """Upload photo via Wall Upload Server (user token)."""
    resp = requests.get(
        f"{_API_BASE}/photos.getWallUploadServer",
        params={"group_id": gid, "access_token": token, "v": _API_VERSION},
        timeout=15,
    ).json()

    if "error" in resp:
        raise RuntimeError(f"VK getWallUploadServer: {resp['error']}")

    with open(photo_path, "rb") as f:
        upload_resp = requests.post(
            resp["response"]["upload_url"], files={"photo": f}, timeout=30,
        ).json()

    if not upload_resp.get("photo") or upload_resp["photo"] == "[]":
        raise RuntimeError(f"VK photo upload failed: {upload_resp}")

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
        raise RuntimeError(f"VK saveWallPhoto: {save_resp['error']}")

    info = save_resp["response"][0]
    return f"photo{info['owner_id']}_{info['id']}"


def _upload_photo_messages(token: str, gid: str, photo_path: str) -> str:
    """Upload photo via Messages Upload Server (community token)."""
    resp = requests.get(
        f"{_API_BASE}/photos.getMessagesUploadServer",
        params={"group_id": gid, "access_token": token, "v": _API_VERSION},
        timeout=15,
    ).json()

    if "error" in resp:
        raise RuntimeError(f"VK getMessagesUploadServer: {resp['error']}")

    with open(photo_path, "rb") as f:
        upload_resp = requests.post(
            resp["response"]["upload_url"], files={"photo": f}, timeout=30,
        ).json()

    if not upload_resp.get("photo") or upload_resp["photo"] == "[]":
        raise RuntimeError(f"VK photo upload failed: {upload_resp}")

    save_resp = requests.get(
        f"{_API_BASE}/photos.saveMessagesPhoto",
        params={
            "photo": upload_resp["photo"],
            "server": upload_resp["server"],
            "hash": upload_resp["hash"],
            "access_token": token,
            "v": _API_VERSION,
        },
        timeout=15,
    ).json()

    if "error" in save_resp:
        raise RuntimeError(f"VK saveMessagesPhoto: {save_resp['error']}")

    info = save_resp["response"][0]
    return f"photo{info['owner_id']}_{info['id']}"


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

    # Try wall upload first (user token), fall back to messages upload (group token)
    try:
        attachment = _upload_photo_wall(token, gid, photo_path)
    except RuntimeError as e:
        if "group auth" in str(e).lower() or "group authorization" in str(e).lower():
            attachment = _upload_photo_messages(token, gid, photo_path)
        else:
            raise

    # Create wall post
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
