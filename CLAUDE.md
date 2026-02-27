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
| `app.py` | Streamlit Web UI (1357 строк) |
| `config.py` | Загрузка env-переменных и API-ключей |
| `generate_text.py` | Генерация текста (Claude/Gemini/OpenAI) |
| `generate_image.py` | Генерация изображений (Gemini/OpenAI) |
| `face_swap.py` | Замена лица (Replicate/Gemini/OpenAI) |
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
| Провайдер | Модель | Статус |
|-----------|--------|--------|
| `openai` | dall-e-3 (1024x1024) | Работает |
| `gemini` | gemini-2.5-flash-image | Работает |

### Face Swap
| Провайдер | Модель | Статус |
|-----------|--------|--------|
| `replicate` | codeplugtech/face-swap:278a81e7... | Работает (платно ~$0.01) |
| `gemini` | gemini-2.5-flash-image | Работает (бесплатно) |
| `openai` | gpt-image-1 | НЕ РАБОТАЕТ (см. ниже) |

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

### 3. OpenAI face swap — gpt-image-1 не поддерживается
**Проблема:** Endpoint `/v1/images/edits` принимает только модель `dall-e-2`, а код отправляет `gpt-image-1`.
**Ошибка:** `Invalid value: 'gpt-image-1'. Value must be 'dall-e-2'`
**Статус:** НЕ ИСПРАВЛЕНО. Нужно либо использовать dall-e-2, либо переписать на другой подход.
**Рекомендация:** Использовать `replicate` или `gemini` для face swap.

### 4. Нерабочие модели Replicate (не использовать)
- `xiankgx/face-swap` — удалена
- `arabyai-replicate/roop_face_swap` — только видео, не изображения
- `cdingram/face-swap` (без hash) — 404
- `easel/advanced-face-swap` — 404
- `fofr/face-swap-with-ideogram` — 404

### 5. Рассинхрон provider.cfg между локальной копией и GitHub
**Проблема:** Streamlit UI обновляет файл через GitHub API, а локальная копия остаётся старой.
**Решение:** Всегда делать `git pull` перед работой, или проверять актуальный provider.cfg на GitHub.

---

## Текущая конфигурация (provider.cfg)
```
TEXT_PROVIDER=openai
IMAGE_PROVIDER=gemini
FACE_SWAP_PROVIDER=gemini
AUTOPUBLISH_ENABLED=true
```

---

## Важные технические детали

- **Telegram:** Caption ≤ 1024 символов → если длиннее, отправляется фото + отдельное сообщение
- **Base64 изображения:** Хранятся в JSON, JPEG quality=85
- **Face swap fallback:** Если ошибка — публикуется без замены лица (не падает)
- **GitHub как БД:** Все данные коммитятся в репозиторий
- **Промпты на русском**, код и API-вызовы на английском
- **expert_face.json** (~875KB) — отслеживается в git

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
