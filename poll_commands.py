#!/usr/bin/env python3
"""
Проверяет Telegram на команды и сигнализирует GitHub Actions.
Использует только stdlib — pip install не нужен.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_root = Path(__file__).parent
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AUTHORIZED_CHAT = str(os.environ["TELEGRAM_CHAT_ID"])
OFFSET_PATH = _root / "state" / "tg_offset.json"
SETTINGS_PATH = _root / "state" / "user_settings.json"


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


def handle_news_settings(args: str) -> None:
    settings = load_settings()

    if args:
        if args.lower() in ("clear", "очистить", "-", "reset", "сброс"):
            settings.pop("filter", None)
            save_settings(settings)
            _tg("sendMessage", data={
                "chat_id": AUTHORIZED_CHAT,
                "parse_mode": "HTML",
                "text": "✅ Фильтр очищен. Все новости показываются без ограничений.",
            })
        else:
            settings["filter"] = args
            save_settings(settings)
            _tg("sendMessage", data={
                "chat_id": AUTHORIZED_CHAT,
                "parse_mode": "HTML",
                "text": (
                    "✅ <b>Фильтр сохранён</b>\n\n"
                    f"{args}\n\n"
                    "<i>Применится к следующему дайджесту.</i>"
                ),
            })
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
                "<code>/news_settings clear</code>"
            )
        else:
            reply = (
                "⚙️ <b>Настройки фильтрации</b>\n\n"
                "Фильтр не задан. Все новости показываются.\n\n"
                "Чтобы задать фильтр:\n"
                "<code>/news_settings [твои требования]</code>\n\n"
                "Пример:\n"
                "<code>/news_settings Не отправляй новости про финансовые отчёты компаний</code>"
            )
        _tg("sendMessage", data={
            "chat_id": AUTHORIZED_CHAT,
            "parse_mode": "HTML",
            "text": reply,
        })


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

        if cmd == "/news" and not trigger:
            trigger = True
            _tg("sendMessage", data={
                "chat_id": AUTHORIZED_CHAT,
                "text": "⏳ Запускаю дайджест через GitHub Actions… подожди ~2 мин",
            })
            print("[poll] /news → запускаю дайджест", file=sys.stderr)

        elif cmd == "/news_settings":
            handle_news_settings(args)

    save_offset(new_offset)
    set_output("trigger", "true" if trigger else "false")


if __name__ == "__main__":
    main()
