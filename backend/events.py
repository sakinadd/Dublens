"""n8n-ə hadisə göndərmək (DubLens 01 · Hadisə qəbulu). Fire-and-forget: n8n işləmirsə tətbiq dayanmır."""
import threading

import requests

from backend import config


def send(event: str, username: str, **data):
    if not config.N8N_EVENT_WEBHOOK:
        return
    payload = {"event": event, "username": username, **data}

    def _post():
        try:
            requests.post(config.N8N_EVENT_WEBHOOK, json=payload, timeout=6)
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def profile(user: dict):
    send("profile", user["username"], name=user.get("name"), email=user.get("email"),
         remind_hour=int(user.get("remind_hour") or 8), remind_on=bool(user.get("remind_on")),
         lang=user.get("lang", "az"))
