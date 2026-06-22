"""Конфиг бота Бобик 2.0 — чат + картинки + видео через Google Cloud (Vertex AI)."""
import os

ALLOWED_USERS = {443612929}  # только Vak
USER_NAMES = {443612929: "Vak"}

GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

# Актуальные модели (старые Imagen 4 / Veo 3 Google закрывает в июне-августе 2026)
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gemini-2.5-flash-image")
VIDEO_MODEL_STD = os.environ.get("VIDEO_MODEL_STD", "veo-3.1-generate-preview")
VIDEO_MODEL_FAST = os.environ.get("VIDEO_MODEL_FAST", "veo-3.1-fast-generate-preview")

# Примерные цены ($) для оценки расходов
PRICE_IMAGE = float(os.environ.get("PRICE_IMAGE", "0.04"))
PRICE_VIDEO_SEC = float(os.environ.get("PRICE_VIDEO_SEC", "0.40"))
PRICE_VIDEO_SEC_AUDIO = float(os.environ.get("PRICE_VIDEO_SEC_AUDIO", "0.60"))
PRICE_VIDEO_SEC_FAST = float(os.environ.get("PRICE_VIDEO_SEC_FAST", "0.10"))

PRICE_CHAT = float(os.environ.get("PRICE_CHAT", "0.001"))
DAILY_LIMIT_USD = float(os.environ.get("DAILY_LIMIT_USD", "5.0"))
FREE_CREDITS_TOTAL = float(os.environ.get("FREE_CREDITS_TOTAL", "0"))

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

DEFAULT_IMAGE = {"aspect": "1:1", "count": 1, "source": "text"}
DEFAULT_VIDEO = {"model": "fast", "seconds": 6, "aspect": "16:9",
                 "audio": False, "count": 1, "source": "text"}

# Модели для чата (пользователь выбирает кнопкой)
# Формат Vertex OpenAI-endpoint: <publisher>/<model>
CHAT_MODELS = [
    ("⚡ Gemini Flash", "google/gemini-2.5-flash"),
    ("🧠 Gemini Pro", "google/gemini-2.5-pro"),
    ("⚫ Grok 4.3", "xai/grok-4.3"),
    ("⚫ Grok 4.1 Fast", "xai/grok-4.1-fast-reasoning"),
]
