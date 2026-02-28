import base64
import io
import json
import logging
import os
import sys
import tempfile
from datetime import datetime

from PIL import Image

from config import TEXT_PROVIDER, IMAGE_PROVIDER, FACE_SWAP_PROVIDER
from generate_text import generate_post
from generate_image import generate_image
from face_swap import apply_face_swap
from post_telegram import send_post

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IDEAS_FILE = os.path.join(BASE_DIR, "ideas.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
PENDING_FILE = os.path.join(BASE_DIR, "pending_post.json")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("autoposter")


# ── JSON helpers ─────────────────────────────────────────────────────────────


def load_ideas() -> list[dict]:
    with open(IDEAS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ideas(ideas: list[dict]) -> None:
    with open(IDEAS_FILE, "w", encoding="utf-8") as f:
        json.dump(ideas, f, ensure_ascii=False, indent=2)


def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history: list[dict]) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_pending() -> dict | None:
    if not os.path.exists(PENDING_FILE):
        return None
    with open(PENDING_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_pending(data: dict) -> None:
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_history_entry(idea: str, post_text: str, message_id: int) -> None:
    history = load_history()
    history.append({
        "date": datetime.now().isoformat(),
        "idea": idea,
        "post_text": post_text,
        "text_provider": TEXT_PROVIDER,
        "image_provider": IMAGE_PROVIDER,
        "message_id": message_id,
    })
    save_history(history)


def get_next_idea(ideas: list[dict]) -> tuple[int, str] | None:
    """Return (index, idea_text) for the first unused idea, or None."""
    for i, item in enumerate(ideas):
        if not item.get("used", False):
            return i, item["idea"]
    return None


# ── Image encoding ───────────────────────────────────────────────────────────


def image_to_base64(image_path: str) -> str:
    """Read image, compress to JPEG quality 85, return base64 string."""
    img = Image.open(image_path)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def base64_to_tempfile(b64_string: str) -> str:
    """Decode base64 to a temporary JPEG file, return its path."""
    data = base64.b64decode(b64_string)
    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="autoposter_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_generate() -> None:
    """Phase 1: generate post draft, save to pending_post.json."""
    log.info("Phase 1: Generating draft")

    # Check if there is an old unfinished draft
    old = load_pending()
    if old and old.get("status") == "pending":
        log.warning(
            "Previous draft was never published (idea: %s). Overwriting.",
            old.get("idea", "?"),
        )

    ideas = load_ideas()
    result = get_next_idea(ideas)
    if result is None:
        log.warning("No unused ideas left in %s", IDEAS_FILE)
        sys.exit(0)

    idx, idea = result
    log.info("Idea #%d: %s", idx, idea)

    # Load custom prompts (if synced from Streamlit)
    custom_system_prompt = None
    custom_image_tpl = None
    prompts_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.json")
    if os.path.exists(prompts_path):
        try:
            with open(prompts_path, "r", encoding="utf-8") as _pf:
                _prompts_data = json.load(_pf)
            custom_system_prompt = _prompts_data.get("system_prompt")
            custom_image_tpl = _prompts_data.get("image_prompt_template")
            log.info("Custom prompts loaded from prompts.json")
        except Exception as exc:
            log.warning("Failed to load prompts.json: %s", exc)

    # Load context document (if synced from Streamlit)
    context_document = None
    context_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_context.json")
    if os.path.exists(context_path):
        try:
            with open(context_path, "r", encoding="utf-8") as _cf:
                _context_data = json.load(_cf)
            context_document = _context_data.get("text")
            if context_document:
                log.info(
                    "Context document loaded: %s (%d chars)",
                    _context_data.get("filename", "?"),
                    len(context_document),
                )
        except Exception as exc:
            log.warning("Failed to load prompt_context.json: %s", exc)

    # Generate text
    log.info("Generating post text via %s...", TEXT_PROVIDER)
    post_text, image_prompt = generate_post(
        idea,
        system_prompt=custom_system_prompt,
        image_prompt_template=custom_image_tpl,
        context_document=context_document,
    )
    log.info("Post text generated (%d chars)", len(post_text))
    log.info("Image prompt: %s", image_prompt[:100])

    # Load expert face for inline generation (gemini) or face swap (replicate)
    expert_b64 = None
    if FACE_SWAP_PROVIDER:
        from face_swap import load_expert_face_b64
        expert_b64 = load_expert_face_b64()

    # Generate image (with expert face inline for gemini provider)
    face_swap_used = ""
    inline_face = (
        FACE_SWAP_PROVIDER in ("gemini", "openai")
        and IMAGE_PROVIDER in ("gemini", "openai")
        and expert_b64
    )

    log.info("Generating image via %s...", IMAGE_PROVIDER)
    image_path = generate_image(
        image_prompt,
        expert_face_b64=expert_b64 if inline_face else None,
    )
    log.info("Image saved to %s", image_path)

    if inline_face:
        face_swap_used = "gemini-inline"
        log.info("Image generated with expert face inline (single API call)")
    elif FACE_SWAP_PROVIDER == "replicate" and expert_b64:
        # Replicate face swap as separate step
        log.info("Applying face swap via %s...", FACE_SWAP_PROVIDER)
        try:
            new_path = apply_face_swap(
                image_path,
                expert_face_b64=expert_b64,
                method=FACE_SWAP_PROVIDER,
                image_prompt=image_prompt,
            )
            if new_path != image_path:
                try:
                    os.remove(image_path)
                except OSError:
                    pass
                image_path = new_path
                face_swap_used = FACE_SWAP_PROVIDER
                log.info("Face swap applied successfully")
        except Exception as e:
            log.warning("Face swap failed, using original image: %s", e)

    # Encode image to base64
    image_b64 = image_to_base64(image_path)
    log.info("Image encoded to base64 (%d chars)", len(image_b64))

    # Save pending draft
    save_pending({
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "idea": idea,
        "idea_index": idx,
        "post_text": post_text,
        "image_prompt": image_prompt,
        "image_base64": image_b64,
        "text_provider": TEXT_PROVIDER,
        "image_provider": IMAGE_PROVIDER,
        "face_swap_provider": face_swap_used,
        "published_at": None,
        "message_id": None,
        "published_by": None,
    })
    log.info("Draft saved to pending_post.json")

    # Cleanup temp image
    try:
        os.remove(image_path)
    except OSError:
        pass

    log.info("Phase 1 done! Draft is ready for review.")


def cmd_publish() -> None:
    """Phase 2: publish pending draft if not already published."""
    log.info("Phase 2: Checking pending draft")

    pending = load_pending()
    if pending is None:
        log.info("No pending_post.json found, nothing to publish")
        sys.exit(0)

    if pending.get("status") != "pending":
        log.info("Draft status is '%s', skipping", pending.get("status"))
        sys.exit(0)

    log.info("Publishing draft: %s", pending.get("idea", "?"))

    # Decode image from base64 to temp file
    image_path = base64_to_tempfile(pending["image_base64"])

    try:
        log.info("Sending to Telegram...")
        result = send_post(image_path, pending["post_text"])
        message_id = result["result"]["message_id"]
        log.info("Posted successfully, message_id=%s", message_id)
    finally:
        try:
            os.remove(image_path)
        except OSError:
            pass

    # Mark idea as used
    ideas = load_ideas()
    idx = pending.get("idea_index")
    if idx is not None and idx < len(ideas):
        ideas[idx]["used"] = True
        save_ideas(ideas)
        log.info("Idea #%d marked as used", idx)

    # Save history
    add_history_entry(pending["idea"], pending["post_text"], message_id)
    log.info("History entry saved")

    # Update pending status
    pending["status"] = "published"
    pending["published_at"] = datetime.now().isoformat()
    pending["message_id"] = message_id
    pending["published_by"] = "auto"
    save_pending(pending)

    log.info("Phase 2 done!")


def cmd_full() -> None:
    """Legacy: full pipeline (generate + publish in one shot)."""
    log.info("Starting full autoposter pipeline")

    ideas = load_ideas()
    result = get_next_idea(ideas)
    if result is None:
        log.warning("No unused ideas left in %s", IDEAS_FILE)
        sys.exit(0)

    idx, idea = result
    log.info("Idea #%d: %s", idx, idea)

    log.info("Generating post text via %s...", TEXT_PROVIDER)
    post_text, image_prompt = generate_post(idea)
    log.info("Post text generated (%d chars)", len(post_text))
    log.info("Image prompt: %s", image_prompt[:100])

    # Load expert face
    expert_b64 = None
    if FACE_SWAP_PROVIDER:
        from face_swap import load_expert_face_b64
        expert_b64 = load_expert_face_b64()

    inline_face = (
        FACE_SWAP_PROVIDER in ("gemini", "openai")
        and IMAGE_PROVIDER in ("gemini", "openai")
        and expert_b64
    )

    log.info("Generating image via %s...", IMAGE_PROVIDER)
    image_path = generate_image(
        image_prompt,
        expert_face_b64=expert_b64 if inline_face else None,
    )
    log.info("Image saved to %s", image_path)

    if inline_face:
        log.info("Image generated with expert face inline (single API call)")
    elif FACE_SWAP_PROVIDER == "replicate" and expert_b64:
        log.info("Applying face swap via %s...", FACE_SWAP_PROVIDER)
        try:
            new_path = apply_face_swap(
                image_path,
                expert_face_b64=expert_b64,
                method=FACE_SWAP_PROVIDER,
                image_prompt=image_prompt,
            )
            if new_path != image_path:
                try:
                    os.remove(image_path)
                except OSError:
                    pass
                image_path = new_path
                log.info("Face swap applied successfully")
        except Exception as e:
            log.warning("Face swap failed, using original image: %s", e)

    log.info("Sending to Telegram...")
    result = send_post(image_path, post_text)
    message_id = result["result"]["message_id"]
    log.info("Posted successfully, message_id=%s", message_id)

    ideas[idx]["used"] = True
    save_ideas(ideas)
    log.info("Idea #%d marked as used", idx)

    add_history_entry(idea, post_text, message_id)
    log.info("History entry saved")

    try:
        os.remove(image_path)
    except OSError:
        pass

    log.info("Done!")


def main() -> None:
    if len(sys.argv) < 2:
        cmd_full()
        return

    command = sys.argv[1]
    commands = {
        "generate": cmd_generate,
        "publish": cmd_publish,
        "full": cmd_full,
    }

    fn = commands.get(command)
    if fn is None:
        print(f"Unknown command: {command}")
        print(f"Usage: {sys.argv[0]} [generate|publish|full]")
        sys.exit(1)

    fn()


if __name__ == "__main__":
    main()
