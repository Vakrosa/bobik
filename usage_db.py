"""Учёт расходов с разбивкой и постоянным хранением.
Если задан env USAGE_BUCKET — пишем в Google Cloud Storage (переживает обновления бота).
Иначе — локальный JSON в /tmp (обнуляется при перезапуске)."""
import json, time, os, threading

BUCKET = os.environ.get("USAGE_BUCKET", "").strip()
BLOB_NAME = os.environ.get("USAGE_BLOB", "bobik_usage.json")
LOCAL = os.environ.get("USAGE_LOCAL", "/tmp/bobik_usage.json")

_lock = threading.Lock()
_records = None
_gcs_blob = None

KIND_LABELS = {"chat": "Чат", "image": "Картинки", "video": "Видео", "team": "Команда"}


def _blob():
    global _gcs_blob
    if not BUCKET:
        return None
    if _gcs_blob is None:
        from google.cloud import storage
        _gcs_blob = storage.Client().bucket(BUCKET).blob(BLOB_NAME)
    return _gcs_blob


def _load():
    global _records
    if _records is not None:
        return _records
    data = []
    try:
        b = _blob()
        if b is not None:
            if b.exists():
                data = json.loads(b.download_as_text() or "[]")
        elif os.path.exists(LOCAL):
            data = json.load(open(LOCAL, encoding="utf-8"))
    except Exception:
        data = []
    _records = data if isinstance(data, list) else []
    return _records


def _save():
    try:
        b = _blob()
        payload = json.dumps(_records, ensure_ascii=False)
        if b is not None:
            b.upload_from_string(payload, content_type="application/json")
        else:
            json.dump(_records, open(LOCAL, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def _today():
    return time.strftime("%Y-%m-%d")


def log(user_id, kind, cost):
    with _lock:
        _load().append({"user_id": int(user_id), "kind": kind,
                        "cost": float(cost), "ts": int(time.time()), "day": _today()})
        _save()


def _sum(filt):
    return sum(r["cost"] for r in _load() if filt(r))


def spent_today(user_id):
    with _lock:
        d = _today()
        return _sum(lambda r: r["user_id"] == user_id and r["day"] == d)


def spent_total(user_id=None):
    with _lock:
        if user_id is None:
            return _sum(lambda r: True)
        return _sum(lambda r: r["user_id"] == user_id)


def can_spend(user_id, est_cost, daily_limit):
    return (spent_today(user_id) + est_cost) <= daily_limit


def _days_ago(n):
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))


def breakdown(user_id=None, period="total"):
    with _lock:
        recs = _load()
        if period == "today":
            d = _today(); pf = lambda r: r["day"] == d
        elif period == "week":
            since = _days_ago(6); pf = lambda r: r["day"] >= since
        else:
            pf = lambda r: True
        out = {}
        for r in recs:
            if user_id is not None and r["user_id"] != user_id:
                continue
            if not pf(r):
                continue
            out[r["kind"]] = out.get(r["kind"], 0.0) + r["cost"]
        return out


def by_user():
    with _lock:
        out = {}
        for r in _load():
            out[r["user_id"]] = out.get(r["user_id"], 0.0) + r["cost"]
        return out
