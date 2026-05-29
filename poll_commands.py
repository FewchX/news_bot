#!/usr/bin/env python3
"""
Проверяет Telegram на команду /news и сигнализирует GitHub Actions.
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


def set_output(key: str, value: str) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT", "")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"[output] {key}={value}")  # локальный запуск


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

        if text.startswith("/news") and not trigger:
            trigger = True
            _tg("sendMessage", data={
                "chat_id": AUTHORIZED_CHAT,
                "text": "⏳ Запускаю дайджест через GitHub Actions… подожди ~2 мин",
            })
            print("[poll] /news нашёл → запускаю дайджест", file=sys.stderr)

    save_offset(new_offset)
    set_output("trigger", "true" if trigger else "false")


if __name__ == "__main__":
    main()
