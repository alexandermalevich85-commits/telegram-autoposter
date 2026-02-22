import json
import logging
import os
import sys

from generate_text import generate_post
from generate_image import generate_image
from post_telegram import send_post

IDEAS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ideas.json")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("autoposter")


def load_ideas() -> list[dict]:
    with open(IDEAS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ideas(ideas: list[dict]) -> None:
    with open(IDEAS_FILE, "w", encoding="utf-8") as f:
        json.dump(ideas, f, ensure_ascii=False, indent=2)


def get_next_idea(ideas: list[dict]) -> tuple[int, str] | None:
    """Return (index, idea_text) for the first unused idea, or None."""
    for i, item in enumerate(ideas):
        if not item.get("used", False):
            return i, item["idea"]
    return None


def main() -> None:
    log.info("Starting autoposter pipeline")

    # 1. Load idea
    ideas = load_ideas()
    result = get_next_idea(ideas)
    if result is None:
        log.warning("No unused ideas left in %s", IDEAS_FILE)
        sys.exit(0)

    idx, idea = result
    log.info("Idea #%d: %s", idx, idea)

    # 2. Generate post text via Claude API
    log.info("Generating post text...")
    post_text, image_prompt = generate_post(idea)
    log.info("Post text generated (%d chars)", len(post_text))
    log.info("Image prompt: %s", image_prompt[:100])

    # 3. Generate image via Gemini API
    log.info("Generating image...")
    image_path = generate_image(image_prompt)
    log.info("Image saved to %s", image_path)

    # 4. Post to Telegram
    log.info("Sending to Telegram...")
    result = send_post(image_path, post_text)
    message_id = result["result"]["message_id"]
    log.info("Posted successfully, message_id=%s", message_id)

    # 5. Mark idea as used
    ideas[idx]["used"] = True
    save_ideas(ideas)
    log.info("Idea #%d marked as used", idx)

    # 6. Cleanup temp image
    try:
        os.remove(image_path)
    except OSError:
        pass

    log.info("Done!")


if __name__ == "__main__":
    main()
