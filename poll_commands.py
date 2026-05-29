#!/usr/bin/env python3
"""
Проверяет Telegram на команды и сигнализирует GitHub Actions.
Использует только stdlib — pip install не нужен.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_root = Path(__file__).parent
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AUTHORIZED_CHAT = str(os.environ["TELEGRAM_CHAT_ID"])
OFFSET_PATH = _root / "state" / "tg_offset.json"
SETTINGS_PATH = _root / "state" / "user_settings.json"
PENDING_DELETE_PATH = _root / "state" / "pending_delete.json"


def _tg(method: str, data: dict | None = None, params: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    if data:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"[poll] HTTP {exc.code}: {exc.read().decode()[:200]}", file=sys.stderr)
        return {}
    except Exception as exc:
        print(f"[poll] error: {exc}", file=sys.stderr)
        return {}


def load_offset() -> int | None:
    try:
        return json.loads(OFFSET_PATH.read_text()).get("offset")
    except Exception:
        return None


def save_offset(offset: int | None) -> None:
    OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_PATH.write_text(json.dumps({"offset": offset}))


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def set_output(key: str, value: str) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT", "")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"[output] {key}={value}")  # локальный запуск


def _tg_send(text: str, parse_mode: str = "HTML") -> int | None:
    """Отправляет сообщение и возвращает message_id."""
    resp = _tg("sendMessage", data={
        "chat_id": AUTHORIZED_CHAT,
        "parse_mode": parse_mode,
        "text": text,
    })
    return resp.get("result", {}).get("message_id")


def _tg_delete_msg(message_id: int) -> None:
    """Удаляет сообщение (тихо игнорирует ошибки)."""
    _tg("deleteMessage", data={"chat_id": AUTHORIZED_CHAT, "message_id": message_id})


def handle_news_settings(args: str) -> int | None:
    """Обрабатывает /news_settings, возвращает message_id ответа бота."""
    settings = load_settings()

    if args:
        if args.lower() in ("clear", "очистить", "-", "reset", "сброс"):
            settings.pop("filter", None)
            save_settings(settings)
            msg_id = _tg_send("✅ Фильтр очищен. Все новости показываются без ограничений.")
        else:
            settings["filter"] = args
            save_settings(settings)
            msg_id = _tg_send(
                "✅ <b>Фильтр сохранён</b>\n\n"
                f"{args}\n\n"
                "<i>Это сообщение удалится через 10 сек.</i>"
            )
        print(f"[poll] /news_settings обновлены: {args!r}", file=sys.stderr)
    else:
        current = settings.get("filter")
        if current:
            reply = (
                "⚙️ <b>Настройки фильтрации</b>\n\n"
                f"Текущий фильтр:\n<i>{current}</i>\n\n"
                "Чтобы изменить:\n"
                "<code>/news_settings [новые требования]</code>\n\n"
                "Чтобы очистить:\n"
                "<code>/news_settings clear</code>\n\n"
                "<i>Это сообщение удалится через 10 сек.</i>"
            )
        else:
            reply = (
                "⚙️ <b>Настройки фильтрации</b>\n\n"
                "Фильтр не задан. Все новости показываются.\n\n"
                "Чтобы задать фильтр:\n"
                "<code>/news_settings [твои требования]</code>\n\n"
                "Пример:\n"
                "<code>/news_settings Не отправляй новости про финансовые отчёты компаний</code>\n\n"
                "<i>Это сообщение удалится через 10 сек.</i>"
            )
        msg_id = _tg_send(reply)

    return msg_id


def main() -> None:
    offset = load_offset()
    params: dict = {"timeout": 30, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset

    result = _tg("getUpdates", params=params)
    updates = result.get("result", [])
    print(f"[poll] {len(updates)} update(s)", file=sys.stderr)

    trigger = False
    new_offset = offset

    for upd in updates:
        new_offset = upd["update_id"] + 1
        msg = upd.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()

        if chat_id != AUTHORIZED_CHAT:
            continue

        # Разбиваем на команду и аргументы
        parts = text.split(None, 1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""
        msg_id = msg.get("message_id")

        # Пробуем удалить сообщение пользователя
        # (работает в группах где бот — админ; в личке игнорируется)
        if msg_id:
            _tg_delete_msg(msg_id)

        if cmd == "/news" and not trigger:
            trigger = True
            resp = _tg("sendMessage", data={
                "chat_id": AUTHORIZED_CHAT,
                "text": "⏳ Запускаю дайджест… подожди ~2 мин",
            })
            # Сохраняем message_id — main.py удалит его после отправки дайджеста
            pending_msg_id = resp.get("result", {}).get("message_id")
            if pending_msg_id:
                PENDING_DELETE_PATH.parent.mkdir(parents=True, exist_ok=True)
                PENDING_DELETE_PATH.write_text(json.dumps({"message_id": pending_msg_id}))
            print("[poll] /news → запускаю дайджест", file=sys.stderr)

        elif cmd == "/news_settings":
            resp_id = handle_news_settings(args)
            if resp_id:
                time.sleep(10)
                _tg_delete_msg(resp_id)

    save_offset(new_offset)
    set_output("trigger", "true" if trigger else "false")


if __name__ == "__main__":
    main()
