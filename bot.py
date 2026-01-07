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


# ================== ВЕРСИЯ (для проверки деплоя) ==================
BOT_VERSION = "full-reminders+inline-useful-2026-01-07-01"


# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATA_FILE = "reminders.json"

TZ_NAME = os.environ.get("BOT_TZ", "Europe/Moscow")
TZ = pytz.timezone(TZ_NAME)

DATE_PICK_DAYS = int(os.environ.get("DATE_PICK_DAYS", "21"))

AUTO_DELETE_AFTER_HOURS = int(os.environ.get("AUTO_DELETE_AFTER_HOURS", "24"))
CLEANUP_INTERVAL_MINUTES = int(os.environ.get("CLEANUP_INTERVAL_MINUTES", "1"))

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Добавь переменную окружения BOT_TOKEN в панели хостинга (Bothost).")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
scheduler = BackgroundScheduler(timezone=TZ)
scheduler.start()

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

    # нормализуем tz/iso
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


# ================== МЕНЮ (Reply) ==================
def kb_main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📌 Напоминания"))
    kb.row(KeyboardButton("📚 Полезная информация"))
    kb.row(KeyboardButton("ℹ️ О боте"))
    return kb


def kb_reminders_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("➕ Добавить напоминание"))
    kb.row(KeyboardButton("📋 Все напоминания"))
    kb.row(KeyboardButton("⬅️ Назад"))
    return kb


# ================== INLINE МЕНЮ: ПОЛЕЗНАЯ ИНФОРМАЦИЯ ==================
USEFUL_LINKS = {
    "rm_schedule": "https://docs.google.com/spreadsheets/d/1ZXCllmYkqmP6y9HRnYm0_2D2f63haeU-vI2gylnL6Pg/edit?usp=drive_link",
    "vacations": "https://docs.google.com/spreadsheets/d/12SEymi_QNwSJ8agRBzXc1UZCfNhabtiLX07KxEsmpzQ/edit?usp=drive_link",
    "ato": "https://docs.google.com/spreadsheets/d/1IiKxS9Tf6oHUJJDhfozvWdbhC9wOZPzapflYv612Du0/edit",
    "dynamics": "https://docs.google.com/spreadsheets/d/1HhgNo3mfd8LrdfBPU2sjVatA-fboBf75387Ryd-qVUg/edit?gid=2086138160#gid=2086138160",
    "roster": "https://docs.google.com/spreadsheets/d/1vwPI_SPnjX5wPI6tu4jAFXSWFubjBQEO56kuCMysL_4/edit?usp=drive_link",
    "contacts": "https://docs.google.com/spreadsheets/d/1P5GbNMQD0A3OWh6GxLAYJDlgC92H95uo/edit?gid=2031453167#gid=2031453167",
    "protocol_rm": "https://docs.google.com/spreadsheets/d/1dBZzfanIbtjgp2sFDzU441Wv6ghT-bryQ19wc034Ye4/edit",
    "protocol_directors": "https://docs.google.com/spreadsheets/d/1cEMp3_84LuXrffAgqAOQq9kG8k-Ks8ev5k3Xo3QR-qo/edit",
}

GROUPS_TEXT = """Группы

Витрины
https://t.me/+9hdkceSRFdU4MmZi

Кофе-бар
https://t.me/+rAM0-VID0Gg0NmUy

Персонал
https://t.me/+ZcNnavnmJQlkZDAy


Цели
https://t.me/+SkzL_Xit6ypkMmZi

Айти вопросы
https://t.me/+oMzRrI1DzGlkNDVi

Логистика
https://t.me/+CsD1pmYTTnQ5NDdi

Технические вопросы 
https://t.me/+0dm4nBMj3LVlMGYy

Качество ЛБК 
https://t.me/+9WmWOSrjBxs1N2Uy

Заказы РЦ и ФК 

Нет ссылки 

Выход на стажировку 
https://t.me/+fa-ESZUYflA0ZThi

Обратная связь ЕДА
https://t.me/+3mipmXTpud5kZWVi


5 pillars
https://t.me/+f_YYEYz1rfc4NjAy

Курьеры кадры
https://t.me/+E7w0LSi4ltBlZjJi

Поиск продукции
https://t.me/+Yw-opolA0tc5ZTY6

Корп академия
https://t.me/+uhlNZjfkeZE0NGYy

Обучение БК 
https://t.me/+GU5oGnyjdgc5OTMy


Важная информация
https://t.me/+QB6nQlAno9xhZTQy


Пожарная безопасность
https://t.me/+l2rMTNe2I_VkMjNi
"""


def kb_useful_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()

    # "Сроки хранения" — callback (позже сделаем поиск по базе)
    kb.row(InlineKeyboardButton("🧊 Сроки хранения", callback_data="ui_storage"))

    # ссылки — url, открываются сразу
    kb.row(InlineKeyboardButton("🗓 Расписание РМ", url=USEFUL_LINKS["rm_schedule"]))
    kb.row(InlineKeyboardButton("🌴 График отпусков", url=USEFUL_LINKS["vacations"]))
    kb.row(InlineKeyboardButton("📊 АТО", url=USEFUL_LINKS["ato"]))
    kb.row(InlineKeyboardButton("🔗 Ссылки на группы", callback_data="ui_groups"))
    kb.row(InlineKeyboardButton("📈 Динамика", url=USEFUL_LINKS["dynamics"]))
    kb.row(InlineKeyboardButton("🧾 Ростер", url=USEFUL_LINKS["roster"]))
    kb.row(InlineKeyboardButton("☎️ Контакт-лист", url=USEFUL_LINKS["contacts"]))

    kb.row(InlineKeyboardButton("📝 Протокол собрания", callback_data="ui_protocol"))
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="ui_back_main"))
    return kb


def kb_protocol_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("👔 РМ", url=USEFUL_LINKS["protocol_rm"]))
    kb.row(InlineKeyboardButton("🧑‍💼 Директора", url=USEFUL_LINKS["protocol_directors"]))
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="ui_back_info"))
    return kb


# ================== INLINE КЛАВИАТУРЫ (напоминания) ==================
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


reschedule_all_from_store()

scheduler.add_job(
    cleanup_expired,
    trigger="interval",
    minutes=CLEANUP_INTERVAL_MINUTES,
    id="cleanup_expired",
    replace_existing=True
)


# ================== НАВИГАЦИЯ /start ==================
@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.send_message(
        message.chat.id,
        "Привет! Выбери раздел 👇\n"
        f"<i>Версия: {BOT_VERSION}</i>",
        reply_markup=kb_main_menu()
    )


@bot.message_handler(commands=["version"])
def version_cmd(message):
    bot.send_message(message.chat.id, f"Версия бота: <b>{BOT_VERSION}</b>")


# ================== РАЗДЕЛЫ МЕНЮ ==================
@bot.message_handler(func=lambda m: m.text == "📌 Напоминания")
def open_reminders_section(message):
    bot.send_message(message.chat.id, "📌 Напоминания:", reply_markup=kb_reminders_menu())


@bot.message_handler(func=lambda m: m.text == "📚 Полезная информация")
def open_info_section(message):
    # Reply-меню не меняем: пользователь остаётся в основном меню,
    # а нужный UX даёт inline-меню под сообщением.
    bot.send_message(
        message.chat.id,
        "📚 <b>Полезная информация</b>\nВыбери пункт 👇",
        reply_markup=kb_main_menu()
    )
    bot.send_message(
        message.chat.id,
        "Меню:",
        reply_markup=kb_useful_inline(),
        disable_web_page_preview=True
    )


@bot.message_handler(func=lambda m: m.text == "ℹ️ О боте")
def about_bot(message):
    bot.send_message(
        message.chat.id,
        "ℹ️ <b>О боте</b>\n\n"
        "• Раздел «Напоминания» — добавление и список\n"
        "• Раздел «Полезная информация» — документы/ссылки/материалы\n\n"
        f"🕒 Таймзона: <b>{TZ_NAME}</b>\n"
        f"🧹 Автоудаление напоминаний: <b>{AUTO_DELETE_AFTER_HOURS} ч</b> после события\n"
        f"🔖 Версия: <b>{BOT_VERSION}</b>",
        reply_markup=kb_main_menu()
    )


@bot.message_handler(func=lambda m: m.text == "⬅️ Назад")
def go_back(message):
    bot.send_message(message.chat.id, "Главное меню 👇", reply_markup=kb_main_menu())


# ================== НАПОМИНАНИЯ: кнопки и команды ==================
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
    bot.send_message(chat_id, "Ок! Введи <b>название</b> напоминания:", reply_markup=kb_reminders_menu())


@bot.message_handler(func=lambda m: m.text == "📋 Все напоминания")
def list_reminders(message):
    chat_id = message.chat.id
    items = get_chat_reminders(chat_id)

    if not items:
        bot.send_message(chat_id, "Пока нет напоминаний в этом чате.", reply_markup=kb_reminders_menu())
        return

    lines = ["📋 <b>Напоминания в этом чате</b>:"]
    for i, r in enumerate(items, 1):
        lines.append(f"{i}. <b>{r['title']}</b> — {format_event_dt(r['event_dt'])}")
    lines.append(f"\n🧹 Автоудаление: через {AUTO_DELETE_AFTER_HOURS} часа после события.")
    bot.send_message(chat_id, "\n".join(lines), reply_markup=kb_reminders_menu())


# ================== СЦЕНАРИЙ ДОБАВЛЕНИЯ: текстовые шаги ==================
# ВАЖНО: не ловим весь текст подряд, иначе ломаются другие разделы
@bot.message_handler(func=lambda m: states.get(m.from_user.id) is not None, content_types=["text"])
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
            bot.send_message(chat_id, "Название не может быть пустым. Введи ещё раз:", reply_markup=kb_reminders_menu())
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
        f"🧹 Автоудаление: через <b>{AUTO_DELETE_AFTER_HOURS} часа</b> после события.\n"
        f"<i>Версия: {BOT_VERSION}</i>",
        reply_markup=kb_reminders_menu()
    )

    states.pop(user_id, None)


# ================== INLINE CALLBACKS (напоминания) ==================
# Важно: не ловим всё подряд, чтобы не мешать ui_*
@bot.callback_query_handler(
    func=lambda call: (
        call.data in {"cancel", "date_manual", "time_manual"} or
        call.data.startswith("date|") or
        call.data.startswith("time|")
    )
)
def callbacks_reminders(call):
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
        bot.send_message(chat_id, "Ок, отменил. Возвращаю меню 👇", reply_markup=kb_reminders_menu())
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


# ================== INLINE CALLBACKS (полезная информация) ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("ui_"))
def callbacks_useful(call):
    chat_id = call.message.chat.id
    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data == "ui_storage":
        bot.send_message(
            chat_id,
            "🧊 <b>Сроки хранения</b>\n\nПока не трогаем — позже сделаем поиск по базе (JSON/таблица).",
            reply_markup=kb_main_menu()
        )
        return

    if data == "ui_groups":
        bot.send_message(
            chat_id,
            GROUPS_TEXT,
            reply_markup=kb_main_menu(),
            disable_web_page_preview=True
        )
        return

    if data == "ui_protocol":
        # редактируем текущее inline-сообщение, чтобы не плодить новые
        try:
            bot.edit_message_text(
                "📝 <b>Протокол собрания</b>\nВыбери раздел 👇",
                chat_id,
                call.message.message_id,
                reply_markup=kb_protocol_inline()
            )
        except Exception:
            bot.send_message(
                chat_id,
                "📝 <b>Протокол собрания</b>\nВыбери раздел 👇",
                reply_markup=kb_protocol_inline()
            )
        return

    if data == "ui_back_info":
        try:
            bot.edit_message_text(
                "📚 <b>Полезная информация</b>\nВыбери пункт 👇",
                chat_id,
                call.message.message_id,
                reply_markup=kb_useful_inline()
            )
        except Exception:
            bot.send_message(chat_id, "Меню:", reply_markup=kb_useful_inline())
        return

    if data == "ui_back_main":
        bot.send_message(chat_id, "Главное меню 👇", reply_markup=kb_main_menu())
        return


if __name__ == "__main__":
    print(f"🤖 Bot is running. TZ={TZ_NAME} | VERSION={BOT_VERSION}")
    bot.infinity_polling(skip_pending=True)
