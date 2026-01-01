import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import pytz
import telebot
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from apscheduler.schedulers.background import BackgroundScheduler


# ================== НАСТРОЙКИ ==================
# В Bothost токен лучше задавать переменной окружения BOT_TOKEN
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

DATA_FILE = "reminders.json"

# Таймзона бота
TZ_NAME = os.environ.get("BOT_TZ", "Europe/Moscow")
TZ = pytz.timezone(TZ_NAME)

# Сколько дней вперед показывать кнопками для выбора даты
DATE_PICK_DAYS = int(os.environ.get("DATE_PICK_DAYS", "21"))

# Автоудаление напоминаний через 24 часа ПОСЛЕ события
AUTO_DELETE_AFTER_HOURS = int(os.environ.get("AUTO_DELETE_AFTER_HOURS", "24"))

# Частота автоочистки (в минутах)
CLEANUP_INTERVAL_MINUTES = int(os.environ.get("CLEANUP_INTERVAL_MINUTES", "1"))


# ================== ПРОВЕРКИ ==================
if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN. Добавь переменную окружения BOT_TOKEN в панели хостинга (Bothost)."
    )

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
scheduler = BackgroundScheduler(timezone=TZ)
scheduler.start()

# states[user_id] = {"step": "...", "chat_id": int, "title": str, "date": "YYYY-MM-DD"}
states: Dict[int, Dict[str, Any]] = {}


# ================== ХРАНЕНИЕ ==================
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"reminders": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {"reminders": []}
    if "reminders" not in data or not isinstance(data["reminders"], list):
        data["reminders"] = []
    return data


def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_tz() -> datetime:
    return datetime.now(TZ)


def dt_from_iso(iso_str: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = TZ.localize(dt)
        else:
            dt = dt.astimezone(TZ)
        return dt
    except Exception:
        return None


def dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = TZ.localize(dt)
    else:
        dt = dt.astimezone(TZ)
    return dt.isoformat()


def add_reminder_to_store(rem: Dict[str, Any]) -> None:
    data = load_data()
    data["reminders"].append(rem)
    save_data(data)


def get_chat_reminders(chat_id: int) -> List[Dict[str, Any]]:
    data = load_data()
    items = [r for r in data.get("reminders", []) if int(r.get("chat_id", 0)) == int(chat_id)]

    # Нормализуем event_dt в TZ (на случай смешанных поясов)
    changed = False
    for r in items:
        dt = dt_from_iso(r.get("event_dt", ""))
        if dt:
            new_iso = dt_to_iso(dt)
            if r.get("event_dt") != new_iso:
                r["event_dt"] = new_iso
                changed = True

    items.sort(key=lambda r: r.get("event_dt", ""))

    if changed:
        all_data = load_data()
        by_id = {r.get("id"): r for r in items if r.get("id")}
        for i, r in enumerate(all_data.get("reminders", [])):
            rid = r.get("id")
            if rid in by_id:
                all_data["reminders"][i] = by_id[rid]
        save_data(all_data)

    return items


# ================== МЕНЮ ==================
def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("➕ Добавить напоминание"))
    kb.row(KeyboardButton("📋 Все напоминания"))
    return kb


# ================== INLINE КЛАВИАТУРЫ ==================
def build_date_picker() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    today = now_tz().date()

    buttons = []
    for i in range(DATE_PICK_DAYS):
        d = today + timedelta(days=i)
        dow = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        text = d.strftime("%d.%m") + f" ({dow})"
        buttons.append(InlineKeyboardButton(text, callback_data=f"date|{d.isoformat()}"))

    for i in range(0, len(buttons), 2):
        kb.row(*buttons[i:i + 2])

    kb.row(InlineKeyboardButton("✍️ Ввести дату вручную", callback_data="date_manual"))
    kb.row(InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    return kb


def build_time_picker() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    common = ["09:00", "12:00", "15:00", "18:00", "21:00"]
    for i in range(0, len(common), 2):
        row = []
        for t in common[i:i + 2]:
            row.append(InlineKeyboardButton(t, callback_data=f"time|{t}"))
        kb.row(*row)

    kb.row(InlineKeyboardButton("✍️ Ввести время вручную", callback_data="time_manual"))
    kb.row(InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    return kb


def validate_time_hhmm(s: str) -> bool:
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except ValueError:
        return False


def format_event_dt(iso_str: str) -> str:
    dt = dt_from_iso(iso_str)
    if not dt:
        return "неизвестная дата"
    return dt.strftime("%d.%m.%Y %H:%M")


# ================== ПЛАНИРОВЩИК НАПОМИНАНИЙ ==================
def schedule_reminder_jobs(reminder: Dict[str, Any]) -> None:
    rem_id = reminder["id"]
    chat_id = int(reminder["chat_id"])
    title = reminder["title"]

    event_dt = dt_from_iso(reminder["event_dt"])
    if not event_dt:
        return

    for kind, delta, label in [
        ("24h", timedelta(hours=24), "за 24 часа"),
        ("1h", timedelta(hours=1), "за 1 час"),
    ]:
        run_at = event_dt - delta
        job_id = f"{rem_id}_{kind}"

        if run_at <= now_tz():
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
            continue

        def _send(chat_id=chat_id, title=title, event_dt=event_dt, label=label):
            bot.send_message(
                chat_id,
                f"⏰ Напоминание ({label})\n"
                f"<b>{title}</b>\n"
                f"📅 Событие: <b>{event_dt.strftime('%d.%m.%Y %H:%M')}</b>"
            )

        scheduler.add_job(
            _send,
            trigger="date",
            run_date=run_at,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=60 * 10
        )


def reschedule_all_from_store() -> None:
    data = load_data()
    for r in data.get("reminders", []):
        dt = dt_from_iso(r.get("event_dt", ""))
        if dt:
            r["event_dt"] = dt_to_iso(dt)
        schedule_reminder_jobs(r)
    save_data(data)


# ================== АВТООЧИСТКА ==================
def cleanup_expired() -> None:
    data = load_data()
    reminders = data.get("reminders", [])
    if not reminders:
        return

    cutoff = now_tz() - timedelta(hours=AUTO_DELETE_AFTER_HOURS)
    keep: List[Dict[str, Any]] = []
    removed_ids: List[str] = []

    for r in reminders:
        dt = dt_from_iso(r.get("event_dt", ""))
        if not dt:
            removed_ids.append(r.get("id", ""))
            continue

        if dt < cutoff:
            removed_ids.append(r.get("id", ""))
        else:
            r["event_dt"] = dt_to_iso(dt)
            keep.append(r)

    if removed_ids:
        for rid in removed_ids:
            if not rid:
                continue
            for kind in ("24h", "1h"):
                try:
                    scheduler.remove_job(f"{rid}_{kind}")
                except Exception:
                    pass

        data["reminders"] = keep
        save_data(data)


# Стартуем планировщик по сохраненным данным
reschedule_all_from_store()

# Запускаем автоочистку
scheduler.add_job(
    cleanup_expired,
    trigger="interval",
    minutes=CLEANUP_INTERVAL_MINUTES,
    id="cleanup_expired",
    replace_existing=True
)


# ================== ХЭНДЛЕРЫ ==================
@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.send_message(
        message.chat.id,
        "Привет! Я бот-напоминалка.\n"
        "Добавляй напоминания и я напомню за 24 часа и за 1 час до события 👇",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(commands=["add"])
def add_cmd(message):
    add_reminder_begin(message)


@bot.message_handler(commands=["list"])
def list_cmd(message):
    list_reminders(message)


@bot.message_handler(func=lambda m: m.text == "➕ Добавить напоминание")
def add_reminder_begin(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    states[user_id] = {"step": "title", "chat_id": chat_id}
    bot.send_message(chat_id, "Ок! Введи <b>название</b> напоминания:", reply_markup=main_menu_kb())


@bot.message_handler(func=lambda m: m.text == "📋 Все напоминания")
def list_reminders(message):
    chat_id = message.chat.id
    items = get_chat_reminders(chat_id)

    if not items:
        bot.send_message(chat_id, "Пока нет напоминаний в этом чате.", reply_markup=main_menu_kb())
        return

    lines = ["📋 <b>Напоминания в этом чате</b>:"]
    for i, r in enumerate(items, 1):
        lines.append(f"{i}. <b>{r['title']}</b> — {format_event_dt(r['event_dt'])}")
    lines.append(f"\n🧹 Напоминания автоматически удаляются через {AUTO_DELETE_AFTER_HOURS} часа после события.")
    bot.send_message(chat_id, "\n".join(lines), reply_markup=main_menu_kb())


@bot.message_handler(func=lambda m: True, content_types=["text"])
def text_router(message):
    user_id = message.from_user.id
    st = states.get(user_id)

    if not st:
        return

    step = st.get("step")
    chat_id = st.get("chat_id")

    if int(chat_id) != int(message.chat.id):
        return

    if step == "title":
        title = message.text.strip()
        if not title:
            bot.send_message(chat_id, "Название не может быть пустым. Введи ещё раз:")
            return

        st["title"] = title
        st["step"] = "date_pick"
        bot.send_message(chat_id, "Выбери <b>дату</b>:", reply_markup=build_date_picker())

    elif step == "date_manual":
        raw = message.text.strip()
        date_iso = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(raw, fmt).date()
                date_iso = d.isoformat()
                break
            except ValueError:
                pass

        if not date_iso:
            bot.send_message(chat_id, "Не понял дату. Пример: <b>31.12.2025</b> или <b>2025-12-31</b>")
            return

        st["date"] = date_iso
        st["step"] = "time_pick"
        bot.send_message(chat_id, "Теперь выбери <b>время</b>:", reply_markup=build_time_picker())

    elif step == "time_manual":
        raw = message.text.strip()
        if not validate_time_hhmm(raw):
            bot.send_message(chat_id, "Не понял время. Пример: <b>18:30</b> (формат HH:MM)")
            return

        finalize_reminder(user_id, chat_id, raw)


def finalize_reminder(user_id: int, chat_id: int, time_hhmm: str) -> None:
    st = states.get(user_id)
    if not st:
        return

    title = st["title"]
    date_iso = st["date"]

    event_dt_naive = datetime.strptime(f"{date_iso} {time_hhmm}", "%Y-%m-%d %H:%M")
    event_dt = TZ.localize(event_dt_naive)

    if event_dt <= now_tz():
        bot.send_message(chat_id, "Это время уже в прошлом. Давай выберем дату/время заново.")
        st["step"] = "date_pick"
        bot.send_message(chat_id, "Выбери <b>дату</b>:", reply_markup=build_date_picker())
        return

    rem = {
        "id": uuid.uuid4().hex,
        "chat_id": int(chat_id),
        "creator_id": int(user_id),
        "title": title,
        "event_dt": dt_to_iso(event_dt),
        "created_at": dt_to_iso(now_tz()),
    }

    add_reminder_to_store(rem)
    schedule_reminder_jobs(rem)

    bot.send_message(
        chat_id,
        "✅ Напоминание добавлено!\n"
        f"<b>{title}</b>\n"
        f"📅 {event_dt.strftime('%d.%m.%Y %H:%M')}\n"
        "Я напомню <b>за 24 часа</b> и <b>за 1 час</b> до события.\n"
        f"🧹 Автоудаление: через <b>{AUTO_DELETE_AFTER_HOURS} часа</b> после события.",
        reply_markup=main_menu_kb()
    )

    states.pop(user_id, None)


@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    st = states.get(user_id)

    data = call.data

    if data == "cancel":
        states.pop(user_id, None)
        bot.answer_callback_query(call.id, "Отменено")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(chat_id, "Ок, отменил. Возвращаю меню 👇", reply_markup=main_menu_kb())
        return

    if not st or int(st.get("chat_id")) != int(chat_id):
        bot.answer_callback_query(call.id)
        return

    if data.startswith("date|"):
        date_iso = data.split("|", 1)[1]
        st["date"] = date_iso
        st["step"] = "time_pick"
        bot.answer_callback_query(call.id, "Дата выбрана")
        bot.edit_message_text(
            "Дата выбрана ✅\nТеперь выбери <b>время</b>:",
            chat_id,
            call.message.message_id,
            reply_markup=build_time_picker()
        )

    elif data == "date_manual":
        st["step"] = "date_manual"
        bot.answer_callback_query(call.id, "Ок")
        bot.edit_message_text(
            "Введи дату вручную: <b>31.12.2025</b> или <b>2025-12-31</b>",
            chat_id,
            call.message.message_id
        )

    elif data.startswith("time|"):
        time_hhmm = data.split("|", 1)[1]
        bot.answer_callback_query(call.id, "Время выбрано")
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        finalize_reminder(user_id, chat_id, time_hhmm)

    elif data == "time_manual":
        st["step"] = "time_manual"
        bot.answer_callback_query(call.id, "Ок")
        bot.edit_message_text(
            "Введи время вручную в формате <b>HH:MM</b> (например, <b>18:30</b>):",
            chat_id,
            call.message.message_id
        )

    else:
        bot.answer_callback_query(call.id)


if __name__ == "__main__":
    print(f"🤖 Bot is running. TZ={TZ_NAME}")
    bot.infinity_polling(skip_pending=True)
