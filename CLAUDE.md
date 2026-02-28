# Telegram Autoposter — Проектная память

## Обзор проекта
Автопостер для Telegram-канала эксперта по естественному омоложению лица.
Целевая аудитория: женщины 30-55 лет.

**Двухфазный пайплайн:**
1. **Phase 1 (05:00 МСК / 02:00 UTC):** Генерация черновика → `pending_post.json`
2. **Phase 2 (15:00 МСК / 12:00 UTC):** Публикация в Telegram

Между фазами — окно 10 часов для ручного редактирования через Streamlit UI.

---

## Архитектура файлов

| Файл | Назначение |
|------|-----------|
| `main.py` | CLI: `generate` / `publish` / `full` |
| `app.py` | Streamlit Web UI (~1390 строк) |
| `config.py` | Загрузка env-переменных, API-ключей, фабрика `get_gemini_client()` |
| `generate_text.py` | Генерация текста (Claude/Gemini/OpenAI) |
| `generate_image.py` | Генерация изображений (Gemini/OpenAI), поддержка inline face |
| `face_swap.py` | Замена лица (Replicate/Gemini/OpenAI) — отдельный шаг |
| `post_telegram.py` | Отправка в Telegram |
| `document_parser.py` | Парсинг PDF/DOCX/TXT документов |

**Данные (JSON):**
- `ideas.json` — пул идей для постов (`used: true/false`)
- `pending_post.json` — текущий черновик (текст + base64 картинка)
- `history.json` — архив опубликованных постов
- `prompts.json` — кастомные промпты (system + image)
- `expert_face.json` — base64 фото эксперта для face swap
- `prompt_context.json` — контекстный документ (опционально)

**Конфигурация:**
- `provider.cfg` — выбор провайдеров + флаг автопубликации
- `.github/workflows/autopublish.yml` — GitHub Actions

---

## Провайдеры

### Текст
| Провайдер | Модель | Статус |
|-----------|--------|--------|
| `openai` | gpt-4o | Работает |
| `claude` | claude-sonnet-4-5-20250929 | Работает |
| `gemini` | gemini-2.5-flash | Работает |

### Изображения
| Провайдер | Модель (без face) | Модель (с inline face) | Статус |
|-----------|-------------------|------------------------|--------|
| `openai` | dall-e-3 (1024x1024) | gpt-image-1 via `images.edit()` | Работает |
| `gemini` | gemini-2.5-flash-image | gemini-2.5-flash-image (multimodal) | Работает (нужен биллинг) |

### Face Swap (отдельный шаг)
| Провайдер | Модель | Статус |
|-----------|--------|--------|
| `replicate` | codeplugtech/face-swap:278a81e7... | Работает (платно ~$0.01) |
| `gemini` | gemini-2.5-flash-image | Работает (нужен биллинг) |
| `openai` | gpt-image-1 via `images.edit()` | Работает |

---

## Inline Face Generation (ключевая фича, февраль 2026)

Вместо двух API-вызовов (генерация + face swap) — **один вызов** с лицом эксперта как референсом.

### Как работает
```
Если FACE_SWAP_PROVIDER in (gemini, openai) AND IMAGE_PROVIDER in (gemini, openai):
  → Inline: generate_image(expert_face_b64=...) — 1 вызов
Если FACE_SWAP_PROVIDER == replicate:
  → Раздельно: generate_image() + apply_face_swap() — 2 вызова
```

### Реализация по провайдерам

**Gemini inline:**
```python
# generate_image.py → _generate_gemini()
contents = [
    prompt + "\n\nСоздай изображение, где главный персонаж имеет лицо "
             "с приложенного референсного фото...",
    types.Part.from_bytes(data=face_bytes, mime_type="image/jpeg"),
]
response = client.models.generate_content(
    model="gemini-2.5-flash-image", contents=contents,
    config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
)
```

**OpenAI inline:**
```python
# generate_image.py → _generate_openai()
response = client.images.edit(
    model="gpt-image-1",
    image=face_file,  # io.BytesIO с фото эксперта
    prompt=full_prompt,
    size="1024x1024", quality="medium",
)
img_b64 = response.data[0].b64_json
```

### Где вызывается inline face
Логика inline face реализована в **4 местах** `app.py` + **2 места** `main.py`:
```python
inline_face = (
    face_swap_prov in ("gemini", "openai")
    and img_prov in ("gemini", "openai")
    and expert_b64_for_swap
)
```

---

## Dual Auth: AI Studio + Vertex AI

`config.py` содержит фабрику `get_gemini_client()` с тремя уровнями приоритета:
1. `api_key_override` (явный ключ) → AI Studio
2. `GOOGLE_PROJECT_ID` + service account → Vertex AI
3. `GEMINI_API_KEY` → AI Studio

```python
def get_gemini_client(api_key_override=None):
    from google import genai
    if api_key_override:
        return genai.Client(api_key=api_key_override)
    if GOOGLE_PROJECT_ID:
        _setup_vertex_credentials()
        return genai.Client(vertexai=True, project=GOOGLE_PROJECT_ID, location=GOOGLE_LOCATION)
    if GEMINI_API_KEY:
        return genai.Client(api_key=GEMINI_API_KEY)
    raise ValueError("No Gemini credentials found...")
```

Все модули используют `get_gemini_client()`: `generate_text.py`, `generate_image.py`, `face_swap.py`.

---

## Решённые проблемы

### 1. Replicate face swap — модель удалена (февраль 2026)
**Проблема:** Оригинальная модель `xiankgx/face-swap` удалена с Replicate (404).
**Решение:** Заменена на `codeplugtech/face-swap` с явным version hash.
**Важно:** Без version hash Replicate SDK использует endpoint `/v1/models/.../predictions` (404). С hash используется `/v1/predictions` (работает).
```python
# ПРАВИЛЬНО — с version hash:
"codeplugtech/face-swap:278a81e7ebb22db98bcba54de985d22cc1abeead2754eb1f2af717247be69b34"

# НЕПРАВИЛЬНО — без hash (404):
"codeplugtech/face-swap"
```

### 2. REPLICATE_API_KEY не был добавлен в GitHub Secrets
**Проблема:** Ключ отсутствовал → ошибка "REPLICATE_API_KEY не задан".
**Решение:** Добавлен в Settings → Secrets → Actions.

### 3. Нерабочие модели Replicate (не использовать)
- `xiankgx/face-swap` — удалена
- `arabyai-replicate/roop_face_swap` — только видео, не изображения
- `cdingram/face-swap` (без hash) — 404
- `easel/advanced-face-swap` — 404
- `fofr/face-swap-with-ideogram` — 404

### 4. Рассинхрон provider.cfg между локальной копией и GitHub
**Проблема:** Streamlit UI обновляет файл через GitHub API, а локальная копия остаётся старой.
**Решение:** Всегда делать `git pull` перед работой, или проверять актуальный provider.cfg на GitHub.

### 5. Gemini: устаревшие модели (февраль 2026)
**Проблема:** Модель `gemini-2.5-flash-preview-04-17` удалена → ошибка `'ascii' codec can't encode`.
**Решение:** Обновлены модели:
- Текст: `gemini-2.5-flash-preview-04-17` → `gemini-2.5-flash` (GA)
- Изображения/face swap: → `gemini-2.5-flash-image` (GA)

### 6. Gemini: API ключ из Cloud Console vs AI Studio
**Проблема:** Ключ из Google Cloud Console (Vertex AI) дает ошибку "API keys are not supported by this API".
**Решение:** Для AI Studio нужен ключ **только с aistudio.google.com**. Ключи из Cloud Console — это Vertex AI, требуют OAuth2.

### 7. Gemini: модели с OAuth2 (не работают с API ключами)
**Проблема:** `gemini-3.1-flash-image-preview` (Nano Banana 2) и `gemini-2.5-flash-preview-05-20` требуют OAuth2.
**Решение:** Использовать GA-модели: `gemini-2.5-flash` (текст), `gemini-2.5-flash-image` (картинки).

### 8. Gemini: квота free tier = 0 для image generation
**Проблема:** Бесплатный ключ AI Studio имеет лимит 0 запросов для `gemini-2.5-flash-preview-image` → ошибка 429 RESOURCE_EXHAUSTED.
**Решение:** Inline face generation (1 вызов вместо 2) снижает расход квоты. Но для стабильной работы нужно **включить биллинг** в AI Studio.

---

## Текущая конфигурация (provider.cfg на GitHub)
```
TEXT_PROVIDER=gemini
IMAGE_PROVIDER=openai
FACE_SWAP_PROVIDER=openai
AUTOPUBLISH_ENABLED=true
```

При этой конфигурации:
- Текст генерируется через **Gemini** (`gemini-2.5-flash`)
- Картинка генерируется через **OpenAI** с лицом эксперта **inline** (`gpt-image-1` via `images.edit()`)
- Face swap как отдельный шаг **не вызывается** (inline)

---

## Комбинации настроек в Streamlit UI

| IMAGE_PROVIDER | FACE_SWAP_PROVIDER | Что происходит |
|----------------|-------------------|----------------|
| `gemini` | `gemini` | 1 вызов: Gemini генерирует картинку с лицом (inline) |
| `openai` | `openai` | 1 вызов: OpenAI gpt-image-1 генерирует картинку с лицом (inline) |
| `gemini` | `openai` | 1 вызов: Gemini + inline face (IMAGE_PROVIDER и FACE_SWAP оба поддерживают inline) |
| `openai` | `gemini` | 1 вызов: OpenAI + inline face |
| `gemini` | `replicate` | 2 вызова: Gemini генерирует + Replicate меняет лицо |
| `openai` | `replicate` | 2 вызова: OpenAI dall-e-3 генерирует + Replicate меняет лицо |
| любой | (пусто) | Картинка без лица эксперта |

---

## Важные технические детали

- **Telegram:** Caption <= 1024 символов → если длиннее, отправляется фото + отдельное сообщение
- **Base64 изображения:** Хранятся в JSON, JPEG quality=85
- **Face swap fallback:** Если ошибка — публикуется без замены лица (не падает)
- **GitHub как БД:** Все данные коммитятся в репозиторий
- **Промпты на русском**, код и API-вызовы на английском
- **expert_face.json** (~875KB) — отслеживается в git
- **SDK:** Используется `google-genai` (новый SDK), НЕ `google.generativeai` (старый)
- **Streamlit Cloud:** Секреты бриджатся в `os.environ` через `_SECRET_KEYS` в `app.py`

---

## Репозиторий
`alexandermalevich85-commits/telegram-autoposter`

## Секреты GitHub Actions
- `CLAUDE_API_KEY`
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `REPLICATE_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`
- `GOOGLE_PROJECT_ID` (опционально, для Vertex AI)
- `GOOGLE_LOCATION` (опционально, для Vertex AI, default: us-central1)
- `GOOGLE_SERVICE_ACCOUNT_JSON` (опционально, для Vertex AI)
