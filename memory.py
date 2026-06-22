"""Постоянная память бота: история диалога + ключевые заметки по каждому пользователю.
Хранится в GCS-бакете (USAGE_BUCKET). Переживает перезапуски и обновления бота."""
import json, os, time, threading
import gcp_media

BUCKET = os.environ.get("USAGE_BUCKET", "").strip()
MAX_HISTORY = 40
_lock = threading.Lock()
_cache = {}
_gcs = None


def _client():
    global _gcs
    if _gcs is None:
        from google.cloud import storage
        _gcs = storage.Client()
    return _gcs


def _blob(uid):
    if not BUCKET:
        return None
    return _client().bucket(BUCKET).blob(f"memory/{uid}.json")


def load(uid):
    if uid in _cache:
        return _cache[uid]
    data = {"notes": "", "history": []}
    try:
        b = _blob(uid)
        if b is not None:
            if b.exists():
                data = json.loads(b.download_as_text() or "{}")
        else:
            p = f"/tmp/mem_{uid}.json"
            if os.path.exists(p):
                data = json.load(open(p, encoding="utf-8"))
    except Exception:
        data = {"notes": "", "history": []}
    _cache[uid] = {"notes": data.get("notes", ""), "history": data.get("history", [])}
    return _cache[uid]


def _save(uid):
    try:
        payload = json.dumps(_cache[uid], ensure_ascii=False)
        b = _blob(uid)
        if b is not None:
            b.upload_from_string(payload, content_type="application/json")
        else:
            json.dump(_cache[uid], open(f"/tmp/mem_{uid}.json", "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def add(uid, role, text):
    with _lock:
        m = load(uid)
        m["history"].append({"role": role, "text": text, "ts": int(time.time())})
        m["history"] = m["history"][-MAX_HISTORY:]
        _save(uid)


def notes(uid):
    return load(uid).get("notes", "")


def recent(uid, n=12):
    return load(uid)["history"][-n:]


def update_notes(uid, exchange):
    """Обновляет компактные заметки (running summary) о пользователе/проекте через Flash."""
    try:
        with _lock:
            old = load(uid).get("notes", "")
        instr = ("Ты ведёшь краткую память о пользователе и его проектах. "
                 "Обнови заметки: добавь новые важные факты, цели, решения, предпочтения, стиль. "
                 "Держи компактно (до 15 строк), убирай устаревшее. Верни ТОЛЬКО сами заметки.")
        user = f"ТЕКУЩИЕ ЗАМЕТКИ:\n{old or '(пусто)'}\n\nНОВЫЙ ОБМЕН:\n{exchange}\n\nОбновлённые заметки:"
        updated = gcp_media.chat([{"role": "user", "text": f"{instr}\n\n{user}"}], "google/gemini-2.5-flash")
        if updated and updated.strip():
            with _lock:
                load(uid)["notes"] = updated.strip()[:4000]
                _save(uid)
    except Exception:
        pass


def forget(uid):
    with _lock:
        _cache[uid] = {"notes": "", "history": []}
        _save(uid)
