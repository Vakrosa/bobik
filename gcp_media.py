"""Генерация через Google Cloud Vertex AI: чат (Gemini), картинки и видео (Veo)."""
import time
from google import genai
from google.genai import types
import google.auth, google.auth.transport.requests
from openai import OpenAI
import config

_client = None
def client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=config.GCP_PROJECT,
                               location=config.GCP_LOCATION)
    return _client

# ---------- ЧАТ (через OpenAI-совместимый endpoint Vertex: Gemini+Claude+Grok) ----------
def _oa_client(location):
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    base = f"https://{host}/v1/projects/{config.GCP_PROJECT}/locations/{location}/endpoints/openapi"
    return OpenAI(base_url=base, api_key=creds.token)

def chat(history, model=None):
    model = model or config.CHAT_MODEL
    msgs = [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]} for m in history[-12:]]
    if model.startswith("claude"):
        from anthropic import AnthropicVertex
        cli = AnthropicVertex(region="global", project_id=config.GCP_PROJECT)
        resp = cli.messages.create(max_tokens=2048, model=model, messages=msgs)
        return "".join(getattr(b, "text", "") for b in resp.content).strip() or "(пустой ответ)"
    loc = config.GCP_LOCATION if model.startswith("google/") else "global"
    resp = _oa_client(loc).chat.completions.create(model=model, messages=msgs)
    return (resp.choices[0].message.content or "").strip() or "(пустой ответ)"

# ---------- КАРТИНКИ ----------
def gen_image(prompt, aspect="1:1", count=1, photo_bytes=None):
    out = []
    full_prompt = f"{prompt}\n\n(aspect ratio {aspect})"
    for _ in range(max(1, int(count))):
        parts = []
        if photo_bytes:
            parts.append(types.Part.from_bytes(data=photo_bytes, mime_type="image/jpeg"))
        parts.append(types.Part.from_text(text=full_prompt))
        resp = client().models.generate_content(
            model=config.IMAGE_MODEL,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for cand in (resp.candidates or []):
            for p in (cand.content.parts or []):
                if getattr(p, "inline_data", None) and p.inline_data.data:
                    out.append(p.inline_data.data)
    if not out:
        raise RuntimeError("Модель не вернула изображение")
    return out

# ---------- ВИДЕО ----------
def gen_video(prompt, fast=True, seconds=6, aspect="16:9", audio=False,
              count=1, photo_bytes=None, poll_timeout=600):
    model = config.VIDEO_MODEL_FAST if fast else config.VIDEO_MODEL_STD
    cfg = types.GenerateVideosConfig(
        number_of_videos=max(1, int(count)),
        duration_seconds=int(seconds),
        aspect_ratio=aspect,
        generate_audio=bool(audio),
    )
    kwargs = {"model": model, "prompt": prompt, "config": cfg}
    if photo_bytes:
        kwargs["image"] = types.Image(image_bytes=photo_bytes, mime_type="image/jpeg")
    op = client().models.generate_videos(**kwargs)
    t0 = time.time()
    while not op.done:
        if time.time() - t0 > poll_timeout:
            raise TimeoutError("Видео генерируется слишком долго")
        time.sleep(8)
        op = client().operations.get(op)
    if getattr(op, "error", None):
        raise RuntimeError(str(op.error))
    out = []
    resp = op.response or op.result
    for gv in (getattr(resp, "generated_videos", None) or []):
        vid = gv.video
        data = getattr(vid, "video_bytes", None)
        if data:
            out.append(data)
    if not out:
        raise RuntimeError("Модель не вернула видео")
    return out


# ---------- ГОЛОС → ТЕКСТ ----------
def transcribe(audio_bytes, mime_type="audio/ogg"):
    parts = [
        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
        types.Part.from_text(text="Расшифруй это голосовое сообщение в текст. "
                                  "Верни ТОЛЬКО распознанный текст, без пояснений и кавычек."),
    ]
    resp = client().models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=parts)],
    )
    return (getattr(resp, "text", "") or "").strip()


# ---------- ЗРЕНИЕ: анализ изображения ----------
def describe_image(image_bytes, question="Опиши это изображение подробно.", mime_type="image/jpeg"):
    parts = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        types.Part.from_text(text=question),
    ]
    resp = client().models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=parts)],
    )
    return (getattr(resp, "text", "") or "").strip()
