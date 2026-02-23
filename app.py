import base64
import json
import os
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
]
try:
    for _k in _SECRET_KEYS:
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

from generate_text import generate_post, DEFAULT_SYSTEM_PROMPT, DEFAULT_IMAGE_PROMPT_TEMPLATE
from generate_image import generate_image
from post_telegram import send_post

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IDEAS_FILE = os.path.join(BASE_DIR, "ideas.json")
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
PROMPTS_FILE = os.path.join(BASE_DIR, "prompts.json")
ENV_FILE = os.path.join(BASE_DIR, ".env")

GITHUB_REPO = "alexandermalevich85-commits/telegram-autoposter"
PROVIDER_CFG_PATH = "provider.cfg"

# ── GitHub sync ──────────────────────────────────────────────────────────────


def _get_github_token() -> str:
    """Get GITHUB_TOKEN from st.secrets (Streamlit Cloud) or env."""
    try:
        if "GITHUB_TOKEN" in st.secrets:
            return str(st.secrets["GITHUB_TOKEN"])
    except Exception:
        pass
    return os.getenv("GITHUB_TOKEN", "")


def update_github_provider_cfg(text_provider: str, image_provider: str) -> tuple[bool, str]:
    """Update provider.cfg in GitHub repo via Contents API.

    Returns (True, "") on success, (False, error_message) on failure.
    """
    token = _get_github_token()
    if not token:
        return False, "GITHUB_TOKEN не задан"

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{PROVIDER_CFG_PATH}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Get current file SHA (required for update)
    sha = None
    resp = http_requests.get(api_url, headers=headers, timeout=10)
    if resp.status_code == 200:
        sha = resp.json().get("sha")
    elif resp.status_code == 404:
        # File doesn't exist yet — will be created
        sha = None
    else:
        msg = resp.json().get("message", resp.text) if resp.text else f"HTTP {resp.status_code}"
        return False, f"Ошибка чтения файла (HTTP {resp.status_code}): {msg}"

    # Build new content
    new_content = f"TEXT_PROVIDER={text_provider}\nIMAGE_PROVIDER={image_provider}\n"
    encoded = base64.b64encode(new_content.encode()).decode()

    payload = {
        "message": f"Update providers: text={text_provider}, image={image_provider}",
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha

    resp = http_requests.put(api_url, headers=headers, json=payload, timeout=10)
    if resp.status_code in (200, 201):
        return True, ""
    msg = resp.json().get("message", resp.text) if resp.text else f"HTTP {resp.status_code}"
    return False, f"HTTP {resp.status_code}: {msg}"


# ── Helpers ──────────────────────────────────────────────────────────────────


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

    if st.button("💾 Сохранить настройки", use_container_width=True):
        save_env({
            "TEXT_PROVIDER": text_prov,
            "IMAGE_PROVIDER": image_prov,
            "CLAUDE_API_KEY": claude_key,
            "GEMINI_API_KEY": gemini_key,
            "OPENAI_API_KEY": openai_key,
            "TELEGRAM_BOT_TOKEN": tg_token,
            "TELEGRAM_CHANNEL_ID": tg_channel,
        })
        st.success("Настройки сохранены в .env!")

        # Sync providers to GitHub for scheduled runs
        if _get_github_token():
            try:
                ok, err = update_github_provider_cfg(text_prov, image_prov)
                if ok:
                    st.success("Провайдеры синхронизированы с GitHub ✅")
                else:
                    st.warning(f"Не удалось обновить provider.cfg на GitHub: {err}")
            except Exception as e:
                st.warning(f"Ошибка синхронизации с GitHub: {e}")
        else:
            st.info("💡 Добавьте GITHUB_TOKEN для авто-синхронизации провайдеров с GitHub Actions")

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_prompts, tab_create, tab_ideas, tab_history, tab_auto = st.tabs(
    ["✏️ Промпты", "🚀 Создать пост", "📋 Идеи", "📊 История", "⏰ Автопубликация"]
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
                            st.success(f"Опубликовано! message_id: {msg_id}")

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

                            # Flash + rerun so history tab shows the new entry
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

    st.subheader("Запуск по расписанию (cron)")
    st.markdown("""
Для автоматической публикации по расписанию добавьте в crontab:

```bash
crontab -e
```

Пример — каждый день в 10:00:
```
0 10 * * * cd /path/to/project && /path/to/venv/bin/python main.py >> autoposter.log 2>&1
```
    """)

    st.divider()
    st.subheader("Ручной запуск")
    st.caption("Сгенерировать пост из следующей идеи, просмотреть и опубликовать")

    ideas = load_json(IDEAS_FILE, [])
    next_idea = None
    for item in ideas:
        if not item.get("used"):
            next_idea = item["idea"]
            break

    if next_idea:
        st.info(f"Следующая идея: **{next_idea}**")

        # Step 1: Generate (with preview)
        if st.button("🎨 Сгенерировать пост", key="auto_generate", use_container_width=True):
            env = load_env_values()
            prompts = load_prompts()

            if not env.get("TELEGRAM_BOT_TOKEN") or not env.get("TELEGRAM_CHANNEL_ID"):
                st.error("Заполните Telegram настройки в сайдбаре!")
            else:
                with st.spinner("Генерирую текст..."):
                    try:
                        post_text, image_prompt = generate_post(
                            next_idea,
                            provider=env.get("TEXT_PROVIDER", "claude"),
                            system_prompt=prompts["system_prompt"],
                            image_prompt_template=prompts["image_prompt_template"],
                        )
                        st.session_state["auto_post_text"] = post_text
                        st.session_state["auto_image_prompt"] = image_prompt
                        st.session_state["auto_idea"] = next_idea
                    except Exception as e:
                        st.error(f"Ошибка генерации текста: {e}")

                if "auto_image_prompt" in st.session_state:
                    with st.spinner("Генерирую картинку..."):
                        try:
                            image_path = generate_image(
                                st.session_state["auto_image_prompt"],
                                provider=env.get("IMAGE_PROVIDER", "gemini"),
                            )
                            st.session_state["auto_image_path"] = image_path
                        except Exception as e:
                            st.error(f"Ошибка генерации картинки: {e}")

        # Step 2: Preview
        if "auto_post_text" in st.session_state:
            st.divider()
            st.subheader("📋 Превью поста")

            col_text, col_img = st.columns([3, 2])

            with col_text:
                auto_edited_text = st.text_area(
                    "Текст поста (можно редактировать)",
                    value=st.session_state["auto_post_text"],
                    height=300,
                    key="auto_text_editor",
                )
                st.session_state["auto_post_text"] = auto_edited_text

                st.caption("Предпросмотр HTML:")
                st.markdown(
                    auto_edited_text.replace("<b>", "**").replace("</b>", "**")
                    .replace("<i>", "*").replace("</i>", "*"),
                    unsafe_allow_html=True,
                )

            with col_img:
                if "auto_image_path" in st.session_state and os.path.exists(st.session_state["auto_image_path"]):
                    st.image(st.session_state["auto_image_path"], caption="Сгенерированная картинка", use_container_width=True)

                auto_edited_img_prompt = st.text_area(
                    "Промпт для картинки (можно изменить)",
                    value=st.session_state.get("auto_image_prompt", ""),
                    height=100,
                    key="auto_img_prompt_editor",
                )
                st.session_state["auto_image_prompt"] = auto_edited_img_prompt

                if st.button("🔄 Перегенерировать картинку", key="auto_regen_img"):
                    env = load_env_values()
                    with st.spinner("Генерирую новую картинку..."):
                        try:
                            old_path = st.session_state.get("auto_image_path")
                            if old_path and os.path.exists(old_path):
                                os.remove(old_path)
                            image_path = generate_image(
                                st.session_state["auto_image_prompt"],
                                provider=env.get("IMAGE_PROVIDER", "gemini"),
                            )
                            st.session_state["auto_image_path"] = image_path
                            st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка: {e}")

            # Step 3: Publish or regenerate
            st.divider()
            col_pub, col_regen = st.columns(2)

            with col_pub:
                if st.button("📤 Опубликовать в Telegram", key="auto_publish", use_container_width=True, type="primary"):
                    env = load_env_values()
                    if "auto_image_path" not in st.session_state:
                        st.error("Сначала сгенерируйте картинку!")
                    else:
                        with st.spinner("Публикую..."):
                            try:
                                result = send_post(
                                    st.session_state["auto_image_path"],
                                    st.session_state["auto_post_text"],
                                    bot_token=env.get("TELEGRAM_BOT_TOKEN"),
                                    channel_id=env.get("TELEGRAM_CHANNEL_ID"),
                                )
                                msg_id = result["result"]["message_id"]

                                # Mark used
                                current_idea = st.session_state.get("auto_idea", "")
                                for item in ideas:
                                    if item["idea"] == current_idea and not item.get("used"):
                                        item["used"] = True
                                        break
                                save_json(IDEAS_FILE, ideas)

                                # History
                                history = load_json(HISTORY_FILE, [])
                                history.append({
                                    "date": datetime.now().isoformat(),
                                    "idea": current_idea,
                                    "post_text": st.session_state["auto_post_text"],
                                    "text_provider": env.get("TEXT_PROVIDER", ""),
                                    "image_provider": env.get("IMAGE_PROVIDER", ""),
                                    "message_id": msg_id,
                                })
                                save_json(HISTORY_FILE, history)

                                # Cleanup
                                old_path = st.session_state.pop("auto_image_path", None)
                                if old_path and os.path.exists(old_path):
                                    os.remove(old_path)
                                st.session_state.pop("auto_post_text", None)
                                st.session_state.pop("auto_image_prompt", None)
                                st.session_state.pop("auto_idea", None)

                                # Flash + rerun so history tab shows the new entry
                                st.session_state["_flash_success"] = True
                                st.session_state["_flash_msg"] = f"✅ Опубликовано! message_id: {msg_id}"
                                st.rerun()

                            except Exception as e:
                                st.error(f"Ошибка публикации: {e}")

            with col_regen:
                if st.button("🔄 Перегенерировать всё", key="auto_regen_all", use_container_width=True):
                    old_path = st.session_state.pop("auto_image_path", None)
                    if old_path and os.path.exists(old_path):
                        os.remove(old_path)
                    st.session_state.pop("auto_post_text", None)
                    st.session_state.pop("auto_image_prompt", None)
                    st.rerun()

    else:
        st.warning("Нет неиспользованных идей. Добавьте новые во вкладке «Идеи».")
