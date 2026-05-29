#!/usr/bin/env python3
"""
Telegram-бот для ручного запроса дайджеста.

Запуск:  python bot.py
Команды в Telegram:
  /news  — немедленно собрать и прислать дайджест
  /start — показать справку
  /stop  — выключить бота (или Ctrl+C в терминале)
"""
import os
import sys
import time

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

TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AUTHORIZED_CHAT = str(os.environ["TELEGRAM_CHAT_ID"])

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


def send(text: str) -> None:
    _tg("sendMessage", chat_id=AUTHORIZED_CHAT, text=text)


def get_updates(offset: int | None) -> list:
    params: dict = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    result = _tg("getUpdates", **params)
    return result.get("result", [])


# ── Digest runner ─────────────────────────────────────────────────────────────

def run_digest() -> None:
    from main import main as _digest
    _digest(force=True)


# ── Main loop ─────────────────────────────────────────────────────────────────

HELP = (
    "Команды:\n"
    "/news  — свежий дайджест прямо сейчас\n"
    "/stop  — выключить бота\n"
    "/start — эта справка"
)


def drain_updates() -> int | None:
    """Пропустить все накопившиеся апдейты, вернуть следующий offset."""
    result = _tg("getUpdates", timeout=0)
    updates = result.get("result", [])
    if updates:
        return updates[-1]["update_id"] + 1
    return None


def main() -> None:
    print("Бот запущен. Жди /news в Telegram или нажми Ctrl+C для выхода.")
    offset = drain_updates()  # пропускаем старые сообщения
    send(f"🤖 Бот запущен.\n{HELP}")

    running = True

    while running:
        updates = get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "").strip()

            if chat_id != AUTHORIZED_CHAT:
                continue

            if text.startswith("/news"):
                send("⏳ Собираю дайджест…")
                try:
                    run_digest()
                except Exception as exc:
                    send(f"❌ Ошибка: {exc}")

            elif text.startswith("/stop"):
                send("👋 Бот выключен.")
                running = False
                break

            elif text.startswith("/start") or text.startswith("/help"):
                send(HELP)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлен.")
