import base64
import io
import json
import os
import tempfile
from datetime import datetime

import requests as http_requests
import streamlit as st
from PIL import Image

# Bridge st.secrets → os.environ BEFORE importing project modules
# so that config.py (which uses os.getenv) picks up Streamlit Cloud secrets.
_SECRET_KEYS = [
    "TEXT_PROVIDER", "IMAGE_PROVIDER",
    "CLAUDE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID", "GITHUB_TOKEN",
    "FACE_SWAP_PROVIDER", "REPLICATE_API_KEY",
]
try:
    for _k in _SECRET_KEYS:
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

from generate_text import generate_post, DEFAULT_SYSTEM_PROMPT, DEFAULT_IMAGE_PROMPT_TEMPLATE
from generate_image import generate_image
from face_swap import apply_face_swap, load_expert_face_b64
from post_telegram import send_post

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IDEAS_FILE = os.path.join(BASE_DIR, "ideas.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
PROMPTS_FILE = os.path.join(BASE_DIR, "prompts.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")

GITHUB_REPO = "alexandermalevich85-commits/telegram-autoposter"
PROVIDER_CFG_PATH = "provider.cfg"
PENDING_POST_PATH = "pending_post.json"
EXPERT_FACE_PATH = "expert_face.json"

# ── GitHub API helpers ───────────────────────────────────────────────────────


def _get_github_token() -> str:
    """Get GITHUB_TOKEN from st.secrets (Streamlit Cloud) or env."""
    try:
        if "GITHUB_TOKEN" in st.secrets:
            return str(st.secrets["GITHUB_TOKEN"])
    except Exception:
        pass
    return os.getenv("GITHUB_TOKEN", "")


def _github_headers() -> dict | None:
    """Build GitHub API headers. Returns None if no token."""
    token = _get_github_token()
    if not token:
        return None
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def read_github_file(path: str) -> tuple[str | None, str | None]:
    """Read a file from GitHub repo via Contents API.

    For files > 1 MB the Contents API does not return inline content,
    so we fall back to the raw download URL.

    Returns (content_string, sha) or (None, None) on failure.
    """
    headers = _github_headers()
    if not headers:
        return None, None
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    try:
        resp = http_requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            sha = data["sha"]

            # Normal case: file < 1 MB — content is base64-encoded inline
            if data.get("content"):
                content = base64.b64decode(data["content"]).decode("utf-8")
                return content, sha

            # Large file (> 1 MB): use download_url for raw content
            download_url = data.get("download_url")
            if download_url:
                raw_resp = http_requests.get(download_url, headers=headers, timeout=30)
                if raw_resp.status_code == 200:
                    return raw_resp.text, sha
    except Exception:
        pass
    return None, None


def write_github_file(
    path: str,
    content: str,
    sha: str | None,
    message: str,
) -> tuple[bool, str]:
    """Write a file to GitHub repo via Contents API.

    Returns (True, "") on success, (False, error_message) on failure.
    """
    headers = _github_headers()
    if not headers:
        return False, "GITHUB_TOKEN не задан"

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode()
    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha

    try:
        resp = http_requests.put(api_url, headers=headers, json=payload, timeout=30)
        if resp.status_code in (200, 201):
            return True, ""
        msg = resp.json().get("message", resp.text) if resp.text else f"HTTP {resp.status_code}"
        return False, f"HTTP {resp.status_code}: {msg}"
    except Exception as e:
        return False, str(e)


def update_github_provider_cfg(
    text_provider: str,
    image_provider: str,
    autopublish_enabled: bool | None = None,
    face_swap_provider: str | None = None,
) -> tuple[bool, str]:
    """Update provider.cfg in GitHub repo.

    Returns (True, "") on success, (False, error_message) on failure.
    """
    # Read current file to get SHA and current values
    content, sha = read_github_file(PROVIDER_CFG_PATH)
    current = {}
    if content:
        for line in content.strip().split("\n"):
            if "=" in line:
                k, _, v = line.partition("=")
                current[k.strip()] = v.strip()

    if autopublish_enabled is None:
        autopublish_enabled = current.get("AUTOPUBLISH_ENABLED", "true").lower() != "false"

    if face_swap_provider is None:
        face_swap_provider = current.get("FACE_SWAP_PROVIDER", "")

    enabled_str = "true" if autopublish_enabled else "false"
    new_content = (
        f"TEXT_PROVIDER={text_provider}\n"
        f"IMAGE_PROVIDER={image_provider}\n"
        f"AUTOPUBLISH_ENABLED={enabled_str}\n"
        f"FACE_SWAP_PROVIDER={face_swap_provider}\n"
    )

    return write_github_file(
        PROVIDER_CFG_PATH,
        new_content,
        sha,
        f"Update config: text={text_provider}, image={image_provider}, "
        f"autopublish={enabled_str}, face_swap={face_swap_provider}",
    )


def read_provider_cfg_from_github() -> dict:
    """Read provider.cfg from GitHub and parse it. Returns dict of values."""
    content, _ = read_github_file(PROVIDER_CFG_PATH)
    result = {}
    if content:
        for line in content.strip().split("\n"):
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip()
    return result


# ── Local helpers ────────────────────────────────────────────────────────────


def load_json(path: str, default=None):
    if not os.path.exists(path):
        return default if default is not None else []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_prompts() -> dict:
    defaults = {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "image_prompt_template": DEFAULT_IMAGE_PROMPT_TEMPLATE,
    }
    saved = load_json(PROMPTS_FILE, {})
    return {**defaults, **saved}


def save_env(values: dict):
    lines = []
    for key, val in values.items():
        lines.append(f"{key}={val}")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def load_env_values() -> dict:
    values = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    values[key.strip()] = val.strip()
    return values


def get_expert_face_b64() -> str | None:
    """Get expert face base64: try local file first, then GitHub."""
    # 1. Try local file
    local_b64 = load_expert_face_b64()
    if local_b64:
        return local_b64
    # 2. Try GitHub
    try:
        content, _ = read_github_file(EXPERT_FACE_PATH)
        if content:
            data = json.loads(content)
            b64 = data.get("image_base64")
            if b64:
                # Cache locally for future calls
                local_path = os.path.join(BASE_DIR, "expert_face.json")
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(content)
                return b64
    except Exception:
        pass
    return None


def image_to_base64(image_path: str) -> str:
    """Compress image to JPEG q85 and return base64 string."""
    img = Image.open(image_path)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def base64_to_bytes(b64_string: str) -> bytes:
    """Decode base64 string to raw bytes."""
    return base64.b64decode(b64_string)


def base64_to_tempfile(b64_string: str) -> str:
    """Decode base64 to a temporary JPEG file, return path."""
    data = base64.b64decode(b64_string)
    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="autoposter_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Автопостер Telegram",
    page_icon="📱",
    layout="wide",
)

st.title("📱 Автопостер для Telegram")

# Show flash messages saved before st.rerun()
if st.session_state.pop("_flash_success", None):
    st.success(st.session_state.pop("_flash_msg", "Готово!"))

# ── Sidebar — Settings ──────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Настройки")

    env = load_env_values()

    text_prov = st.selectbox(
        "Провайдер текста",
        ["claude", "gemini", "openai"],
        index=["claude", "gemini", "openai"].index(env.get("TEXT_PROVIDER", "claude"))
        if env.get("TEXT_PROVIDER", "claude") in ["claude", "gemini", "openai"]
        else 0,
    )
    image_prov = st.selectbox(
        "Провайдер картинок",
        ["gemini", "openai"],
        index=["gemini", "openai"].index(env.get("IMAGE_PROVIDER", "gemini"))
        if env.get("IMAGE_PROVIDER", "gemini") in ["gemini", "openai"]
        else 0,
    )

    st.divider()
    st.subheader("🔑 API-ключи")

    claude_key = st.text_input("Claude API Key", value=env.get("CLAUDE_API_KEY", ""), type="password")
    gemini_key = st.text_input("Gemini API Key", value=env.get("GEMINI_API_KEY", ""), type="password")
    openai_key = st.text_input("OpenAI API Key", value=env.get("OPENAI_API_KEY", ""), type="password")

    st.divider()
    st.subheader("📨 Telegram")

    tg_token = st.text_input("Bot Token", value=env.get("TELEGRAM_BOT_TOKEN", ""), type="password")
    tg_channel = st.text_input("Channel ID", value=env.get("TELEGRAM_CHANNEL_ID", ""))

    st.divider()
    st.subheader("🎭 Face Swap")
    st.caption("Замена лица на фото эксперта")

    face_swap_options = ["", "replicate", "gemini", "openai"]
    face_swap_labels = ["Выключено", "Replicate (лучшее качество)", "Gemini (бесплатно)", "OpenAI gpt-image-1"]
    current_fs = env.get("FACE_SWAP_PROVIDER", "")
    fs_index = face_swap_options.index(current_fs) if current_fs in face_swap_options else 0
    face_swap_prov = st.selectbox(
        "Метод замены лица",
        face_swap_options,
        index=fs_index,
        format_func=lambda x: face_swap_labels[face_swap_options.index(x)],
    )

    replicate_key = ""
    if face_swap_prov == "replicate":
        replicate_key = st.text_input(
            "Replicate API Key",
            value=env.get("REPLICATE_API_KEY", ""),
            type="password",
        )

    # Expert face upload
    st.caption("Фото эксперта (для замены лица)")
    expert_face_file = st.file_uploader(
        "Загрузить фото эксперта",
        type=["jpg", "jpeg", "png"],
        key="expert_face_upload",
    )

    # Show current expert face status
    expert_b64 = get_expert_face_b64()
    if expert_b64:
        st.success("Фото эксперта загружено ✅")
        if st.checkbox("Показать фото", key="show_expert_face"):
            st.image(base64.b64decode(expert_b64), width=150)
    else:
        st.info("Фото эксперта не загружено")

    if expert_face_file is not None:
        # Save expert face locally and to GitHub
        img = Image.open(expert_face_file)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=90)
        face_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        face_json = json.dumps({"image_base64": face_b64}, ensure_ascii=False)

        # Save locally
        local_face_path = os.path.join(BASE_DIR, "expert_face.json")
        with open(local_face_path, "w", encoding="utf-8") as f:
            f.write(face_json)

        # Save to GitHub
        if _get_github_token():
            _, face_sha = read_github_file(EXPERT_FACE_PATH)
            ok, err = write_github_file(
                EXPERT_FACE_PATH, face_json, face_sha,
                "Upload expert face photo [streamlit]",
            )
            if ok:
                st.success("Фото эксперта сохранено (локально + GitHub) ✅")
            else:
                st.warning(f"Сохранено локально, но ошибка GitHub: {err}")
        else:
            st.success("Фото эксперта сохранено локально ✅")

    if st.button("💾 Сохранить настройки", use_container_width=True):
        env_data = {
            "TEXT_PROVIDER": text_prov,
            "IMAGE_PROVIDER": image_prov,
            "CLAUDE_API_KEY": claude_key,
            "GEMINI_API_KEY": gemini_key,
            "OPENAI_API_KEY": openai_key,
            "TELEGRAM_BOT_TOKEN": tg_token,
            "TELEGRAM_CHANNEL_ID": tg_channel,
            "FACE_SWAP_PROVIDER": face_swap_prov,
        }
        if replicate_key:
            env_data["REPLICATE_API_KEY"] = replicate_key
        save_env(env_data)
        st.success("Настройки сохранены в .env!")

        # Sync providers to GitHub for scheduled runs
        if _get_github_token():
            try:
                ok, err = update_github_provider_cfg(
                    text_prov, image_prov,
                    face_swap_provider=face_swap_prov,
                )
                if ok:
                    st.success("Провайдеры синхронизированы с GitHub ✅")
                else:
                    st.warning(f"Не удалось обновить provider.cfg на GitHub: {err}")
            except Exception as e:
                st.warning(f"Ошибка синхронизации с GitHub: {e}")
        else:
            st.info("💡 Добавьте GITHUB_TOKEN для авто-синхронизации провайдеров с GitHub Actions")

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_prompts, tab_ideas, tab_create, tab_auto, tab_history = st.tabs(
    ["✏️ Промпты", "📋 Идеи", "🚀 Создать пост", "⏰ Автопубликация", "📊 История"]
)

# ── Tab: Prompts ─────────────────────────────────────────────────────────────

with tab_prompts:
    st.header("✏️ Настройка промптов")

    prompts = load_prompts()

    st.subheader("Системный промпт для текста")
    st.caption("Инструкции для AI при генерации текста поста")
    new_system = st.text_area(
        "Системный промпт",
        value=prompts["system_prompt"],
        height=350,
        label_visibility="collapsed",
    )

    st.subheader("Шаблон промпта для картинки")
    st.caption("Используется как fallback, если AI не вернул промпт. Используйте {idea} для подстановки темы.")
    new_image_tpl = st.text_area(
        "Промпт для картинки",
        value=prompts["image_prompt_template"],
        height=100,
        label_visibility="collapsed",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Сохранить промпты", use_container_width=True):
            save_json(PROMPTS_FILE, {
                "system_prompt": new_system,
                "image_prompt_template": new_image_tpl,
            })
            st.success("Промпты сохранены!")
    with col2:
        if st.button("🔄 Сбросить по умолчанию", use_container_width=True):
            if os.path.exists(PROMPTS_FILE):
                os.remove(PROMPTS_FILE)
            st.success("Промпты сброшены!")
            st.rerun()

# ── Tab: Create Post ─────────────────────────────────────────────────────────

with tab_create:
    st.header("🚀 Создать пост")

    ideas = load_json(IDEAS_FILE, [])
    unused = [item["idea"] for item in ideas if not item.get("used", False)]

    input_mode = st.radio("Источник идеи", ["Из списка", "Ввести вручную"], horizontal=True)

    if input_mode == "Из списка":
        if unused:
            idea = st.selectbox("Выберите идею", unused)
        else:
            st.warning("Нет неиспользованных идей. Добавьте новые во вкладке «Идеи».")
            idea = ""
    else:
        idea = st.text_input("Введите идею для поста")

    # Generate
    if st.button("🎨 Сгенерировать пост", disabled=not idea, use_container_width=True):
        prompts = load_prompts()
        env = load_env_values()

        with st.spinner("Генерирую текст..."):
            try:
                post_text, image_prompt = generate_post(
                    idea,
                    provider=env.get("TEXT_PROVIDER", "claude"),
                    system_prompt=prompts["system_prompt"],
                    image_prompt_template=prompts["image_prompt_template"],
                )
                st.session_state["post_text"] = post_text
                st.session_state["image_prompt"] = image_prompt
                st.session_state["idea"] = idea
            except Exception as e:
                st.error(f"Ошибка генерации текста: {e}")

        if "image_prompt" in st.session_state:
            with st.spinner("Генерирую картинку..."):
                try:
                    image_path = generate_image(
                        st.session_state["image_prompt"],
                        provider=env.get("IMAGE_PROVIDER", "gemini"),
                    )
                    st.session_state["image_path"] = image_path
                except Exception as e:
                    st.error(f"Ошибка генерации картинки: {e}")

            # Apply face swap if enabled (read from sidebar widget, not .env)
            if face_swap_prov and "image_path" in st.session_state:
                expert_b64_for_swap = get_expert_face_b64()
                if expert_b64_for_swap:
                    with st.spinner(f"Применяю face swap ({face_swap_prov})..."):
                        try:
                            new_path = apply_face_swap(
                                st.session_state["image_path"],
                                expert_face_b64=expert_b64_for_swap,
                                method=face_swap_prov,
                                image_prompt=st.session_state.get("image_prompt", ""),
                            )
                            if new_path != st.session_state["image_path"]:
                                old = st.session_state["image_path"]
                                st.session_state["image_path"] = new_path
                                try:
                                    os.remove(old)
                                except OSError:
                                    pass
                                st.success("Face swap применён!")
                        except Exception as e:
                            st.warning(f"Face swap ошибка: {e}. Используется оригинал.")
                else:
                    st.info("Face swap пропущен (фото эксперта не загружено)")

    # Preview
    if "post_text" in st.session_state:
        st.divider()
        st.subheader("Превью поста")

        col_text, col_img = st.columns([3, 2])

        with col_text:
            edited_text = st.text_area(
                "Текст поста (можно редактировать)",
                value=st.session_state["post_text"],
                height=300,
            )
            st.session_state["post_text"] = edited_text

            st.caption("Предпросмотр HTML:")
            st.markdown(edited_text.replace("<b>", "**").replace("</b>", "**")
                        .replace("<i>", "*").replace("</i>", "*"), unsafe_allow_html=True)

        with col_img:
            if "image_path" in st.session_state and os.path.exists(st.session_state["image_path"]):
                st.image(st.session_state["image_path"], caption="Сгенерированная картинка", use_container_width=True)

            # Upload custom image
            custom_img = st.file_uploader(
                "📷 Загрузить свою картинку",
                type=["jpg", "jpeg", "png"],
                key="create_custom_img",
            )
            if custom_img is not None:
                img = Image.open(custom_img)
                fd, custom_path = tempfile.mkstemp(suffix=".png", prefix="autoposter_custom_")
                os.close(fd)
                img.save(custom_path, "PNG")
                old_path = st.session_state.get("image_path")
                if old_path and os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass
                st.session_state["image_path"] = custom_path
                st.success("Картинка заменена!")
                st.rerun()

            edited_img_prompt = st.text_area(
                "Промпт для картинки (можно изменить)",
                value=st.session_state.get("image_prompt", ""),
                height=100,
            )
            st.session_state["image_prompt"] = edited_img_prompt

            if st.button("🔄 Перегенерировать картинку"):
                env = load_env_values()
                with st.spinner("Генерирую новую картинку..."):
                    try:
                        old_path = st.session_state.get("image_path")
                        if old_path and os.path.exists(old_path):
                            os.remove(old_path)
                        image_path = generate_image(
                            st.session_state["image_prompt"],
                            provider=env.get("IMAGE_PROVIDER", "gemini"),
                        )
                        # Apply face swap if enabled (read from sidebar widget)
                        if face_swap_prov:
                            expert_b64_regen = get_expert_face_b64()
                            if expert_b64_regen:
                                try:
                                    new_path = apply_face_swap(
                                        image_path,
                                        expert_face_b64=expert_b64_regen,
                                        method=face_swap_prov,
                                        image_prompt=st.session_state.get("image_prompt", ""),
                                    )
                                    if new_path != image_path:
                                        os.remove(image_path)
                                        image_path = new_path
                                except Exception:
                                    pass
                        st.session_state["image_path"] = image_path
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка: {e}")

        # Publish
        st.divider()
        col_pub, col_regen = st.columns(2)

        with col_pub:
            if st.button("📤 Опубликовать в Telegram", use_container_width=True, type="primary"):
                env = load_env_values()
                if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHANNEL_ID"):
                    st.error("Заполните Telegram Bot Token и Channel ID в настройках!")
                elif "image_path" not in st.session_state:
                    st.error("Сначала сгенерируйте картинку!")
                else:
                    with st.spinner("Публикую..."):
                        try:
                            result = send_post(
                                st.session_state["image_path"],
                                st.session_state["post_text"],
                                bot_token=env.get("TELEGRAM_BOT_TOKEN"),
                                channel_id=env.get("TELEGRAM_CHANNEL_ID"),
                            )
                            msg_id = result["result"]["message_id"]

                            # Mark idea as used
                            current_idea = st.session_state.get("idea", "")
                            ideas = load_json(IDEAS_FILE, [])
                            for item in ideas:
                                if item["idea"] == current_idea and not item.get("used"):
                                    item["used"] = True
                                    break
                            save_json(IDEAS_FILE, ideas)

                            # Save history
                            history = load_json(HISTORY_FILE, [])
                            history.append({
                                "date": datetime.now().isoformat(),
                                "idea": current_idea,
                                "post_text": st.session_state["post_text"],
                                "text_provider": env.get("TEXT_PROVIDER", ""),
                                "image_provider": env.get("IMAGE_PROVIDER", ""),
                                "message_id": msg_id,
                            })
                            save_json(HISTORY_FILE, history)

                            # Cleanup
                            old_path = st.session_state.pop("image_path", None)
                            if old_path and os.path.exists(old_path):
                                os.remove(old_path)
                            st.session_state.pop("post_text", None)
                            st.session_state.pop("image_prompt", None)
                            st.session_state.pop("idea", None)

                            st.session_state["_flash_success"] = True
                            st.session_state["_flash_msg"] = f"✅ Опубликовано! message_id: {msg_id}"
                            st.rerun()

                        except Exception as e:
                            st.error(f"Ошибка публикации: {e}")

        with col_regen:
            if st.button("🔄 Перегенерировать всё", use_container_width=True):
                old_path = st.session_state.pop("image_path", None)
                if old_path and os.path.exists(old_path):
                    os.remove(old_path)
                st.session_state.pop("post_text", None)
                st.session_state.pop("image_prompt", None)
                st.rerun()

# ── Tab: Ideas ───────────────────────────────────────────────────────────────

with tab_ideas:
    st.header("📋 Управление идеями")

    ideas = load_json(IDEAS_FILE, [])

    # Add new idea
    st.subheader("Добавить идею")
    new_idea = st.text_input("Новая идея для поста", key="new_idea_input")
    if st.button("➕ Добавить", disabled=not new_idea):
        ideas.append({"idea": new_idea, "used": False})
        save_json(IDEAS_FILE, ideas)
        st.success(f"Идея добавлена: {new_idea}")
        st.rerun()

    st.divider()

    # Ideas table
    if not ideas:
        st.info("Пока нет идей. Добавьте первую!")
    else:
        for i, item in enumerate(ideas):
            col_status, col_text, col_actions = st.columns([1, 6, 3])

            with col_status:
                if item.get("used"):
                    st.markdown("✅")
                else:
                    st.markdown("⏳")

            with col_text:
                if item.get("used"):
                    st.markdown(f"~~{item['idea']}~~")
                else:
                    st.write(item["idea"])

            with col_actions:
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if item.get("used") and st.button("🔄", key=f"reset_{i}", help="Сбросить статус"):
                        ideas[i]["used"] = False
                        save_json(IDEAS_FILE, ideas)
                        st.rerun()
                with btn_col2:
                    if st.button("🗑️", key=f"del_{i}", help="Удалить"):
                        ideas.pop(i)
                        save_json(IDEAS_FILE, ideas)
                        st.rerun()

    st.divider()
    st.caption(f"Всего идей: {len(ideas)} | Неиспользованных: {sum(1 for i in ideas if not i.get('used'))}")

# ── Tab: History ─────────────────────────────────────────────────────────────

with tab_history:
    st.header("📊 История публикаций")

    history = load_json(HISTORY_FILE, [])

    if not history:
        st.info("Пока нет опубликованных постов.")
    else:
        for entry in reversed(history):
            with st.expander(f"📅 {entry['date'][:16]} — {entry.get('idea', 'N/A')}", expanded=False):
                st.markdown(
                    f"**Идея:** {entry.get('idea', 'N/A')}  \n"
                    f"**Дата:** {entry.get('date', 'N/A')}  \n"
                    f"**Провайдеры:** текст — `{entry.get('text_provider', 'N/A')}`, "
                    f"картинка — `{entry.get('image_provider', 'N/A')}`  \n"
                    f"**Message ID:** `{entry.get('message_id', 'N/A')}`"
                )

                if entry.get("post_text"):
                    post = entry["post_text"]
                    st.divider()
                    st.caption(f"Текст поста ({len(post)} символов):")
                    st.text_area(
                        "Текст (исходный HTML)",
                        value=post,
                        height=250,
                        disabled=True,
                        key=f"hist_{entry.get('message_id', id(entry))}",
                    )
                    st.caption("Предпросмотр:")
                    st.markdown(
                        post.replace("<b>", "**").replace("</b>", "**")
                        .replace("<i>", "*").replace("</i>", "*"),
                        unsafe_allow_html=True,
                    )

        st.caption(f"Всего публикаций: {len(history)}")

# ── Tab: Auto-publish ────────────────────────────────────────────────────────

with tab_auto:
    st.header("⏰ Автопубликация")

    # ── Toggle: enable / disable ─────────────────────────────────────────────

    github_cfg = read_provider_cfg_from_github()
    current_enabled = github_cfg.get("AUTOPUBLISH_ENABLED", "true").lower() != "false"

    st.subheader("🔘 Управление")

    new_enabled = st.toggle(
        "Ежедневная автопубликация включена",
        value=current_enabled,
        key="autopublish_toggle",
    )

    # Detect toggle change
    if new_enabled != current_enabled:
        with st.spinner("Обновляю настройку на GitHub..."):
            ok, err = update_github_provider_cfg(
                github_cfg.get("TEXT_PROVIDER", "openai"),
                github_cfg.get("IMAGE_PROVIDER", "openai"),
                autopublish_enabled=new_enabled,
            )
            if ok:
                st.success("✅ Автопубликация " + ("включена" if new_enabled else "выключена"))
                st.rerun()
            else:
                st.error(f"Ошибка обновления: {err}")

    if new_enabled:
        st.info(
            "📅 **Расписание:**\n"
            "- **05:00 МСК** — генерация черновика (текст + картинка)\n"
            "- **05:00–15:00** — вы можете просмотреть, отредактировать и опубликовать вручную\n"
            "- **15:00 МСК** — если не опубликовано вручную, пост уйдёт автоматически"
        )
    else:
        st.warning("⏸️ Автопубликация выключена. Посты не будут генерироваться и публиковаться автоматически.")

    st.divider()

    # ── Pending draft panel ──────────────────────────────────────────────────

    st.subheader("📋 Черновик поста")

    # Fetch pending_post.json from GitHub
    pending_raw, pending_sha = read_github_file(PENDING_POST_PATH)

    if pending_raw is None:
        st.info("📭 Нет черновика. Следующий черновик будет сгенерирован в **05:00 МСК**.")
    else:
        try:
            pending = json.loads(pending_raw)
        except json.JSONDecodeError:
            st.error("Ошибка чтения pending_post.json")
            pending = None

        if pending:
            status = pending.get("status", "unknown")
            created = pending.get("created_at", "")[:16]

            if status == "published":
                # ── Already published ────────────────────────────────────
                published_by = pending.get("published_by", "?")
                published_at = (pending.get("published_at") or "")[:16]
                msg_id = pending.get("message_id", "?")
                by_label = "вручную" if published_by == "manual" else "автоматически"

                st.success(
                    f"✅ Пост опубликован **{by_label}** "
                    f"в {published_at} (message_id: {msg_id})"
                )

                with st.expander("Показать опубликованный пост", expanded=False):
                    st.markdown(
                        pending.get("post_text", "").replace("<b>", "**").replace("</b>", "**")
                        .replace("<i>", "*").replace("</i>", "*"),
                        unsafe_allow_html=True,
                    )
                    if pending.get("image_base64"):
                        st.image(
                            base64_to_bytes(pending["image_base64"]),
                            caption="Картинка поста",
                            use_container_width=True,
                        )

            elif status == "pending":
                # ── Pending draft — editable ─────────────────────────────
                st.warning(f"⏳ Черновик от **{created}** ожидает публикации")
                st.caption(f"Идея: **{pending.get('idea', 'N/A')}** | "
                           f"Провайдеры: текст — `{pending.get('text_provider')}`, "
                           f"картинка — `{pending.get('image_provider')}`")

                col_text, col_img = st.columns([3, 2])

                with col_text:
                    draft_text = st.text_area(
                        "Текст поста (можно редактировать перед публикацией)",
                        value=pending.get("post_text", ""),
                        height=300,
                        key="draft_text_editor",
                    )

                    st.caption("Предпросмотр HTML:")
                    st.markdown(
                        draft_text.replace("<b>", "**").replace("</b>", "**")
                        .replace("<i>", "*").replace("</i>", "*"),
                        unsafe_allow_html=True,
                    )

                with col_img:
                    if pending.get("image_base64"):
                        st.image(
                            base64_to_bytes(pending["image_base64"]),
                            caption="Сгенерированная картинка",
                            use_container_width=True,
                        )

                    # Upload custom image for draft
                    draft_custom_img = st.file_uploader(
                        "📷 Загрузить свою картинку",
                        type=["jpg", "jpeg", "png"],
                        key="draft_custom_img",
                    )
                    if draft_custom_img is not None:
                        img = Image.open(draft_custom_img)
                        buf = io.BytesIO()
                        img.convert("RGB").save(buf, format="JPEG", quality=85)
                        new_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

                        pending["image_base64"] = new_b64
                        ok, err = write_github_file(
                            PENDING_POST_PATH,
                            json.dumps(pending, ensure_ascii=False, indent=2),
                            pending_sha,
                            "Update draft: custom image uploaded [manual]",
                        )
                        if ok:
                            st.success("Картинка заменена!")
                            st.rerun()
                        else:
                            st.error(f"Ошибка сохранения: {err}")

                    draft_img_prompt = st.text_area(
                        "Промпт для картинки",
                        value=pending.get("image_prompt", ""),
                        height=100,
                        key="draft_img_prompt_editor",
                    )

                    if st.button("🔄 Перегенерировать картинку", key="draft_regen_img"):
                        env = load_env_values()
                        with st.spinner("Генерирую новую картинку..."):
                            try:
                                new_image_path = generate_image(
                                    draft_img_prompt,
                                    provider=env.get("IMAGE_PROVIDER", "openai"),
                                )
                                # Apply face swap if enabled
                                if face_swap_prov:
                                    expert_b64_regen = get_expert_face_b64()
                                    if expert_b64_regen:
                                        try:
                                            swapped = apply_face_swap(
                                                new_image_path,
                                                expert_face_b64=expert_b64_regen,
                                                method=face_swap_prov,
                                                image_prompt=draft_img_prompt,
                                            )
                                            if swapped != new_image_path:
                                                os.remove(new_image_path)
                                                new_image_path = swapped
                                        except Exception as e:
                                            st.warning(f"Face swap ошибка: {e}")
                                new_b64 = image_to_base64(new_image_path)
                                os.remove(new_image_path)

                                # Update pending on GitHub
                                pending["image_base64"] = new_b64
                                pending["image_prompt"] = draft_img_prompt
                                ok, err = write_github_file(
                                    PENDING_POST_PATH,
                                    json.dumps(pending, ensure_ascii=False, indent=2),
                                    pending_sha,
                                    "Update draft: regenerated image [manual]",
                                )
                                if ok:
                                    st.success("Картинка обновлена!")
                                    st.rerun()
                                else:
                                    st.error(f"Ошибка сохранения на GitHub: {err}")
                            except Exception as e:
                                st.error(f"Ошибка: {e}")

                # ── Action buttons ───────────────────────────────────────
                st.divider()
                col_pub, col_save = st.columns(2)

                with col_pub:
                    if st.button("📤 Опубликовать в Telegram", key="draft_publish",
                                 use_container_width=True, type="primary"):
                        env = load_env_values()
                        bot_token = env.get("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
                        channel_id = env.get("TELEGRAM_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID", "")

                        if not bot_token or not channel_id:
                            st.error("Заполните Telegram настройки!")
                        elif not pending.get("image_base64"):
                            st.error("Нет картинки в черновике!")
                        else:
                            with st.spinner("Публикую..."):
                                try:
                                    # Decode image to temp file
                                    tmp_path = base64_to_tempfile(pending["image_base64"])
                                    try:
                                        result = send_post(
                                            tmp_path,
                                            draft_text,
                                            bot_token=bot_token,
                                            channel_id=channel_id,
                                        )
                                        msg_id = result["result"]["message_id"]
                                    finally:
                                        try:
                                            os.remove(tmp_path)
                                        except OSError:
                                            pass

                                    # 1. Update pending_post.json on GitHub
                                    pending["status"] = "published"
                                    pending["published_at"] = datetime.now().isoformat()
                                    pending["message_id"] = msg_id
                                    pending["published_by"] = "manual"
                                    pending["post_text"] = draft_text
                                    ok1, err1 = write_github_file(
                                        PENDING_POST_PATH,
                                        json.dumps(pending, ensure_ascii=False, indent=2),
                                        pending_sha,
                                        f"Manual publish: message_id={msg_id} [manual]",
                                    )

                                    # 2. Update ideas.json on GitHub
                                    ideas_raw, ideas_sha = read_github_file("ideas.json")
                                    if ideas_raw:
                                        ideas_data = json.loads(ideas_raw)
                                        idx = pending.get("idea_index")
                                        if idx is not None and idx < len(ideas_data):
                                            ideas_data[idx]["used"] = True
                                            write_github_file(
                                                "ideas.json",
                                                json.dumps(ideas_data, ensure_ascii=False, indent=2),
                                                ideas_sha,
                                                f"Mark idea #{idx} as used [manual]",
                                            )

                                    # 3. Update history.json on GitHub
                                    hist_raw, hist_sha = read_github_file("history.json")
                                    hist_data = json.loads(hist_raw) if hist_raw else []
                                    hist_data.append({
                                        "date": datetime.now().isoformat(),
                                        "idea": pending.get("idea", ""),
                                        "post_text": draft_text,
                                        "text_provider": pending.get("text_provider", ""),
                                        "image_provider": pending.get("image_provider", ""),
                                        "message_id": msg_id,
                                    })
                                    write_github_file(
                                        "history.json",
                                        json.dumps(hist_data, ensure_ascii=False, indent=2),
                                        hist_sha,
                                        f"Add history entry for msg {msg_id} [manual]",
                                    )

                                    # Also update local files
                                    local_ideas = load_json(IDEAS_FILE, [])
                                    idx = pending.get("idea_index")
                                    if idx is not None and idx < len(local_ideas):
                                        local_ideas[idx]["used"] = True
                                        save_json(IDEAS_FILE, local_ideas)

                                    local_hist = load_json(HISTORY_FILE, [])
                                    local_hist.append({
                                        "date": datetime.now().isoformat(),
                                        "idea": pending.get("idea", ""),
                                        "post_text": draft_text,
                                        "text_provider": pending.get("text_provider", ""),
                                        "image_provider": pending.get("image_provider", ""),
                                        "message_id": msg_id,
                                    })
                                    save_json(HISTORY_FILE, local_hist)

                                    st.session_state["_flash_success"] = True
                                    st.session_state["_flash_msg"] = f"✅ Опубликовано! message_id: {msg_id}"
                                    st.rerun()

                                except Exception as e:
                                    st.error(f"Ошибка публикации: {e}")

                with col_save:
                    if st.button("💾 Сохранить изменения текста", key="draft_save_text",
                                 use_container_width=True):
                        pending["post_text"] = draft_text
                        pending["image_prompt"] = draft_img_prompt
                        ok, err = write_github_file(
                            PENDING_POST_PATH,
                            json.dumps(pending, ensure_ascii=False, indent=2),
                            pending_sha,
                            "Update draft text [manual]",
                        )
                        if ok:
                            st.success("Текст черновика сохранён на GitHub!")
                            st.rerun()
                        else:
                            st.error(f"Ошибка: {err}")

            else:
                st.info(f"Статус черновика: `{status}`")

    # ── Manual generate (for testing) ────────────────────────────────────────

    st.divider()
    st.subheader("🧪 Ручная генерация черновика")
    st.caption("Сгенерировать черновик прямо сейчас (для тестирования)")

    ideas = load_json(IDEAS_FILE, [])
    next_idea = None
    next_idx = None
    for i, item in enumerate(ideas):
        if not item.get("used"):
            next_idea = item["idea"]
            next_idx = i
            break

    if next_idea:
        st.info(f"Следующая идея: **{next_idea}**")

        if st.button("🎨 Сгенерировать черновик", key="manual_gen", use_container_width=True):
            env = load_env_values()
            prompts = load_prompts()

            with st.spinner("Генерирую текст..."):
                try:
                    post_text, image_prompt = generate_post(
                        next_idea,
                        provider=env.get("TEXT_PROVIDER", "openai"),
                        system_prompt=prompts["system_prompt"],
                        image_prompt_template=prompts["image_prompt_template"],
                    )
                except Exception as e:
                    st.error(f"Ошибка генерации текста: {e}")
                    post_text = None

            if post_text:
                with st.spinner("Генерирую картинку..."):
                    try:
                        img_path = generate_image(
                            image_prompt,
                            provider=env.get("IMAGE_PROVIDER", "openai"),
                        )
                        # Apply face swap if enabled (read from sidebar widget)
                        if face_swap_prov:
                            expert_b64_draft = get_expert_face_b64()
                            if expert_b64_draft:
                                try:
                                    new_path = apply_face_swap(
                                        img_path,
                                        expert_face_b64=expert_b64_draft,
                                        method=face_swap_prov,
                                        image_prompt=image_prompt,
                                    )
                                    if new_path != img_path:
                                        os.remove(img_path)
                                        img_path = new_path
                                except Exception as e:
                                    st.warning(f"Face swap ошибка: {e}")
                        img_b64 = image_to_base64(img_path)
                        os.remove(img_path)
                    except Exception as e:
                        st.error(f"Ошибка генерации картинки: {e}")
                        img_b64 = None

                if img_b64:
                    # Save to GitHub as pending draft
                    draft_data = {
                        "status": "pending",
                        "created_at": datetime.now().isoformat(),
                        "idea": next_idea,
                        "idea_index": next_idx,
                        "post_text": post_text,
                        "image_prompt": image_prompt,
                        "image_base64": img_b64,
                        "text_provider": env.get("TEXT_PROVIDER", "openai"),
                        "image_provider": env.get("IMAGE_PROVIDER", "openai"),
                        "face_swap_provider": face_swap_prov if face_swap_prov else "",
                        "published_at": None,
                        "message_id": None,
                        "published_by": None,
                    }

                    # Read existing SHA if file exists
                    _, existing_sha = read_github_file(PENDING_POST_PATH)

                    with st.spinner("Сохраняю черновик на GitHub..."):
                        ok, err = write_github_file(
                            PENDING_POST_PATH,
                            json.dumps(draft_data, ensure_ascii=False, indent=2),
                            existing_sha,
                            "Manual draft generation [streamlit]",
                        )
                        if ok:
                            st.session_state["_flash_success"] = True
                            st.session_state["_flash_msg"] = "✅ Черновик сгенерирован и сохранён!"
                            st.rerun()
                        else:
                            st.error(f"Ошибка сохранения на GitHub: {err}")
    else:
        st.warning("Нет неиспользованных идей. Добавьте новые во вкладке «Идеи».")
