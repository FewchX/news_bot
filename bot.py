#!/usr/bin/env python3
"""
Telegram-бот: long-polling, работает постоянно на сервере.

Команды:
  /news            — дайджест прямо сейчас
  /news_settings   — показать текущий фильтр новостей
  /news_settings … — задать новый фильтр
  /news_settings clear — сбросить фильтр
  /start | /help   — справка
"""
import json
import os
import sys
import time
import threading

import requests

# ── .env loader ───────────────────────────────────────────────────────────────
_root = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_root, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

TG_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
AUTHORIZED_CHAT = str(os.environ["TELEGRAM_CHAT_ID"])
SETTINGS_PATH  = os.path.join(_root, "state", "user_settings.json")

# ── Telegram helpers ──────────────────────────────────────────────────────────

def _tg(method: str, **kwargs) -> dict:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/{method}",
            json=kwargs,
            timeout=40,
        )
        return resp.json()
    except Exception as exc:
        print(f"[tg] {method} error: {exc}", file=sys.stderr)
        return {}


def send(text: str, parse_mode: str = "HTML") -> int | None:
    """Отправляет сообщение, возвращает message_id."""
    resp = _tg(
        "sendMessage",
        chat_id=AUTHORIZED_CHAT,
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
    )
    return resp.get("result", {}).get("message_id")


def delete_msg(message_id: int) -> None:
    _tg("deleteMessage", chat_id=AUTHORIZED_CHAT, message_id=message_id)


def try_delete_user_msg(msg_id: int) -> None:
    """Удаляет сообщение пользователя (работает в группах, тихо падает в личке)."""
    _tg("deleteMessage", chat_id=AUTHORIZED_CHAT, message_id=msg_id)


def get_updates(offset: int | None) -> list:
    params: dict = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    return _tg("getUpdates", **params).get("result", [])


def drain_updates() -> int | None:
    """Пропускаем накопившиеся старые сообщения при старте."""
    updates = _tg("getUpdates", timeout=0).get("result", [])
    if updates:
        return updates[-1]["update_id"] + 1
    return None


# ── Settings helpers ──────────────────────────────────────────────────────────

def load_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(s: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def handle_news_settings(args: str) -> None:
    settings = load_settings()

    if args:
        if args.lower() in ("clear", "очистить", "-", "reset", "сброс"):
            settings.pop("filter", None)
            save_settings(settings)
            mid = send("✅ Фильтр очищен. Все новости показываются без ограничений.")
        else:
            settings["filter"] = args
            save_settings(settings)
            mid = send(
                "✅ <b>Фильтр сохранён</b>\n\n"
                f"{args}\n\n"
                "<i>Это сообщение удалится через 10 сек.</i>"
            )
        if mid:
            threading.Timer(10, delete_msg, args=(mid,)).start()
    else:
        current = settings.get("filter")
        if current:
            text = (
                "⚙️ <b>Настройки фильтрации</b>\n\n"
                f"Текущий фильтр:\n<i>{current}</i>\n\n"
                "Изменить:\n<code>/news_settings [новые требования]</code>\n"
                "Очистить:\n<code>/news_settings clear</code>\n\n"
                "<i>Это сообщение удалится через 10 сек.</i>"
            )
        else:
            text = (
                "⚙️ <b>Настройки фильтрации</b>\n\n"
                "Фильтр не задан. Все новости показываются.\n\n"
                "Задать:\n<code>/news_settings [требования]</code>\n\n"
                "Пример:\n"
                "<code>/news_settings Не отправляй финансовые отчёты компаний</code>\n\n"
                "<i>Это сообщение удалится через 10 сек.</i>"
            )
        mid = send(text)
        if mid:
            threading.Timer(10, delete_msg, args=(mid,)).start()


# ── Digest runner ─────────────────────────────────────────────────────────────

_digest_lock = threading.Lock()


def run_digest() -> None:
    """Запускает дайджест в отдельном потоке чтобы не блокировать polling."""
    def _run():
        with _digest_lock:
            try:
                from main import main as _digest
                _digest(force=True)
            except Exception as exc:
                send(f"❌ Ошибка дайджеста: {exc}", parse_mode=None)
    threading.Thread(target=_run, daemon=True).start()


# ── Main loop ─────────────────────────────────────────────────────────────────

HELP = (
    "Команды:\n"
    "/news — свежий дайджест прямо сейчас\n"
    "/news_settings — настройки фильтрации\n"
    "/start — эта справка"
)


def main() -> None:
    print("[bot] Запускаемся…", file=sys.stderr)
    offset = drain_updates()
    print(f"[bot] Старые сообщения пропущены. Offset={offset}", file=sys.stderr)

    while True:
        try:
            updates = get_updates(offset)
        except Exception as exc:
            print(f"[bot] getUpdates error: {exc}", file=sys.stderr)
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            msg   = upd.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text    = (msg.get("text") or "").strip()
            msg_id  = msg.get("message_id")

            if chat_id != AUTHORIZED_CHAT:
                continue

            parts = text.split(None, 1)
            cmd  = parts[0].lower() if parts else ""
            args = parts[1].strip() if len(parts) > 1 else ""

            # Пробуем удалить сообщение пользователя (работает только в группах)
            if msg_id:
                try_delete_user_msg(msg_id)

            if cmd == "/news":
                waiting_id = send("⏳ Собираю дайджест…", parse_mode=None)
                run_digest()
                # "⏳" удалится из main.py через pending_delete.json —
                # или просто удаляем здесь через 10 сек как запасной вариант
                if waiting_id:
                    threading.Timer(130, delete_msg, args=(waiting_id,)).start()

            elif cmd == "/news_settings":
                handle_news_settings(args)

            elif cmd in ("/start", "/help"):
                send(HELP, parse_mode=None)

        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[bot] Остановлен.")
