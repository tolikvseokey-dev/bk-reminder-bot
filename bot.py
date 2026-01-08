import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

import pytz
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from apscheduler.schedulers.background import BackgroundScheduler

try:
    from openpyxl import load_workbook
except Exception as e:
    raise RuntimeError("Не установлен openpyxl. Добавь в requirements.txt строку: openpyxl") from e


# ================== ВЕРСИЯ ==================
BOT_VERSION = "inline+storage-universal-schema-skip-empty-2026-01-08-02"


# ================== НАСТРОЙКИ ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATA_FILE = "reminders.json"

TZ_NAME = os.environ.get("BOT_TZ", "Europe/Moscow")
TZ = pytz.timezone(TZ_NAME)

DATE_PICK_DAYS = int(os.environ.get("DATE_PICK_DAYS", "21"))

AUTO_DELETE_AFTER_HOURS = int(os.environ.get("AUTO_DELETE_AFTER_HOURS", "24"))
CLEANUP_INTERVAL_MINUTES = int(os.environ.get("CLEANUP_INTERVAL_MINUTES", "1"))

STORAGE_FILE_ENV = os.environ.get("STORAGE_FILE", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Добавь переменную окружения BOT_TOKEN в панели хостинга (Bothost).")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
scheduler = BackgroundScheduler(timezone=TZ)
scheduler.start()

states: Dict[int, Dict[str, Any]] = {}


# ================== ХРАНЕНИЕ НАПОМИНАНИЙ ==================
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


# ================== INLINE МЕНЮ ==================
def kb_main_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("📌 Напоминания", callback_data="nav_reminders"))
    kb.row(InlineKeyboardButton("📚 Полезная информация", callback_data="nav_useful"))
    kb.row(InlineKeyboardButton("🧊 Сроки хранения (поиск)", callback_data="nav_storage"))
    kb.row(InlineKeyboardButton("ℹ️ О боте", callback_data="nav_about"))
    return kb


def kb_reminders_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("➕ Добавить напоминание", callback_data="rem_add"))
    kb.row(InlineKeyboardButton("📋 Все напоминания", callback_data="rem_list"))
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="nav_main"))
    return kb


def kb_cancel_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("❌ Отмена", callback_data="cancel"))
    kb.row(InlineKeyboardButton("⬅️ Назад в меню", callback_data="nav_main"))
    return kb


# ================== ПОЛЕЗНАЯ ИНФОРМАЦИЯ (INLINE) ==================
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
    kb.row(InlineKeyboardButton("🗓 Расписание РМ", url=USEFUL_LINKS["rm_schedule"]))
    kb.row(InlineKeyboardButton("🌴 График отпусков", url=USEFUL_LINKS["vacations"]))
    kb.row(InlineKeyboardButton("📊 АТО", url=USEFUL_LINKS["ato"]))
    kb.row(InlineKeyboardButton("🔗 Ссылки на группы", callback_data="ui_groups"))
    kb.row(InlineKeyboardButton("📈 Динамика", url=USEFUL_LINKS["dynamics"]))
    kb.row(InlineKeyboardButton("🧾 Ростер", url=USEFUL_LINKS["roster"]))
    kb.row(InlineKeyboardButton("☎️ Контакт-лист", url=USEFUL_LINKS["contacts"]))
    kb.row(InlineKeyboardButton("📝 Протокол собрания", callback_data="ui_protocol"))
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="nav_main"))
    return kb


def kb_protocol_inline() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("👔 РМ", url=USEFUL_LINKS["protocol_rm"]))
    kb.row(InlineKeyboardButton("🧑‍💼 Директора", url=USEFUL_LINKS["protocol_directors"]))
    kb.row(InlineKeyboardButton("⬅️ Назад", callback_data="nav_useful"))
    return kb


# ================== INLINE ПИКЕРЫ ДАТЫ/ВРЕМЕНИ ==================
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


# ================== БАЗА СРОКОВ ХРАНЕНИЯ (XLSX) ==================
def _script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def find_storage_file() -> Optional[str]:
    if STORAGE_FILE_ENV:
        p = STORAGE_FILE_ENV
        if not os.path.isabs(p):
            p = os.path.join(_script_dir(), p)
        if os.path.exists(p):
            return p

    candidates = [
        "storage.xlsx",
        "Storage.xlsx",
        "Storage .xlsx",
        "Storage  .xlsx",
        "Меню БК без картинок .xlsx",
        "Меню БК без картинок.xlsx",
    ]
    for name in candidates:
        p = os.path.join(_script_dir(), name)
        if os.path.exists(p):
            return p
    return None


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() == "none":
        return ""
    return s


def _norm_header(s: str) -> str:
    # нормализуем заголовки, чтобы ловить варианты с лишними пробелами
    return " ".join((s or "").strip().split()).lower()


StorageRow = Dict[str, Any]

STORAGE_DB: List[StorageRow] = []
STORAGE_READY: bool = False
STORAGE_SOURCE_PATH: str = ""

# Универсальный порядок вывода (как ты задал)
STORAGE_TEMPLATE_HEADERS = [
    "Выход (г)",
    "Срок хранения",
    "Рекомендуемая температура отдачи",
    "Маркировка на витрине",
    "Упаковка собой",
]
STORAGE_TEMPLATE_HEADERS_NORM = [_norm_header(x) for x in STORAGE_TEMPLATE_HEADERS]
STORAGE_NAME_HEADER_NORM = _norm_header("Наименование")


def load_storage_db() -> Tuple[int, List[str]]:
    """
    Загружает XLSX в память.
    Ищем колонки по заголовкам в 1 строке (A1..Z1).
    Вывод формируем по шаблону, пустые поля НЕ показываем.
    """
    global STORAGE_DB, STORAGE_READY, STORAGE_SOURCE_PATH

    path = find_storage_file()
    STORAGE_DB = []
    STORAGE_READY = False
    STORAGE_SOURCE_PATH = path or ""

    if not path:
        return 0, []

    wb = load_workbook(path, data_only=True)
    sheet_names = wb.sheetnames

    for sheet_name in sheet_names:
        ws = wb[sheet_name]

        # читаем заголовки первой строки (до 30 колонок с запасом)
        header_map: Dict[str, int] = {}  # norm_header -> column_index (1-based)
        for col in range(1, 31):
            h = _cell_str(ws.cell(row=1, column=col).value)
            if not h:
                continue
            header_map[_norm_header(h)] = col

        # обязательное: Наименование. Если нет — пробуем считать, что это колонка A
        name_col = header_map.get(STORAGE_NAME_HEADER_NORM, 1)

        # колонки по шаблону (если каких-то заголовков нет на листе — поле всегда будет пустым)
        field_cols: List[Tuple[str, Optional[int]]] = []
        for h, hn in zip(STORAGE_TEMPLATE_HEADERS, STORAGE_TEMPLATE_HEADERS_NORM):
            field_cols.append((h, header_map.get(hn)))

        # читаем строки до конца
        # max_row берём от листа
        for row in range(2, ws.max_row + 1):
            name = _cell_str(ws.cell(row=row, column=name_col).value)
            if not name:
                continue

            # пропускаем "разделители" — когда заполнено только Наименование, а остальные пустые
            any_field = False
            fields: Dict[str, str] = {}
            for h, col in field_cols:
                val = _cell_str(ws.cell(row=row, column=col).value) if col else ""
                if val:
                    any_field = True
                fields[h] = val

            if not any_field:
                # это заголовок-разделитель внутри листа
                continue

            STORAGE_DB.append({
                "category": sheet_name,
                "name": name,
                "name_lc": name.lower(),
                "fields": fields,  # ключи = заголовки шаблона
            })

    STORAGE_READY = True
    return len(STORAGE_DB), sheet_names


# загружаем при старте
_count, _sheets = load_storage_db()


def storage_search(query: str, limit: int = 12) -> List[StorageRow]:
    q = (query or "").strip().lower()
    if not q:
        return []

    hits = [row for row in STORAGE_DB if q in row["name_lc"]]

    if not hits:
        parts = [p for p in q.split() if p]
        if parts:
            hits = [row for row in STORAGE_DB if all(p in row["name_lc"] for p in parts)]

    return hits[:limit]


def format_storage_row(row: StorageRow) -> str:
    category = row.get("category", "")
    name = row.get("name", "")
    fields: Dict[str, str] = row.get("fields", {}) or {}

    lines = []
    if category:
        lines.append(f"📂 <b>{category}</b>")
    if name:
        lines.append(f"\n<b>{name}</b>")

    # выводим по шаблону и пропускаем пустое (как ты просил)
    for h in STORAGE_TEMPLATE_HEADERS:
        v = _cell_str(fields.get(h, ""))
        if not v:
            continue
        lines.append(f"\n<b>{h}:</b>\n{v}")

    return "\n".join(lines).strip()


def kb_storage_after_result() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("🔎 Новый поиск", callback_data="storage_newsearch"))
    kb.row(InlineKeyboardButton("❌ Выйти из поиска", callback_data="storage_exit"))
    kb.row(InlineKeyboardButton("⬅️ В меню", callback_data="nav_main"))
    return kb


def kb_storage_pick_list(results: List[StorageRow]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    for i, row in enumerate(results[:8]):
        title = row.get("name", "")
        if len(title) > 40:
            title = title[:40] + "…"
        kb.row(InlineKeyboardButton(f"{i+1}) {title}", callback_data=f"storage_pick|{i}"))
    kb.row(InlineKeyboardButton("🔎 Новый поиск", callback_data="storage_newsearch"))
    kb.row(InlineKeyboardButton("❌ Выйти из поиска", callback_data="storage_exit"))
    kb.row(InlineKeyboardButton("⬅️ В меню", callback_data="nav_main"))
    return kb


def kb_storage_start() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("🔄 Перезагрузить базу", callback_data="storage_reload"))
    kb.row(InlineKeyboardButton("❌ Выйти из поиска", callback_data="storage_exit"))
    kb.row(InlineKeyboardButton("⬅️ В меню", callback_data="nav_main"))
    return kb


# ================== STATE HELPERS ==================
def clear_user_state(user_id: int) -> None:
    states.pop(user_id, None)


def clear_storage_mode(user_id: int) -> None:
    st = states.get(user_id)
    if not st:
        return
    if st.get("mode") == "storage_search":
        clear_user_state(user_id)


# ================== УТИЛИТА: УБРАТЬ СТАРУЮ REPLY-КЛАВУ ==================
def remove_old_keyboard(chat_id: int) -> None:
    bot.send_message(chat_id, "Обновил меню ✅", reply_markup=ReplyKeyboardRemove())


# ================== /start /menu ==================
@bot.message_handler(commands=["start", "menu"])
def start_cmd(message):
    clear_user_state(message.from_user.id)
    remove_old_keyboard(message.chat.id)
    bot.send_message(
        message.chat.id,
        "Главное меню 👇\n"
        f"<i>Версия: {BOT_VERSION}</i>",
        reply_markup=kb_main_inline()
    )


# ================== ПОДХВАТ СТАРЫХ КНОПОК (если их нажмут) ==================
@bot.message_handler(func=lambda m: (m.text or "").strip() in {
    "📌 Напоминания", "📚 Полезная информация", "ℹ️ О боте",
    "➕ Добавить напоминание", "📋 Все напоминания", "⬅️ Назад"
})
def legacy_buttons_handler(message):
    clear_user_state(message.from_user.id)
    remove_old_keyboard(message.chat.id)
    bot.send_message(message.chat.id, "Перешли на новое меню (inline) 👇", reply_markup=kb_main_inline())


# ================== NAV CALLBACKS ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("nav_"))
def nav_callbacks(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data == "nav_main":
        clear_user_state(user_id)
        try:
            bot.edit_message_text("Главное меню 👇", chat_id, call.message.message_id, reply_markup=kb_main_inline())
        except Exception:
            bot.send_message(chat_id, "Главное меню 👇", reply_markup=kb_main_inline())
        return

    if data == "nav_reminders":
        clear_user_state(user_id)
        try:
            bot.edit_message_text("📌 <b>Напоминания</b> — выбери действие:", chat_id, call.message.message_id, reply_markup=kb_reminders_inline())
        except Exception:
            bot.send_message(chat_id, "📌 <b>Напоминания</b> — выбери действие:", reply_markup=kb_reminders_inline())
        return

    if data == "nav_useful":
        clear_user_state(user_id)
        try:
            bot.edit_message_text("📚 <b>Полезная информация</b> — выбери пункт:", chat_id, call.message.message_id, reply_markup=kb_useful_inline())
        except Exception:
            bot.send_message(chat_id, "📚 <b>Полезная информация</b> — выбери пункт:", reply_markup=kb_useful_inline())
        return

    if data == "nav_storage":
        if not STORAGE_READY:
            bot.send_message(
                chat_id,
                "🧊 <b>Сроки хранения</b>\n\n"
                "База не загружена. Проверь файл рядом с bot.py или задай STORAGE_FILE.",
                reply_markup=kb_storage_start()
            )
            return

        states[user_id] = {"mode": "storage_search", "chat_id": chat_id}
        bot.send_message(
            chat_id,
            "🧊 <b>Сроки хранения — поиск</b>\n\n"
            "Введи название продукта (можно часть слова).\n"
            "Пример: <i>омлет</i>, <i>песто</i>, <i>суп</i>\n\n"
            "Чтобы выйти — нажми «❌ Выйти из поиска».",
            reply_markup=kb_storage_start()
        )
        return

    if data == "nav_about":
        clear_user_state(user_id)
        text = (
            "ℹ️ <b>О боте</b>\n\n"
            "• Напоминания: добавление и список\n"
            "• Полезная информация: ссылки/материалы\n"
            "• Сроки хранения: поиск по Excel базе\n\n"
            f"🕒 Таймзона: <b>{TZ_NAME}</b>\n"
            f"🧹 Автоудаление напоминаний: <b>{AUTO_DELETE_AFTER_HOURS} ч</b> после события\n"
            f"🧊 База сроков хранения: <b>{'загружена' if STORAGE_READY else 'не загружена'}</b>\n"
            f"🔖 Версия: <b>{BOT_VERSION}</b>"
        )
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=kb_main_inline())
        except Exception:
            bot.send_message(chat_id, text, reply_markup=kb_main_inline())
        return


# ================== CALLBACKS (полезная информация) ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("ui_"))
def callbacks_useful(call):
    chat_id = call.message.chat.id
    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data == "ui_groups":
        bot.send_message(chat_id, GROUPS_TEXT, disable_web_page_preview=True, reply_markup=kb_useful_inline())
        return

    if data == "ui_protocol":
        try:
            bot.edit_message_text(
                "📝 <b>Протокол собрания</b>\nВыбери раздел 👇",
                chat_id,
                call.message.message_id,
                reply_markup=kb_protocol_inline()
            )
        except Exception:
            bot.send_message(chat_id, "📝 <b>Протокол собрания</b>\nВыбери раздел 👇", reply_markup=kb_protocol_inline())
        return


# ================== REMINDERS MENU CALLBACKS ==================
@bot.callback_query_handler(func=lambda call: call.data in {"rem_add", "rem_list"})
def reminders_menu_callbacks(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data == "rem_add":
        clear_user_state(user_id)
        states[user_id] = {"step": "title", "chat_id": chat_id}
        bot.send_message(chat_id, "Ок! Введи <b>название</b> напоминания:", reply_markup=kb_cancel_inline())
        return

    if data == "rem_list":
        items = get_chat_reminders(chat_id)
        if not items:
            bot.send_message(chat_id, "Пока нет напоминаний в этом чате.", reply_markup=kb_reminders_inline())
            return

        lines = ["📋 <b>Напоминания в этом чате</b>:"]
        for i, r in enumerate(items, 1):
            lines.append(f"{i}. <b>{r['title']}</b> — {format_event_dt(r['event_dt'])}")
        lines.append(f"\n🧹 Автоудаление: через {AUTO_DELETE_AFTER_HOURS} ч после события.")
        bot.send_message(chat_id, "\n".join(lines), reply_markup=kb_reminders_inline())
        return


# ================== CALLBACKS (дата/время/отмена) ==================
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

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data == "cancel":
        clear_user_state(user_id)
        bot.send_message(chat_id, "Ок, отменил. Возвращаюсь в меню:", reply_markup=kb_reminders_inline())
        return

    if not st or int(st.get("chat_id")) != int(chat_id):
        return

    if data.startswith("date|"):
        date_iso = data.split("|", 1)[1]
        st["date"] = date_iso
        st["step"] = "time_pick"
        bot.edit_message_text(
            "Дата выбрана ✅\nТеперь выбери <b>время</b>:",
            chat_id,
            call.message.message_id,
            reply_markup=build_time_picker()
        )
        return

    if data == "date_manual":
        st["step"] = "date_manual"
        bot.edit_message_text(
            "Введи дату вручную: <b>31.12.2026</b> или <b>2026-12-31</b>",
            chat_id,
            call.message.message_id
        )
        return

    if data.startswith("time|"):
        time_hhmm = data.split("|", 1)[1]
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        finalize_reminder(user_id, chat_id, time_hhmm)
        return

    if data == "time_manual":
        st["step"] = "time_manual"
        bot.edit_message_text(
            "Введи время вручную в формате <b>HH:MM</b> (например, <b>18:30</b>):",
            chat_id,
            call.message.message_id
        )
        return


# ================== CALLBACKS (сроки хранения) ==================
@bot.callback_query_handler(func=lambda call: call.data.startswith("storage_"))
def callbacks_storage(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data

    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if data == "storage_exit":
        clear_storage_mode(user_id)
        bot.send_message(chat_id, "Ок, вышел из поиска ✅", reply_markup=kb_main_inline())
        return

    if data == "storage_newsearch":
        states[user_id] = {"mode": "storage_search", "chat_id": chat_id}
        bot.send_message(chat_id, "🔎 Введи название продукта для поиска:", reply_markup=kb_storage_start())
        return

    if data == "storage_reload":
        count, sheets = load_storage_db()
        if count == 0:
            bot.send_message(
                chat_id,
                "❌ Не нашёл файл базы.\n"
                "Проверь, что xlsx лежит рядом с bot.py или задай STORAGE_FILE.",
                reply_markup=kb_storage_start()
            )
            return
        bot.send_message(
            chat_id,
            f"✅ База перезагружена: <b>{count}</b> строк.\n"
            f"Листы: {', '.join(sheets)}",
            reply_markup=kb_storage_start()
        )
        return

    if data.startswith("storage_pick|"):
        st = states.get(user_id, {})
        results = st.get("storage_results", [])
        try:
            idx = int(data.split("|", 1)[1])
        except Exception:
            idx = -1

        if not results or idx < 0 or idx >= len(results):
            bot.send_message(chat_id, "Не нашёл выбранный результат. Сделай новый поиск.", reply_markup=kb_storage_after_result())
            return

        row = results[idx]
        bot.send_message(chat_id, format_storage_row(row), reply_markup=kb_storage_after_result())
        clear_storage_mode(user_id)
        return


# ================== ТЕКСТОВЫЙ РОУТЕР (ТОЛЬКО КОГДА ЕСТЬ STATE) ==================
@bot.message_handler(func=lambda m: states.get(m.from_user.id) is not None, content_types=["text"])
def text_router(message):
    user_id = message.from_user.id
    st = states.get(user_id)
    if not st:
        return

    chat_id = st.get("chat_id")
    if int(chat_id) != int(message.chat.id):
        return

    # ====== режим поиска сроков хранения ======
    if st.get("mode") == "storage_search":
        query = (message.text or "").strip()
        if not query:
            bot.send_message(message.chat.id, "Введи название продукта текстом.", reply_markup=kb_storage_start())
            return

        if not STORAGE_READY:
            bot.send_message(message.chat.id, "База не загружена.", reply_markup=kb_storage_start())
            return

        results = storage_search(query, limit=12)
        if not results:
            bot.send_message(
                message.chat.id,
                f"Ничего не нашёл по запросу: <b>{query}</b>\n"
                "Попробуй другое слово или более короткий запрос.",
                reply_markup=kb_storage_start()
            )
            return

        st["storage_results"] = results

        if len(results) == 1:
            bot.send_message(message.chat.id, format_storage_row(results[0]), reply_markup=kb_storage_after_result())
            clear_storage_mode(user_id)
            return

        bot.send_message(message.chat.id, f"Нашёл вариантов: <b>{len(results)}</b>\nВыбери нужный:", reply_markup=kb_storage_pick_list(results))
        return

    # ====== сценарий напоминаний ======
    step = st.get("step")

    if step == "title":
        title = (message.text or "").strip()
        if not title:
            bot.send_message(message.chat.id, "Название не может быть пустым. Введи ещё раз:", reply_markup=kb_cancel_inline())
            return

        st["title"] = title
        st["step"] = "date_pick"
        bot.send_message(message.chat.id, "Выбери <b>дату</b>:", reply_markup=build_date_picker())
        return

    if step == "date_manual":
        raw = (message.text or "").strip()
        date_iso = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(raw, fmt).date()
                date_iso = d.isoformat()
                break
            except ValueError:
                pass

        if not date_iso:
            bot.send_message(message.chat.id, "Не понял дату. Пример: <b>31.12.2026</b> или <b>2026-12-31</b>")
            return

        st["date"] = date_iso
        st["step"] = "time_pick"
        bot.send_message(message.chat.id, "Теперь выбери <b>время</b>:", reply_markup=build_time_picker())
        return

    if step == "time_manual":
        raw = (message.text or "").strip()
        if not validate_time_hhmm(raw):
            bot.send_message(message.chat.id, "Не понял время. Пример: <b>18:30</b> (формат HH:MM)")
            return

        finalize_reminder(user_id, message.chat.id, raw)
        return


def finalize_reminder(user_id: int, chat_id: int, time_hhmm: str) -> None:
    st = states.get(user_id)
    if not st:
        return

    title = st["title"]
    date_iso = st["date"]

    event_dt_naive = datetime.strptime(f"{date_iso} {time_hhmm}", "%Y-%m-%d %H:%M")
    event_dt = TZ.localize(event_dt_naive)

    if event_dt <= now_tz():
        bot.send_message(chat_id, "Это время уже в прошлом. Давай выберем заново дату/время.")
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
        f"🧹 Автоудаление: через <b>{AUTO_DELETE_AFTER_HOURS} ч</b> после события.\n\n"
        "Дальше что делаем?",
        reply_markup=kb_reminders_inline()
    )

    clear_user_state(user_id)


if __name__ == "__main__":
    print(f"🤖 Bot is running. TZ={TZ_NAME} | VERSION={BOT_VERSION}")
    print(f"🧊 Storage ready: {STORAGE_READY} | file: {STORAGE_SOURCE_PATH} | rows: {len(STORAGE_DB)}")
    bot.infinity_polling(skip_pending=True)
