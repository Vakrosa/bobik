"""Бобик — Telegram-бот: Чат + Картинки + Видео + Команда агентов + Голос + Память + Зрение."""
import io, logging, asyncio
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)
import config, usage_db, gcp_media, agents, memory

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bobik")

STATE = {}

def st(uid):
    if uid not in STATE:
        STATE[uid] = {"mode": None, "await": None,
                      "chat_model": config.CHAT_MODELS[0][1],
                      "img": dict(config.DEFAULT_IMAGE),
                      "vid": dict(config.DEFAULT_VIDEO)}
    return STATE[uid]

def allowed(update):
    u = update.effective_user
    return bool(u and u.id in config.ALLOWED_USERS)

def _bg(coro_fn, *args):
    try:
        asyncio.get_event_loop().create_task(asyncio.to_thread(coro_fn, *args))
    except Exception:
        pass

TG_LIMIT = 4000
async def safe_send(update, text, **kwargs):
    """Шлёт текст, разбивая на куски <=4096 символов (лимит Telegram). Не роняет хэндлер."""
    text = text if (text and str(text).strip()) else "(пусто)"
    chunks = [text[i:i + TG_LIMIT] for i in range(0, len(text), TG_LIMIT)] or ["(пусто)"]
    last = len(chunks) - 1
    for idx, ch in enumerate(chunks):
        kw = dict(kwargs) if idx == last else {}
        kw.setdefault('disable_web_page_preview', True)
        try:
            await update.effective_message.reply_text(ch, **kw)
        except Exception:
            try:
                await update.effective_message.reply_text(ch[:TG_LIMIT])
            except Exception:
                pass

# ---------- МЕНЮ ----------
def main_menu():
    return M([[B("💬 Чат", callback_data="m:chat"), B("🖼 Картинка", callback_data="m:img")],
              [B("🎬 Видео", callback_data="m:vid"), B("💰 Баланс", callback_data="m:bal")],
              [B("👥 Команда (живой совет)", callback_data="m:team")]])

def chat_menu(s):
    rows = []
    for idx, (name, mid) in enumerate(config.CHAT_MODELS):
        mark = "✅ " if s["chat_model"] == mid else ""
        rows.append([B(f"{mark}{name}", callback_data=f"cm:{idx}")])
    rows.append([B("⬅️ Назад", callback_data="m:home")])
    return M(rows)

def img_menu(s):
    i = s["img"]
    return M([
        [B(f"📐 Формат: {i['aspect']}", callback_data="i:aspect"),
         B(f"🔢 Кол-во: {i['count']}", callback_data="i:count")],
        [B("📝 Создать по описанию", callback_data="i:gotext")],
        [B("📸 Из моего фото (редактировать)", callback_data="i:gophoto")],
        [B("⬅️ Назад", callback_data="m:home")],
    ])

def vid_menu(s):
    v = s["vid"]
    model = {"lite": "Veo 3.1 Lite", "std": "Veo 3.1", "fast": "Veo Fast"}.get(v["model"], "Veo 3.1")
    audio = "🔊 Вкл" if v["audio"] else "🔇 Выкл"
    return M([
        [B(f"🎞 {model}", callback_data="v:model"), B(f"⏱ {v['seconds']}с", callback_data="v:seconds")],
        [B(f"📐 {v['aspect']}", callback_data="v:aspect"), B(f"Звук: {audio}", callback_data="v:audio")],
        [B(f"🔢 Кол-во: {v['count']}", callback_data="v:count")],
        [B("📝 Видео по описанию", callback_data="v:gotext")],
        [B("📸 Видео из моего фото", callback_data="v:gophoto")],
        [B("⬅️ Назад", callback_data="m:home")],
    ])

CYCLE = {"i_aspect": ["1:1", "16:9", "9:16", "3:4", "4:3"], "i_count": [1, 2, 3, 4],
         "v_seconds": [4, 6, 8], "v_aspect": ["16:9", "9:16"], "v_count": [1, 2]}
def cyc(lst, cur): return lst[(lst.index(cur) + 1) % len(lst)] if cur in lst else lst[0]

# ---------- ХЭНДЛЕРЫ ----------
async def start(update, ctx):
    if not allowed(update):
        return await update.effective_message.reply_text("⛔ Доступ только для владельцев.")
    s = st(update.effective_user.id); s["mode"] = None; s["await"] = None
    await update.effective_message.reply_text(
        "👋 Привет! Я Бобик v20 — работаю через Google Cloud.\n"
        "Пишу/слушаю/вижу и помню наши прошлые разговоры.\n"
        "Можно текстом, 🎤 голосом или 📸 фото.\nВыбери, что делаем:",
        reply_markup=main_menu())

async def forget_cmd(update, ctx):
    if not allowed(update): return
    memory.forget(update.effective_user.id)
    await update.effective_message.reply_text("🧽 Память очищена. Начинаем с чистого листа.")

async def on_cb(update, ctx):
    if not allowed(update): return
    q = update.callback_query; await q.answer()
    uid = update.effective_user.id; s = st(uid); d = q.data

    if d.startswith("ph:"):
        photo = s.get("pending_photo"); cap = s.get("pending_caption", "")
        if not photo:
            return await q.edit_message_text("Фото потерялось — пришли заново.")
        act = d.split(":")[1]
        if act == "vid":
            s["await"] = None
            await q.edit_message_text("🎬 Делаю видео из фото…")
            return await run_video(update, ctx, uid, s, prompt=cap or "Оживи это фото, красиво", photo=photo)
        if act == "img":
            s["await"] = None
            await q.edit_message_text("🖼 Переделываю фото…")
            return await run_image(update, ctx, uid, s, prompt=cap or "Улучши и преобрази это фото", photo=photo)
        await q.edit_message_text("👀 Смотрю фото…")
        try:
            desc = await asyncio.to_thread(gcp_media.describe_image, photo,
                                           cap or "Опиши это изображение подробно: стиль, цвета, детали, настроение.")
        except Exception as e:
            return await update.effective_message.reply_text(f"Не смог разглядеть фото: {e}")
        if act == "team":
            return await run_team(update, ctx, uid, s, task=f"{cap}\n\n[Пользователь прислал фото. Что на нём: {desc}]")
        return await update.effective_message.reply_text(f"📸 На фото: {desc}")

    if d == "m:home":
        s["mode"] = None; s["await"] = None
        return await q.edit_message_text("Выбери, что делаем:", reply_markup=main_menu())
    if d == "m:chat":
        return await q.edit_message_text("💬 С кем общаемся? Выбери модель:", reply_markup=chat_menu(s))
    if d.startswith("cm:"):
        idx = int(d.split(":")[1]); s["chat_model"] = config.CHAT_MODELS[idx][1]
        s["mode"] = "chat"; s["await"] = "chat"
        name = config.CHAT_MODELS[idx][0]
        return await q.edit_message_text(f"💬 Чат с {name}. Я помню прошлые разговоры. Пиши, говори или шли фото.\n/start — выйти, /forget — забыть всё.")
    if d == "m:img":
        s["mode"] = "img"
        return await q.edit_message_text("🖼 Картинка. Настрой формат/кол-во и выбери способ:", reply_markup=img_menu(s))
    if d == "m:vid":
        s["mode"] = "vid"
        return await q.edit_message_text("🎬 Видео. Настрой параметры и выбери способ:", reply_markup=vid_menu(s))
    if d == "m:team":
        s["mode"] = "team"; s["await"] = "team"
        return await q.edit_message_text(
            "👥 Режим «Команда». Напиши/наговори задачу или пришли фото — команда обсудит, "
            "доведёт до готового результата и даст короткое резюме. Я помню контекст проекта.\n/start — выйти.")
    if d == "m:bal":
        return await q.edit_message_text(balance_text(uid), reply_markup=main_menu())

    if d == "i:aspect": s["img"]["aspect"] = cyc(CYCLE["i_aspect"], s["img"]["aspect"])
    elif d == "i:count": s["img"]["count"] = cyc(CYCLE["i_count"], s["img"]["count"])
    elif d == "i:gotext":
        s["await"] = "img_text"
        return await q.edit_message_text("📝 Пришли описание картинки (текстом или голосом).")
    elif d == "i:gophoto":
        s["await"] = "img_photo"
        return await q.edit_message_text("📸 Пришли СВОЁ фото. В подписи напиши, что с ним сделать. Без подписи — просто улучшу.")
    elif d == "v:model": s["vid"]["model"] = {"fast": "lite", "lite": "std", "std": "fast"}.get(s["vid"]["model"], "fast")
    elif d == "v:seconds": s["vid"]["seconds"] = cyc(CYCLE["v_seconds"], s["vid"]["seconds"])
    elif d == "v:aspect": s["vid"]["aspect"] = cyc(CYCLE["v_aspect"], s["vid"]["aspect"])
    elif d == "v:audio": s["vid"]["audio"] = not s["vid"]["audio"]
    elif d == "v:count": s["vid"]["count"] = cyc(CYCLE["v_count"], s["vid"]["count"])
    elif d == "v:gotext":
        s["await"] = "vid_text"
        return await q.edit_message_text("📝 Пришли описание видео (текстом или голосом).")
    elif d == "v:gophoto":
        s["await"] = "vid_photo"
        return await q.edit_message_text("📸 Пришли СВОЁ фото — сделаю из него видео. В подписи напиши, что должно происходить.")

    if d.startswith("i:"): return await q.edit_message_reply_markup(reply_markup=img_menu(s))
    if d.startswith("v:"): return await q.edit_message_reply_markup(reply_markup=vid_menu(s))

def _fmt_brk(brk):
    if not brk:
        return "—"
    parts = [f"{usage_db.KIND_LABELS.get(k,k)} ${v:.2f}" for k, v in sorted(brk.items(), key=lambda x: -x[1])]
    return " · ".join(parts)

def balance_text(uid):
    today = usage_db.spent_today(uid)
    limit = config.DAILY_LIMIT_USD
    left = max(0, limit - today)
    b_today = usage_db.breakdown(period="today")
    b_week = usage_db.breakdown(period="week")
    b_total = usage_db.breakdown(period="total")
    total = sum(b_total.values())
    lines = ["💰 КАЛЬКУЛЯТОР РАСХОДОВ (оценка)", ""]
    lines.append(f"📅 Сегодня (ты): ${today:.2f} из ${limit:.2f} · осталось ${left:.2f}")
    lines.append(f"   по всем: {_fmt_brk(b_today)}")
    lines.append(f"📆 За 7 дней: ${sum(b_week.values()):.2f}  ({_fmt_brk(b_week)})")
    lines.append(f"📊 Всего: ${total:.2f}  ({_fmt_brk(b_total)})")
    bu = usage_db.by_user()
    if bu:
        who = " · ".join(f"{config.USER_NAMES.get(u, u)} ${v:.2f}" for u, v in sorted(bu.items(), key=lambda x: -x[1]))
        lines.append(f"👤 По людям: {who}")
    if config.FREE_CREDITS_TOTAL > 0:
        lines.append(f"💳 Осталось из кредитов: ${max(0, config.FREE_CREDITS_TOTAL - total):.2f}")
    if total > 0:
        top = max(b_total, key=b_total.get)
        lines.append("")
        lines.append(f"💡 Больше всего уходит на «{usage_db.KIND_LABELS.get(top, top)}» — если дорого, снизь там кол-во/качество.")
    lines.append("\n⚠️ Это оценка бота. Точные траты — в Google Cloud → Billing.")
    return "\n".join(lines)

def est_img(s): return config.PRICE_IMAGE * s["img"]["count"]
def est_vid(s):
    v = s["vid"]
    rate = config.PRICE_VIDEO_SEC_FAST if v["model"] in ("fast", "lite") else (
        config.PRICE_VIDEO_SEC_AUDIO if v["audio"] else config.PRICE_VIDEO_SEC)
    return rate * v["seconds"] * v["count"]

# единая обработка текста (из печати, голоса или описания фото)
async def handle_text(update, ctx, uid, s, txt):
    a = s.get("await")
    if a == "chat":
        memory.add(uid, "user", txt)
        await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
        nts = memory.notes(uid)
        msgs = []
        if nts:
            msgs.append({"role": "user", "text": f"[ПАМЯТЬ — что ты помнишь о пользователе и его проектах, учитывай: {nts}]"})
        for h in memory.recent(uid, 12):
            msgs.append({"role": h["role"], "text": h["text"]})
        try:
            ans = await asyncio.to_thread(gcp_media.chat, msgs, s["chat_model"])
        except Exception as e:
            return await update.effective_message.reply_text(f"Ошибка чата: {e}")
        memory.add(uid, "model", ans)
        usage_db.log(uid, "chat", config.PRICE_CHAT)
        await safe_send(update, ans)
        _bg(memory.update_notes, uid, f"User: {txt}\nAssistant: {ans}")
        return
    if a == "team": return await run_team(update, ctx, uid, s, task=txt)
    if a == "img_text": return await run_image(update, ctx, uid, s, prompt=txt)
    if a == "vid_text": return await run_video(update, ctx, uid, s, prompt=txt)
    await update.effective_message.reply_text("Открой меню: /start")

async def on_text(update, ctx):
    if not allowed(update): return
    uid = update.effective_user.id; s = st(uid)
    await handle_text(update, ctx, uid, s, update.effective_message.text)

async def on_voice(update, ctx):
    if not allowed(update): return
    uid = update.effective_user.id; s = st(uid)
    v = update.effective_message.voice or update.effective_message.audio
    if v is None: return
    if (getattr(v, 'file_size', 0) or 0) > 19_000_000:
        return await update.effective_message.reply_text('🎤 Файл великоват (>20 МБ) — Telegram не даёт мне его скачать. Запиши короче или напиши текстом.')
    await ctx.bot.send_chat_action(update.effective_chat.id, "typing")
    f = await v.get_file()
    buf = io.BytesIO(); await f.download_to_memory(buf)
    mime = getattr(v, "mime_type", None) or "audio/ogg"
    try:
        txt = await asyncio.to_thread(gcp_media.transcribe, buf.getvalue(), mime)
    except Exception as e:
        return await update.effective_message.reply_text(f"Не разобрал голос: {e}")
    if not txt:
        return await update.effective_message.reply_text("🎤 Пустое голосовое — повтори?")
    await update.effective_message.reply_text(f"🎤 Услышал: {txt}")
    if s.get("await") is None:
        s["mode"] = "chat"; s["await"] = "chat"
    await handle_text(update, ctx, uid, s, txt)

async def run_team(update, ctx, uid, s, task):
    chat_id = update.effective_chat.id
    if s.get("busy"):
        return await update.effective_message.reply_text("⏳ Секунду — ещё дорабатываю прошлую задачу.")
    est = config.PRICE_CHAT * 8
    if not usage_db.can_spend(uid, est, config.DAILY_LIMIT_USD):
        return await update.effective_message.reply_text(f"⛔ Дневной лимит ${config.DAILY_LIMIT_USD:.2f} исчерпан.")
    s["busy"] = True
    try:
        nts = memory.notes(uid)
        task_full = task if not nts else f"{task}\n\n[Контекст-память о пользователе/проекте: {nts}]"
        await ctx.bot.send_chat_action(chat_id, "typing")
        try:
            keys = await asyncio.to_thread(agents.plan, task_full)
        except Exception as e:
            return await update.effective_message.reply_text(f"Ошибка команды: {e}")
        names = ", ".join(agents.ROLES[k][0] for k in keys)
        await safe_send(update, f"👥 Над задачей работают: {names}\nОбсуждают…")
        transcript = []
        for k in keys:
            try:
                await ctx.bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            try:
                text = await asyncio.to_thread(agents.speak, k, task_full, transcript)
            except Exception as e:
                text = f"(не смог ответить: {e})"
            transcript.append((agents.ROLES[k][0], text))
            await safe_send(update, f"{agents.ROLES[k][0]}:\n{text}")
        await ctx.bot.send_chat_action(chat_id, "typing")
        try:
            final = await asyncio.to_thread(agents.finalize, task_full, transcript)
        except Exception as e:
            final = f"(не смог свести итог: {e})"
        await safe_send(update, f"🧠 ИТОГ:\n{final}")
        try:
            short = await asyncio.to_thread(agents.brief, task, final)
            if short:
                await safe_send(update, f"📌 Если коротко: {short}", reply_markup=main_menu())
        except Exception:
            pass
        usage_db.log(uid, "team", est)
        _bg(memory.update_notes, uid, f"Задача команде: {task}\nИтог: {final}")
    finally:
        s["busy"] = False

async def on_photo(update, ctx):
    if not allowed(update): return
    uid = update.effective_user.id; s = st(uid); a = s.get("await")
    f = await update.effective_message.photo[-1].get_file()
    buf = io.BytesIO(); await f.download_to_memory(buf); photo = buf.getvalue()
    caption = update.effective_message.caption or ""
    # режим генерации из фото
    if a == "img_photo":
        prompt = caption or "Улучши и преобрази это фото"
        return await run_image(update, ctx, uid, s, prompt=prompt, photo=photo)
    if a == "vid_photo":
        prompt = caption or "Оживи это фото, сделай красивое видео"
        return await run_video(update, ctx, uid, s, prompt=prompt, photo=photo)
    # иначе — спросить кнопками, что сделать с фото (чтобы не путать режимы)
    s["pending_photo"] = photo
    s["pending_caption"] = caption
    kb = M([
        [B("🎬 Сделать видео из фото", callback_data="ph:vid")],
        [B("🖼 Переделать/улучшить картинку", callback_data="ph:img")],
        [B("👥 Обсудить командой", callback_data="ph:team"), B("💬 Описать/ответить", callback_data="ph:desc")],
    ])
    await update.effective_message.reply_text(
        "📸 Фото получил. Что с ним сделать?" + (f"\n(подпись: «{caption}»)" if caption else ""),
        reply_markup=kb)

async def run_image(update, ctx, uid, s, prompt, photo=None):
    est = est_img(s)
    if not usage_db.can_spend(uid, est, config.DAILY_LIMIT_USD):
        return await update.effective_message.reply_text(f"⛔ Дневной лимит ${config.DAILY_LIMIT_USD:.2f} исчерпан.")
    s["await"] = None
    await update.effective_message.reply_text("🖼 Генерирую…")
    await ctx.bot.send_chat_action(update.effective_chat.id, "upload_photo")
    try:
        imgs = await asyncio.to_thread(gcp_media.gen_image, prompt, s["img"]["aspect"], s["img"]["count"], photo)
    except Exception as e:
        return await update.effective_message.reply_text(f"Ошибка картинки: {e}")
    usage_db.log(uid, "image", est)
    for b in imgs: await update.effective_message.reply_photo(io.BytesIO(b))
    await update.effective_message.reply_text(f"Готово. ~${est:.2f}. Ещё?", reply_markup=img_menu(s))

async def run_video(update, ctx, uid, s, prompt, photo=None):
    est = est_vid(s)
    if not usage_db.can_spend(uid, est, config.DAILY_LIMIT_USD):
        return await update.effective_message.reply_text(f"⛔ Дневной лимит ${config.DAILY_LIMIT_USD:.2f} исчерпан.")
    s["await"] = None
    await update.effective_message.reply_text(f"🎬 Генерирую видео (~{s['vid']['seconds']}с, пару минут)…")
    await ctx.bot.send_chat_action(update.effective_chat.id, "upload_video")
    v = s["vid"]
    try:
        mid = {"lite": config.VIDEO_MODEL_LITE, "std": config.VIDEO_MODEL_STD, "fast": config.VIDEO_MODEL_FAST}.get(v["model"], config.VIDEO_MODEL_FAST)
        vids = await asyncio.to_thread(gcp_media.gen_video, prompt, mid,
                                       v["seconds"], v["aspect"], v["audio"], v["count"], photo)
    except Exception as e:
        return await update.effective_message.reply_text(f"Ошибка видео: {e}")
    usage_db.log(uid, "video", est)
    for b in vids: await update.effective_message.reply_video(io.BytesIO(b))
    await update.effective_message.reply_text(f"Готово. ~${est:.2f}. Ещё?", reply_markup=vid_menu(s))

async def on_document(update, ctx):
    if not allowed(update): return
    uid = update.effective_user.id; s = st(uid)
    doc = update.effective_message.document
    if doc is None: return
    name = doc.file_name or "файл"
    low = name.lower()
    size = getattr(doc, "file_size", 0) or 0
    caption = update.effective_message.caption or ""
    if size > 19_000_000:
        return await update.effective_message.reply_text(
            f"📎 «{name}» больше 20 МБ — Telegram не даёт мне его скачать. "
            "Пришли файл поменьше или опиши задачу текстом/голосом.")
    f = await doc.get_file()
    buf = io.BytesIO(); await f.download_to_memory(buf); data = buf.getvalue()
    if low.endswith((".txt", ".md", ".csv", ".json")):
        content = data.decode("utf-8", errors="replace")[:8000]
        text = caption or "Вот текст из файла — учти его в задаче."
        combined = f"{text}\n\n[Содержимое файла {name}]:\n{content}"
        if s.get("await") not in ("team", "chat"):
            s["mode"] = "chat"; s["await"] = "chat"
        return await handle_text(update, ctx, uid, s, combined)
    if low.endswith((".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac")):
        await update.effective_message.reply_text("🎧 Слушаю аудио…")
        try:
            txt = await asyncio.to_thread(gcp_media.transcribe, data, getattr(doc, "mime_type", None) or "audio/wav")
        except Exception as e:
            return await update.effective_message.reply_text(f"Не разобрал аудио: {e}")
        if not txt:
            return await update.effective_message.reply_text("Не смог распознать аудио. Опиши задачу текстом.")
        await update.effective_message.reply_text(f"🎧 Распознал из аудио: {txt[:500]}")
        if s.get("await") is None:
            s["mode"] = "chat"; s["await"] = "chat"
        return await handle_text(update, ctx, uid, s, (caption + "\n" + txt) if caption else txt)
    return await update.effective_message.reply_text(
        f"📎 Файл «{name}» пока не читаю. Пришли .txt, фото, голосовое — или опиши словами.")

def build_application():
    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("forget", forget_cmd))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app

if __name__ == "__main__":
    build_application().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
