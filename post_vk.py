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

import requests

from config import VK_ACCESS_TOKEN, VK_GROUP_ID, VK_FOOTER
from utils import strip_html

_API_VERSION = "5.199"
_API_BASE = "https://api.vk.com/method"


def _vk_post(method: str, params: dict, timeout: int = 15) -> dict:
    """Make a VK API call using POST (keeps token out of URL/logs)."""
    resp = requests.post(
        f"{_API_BASE}/{method}",
        data={**params, "v": _API_VERSION},
        timeout=timeout,
    ).json()
    if "error" in resp:
        raise RuntimeError(f"VK {method}: {resp['error']}")
    return resp


def _upload_photo_wall(token: str, gid: str, photo_path: str) -> str:
    """Upload photo via Wall Upload Server (user token)."""
    resp = _vk_post("photos.getWallUploadServer", {
        "group_id": gid, "access_token": token,
    })

    with open(photo_path, "rb") as f:
        upload_resp = requests.post(
            resp["response"]["upload_url"], files={"photo": f}, timeout=30,
        ).json()

    if not upload_resp.get("photo") or upload_resp["photo"] == "[]":
        raise RuntimeError(f"VK photo upload failed: {upload_resp}")

    save_resp = _vk_post("photos.saveWallPhoto", {
        "group_id": gid,
        "photo": upload_resp["photo"],
        "server": upload_resp["server"],
        "hash": upload_resp["hash"],
        "access_token": token,
    })

    info = save_resp["response"][0]
    attachment = f"photo{info['owner_id']}_{info['id']}"
    if info.get("access_key"):
        attachment += f"_{info['access_key']}"
    return attachment


def _upload_photo_messages(token: str, gid: str, photo_path: str) -> str:
    """Upload photo via Messages Upload Server (community token).

    Photos saved via saveMessagesPhoto belong to the bot/community messages
    album, NOT the wall album. To attach them to a wall.post, VK requires
    the ``access_key`` that is returned alongside the photo metadata.
    Without it the attachment silently resolves to nothing and the post
    appears without an image.
    """
    resp = _vk_post("photos.getMessagesUploadServer", {
        "group_id": gid, "access_token": token,
    })

    with open(photo_path, "rb") as f:
        upload_resp = requests.post(
            resp["response"]["upload_url"], files={"photo": f}, timeout=30,
        ).json()

    if not upload_resp.get("photo") or upload_resp["photo"] == "[]":
        raise RuntimeError(f"VK photo upload failed: {upload_resp}")

    save_resp = _vk_post("photos.saveMessagesPhoto", {
        "photo": upload_resp["photo"],
        "server": upload_resp["server"],
        "hash": upload_resp["hash"],
        "access_token": token,
    })

    info = save_resp["response"][0]
    attachment = f"photo{info['owner_id']}_{info['id']}"
    # access_key is REQUIRED for message-album photos used in wall posts
    if info.get("access_key"):
        attachment += f"_{info['access_key']}"
    return attachment


def send_post(
    photo_path: str,
    caption: str,
    access_token: str | None = None,
    group_id: str | None = None,
    footer_text: str | None = None,
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

    plain_text = strip_html(caption)

    # Append platform-specific footer (e.g., VK bot/group link)
    footer = footer_text if footer_text is not None else VK_FOOTER
    if footer:
        plain_text = plain_text + "\n\n" + footer

    # Try wall upload first (user token), fall back to messages upload (group token)
    try:
        attachment = _upload_photo_wall(token, gid, photo_path)
    except RuntimeError as e:
        if "group auth" in str(e).lower() or "group authorization" in str(e).lower():
            attachment = _upload_photo_messages(token, gid, photo_path)
        else:
            raise

    # Create wall post (using POST to keep token out of URL)
    post_resp = _vk_post("wall.post", {
        "owner_id": f"-{gid}",
        "from_group": 1,
        "message": plain_text,
        "attachments": attachment,
        "access_token": token,
    })

    post_id = post_resp["response"]["post_id"]

    return {
        "ok": True,
        "result": {"message_id": f"wall-{gid}_{post_id}"},
    }
